"""Clear the category pages already sitting in the pump review queue.

    python -m scripts.clear_category_candidates            # dry run, writes nothing
    python -m scripts.clear_category_candidates --commit   # reject them

A page titled "API 610 VS6 Vertical Suspended Pumps" describes a configuration hundreds
of manufacturers build, not a product anybody can quote for. Screening now rules those
pages out before a candidate exists, but the ones extracted before that change are still
in the queue: blocked, unstorable, and taking up the reviewer's attention on every visit.

This rejects them, which is what a reviewer would do by hand. The decision is recorded on
the candidate with the reason, and the captured page itself is untouched - it stays in
`sources` with its text, so a later run that finds a real product on the same site can
still read it.

Safe to re-run: a candidate already decided is left alone.
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from app.core.config import settings
from app.core.db import tenant_session
from app.core.logging import configure_logging, get_logger
from app.models.ai import ExtractedEntity
from app.models.enums import ReviewDecision
from app.services import discovery
from app.services.pump_discovery import KIND, category_page_reason

configure_logging(settings.LOG_LEVEL, json_logs=False)
log = get_logger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", action="store_true", help="reject the candidates")
    args = parser.parse_args()

    with tenant_session(None, is_platform_admin=True) as db:
        pending = db.scalars(
            select(ExtractedEntity).where(
                ExtractedEntity.entity_type == KIND.entity_type,
                ExtractedEntity.promoted_at.is_(None),
                ExtractedEntity.review_decision == ReviewDecision.PENDING,
            )
        ).all()

        cleared = 0
        for entity in pending:
            payload = entity.payload or {}
            subject = payload.get("subject") or {}
            code = subject.get("model_code") or (payload.get("fields") or {}).get("model_code")
            reason = category_page_reason(code)
            if not reason:
                continue

            cleared += 1
            vendor = subject.get("vendor_name") or "unidentified manufacturer"
            print(f"   {vendor:32} {str(code)!r}")
            discovery.reject_candidate(db, entity)
            entity.review_notes = reason

        print(f"\n{cleared} of {len(pending)} pending candidate(s) name a category")
        if args.commit:
            db.commit()
            print("rejected - the queue holds only candidates that can be stored")
        else:
            db.rollback()
            print("dry run - nothing written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
