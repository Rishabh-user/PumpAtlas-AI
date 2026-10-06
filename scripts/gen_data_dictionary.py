"""Generate ``docs/DATA_DICTIONARY.md`` from the models.

Two parts:

1. A **requirements traceability matrix** - every field named in the product brief,
   mapped to the column that holds it. If a mapped column does not exist, this script
   exits non-zero, which is what stops the schema drifting away from the brief.
2. A full table-by-table dictionary with types, nullability and column comments.

    python scripts/gen_data_dictionary.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.models import Base  # noqa: E402
from requirements_map import REQUIREMENTS, all_referenced_columns  # noqa: E402
from sqlalchemy.dialects import postgresql  # noqa: E402

DIALECT = postgresql.dialect()

TABLE_NOTES: dict[str, str] = {
    "tenants": "Client companies. The root of every isolation boundary.",
    "tenant_permissions": "Per-tenant feature entitlements and cross-tenant sharing grants.",
    "users": "People. ``tenant_id IS NULL`` marks Targeticon platform staff.",
    "roles": "The six product roles, with their resource/action matrix.",
    "user_roles": "Role assignment join table.",
    "api_keys": "Machine credentials for API-first integrations. Only hashes are stored.",
    "vendors": "Suppliers. ``tenant_id IS NULL`` marks curated shared master data.",
    "vendor_contacts": "Authorized representatives, agents and service contacts.",
    "pumps": "Vendor product lines, e.g. a named API 610 family.",
    "pump_models": "Orderable configurations. Every spec table hangs off this row.",
    "technical_specs": "Hydraulic, mechanical, material, certification and testing data.",
    "commercial_specs": "Pricing, terms, warranty, escalation and life-cycle economics.",
    "dimensional_specs": "Weights, envelope, lifting and foundation loading.",
    "delivery_specs": "Lead time, logistics, FAT and export control.",
    "operational_specs": "Track record, references, service network, HSE and QA/QC.",
    "administrative_specs": "Legal entity, representation, ESG, cyber and data quality.",
    "sources": "Captured evidence: raw content, parsed text, capture date, confidence.",
    "documents": "Binary artefacts in object storage, with checksums.",
    "import_batches": "One ingestion run. Drives the import queue screen.",
    "crawl_schedules": "Scheduled crawl and periodic web-search targets.",
    "ai_jobs": "Every AI or web-search call, with tokens, cost, latency and prompt version.",
    "extracted_entities": "Candidate records from the model, awaiting human review.",
    "ai_suggestions": "Field-level proposals awaiting approval on the AI review screen.",
    "field_provenance": "Per-field lineage. The answer to 'where did this number come from?'.",
    "confidence_scores": "Stored scorecards: technical, commercial, delivery, data confidence.",
    "data_quality_flags": "Contradictions, out-of-range values, staleness, duplicate suspicion.",
    "duplicate_candidates": "Suspected duplicate pairs, with the signals that flagged them.",
    "search_index": "Denormalised one-row-per-model index backing full-text search.",
    "requirement_profiles": "The buyer's duty point and acceptance criteria.",
    "comparisons": "Saved side-by-side evaluations - the procurement deliverable.",
    "comparison_items": "One scored candidate inside a comparison.",
    "saved_searches": "Stored queries, optionally alerting on new matches.",
    "tags": "Analyst-managed labels: watchlists, project codes, risk markers.",
    "tagged_records": "Tag assignment join table.",
    "audit_logs": "Append-only audit trail. Highest-volume table; partition by month.",
    "record_versions": "Full-row snapshots for change tracking and rollback.",
}


def known_columns() -> set[str]:
    return {
        f"{table.name}.{column.name}"
        for table in Base.metadata.sorted_tables
        for column in table.columns
    }


def verify_mapping() -> list[str]:
    """Every column named in the requirements map must exist. Returns the missing ones."""
    existing = known_columns()
    return [column for column in all_referenced_columns() if column not in existing]


def render_matrix() -> str:
    lines = [
        "## 1. Requirements traceability",
        "",
        "Every intelligence field named in the product brief, and the column that holds it.",
        "`scripts/gen_data_dictionary.py` fails if any column listed here is missing from",
        "the models, so this table cannot go stale.",
        "",
    ]
    for group, requirements in REQUIREMENTS.items():
        lines.append(f"### {group}")
        lines.append("")
        lines.append("| Required field | Columns |")
        lines.append("| --- | --- |")
        for requirement, columns in requirements.items():
            rendered = "<br>".join(f"`{column}`" for column in columns)
            lines.append(f"| **{requirement}** | {rendered} |")
        lines.append("")
    return "\n".join(lines)


def render_dictionary() -> str:
    lines = [
        "## 2. Table reference",
        "",
        "Generated from `backend/app/models`. Units are carried in column names",
        "(`_m3h`, `_m`, `_kw`, `_kg`, `_mm`, `_barg`, `_c`, `_usd`); values are stored in SI",
        "with the original figure preserved in `source_units` and",
        "`field_provenance.original_value`.",
        "",
    ]
    for table in sorted(Base.metadata.sorted_tables, key=lambda t: t.name):
        note = TABLE_NOTES.get(table.name, "")
        lines.append(f"### `{table.name}`")
        lines.append("")
        if note:
            lines.append(note)
            lines.append("")
        lines.append("| Column | Type | Null | Notes |")
        lines.append("| --- | --- | --- | --- |")
        for column in table.columns:
            type_name = column.type.compile(dialect=DIALECT)
            nullable = "yes" if column.nullable else "no"
            note_text = (column.comment or "").replace("|", r"\|")
            if column.foreign_keys:
                targets = ", ".join(
                    f"`{fk.column.table.name}.{fk.column.name}`" for fk in column.foreign_keys
                )
                note_text = f"FK to {targets}. {note_text}".strip()
            if column.primary_key:
                note_text = f"Primary key. {note_text}".strip()
            lines.append(f"| `{column.name}` | {type_name} | {nullable} | {note_text} |")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    missing = verify_mapping()
    if missing:
        print("Requirements map references columns that do not exist:", file=sys.stderr)
        for column in missing:
            print(f"  - {column}", file=sys.stderr)
        return 1

    tables = len(Base.metadata.tables)
    columns = sum(len(t.columns) for t in Base.metadata.tables.values())
    requirement_count = sum(len(group) for group in REQUIREMENTS.values())

    header = f"""# PumpAtlas AI - data dictionary

**GENERATED FILE** - do not edit by hand.
Regenerate with `python scripts/gen_data_dictionary.py`.

PostgreSQL is the system of record. {tables} tables, {columns} columns,
{requirement_count} brief requirements mapped, all verified present.

---

"""
    target = ROOT / "docs" / "DATA_DICTIONARY.md"
    target.write_text(header + render_matrix() + "\n" + render_dictionary(), encoding="utf-8")
    print(f"wrote {target.relative_to(ROOT)}")
    print(f"  requirements mapped: {requirement_count}")
    print(f"  columns referenced:  {len(all_referenced_columns())}")
    print(f"  tables documented:   {tables}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
