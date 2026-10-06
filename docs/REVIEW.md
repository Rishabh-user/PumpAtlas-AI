# Project review — October 2026

A full pass over PumpAtlas AI: code, database, security posture and operations. Findings
are ordered by what they cost if left alone, each with the evidence behind it and what
fixing it involves. Everything here was measured against the running system on
2026-10-06, not inferred from the code.

**Verdict.** The engineering is sound and unusually disciplined in the places that are
hardest to retrofit — tenant isolation, provenance, and the write gate that refuses
unevidenced values. The risks are not in the architecture. They are that the whole thing
is unversioned, that a client's commercially sensitive documents sit unprotected in the
working tree, and that most of the data now in the database arrived through an import
path that bypasses the guarantees the rest of the system is built on.

---

## What is working

Credit where it is due, because these are the parts that are expensive to add later.

| | Evidence |
| --- | --- |
| Tenant isolation | Row-level security **enabled and forced** on every tenant table, with policies — `vendors`, `pump_models`, `search_index`, `vendor_contacts`, `field_provenance`, `sources`, `audit_logs`, `users`, `api_keys`. The application connects as `pumpatlas_app`: not a superuser, and **does not bypass RLS**. Isolation cannot be undone by an application bug. |
| Tests | 879 passing, 32 skipped (all requiring a live stack), lint clean across `app`, `tests` and `scripts`. |
| Frontend | Compiles clean; the client/server boundary check passes across 98 files and 44 client modules. |
| Traceability | 1,634 field-provenance rows, 184 record versions, 508 audit entries. Every AI-written value carries a verbatim quote or it is refused. |
| Deduplication | **Zero** duplicate normalised names within any tenancy, across 1,684 vendors. |
| Dependencies | 24 pinned versions, no floating ranges. |
| Code hygiene | Zero `TODO`/`FIXME`/`HACK` markers in 30k lines of Python and 16.5k of TypeScript. |
| Known AI failures | The 9 failed provider jobs are all from 2–7 September; the "assistant prefill" 400s are already handled by a retry path that drops the unsupported feature. Not an open defect. |

---

## Critical

### C1 · The project is not under version control

`git rev-parse` reports no repository. 46,000 lines of code, a schema, and a fleet of
operational scripts, with **no history, no branches, no diffs, no blame and no way back**.

This is the finding that makes every other finding worse. Several agent sessions have
been editing these same files — this review found files changed since the last session
with no record of what changed or why. One bad overwrite is unrecoverable.

```bash
cd "D:/Targeticon/PumpAtlas AI"
# Do C2 FIRST — see below — then:
git init && git add -A && git commit -m "PumpAtlas AI: initial import"
```

### C2 · Client-confidential documents sit in the tree and are not ignored

`Approved Vendor List/` holds a **signed** approved suppliers list (ONGC KG-DWN-98/2) and
five SAP vendor-master exports. `.gitignore` does not mention them.

An approved vendor list tells a competitor who a client will buy from; the import script's
own docstring says so. The moment someone runs `git add .` — which C1 asks for — that
goes into history permanently, and history is what gets pushed to a remote.

**Do this before `git init`:**

```bash
printf '\n# Client documents: commercially sensitive, never committed.\nApproved Vendor List/\n*.XLSX\n' >> .gitignore
```

Also note there are two `.env` files (repo root and `backend/`). Both are matched by the
existing `.env` rule; confirm that after `git init` with `git check-ignore -v .env backend/.env`.

### C3 · Migration 002 has never been applied

```
migration 002 applied: False
```

`vendor_contacts` still lacks `source_id`, `captured_at` and `origin`. The guard built for
this behaves correctly — contact auto-recording is skipped rather than writing untraceable
values — but it means the feature has been inert since it was written, and it blocks H1
below.

```bash
python scripts/apply_schema.py --url "postgresql://OWNER:PASSWORD@HOST/DB?sslmode=require" \
    --file db/migrations/002_vendor_contact_provenance.sql
```

Restart the API afterwards; the column check is cached per process.

---

## High

### H1 · 1,426 contacts are trapped in a JSON blob

| | |
| --- | --- |
| Contacts inside `vendors.extra->'contacts'` | **1,426**, across 1,350 vendors |
| Rows in `vendor_contacts` | **1** |

The blobs already have the shape of the table:

```json
{ "role": "commercial", "email": "...@2hoffshore.com",
  "phone": "60327260500", "company_name": "2H OFFSHORE ENGINEERING SDN BHD" }
```

Because they are in `extra`, they are invisible to `GET /vendors/{id}/contacts`, to the
Contacts panel on the vendor page (which reads "No contacts recorded" for all 1,350), and
to the external API handed to the other project. They cannot be searched, deduplicated or
checked against the contact details found on the web.

This is the single highest-value fix in the review: the data is already there and correct,
it is simply in the wrong place. A migration script should move each entry into
`vendor_contacts` with `origin='manual'` and `source_id` pointing at the import document
that carried it — which requires **C3 first**, since those columns do not exist yet.

### H2 · 241 vendors are "approved" with nobody accountable

```
approval_status | n   | with approver | with expiry | with provenance
approved        | 241 | 0             | 0           | 2
```

These came from the client's approved supplier lists, so the *status* is legitimate — but
the record does not say who approved them, under what authority, or when it lapses. An
approval nobody can account for is the thing `approval_status` exists to prevent, and it
is now the state of 241 records rather than the 2 this review caught last month.

`POST /vendors/{id}/qualification` records all three and refuses a decision without a
reason. The import path writes the column directly and bypasses it. Either route the
import through that endpoint's logic, or have it stamp the approving document as the
provenance source and the list's own date as the expiry.

### H3 · No rate limiting, on an API that now spends money

There is no limiter anywhere in `app/main.py` or `app/core/`. Login lockout exists (5
attempts), but nothing else is bounded.

Two active API keys have been issued to another project. `POST /chat/ask` with
`use_web: true` triggers a web search and reads pages — real provider spend per call — and
`POST /vendors/{id}/enrich` starts a discovery run. A loop at the far end, or one leaked
key, is an unbounded bill with no ceiling and no alert.

At minimum: a per-key request limit on the AI endpoints, and a daily cap on provider spend.

### H4 · The quality dashboard is averaging 0.5% of the data

```
vendors      1684 rows, 8 with a completeness figure
pump_models   160 rows, 79 with a completeness figure
```

`repair_vendor_data` was never run at scale, so `data_completeness_pct` is unset on 1,676
vendors. The dashboard average, the "least complete" sort and the `completeness_min`
filter are all computed from the handful that have it — which is worse than showing
nothing, because it looks like an answer.

```bash
python -m scripts.repair_vendor_data            # dry run
python -m scripts.repair_vendor_data --commit
```

---

## Medium

### M1 · A quarter of all discovery runs die from API restarts

22 of 97 runs failed with *"Interrupted by an API restart. This run executed in the API
process."* Redis is absent, so `dispatch` falls back to running discovery inside the API
worker, and any reload kills it mid-flight.

The fallback is the right design for a developer machine; it is not a deployment. Running
Redis and a Celery worker turns a 23% loss rate into zero, and is the difference between
"the sweep is still going" and "the sweep died when you saved a file".

### M2 · The search index is going stale and nothing refreshes it

87 of 160 rows were last indexed more than a week ago. Nothing missing (0 models absent —
that gap was fixed), but nothing scheduled either: a row refreshes only when its record is
written. Vendor-level changes — a new name, a country, an approval — do not reach the index
until something touches the model.

### M3 · Two of the five scorecards cannot score

| group | current rows (of 160 models) |
| --- | --- |
| technical | 76 |
| delivery | 7 |
| commercial | **4** |
| administrative | 4 |
| dimensional | 3 |
| operational | **2** |

Commercial fit and delivery risk are structurally 0.0/E for almost every record, and will
stay that way until datasheets are read. `scripts.pending_pumps` lists exactly which
records are waiting and what each is missing; the "Find datasheet" button on a model is
the per-record action.

### M4 · 27 candidates are still waiting in the pump review queue

Some are the API-type-code category pages ("OH1", "VS6", "API 610 OH1") that are now
refused at screening. The cleanup for the ones already queued has not been run:

```bash
python -m scripts.clear_category_candidates    # then --commit
python -m scripts.flag_category_models         # 13 models named after a category
```

### M5 · One table has no row-level security

`ai_provider_configs` — the only table in `public` with RLS off. It is platform-scoped
(no `tenant_id` column), so this is defensible: there is no tenant boundary to enforce.
Its protection is that `encrypted_api_key` is Fernet-encrypted and the role reaching it is
`pumpatlas_app`. Worth a comment in the schema saying that is deliberate, so the next
person auditing does not have to work it out.

---

## Carried over, unverified

These were raised in earlier sessions and I cannot confirm their state from here:

* **Credential rotation.** Five credentials reached a chat transcript and should be treated
  as compromised: the Render owner database password, the `pumpatlas_app` password, and the
  OpenAI, Anthropic and Parallel API keys.
* **The default admin password.** `admin@targeticon.com` was created with a published
  default. `python -m scripts.manage_user set-password --email admin@targeticon.com`.

---

## What I would do, in order

1. **Add the client documents to `.gitignore`** (C2) — five minutes, and it must precede step 2.
2. **`git init` and commit** (C1). Nothing else on this list is safe to do without it.
3. **Apply migration 002** (C3), restart the API.
4. **Move the 1,426 contacts out of `extra`** (H1) — the biggest visible improvement for the least work.
5. **Run `repair_vendor_data --commit`** (H4), and the two queue cleanups (M4).
6. **Put a limiter on the AI endpoints** (H3) before the other project goes live.
7. **Give the imported approvals an approver and an expiry** (H2).
8. **Stand up Redis and a worker** (M1) when discovery stops being something a person watches.

Items 1–5 are a day's work and remove every finding that is currently costing something.
