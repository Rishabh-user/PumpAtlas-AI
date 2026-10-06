"""Application settings, loaded from environment / .env."""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: The stand-in for local work. Named rather than inlined so the guard below and the
#: deployment checklist can both refer to the same value.
DEV_SECRET_KEY = "dev-only-secret-change-me"

#: Shorter than this and `ai_settings._fernet` cannot derive an encryption key, so
#: storing a provider credential fails at the point of use instead of at startup.
MIN_SECRET_KEY_CHARS = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    # ---------- core ----------
    PROJECT_NAME: str = "PumpAtlas AI"
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    API_V1_PREFIX: str = "/api/v1"

    # ---------- security ----------
    #: Signs every token, and derives the key that encrypts stored AI provider
    #: credentials. The default is usable for local work and refused in production.
    SECRET_KEY: str = DEV_SECRET_KEY
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14
    # Kept as a plain string: pydantic-settings tries to JSON-decode a complex type
    # read from a dotenv file *before* any validator runs, so `list[str]` here rejects
    # the natural `CORS_ORIGINS=http://localhost:3000`. Parsed by `cors_origins` below.
    CORS_ORIGINS: str = "http://localhost:3000"

    # ---------- postgres ----------
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "pumpatlas"
    POSTGRES_USER: str = "pumpatlas"
    POSTGRES_PASSWORD: str = "pumpatlas"
    # Managed providers (Render, RDS, Cloud SQL, Neon) require TLS. "prefer" is right
    # for a local container; set "require" or "verify-full" for anything hosted.
    POSTGRES_SSLMODE: str = "prefer"
    DATABASE_URL: str | None = None
    # Managed tiers cap connections tightly (Render's smaller plans allow ~100 total,
    # shared with their own monitoring). Every API worker, Celery worker and beat
    # process opens its own pool, so keep the defaults modest and raise deliberately.
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 5
    DB_POOL_RECYCLE_SECONDS: int = 1800
    DB_CONNECT_TIMEOUT_SECONDS: int = 15
    DB_STATEMENT_TIMEOUT: str = "30s"
    DB_ECHO: bool = False

    # ---------- redis / celery ----------
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    # Development escape hatch: run background tasks inline, in the calling process,
    # with no broker at all. Removes the Redis dependency entirely, at the cost of the
    # request blocking for the whole task - an AI extraction can take 90 seconds, so
    # this is for local work and tests, never for a deployment.
    CELERY_TASK_ALWAYS_EAGER: bool = False

    # ---------- object storage ----------
    S3_ENDPOINT_URL: str | None = None
    S3_REGION: str = "us-east-1"
    S3_BUCKET: str = "pumpatlas-documents"
    S3_ACCESS_KEY: str | None = None
    S3_SECRET_KEY: str | None = None
    S3_USE_SSL: bool = False
    LOCAL_STORAGE_DIR: str = "./.data/documents"

    # ---------- AI: OpenRouter Gemma ----------
    AI_ENABLED: bool = True
    OPENROUTER_API_KEY: str | None = None
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_MODEL: str = "google/gemma-3-27b-it"
    OPENROUTER_FALLBACK_MODEL: str = "google/gemma-3-12b-it"
    OPENROUTER_TIMEOUT_SECONDS: int = 120
    OPENROUTER_MAX_RETRIES: int = 3
    OPENROUTER_MAX_INPUT_CHARS: int = 60_000

    # ---------- Web search: Parallel AI ----------
    # --- reading models: whoever reads a captured page and extracts fields ----------
    #
    # OpenRouter, OpenAI and most gateways speak the same chat-completions shape, so
    # those two differ only in base URL, key and model. Anthropic's Messages API is a
    # different contract and has its own client.
    #
    # Only a fallback now: providers, models and keys are configured at /ai-settings
    # and held in the database, so these are what an installation uses before anyone has
    # visited that page.
    EXTRACTION_PROVIDER: str = "openrouter"

    OPENAI_API_KEY: str | None = None
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_TIMEOUT_SECONDS: int = 120

    ANTHROPIC_API_KEY: str | None = None
    ANTHROPIC_BASE_URL: str = "https://api.anthropic.com"
    ANTHROPIC_MODEL: str = "claude-sonnet-5"
    #: Pinned: Anthropic requires the header and treats it as the contract version.
    ANTHROPIC_VERSION: str = "2023-06-01"
    ANTHROPIC_TIMEOUT_SECONDS: int = 120
    ANTHROPIC_MAX_INPUT_CHARS: int = 200_000

    # --- web search: whoever finds the candidate pages ------------------------------
    #
    # All three return a list of URLs that the capture step then fetches itself, so the
    # provenance path is identical whichever found the page.
    SEARCH_PROVIDER: str = "parallel"
    #: How many web searches a provider may run inside one server-tool call.
    SEARCH_MAX_USES: int = 5

    PARALLEL_API_KEY: str | None = None
    PARALLEL_BASE_URL: str = "https://api.parallel.ai"
    PARALLEL_TIMEOUT_SECONDS: int = 180
    PARALLEL_MAX_RESULTS: int = 15

    # ---------- ingestion ----------
    MAX_UPLOAD_MB: int = 50
    CRAWL_USER_AGENT: str = "PumpAtlasAI/1.0 (+https://targeticon.com/pumpatlas)"
    CRAWL_RESPECT_ROBOTS: bool = True
    CRAWL_MAX_PAGE_BYTES: int = 10 * 1024 * 1024

    # ---------- bootstrap ----------
    #
    # There is deliberately no administrator email or password here. A login belongs in
    # the users table, where it can be rotated, audited and revoked; in configuration it
    # is readable by anything that can read the environment, copied into every backup and
    # deployment dashboard, and identical on every machine sharing the file. This project
    # shipped `FIRST_ADMIN_PASSWORD=ChangeMe!123`, so an installation that never edited
    # `.env` ran with an administrator password published in its own repository.
    #
    # Accounts are created with `python -m scripts.manage_user create`, which reads the
    # password from a prompt and stores only its hash.

    @field_validator("SECRET_KEY")
    @classmethod
    def _secret_key_is_usable(cls, value: str) -> str:
        """Refuse an empty SECRET_KEY outright.

        An absent key falls back to the development default, which the production checks
        catch. An *empty* one - `SECRET_KEY=` copied from a template, or a variable set to
        nothing by a deployment dashboard - would sign tokens with a zero-length secret
        and go unnoticed, because nothing else complains. So the empty case is the one
        that raises, while a short key is only reported: the offline test suite runs on
        one, and breaking it would buy nothing.
        """
        if not value.strip():
            raise ValueError(
                "SECRET_KEY is empty. Generate one with `openssl rand -hex 32`, or "
                "remove the line entirely to fall back to the development default. An "
                "empty value signs tokens with a zero-length secret."
            )
        return value

    @property
    def secret_key_is_weak(self) -> bool:
        """True when the secret is the development default or too short to encrypt with.

        Read by the readiness endpoint rather than raised here, so a misconfigured
        deployment is visible without making the process unstartable.
        """
        return self.SECRET_KEY == DEV_SECRET_KEY or len(self.SECRET_KEY) < MIN_SECRET_KEY_CHARS

    @property
    def cors_origins(self) -> list[str]:
        """Comma-separated origins, or `*` to allow any (development only)."""
        raw = self.CORS_ORIGINS.strip()
        if raw == "*":
            return ["*"]
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    @property
    def sqlalchemy_url(self) -> str:
        """SQLAlchemy URL, normalised for psycopg 3.

        A provider-supplied `DATABASE_URL` starts `postgresql://`, which SQLAlchemy maps
        to psycopg2. Rewriting the scheme here means the URL can be pasted straight from
        a Render or RDS dashboard without anyone having to know that.
        """
        if self.DATABASE_URL:
            url = self.DATABASE_URL
            for prefix in ("postgresql+psycopg2://", "postgres://", "postgresql://"):
                if url.startswith(prefix):
                    url = "postgresql+psycopg://" + url[len(prefix) :]
                    break
            if "sslmode=" not in url and self.POSTGRES_SSLMODE:
                url += ("&" if "?" in url else "?") + f"sslmode={self.POSTGRES_SSLMODE}"
            return url
        return (
            f"postgresql+psycopg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
            f"?sslmode={self.POSTGRES_SSLMODE}"
        )

    @property
    def database_host_summary(self) -> str:
        """Host and database only - safe to log, never includes the password."""
        if self.DATABASE_URL:
            from urllib.parse import urlparse

            parsed = urlparse(self.DATABASE_URL)
            return f"{parsed.hostname}:{parsed.port or 5432}{parsed.path}"
        return f"{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    @property
    def background_jobs_need_a_broker(self) -> bool:
        return not self.CELERY_TASK_ALWAYS_EAGER

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() in {"production", "prod"}

    @property
    def use_s3(self) -> bool:
        """Whether documents go to object storage rather than local disk.

        Having a key is what selects the backend, which makes a half-configured S3 worse
        than none: `.env.example` once shipped the MinIO credentials filled in, so a
        machine without MinIO chose `S3Storage`, pointed it at a dead endpoint and failed
        every upload instead of writing to `LOCAL_STORAGE_DIR`. Left empty, local mode is
        the deliberate choice rather than the accident.
        """
        return bool(self.S3_ACCESS_KEY and self.S3_SECRET_KEY)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
