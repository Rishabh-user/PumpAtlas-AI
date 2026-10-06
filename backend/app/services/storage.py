"""Object storage for documents.

S3-compatible in every real environment (AWS S3, MinIO in Compose). Falls back to a
local directory when no credentials are configured so the platform runs on a laptop
without MinIO.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class StoredObject:
    key: str
    bucket: str | None
    size_bytes: int
    checksum_sha256: str


def build_key(tenant_id: uuid.UUID | str | None, filename: str) -> str:
    safe = Path(filename).name.replace(" ", "_")
    scope = str(tenant_id) if tenant_id else "shared"
    return f"tenants/{scope}/documents/{uuid.uuid4().hex}/{safe}"


class LocalStorage:
    """Development backend. Not for production - no durability guarantees."""

    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root or settings.LOCAL_STORAGE_DIR)

    def put(self, key: str, data: bytes, content_type: str | None = None) -> StoredObject:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return StoredObject(
            key=key,
            bucket=None,
            size_bytes=len(data),
            checksum_sha256=hashlib.sha256(data).hexdigest(),
        )

    def get(self, key: str) -> bytes:
        return (self.root / key).read_bytes()

    def delete(self, key: str) -> None:
        target = self.root / key
        if target.exists():
            target.unlink()

    def presigned_url(self, key: str, expires_in: int = 900) -> str:
        # Local mode streams through the API instead of redirecting to storage.
        return f"{settings.API_V1_PREFIX}/documents/download?key={key}"


class S3Storage:
    def __init__(self) -> None:
        import boto3  # imported lazily so local mode needs no AWS SDK

        self.bucket = settings.S3_BUCKET
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            region_name=settings.S3_REGION,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            use_ssl=settings.S3_USE_SSL,
        )

    def ensure_bucket(self) -> None:
        from botocore.exceptions import ClientError

        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            log.info("storage.creating_bucket", bucket=self.bucket)
            self.client.create_bucket(Bucket=self.bucket)

    def put(self, key: str, data: bytes, content_type: str | None = None) -> StoredObject:
        checksum = hashlib.sha256(data).hexdigest()
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type or "application/octet-stream",
            # Encryption at rest; MinIO honours SSE-S3 when configured.
            ServerSideEncryption="AES256",
            Metadata={"sha256": checksum},
        )
        return StoredObject(
            key=key, bucket=self.bucket, size_bytes=len(data), checksum_sha256=checksum
        )

    def get(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def presigned_url(self, key: str, expires_in: int = 900) -> str:
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires_in
        )


_storage: LocalStorage | S3Storage | None = None


def get_storage() -> LocalStorage | S3Storage:
    global _storage
    if _storage is None:
        if settings.use_s3:
            storage = S3Storage()
            try:
                storage.ensure_bucket()
            except Exception as exc:  # noqa: BLE001 - startup should not hard fail
                log.warning("storage.bucket_check_failed", error=str(exc))
            _storage = storage
        else:
            log.info("storage.local_mode", root=settings.LOCAL_STORAGE_DIR)
            _storage = LocalStorage()
    return _storage
