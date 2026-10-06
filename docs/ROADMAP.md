# Roadmap

Status against the three phases in the brief.

## Phase 1 - MVP: ingestion, schema, search, basic AI extraction

**Built.**

| Capability | Where |
| --- | --- |
| PostgreSQL schema: 36 tables, 1141 columns | `db/schema.sql`, generated from `backend/app/models` |
| RLS tenant isolation + shared master data | `db/rls.sql` |
| Spec versioning triggers, search-vector trigger | `db/functions.sql` |
| Ingestion: upload, URL, crawl, API, manual form, Parallel AI results | `app/services/ingestion.py`, `app/api/v1/ingest.py` |
| Parsing: PDF, DOCX, XLSX, CSV, HTML with tables preserved | `app/services/parsing.py` |
| Gemma extraction with per-field confidence and evidence quotes | `app/ai/`, `app/services/extraction.py` |
| Promotion into the system of record, with provenance | `app/services/promotion.py` |
| Full-text search, structured filters, facets, similar-pump matching | `app/services/search.py` |
| Auth, RBAC across six roles, API keys | `app/core/security.py`, `app/core/rbac.py` |
| Celery pipeline on separate ingest / ai / index queues | `app/workers/` |
| Dashboard: search, vendors, pump profile, imports, AI review, quality, audit, tenants | `frontend/src/app/` |
| Compose stack: Postgres, Redis, MinIO, API, worker, beat, frontend | `docker-compose.yml` |

## Phase 2 - enrichment, comparison, scorecards, multi-tenant access

**Built.**

| Capability | Where |
| --- | --- |
| Missing-field detection, normalisation, vendor summaries | `app/workers/tasks.py`, `app/api/v1/ai_review.py` |
| Field-level suggestions with human approval | `ai_suggestions`, AI review screen |
| Contradiction, out-of-range and unit-mistake detection | `app/services/quality.py` |
| Duplicate detection (deterministic + AI adjudication) and merge | `app/services/dedupe.py` |
| Four scorecards plus a weighted overall, with per-criterion breakdown | `app/services/scoring.py` |
| Requirement profiles: duty point, hard requirements, tenant weighting | `requirement_profiles` |
| Comparison view with a frozen snapshot and optional AI narrative | `app/services/comparison.py` |
| Change tracking: spec versions, row snapshots, field history | `record_versions`, `field_provenance` |
| Tenant management, entitlements, cross-tenant grants, quotas | `app/api/v1/tenants.py` |

## Phase 3 - advanced analytics, alerts, vendor intelligence, enterprise controls

**Foundations in place; the following remain.**

| Capability | Status | What is already there |
| --- | --- | --- |
| Saved-search alerting | Not built | `saved_searches.alert_enabled` / `alert_frequency` / `last_alert_at` exist; needs a beat task and a delivery channel |
| Price-trend and benchmark analytics | Not built | Every spec row is versioned with dates, so the time series is already captured |
| Vendor risk scoring over time | Not built | Scorecards are stored per computation with `computed_at`; needs trend aggregation |
| OpenSearch backend | Not built | `search_index` is designed as the seam - add a second consumer of the same table |
| SSO / SAML / OIDC | Not built | Auth is centralised in `core/security.py` and `core/deps.py`; MFA columns exist on `users` |
| Field-level encryption for commercial terms | Not built | Encryption at rest is at the volume and S3 layer today |
| `audit_logs` partitioning | Not built | Already a bigint identity PK read in time order; partition by month |
| Export to Excel / PDF decision packs | Not built | `comparisons.snapshot` holds everything a pack needs |
| Real cron parsing for crawl schedules | Approximate | `_next_run()` is a coarse estimate; swap in `croniter` without touching callers |
| Windows worker concurrency | Workaround | Celery needs `--pool=solo` on Windows (no `fork()`); Linux uses the prefork pool normally |
| OCR for scanned datasheets | Not built | The PDF parser already flags "likely scanned, needs OCR" |

## What has been verified against a live stack

Run on Windows 11 with PostgreSQL 16, Redis 7 and MinIO in containers:

| Verified | How |
| --- | --- |
| All five SQL files apply cleanly | Container init log, zero errors |
| 36 tables, 1141 columns, 25 enums, 55 RLS policies, 9 triggers | Queried from `pg_catalog` |
| Tenant isolation | A second tenant's records are invisible to the first by search, by direct UUID, and through similar-pump matching |
| Platform-admin tenant scoping | `X-Tenant-Id` narrows the visible data rather than bypassing it |
| Spec versioning triggers | Version 2 inserted, version 1 retired by the trigger, both readable |
| Provenance across versions | Carried-forward fields keep their lineage after an unrelated edit |
| Quality validators | Contradictory weights and a feet-as-metres value both flagged, with plain-language messages |
| Scoring and comparison | Scored against a requirement profile, ranked, snapshot frozen |
| RBAC | A client user is refused commercial writes, ingestion, the quality dashboard and the audit trail |
| Audit trail | Logins and writes recorded with diffs |
| Duplicate detection | `pg_trgm` flags a near-duplicate vendor with explainable signals |
| Celery pipeline | Task dispatched from the app, executed by the worker, search index updated |
| Frontend | Login sets an httpOnly cookie; the dashboard renders live KPIs; the proxy attaches the token and returns 401 without it |

`backend/tests/test_live_integration.py` holds these as 32 repeatable tests.

## Bugs this verification found

Every one of these was invisible to the offline suite:

| Bug | Consequence had it shipped |
| --- | --- |
| Six spec tables shared one explicit constraint name | The schema would not apply at all - PostgreSQL rejected the second `CREATE` |
| `CORS_ORIGINS` typed as `list[str]` | The app would not start from any `.env` file |
| `Tenant.permissions` had two FK paths to `tenants` | First ORM use raised `AmbiguousForeignKeysError` |
| Tenant GUC was transaction-local only | Every create-then-read handler lost tenant context after `commit()` and was denied by RLS |
| UUID columns typed as `str` in response schemas | The provenance endpoint returned 500 |
| Provenance summary scoped to the `pump_models` row | The headline "% AI-derived" always read zero - the platform's central claim, silently broken |
| `X-Tenant-Id` kept the platform-admin RLS bypass on | Support staff believing they were scoped to one client would in fact see every client |
| A new spec version did not carry values forward on the promotion path | Promoting three extracted fields would retire a version holding twenty |
| Carried-forward values lost their provenance | Traceability lasted exactly one edit |
| `audit._jsonable` did not handle `date` or enums | Every spec write failed on the JSONB audit snapshot |
| Tasks declared with `@shared_task`, no configured app imported | Every background job published to RabbitMQ on 5672 instead of Redis, in every environment |
| `passlib` 1.7.4 reads `bcrypt.__about__` | Spurious error logged on every password operation |

## Known limitations, stated plainly

* **Parallel AI endpoint shape.** The Search API is versioned beta. The client posts to
  `/v1beta/search` and normalises the documented response shape plus common variants;
  verify it against current API docs before production use.
* **`_next_run()` is approximate.** Beat dispatches due schedules every 15 minutes, so a
  coarse estimate prevents double-firing, but it is not a cron implementation.
* **Local storage mode is development only.** No durability guarantees; set S3
  credentials for anything real.
* **The AI and web-search paths are still unexercised.** Everything else has been run
  against a live stack, but extraction, enrichment, vendor summarisation and Parallel AI
  discovery need real `OPENROUTER_API_KEY` and `PARALLEL_API_KEY` credentials. The code
  paths, prompts, JSON recovery and job accounting are implemented and unit-tested; what
  has not happened is a real model call.
* **`ai_jobs.cost_usd` depends on the provider reporting cost.** OpenRouter returns it in
  `usage.cost` on most models; where it does not, the column stays null and only tokens
  are recorded.
