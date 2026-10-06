"""Duplicate detection and merging.

Two layers, in this order:

1. **Deterministic signals** - normalised name equality, trigram similarity, matching
   duty point, shared website domain. Cheap, explainable, runs on every write.
2. **AI adjudication** - Gemma is asked only about the ambiguous middle band, because
   the interesting cases (same family, different material class or stage count) are
   judgement calls a similarity score gets wrong.

Merging is never automatic. A merge rewrites references and marks the loser with
``merged_into_*``, so nothing is deleted and the decision stays auditable.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.ai import DuplicateCandidate
from app.models.enums import AuditAction
from app.models.pump import Pump, PumpModel
from app.models.search import SearchIndex
from app.models.vendor import Vendor
from app.services import audit
from app.services.promotion import normalize_model_code

log = get_logger(__name__)

# Above this, present as a likely duplicate. Between LOW and HIGH, ask the model.
HIGH_CONFIDENCE = 0.90
LOW_CONFIDENCE = 0.55


@dataclass
class DuplicateSignal:
    name: str
    score: float
    detail: str


def _combine(signals: list[DuplicateSignal]) -> float:
    """The strongest signal, nudged up by whatever corroborates it.

    Two earlier shapes were both wrong. `strongest * 0.8 + support * 0.2` discounted a
    lone signal by a fifth whatever else was present, so a trigram match of 0.615 scored
    0.492 and fell under the recording threshold - "Flowserve" and "Flow Serve" stayed
    two companies because the only signal that identified them was marked down for being
    alone. Taking `max(strongest, weighted)` fixed that and made corroboration count for
    nothing, since the weighted form is below the strongest whenever support is.

    So: start at the strongest signal and spend a fraction of the remaining headroom on
    support. Never below the strongest, always above it when anything agrees, and it
    cannot exceed 1.
    """
    if not signals:
        return 0.0
    strongest = max(s.score for s in signals)
    weaker = [s.score for s in signals if s.score < strongest]
    support = sum(weaker) / len(weaker) if weaker else 0.0
    return round(min(1.0, strongest + (1.0 - strongest) * support * 0.2), 4)


def find_vendor_duplicates(
    db: Session,
    vendor: Vendor,
    *,
    trigram_threshold: float = 0.55,
    limit: int = 10,
    same_tenant_only: bool = True,
) -> list[tuple[Vendor, float, list[DuplicateSignal]]]:
    """Candidate duplicates for one vendor, with the signals that flagged them.

    Scoped to the vendor's own tenancy by default, because that is the only kind of
    duplicate :func:`merge_vendors` will act on — it refuses to merge across a tenant
    boundary, and rightly: one client's supplier record and the shared-master record for
    the same company are separate on purpose. Proposing a pair that can never be merged
    produces a work item nobody can close.


    Pass ``same_tenant_only=False`` to see the overlap anyway, which is information for a
    platform administrator rather than a task: "this company is also recorded in two
    other tenancies".
    """
    similarity = func.similarity(Vendor.normalized_name, vendor.normalized_name)
    stmt = (
        select(Vendor, similarity.label("sim"))
        .where(
            Vendor.id != vendor.id,
            Vendor.deleted_at.is_(None),
            Vendor.merged_into_vendor_id.is_(None),
            similarity >= trigram_threshold,
        )
        .order_by(similarity.desc())
        .limit(limit)
    )
    if same_tenant_only:
        stmt = stmt.where(
            Vendor.tenant_id == vendor.tenant_id
            if vendor.tenant_id is not None
            else Vendor.tenant_id.is_(None)
        )

    results: list[tuple[Vendor, float, list[DuplicateSignal]]] = []
    for candidate, sim in db.execute(stmt).all():
        signals = [DuplicateSignal("trigram_name", float(sim), f"name similarity {float(sim):.2f}")]
        if candidate.normalized_name == vendor.normalized_name:
            signals.append(
                DuplicateSignal("normalized_name", 1.0, "normalised names are identical")
            )
        elif _squash(candidate.normalized_name) == _squash(vendor.normalized_name):
            # "Flowserve" and "Flow Serve"; "Ruhr Pumpen" and "Ruhrpumpen". Trigram
            # similarity treats a space as a real difference and scored this pair 0.615,
            # under the threshold, while a human needs no threshold at all.
            signals.append(
                DuplicateSignal(
                    "squashed_name",
                    0.97,
                    "identical once spaces and punctuation are removed",
                )
            )
        elif _fold_digraphs(candidate.normalized_name) == _fold_digraphs(vendor.normalized_name):
            # "Apollo Goessnitz" and "Apollo Gossnitz" - the company's own ASCII spelling
            # against the accent-folded one. Trigram similarity scores that pair below
            # the threshold; a German reader would not hesitate.
            signals.append(
                DuplicateSignal(
                    "transliterated_name",
                    0.9,
                    "identical once umlaut spellings are reconciled",
                )
            )
        if vendor.website and candidate.website:
            if _domain(vendor.website) == _domain(candidate.website):
                signals.append(DuplicateSignal("website", 0.95, "same web domain"))
        if vendor.country and candidate.country == vendor.country:
            signals.append(DuplicateSignal("country", 0.4, "same country"))
        if vendor.dun_bradstreet_number and (
            candidate.dun_bradstreet_number == vendor.dun_bradstreet_number
        ):
            signals.append(DuplicateSignal("dnb", 1.0, "same D&B number"))
        aliases = {a.lower() for a in (candidate.aliases or [])}
        if vendor.name.lower() in aliases:
            signals.append(DuplicateSignal("alias", 0.9, "name matches a recorded alias"))
        results.append((candidate, _combine(signals), signals))

    results.sort(key=lambda item: item[1], reverse=True)
    return results


def _squash(name: str) -> str:
    """A name with every space and separator removed, for comparing spellings."""
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


#: How a German or Nordic name is written when the keyboard has no umlaut.
#:
#: The normaliser folds accents, so "Gößnitz" becomes "gossnitz". A company writing its
#: own name in ASCII does not fold, it expands: Apollo Gößnitz GmbH writes itself
#: "Apollo Goessnitz GmbH", and its domain is apollo-goessnitz.de. Both spellings are in
#: this database, as two records with two different normalised names and two different
#: sets of pump models, and neither dedupe pass could see the other.
_EXPANSIONS = {"ae": "a", "oe": "o", "ue": "u", "ss": "s"}


def _fold_digraphs(name: str) -> str:
    """The squashed name with ASCII-expanded umlauts collapsed back.

    "goessnitz" and "gossnitz" both become "gosnitz". Applied to both sides, so it only
    ever compares like with like - and it is a *signal*, never the stored key, because
    collapsing doubled letters loses information a person may need back.
    """
    folded = _squash(name)
    for digraph, single in _EXPANSIONS.items():
        folded = folded.replace(digraph, single)
    return folded


def _domain(url: str) -> str:
    from urllib.parse import urlparse

    netloc = urlparse(url if "//" in url else f"//{url}").netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


def find_pump_model_duplicates(
    db: Session, pump_model_id: uuid.UUID, *, limit: int = 10
) -> list[tuple[uuid.UUID, float, list[DuplicateSignal]]]:
    """Duplicate models: same vendor, near-identical code, matching duty point."""
    anchor = db.scalar(select(SearchIndex).where(SearchIndex.pump_model_id == pump_model_id))
    if anchor is None:
        return []

    stmt = select(SearchIndex).where(
        SearchIndex.pump_model_id != pump_model_id,
        SearchIndex.vendor_id == anchor.vendor_id,
    )
    anchor_code = normalize_model_code(anchor.model_code)
    out: list[tuple[uuid.UUID, float, list[DuplicateSignal]]] = []

    for row in db.scalars(stmt).all():
        signals: list[DuplicateSignal] = []
        candidate_code = normalize_model_code(row.model_code)
        if candidate_code and candidate_code == anchor_code:
            signals.append(DuplicateSignal("model_code", 1.0, "identical normalised model code"))
        elif (
            candidate_code
            and anchor_code
            and (candidate_code in anchor_code or anchor_code in candidate_code)
        ):
            signals.append(
                DuplicateSignal("model_code_prefix", 0.7, "one model code contains the other")
            )

        if (
            anchor.rated_capacity_m3h
            and row.rated_capacity_m3h
            and anchor.rated_head_m
            and (row.rated_head_m)
        ):
            capacity_delta = abs(
                (row.rated_capacity_m3h - anchor.rated_capacity_m3h) / anchor.rated_capacity_m3h
            )
            head_delta = abs((row.rated_head_m - anchor.rated_head_m) / anchor.rated_head_m)
            if capacity_delta < Decimal("0.02") and head_delta < Decimal("0.02"):
                signals.append(DuplicateSignal("duty_point", 0.85, "duty point matches within 2%"))
            elif capacity_delta < Decimal("0.10") and head_delta < Decimal("0.10"):
                signals.append(
                    DuplicateSignal("duty_point_near", 0.5, "duty point matches within 10%")
                )

        # Material class and standard disagreement is the classic false positive:
        # the same hydraulic in S-6 and A-8 is two genuinely different products.
        if (
            anchor.material_class
            and row.material_class
            and (anchor.material_class != row.material_class)
        ):
            signals.append(
                DuplicateSignal(
                    "material_class_conflict",
                    -0.35,
                    f"different material class ({anchor.material_class} vs {row.material_class})",
                )
            )

        positives = [s for s in signals if s.score > 0]
        if not positives:
            continue
        score = _combine(positives) + sum(s.score for s in signals if s.score < 0)
        out.append((row.pump_model_id, round(max(0.0, min(1.0, score)), 4), signals))

    out.sort(key=lambda item: item[1], reverse=True)
    return out[:limit]


def record_candidates(
    db: Session,
    *,
    tenant_id: uuid.UUID | None,
    entity_type: str,
    anchor_id: uuid.UUID,
    candidates: list[tuple[uuid.UUID, float, list[DuplicateSignal]]],
    detection_method: str = "deterministic",
    min_score: float = LOW_CONFIDENCE,
) -> list[DuplicateCandidate]:
    """Persist candidate pairs, ordering ids so a pair is never stored twice."""
    created: list[DuplicateCandidate] = []
    for candidate_id, score, signals in candidates:
        if score < min_score:
            continue
        id_a, id_b = sorted([anchor_id, candidate_id], key=str)
        existing = db.scalar(
            select(DuplicateCandidate).where(
                DuplicateCandidate.tenant_id == tenant_id,
                DuplicateCandidate.entity_type == entity_type,
                DuplicateCandidate.entity_id_a == id_a,
                DuplicateCandidate.entity_id_b == id_b,
            )
        )
        signal_map = {s.name: {"score": s.score, "detail": s.detail} for s in signals}
        if existing is not None:
            if existing.status == "open":
                existing.similarity_score = Decimal(str(score))
                existing.match_signals = signal_map
            continue
        row = DuplicateCandidate(
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_id_a=id_a,
            entity_id_b=id_b,
            similarity_score=Decimal(str(score)),
            match_signals=signal_map,
            detection_method=detection_method,
            status="open",
        )
        db.add(row)
        created.append(row)
    db.flush()
    return created


def scan_vendor(db: Session, vendor: Vendor) -> list[DuplicateCandidate]:
    candidates = [
        (candidate.id, score, signals)
        for candidate, score, signals in find_vendor_duplicates(db, vendor)
    ]
    return record_candidates(
        db,
        tenant_id=vendor.tenant_id,
        entity_type="vendors",
        anchor_id=vendor.id,
        candidates=candidates,
    )


def scan_pump_model(db: Session, pump_model: PumpModel) -> list[DuplicateCandidate]:
    return record_candidates(
        db,
        tenant_id=pump_model.tenant_id,
        entity_type="pump_models",
        anchor_id=pump_model.id,
        candidates=find_pump_model_duplicates(db, pump_model.id),
    )


def merge_vendors(
    db: Session,
    *,
    keep_id: uuid.UUID,
    merge_id: uuid.UUID,
    principal=None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Repoint a duplicate vendor's children and retire it. Nothing is deleted."""
    keep = db.get(Vendor, keep_id)
    loser = db.get(Vendor, merge_id)
    if keep is None or loser is None:
        raise ValueError("Both vendors must exist to merge")
    if keep.id == loser.id:
        raise ValueError("Cannot merge a vendor into itself")
    if keep.tenant_id != loser.tenant_id:
        raise ValueError("Refusing to merge vendors across tenant boundaries")

    moved_pumps = db.execute(
        update(Pump).where(Pump.vendor_id == loser.id).values(vendor_id=keep.id)
    ).rowcount

    # Keep the losing name searchable as an alias.
    aliases = list(keep.aliases or [])
    for alias in [loser.name, *(loser.aliases or [])]:
        if alias and alias not in aliases and alias != keep.name:
            aliases.append(alias)
    keep.aliases = aliases

    # Fill gaps on the surviving record rather than overwriting anything.
    for column in keep.__table__.columns:
        name = column.name
        if name in {
            "id",
            "tenant_id",
            "created_at",
            "updated_at",
            "name",
            "normalized_name",
            "aliases",
            "merged_into_vendor_id",
        }:
            continue
        if getattr(keep, name, None) in (None, "", [], {}) and getattr(loser, name, None) not in (
            None,
            "",
            [],
            {},
        ):
            setattr(keep, name, getattr(loser, name))

    loser.merged_into_vendor_id = keep.id
    loser.deleted_at = func.now()

    db.execute(
        update(DuplicateCandidate)
        .where(
            DuplicateCandidate.entity_type == "vendors",
            DuplicateCandidate.entity_id_a.in_([keep.id, loser.id]),
            DuplicateCandidate.entity_id_b.in_([keep.id, loser.id]),
        )
        .values(status="merged", merged_into_id=keep.id, notes=notes)
    )

    audit.record_audit(
        db,
        action=AuditAction.MERGE,
        principal=principal,
        entity_type="vendors",
        entity_id=keep.id,
        entity_label=keep.name,
        summary=f"Merged vendor {loser.name} into {keep.name}",
        changes={"merged_vendor_id": {"from": None, "to": str(loser.id)}},
        context={"pumps_moved": moved_pumps, "notes": notes},
        tenant_id=keep.tenant_id,
    )
    db.flush()
    log.info(
        "dedupe.vendors_merged",
        keep_id=str(keep.id),
        merged_id=str(loser.id),
        pumps_moved=moved_pumps,
    )
    return {"kept": str(keep.id), "merged": str(loser.id), "pumps_moved": moved_pumps}


def adjudicate_with_ai(
    db: Session,
    *,
    tenant_id: uuid.UUID | None,
    entity_type: str,
    record_a: dict[str, Any],
    record_b: dict[str, Any],
    candidate: DuplicateCandidate | None = None,
    client=None,
    user_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Ask Gemma to settle an ambiguous pair. Advisory only - a human still merges."""
    import json

    from app.ai import prompts
    from app.ai.openrouter import OpenRouterClient
    from app.models.enums import AiJobType
    from app.services import extraction

    client = client or OpenRouterClient()
    payload = json.dumps({"record_a": record_a, "record_b": record_b}, indent=2, default=str)
    job, result, error = extraction.execute_ai_job(
        db,
        client,
        prompts.SYSTEM_DEDUPE,
        payload,
        job_kwargs={
            "tenant_id": tenant_id,
            "job_type": AiJobType.DEDUPE_CANDIDATE,
            "subject_type": entity_type,
            "subject_id": candidate.id if candidate else None,
            "prompt_name": "dedupe_candidate",
            "request_payload": {"entity_type": entity_type},
            "model": client.model,
            "user_id": user_id,
        },
    )
    if error is not None:
        raise error
    verdict = (result.data if result else None) or {}
    if candidate is not None:
        candidate.detection_method = "ai"
        candidate.ai_job_id = job.id
        signals = dict(candidate.match_signals or {})
        signals["ai_verdict"] = {
            "verdict": verdict.get("verdict"),
            "confidence": verdict.get("confidence"),
            "reason": verdict.get("reason"),
        }
        candidate.match_signals = signals
        if verdict.get("verdict") == "different":
            candidate.status = "distinct"
        db.flush()
    return verdict
