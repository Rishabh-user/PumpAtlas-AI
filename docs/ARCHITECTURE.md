# Architecture

## The one rule everything else follows

**PostgreSQL is the system of record. AI is an assistant layer that proposes; it never
writes.**

Every intelligence value in the platform is a row in PostgreSQL with a version history
and a provenance record naming its source. Gemma and Parallel AI produce *candidates*
which land in `extracted_entities` and `ai_suggestions`; a human (or an explicit
auto-promote threshold) turns a candidate into a fact. That boundary is enforced in code,
not by convention - see [AI and provenance](AI_AND_PROVENANCE.md).

## Request path

```
Browser
  |
  |  session token in an httpOnly cookie
  v
Next.js (server components + /api/proxy route handler)
  |
  |  Authorization: Bearer ..., X-Tenant-Id
  v
FastAPI  ---->  PostgreSQL  (RLS bound to app.tenant_id for the transaction)
  |               ^
  |               |
  +--> Redis ---> Celery workers (ingest / ai / index queues)
                    |
                    +--> OpenRouter (Gemma)      extraction, normalisation, QC
                    +--> Parallel AI             web search orchestration
                    +--> S3 / MinIO              documents
```

The browser never holds the API token and never learns the API host. The
`/api/proxy/[...path]` route handler moves the token from the cookie into an
`Authorization` header server-side.

## Layers in the backend

| Layer | Path | Responsibility |
| --- | --- | --- |
| API | `app/api/v1/` | HTTP shape, status codes, RBAC guards. No business logic. |
| Schemas | `app/schemas/` | Validation and serialisation. Spec schemas are **derived from the models** (`schemas/derive.py`) so 400+ columns cannot drift. |
| Services | `app/services/` | All business logic: ingestion, extraction, promotion, scoring, dedupe, quality, indexing. |
| AI clients | `app/ai/` | OpenRouter and Parallel AI transport, prompts, JSON recovery. |
| Models | `app/models/` | SQLAlchemy 2.0 declarative models - the single definition of the schema. |
| Workers | `app/workers/` | Celery tasks. Each opens its own tenant-scoped session. |
| Core | `app/core/` | Settings, DB engine, security, RBAC matrix, dependencies, logging. |

`db/schema.sql` is **generated** from the models by `scripts/gen_schema.py`, so the SQL
file and the ORM can never disagree. `scripts/check.sh` fails the build if it is stale.

The SQL files apply in a fixed order: `extensions.sql` (pgcrypto, pg_trgm, unaccent,
btree_gin and the `pumpatlas` text-search configuration), `schema.sql`, `functions.sql`
(triggers), `rls.sql` (policies), `app_role.sql` (the `NOBYPASSRLS` application role).
`partitions.sql` is optional and only needed once `audit_logs` grows.

## The ingestion pipeline

```
 upload / URL / crawl / API / manual form / Parallel AI result
                        |
                        v
                 sources  (raw content + parsed text + capture date + confidence)
                        |
                 [Celery: ai queue]
                        v
              extracted_entities  (candidate JSON + per-field confidence + evidence quote)
                        |
              AI review screen, or auto-promote above 0.85 confidence
                        v
        vendors -> pumps -> pump_models -> the six spec tables
                        |
                        +--> field_provenance   (one row per field written)
                        +--> record_versions    (row snapshot + diff)
                        +--> audit_logs         (who, when, what changed)
                        +--> data_quality_flags (validators + AI quality check)
                        |
                 [Celery: index queue]
                        v
                  search_index  (tsvector + numeric filter columns)
```

A failure at any stage never destroys the stage before it. A parsing error leaves the
source row intact and retryable; a promotion that cannot resolve a vendor becomes a
review task rather than an exception.

## Why the schema looks like this

**Six spec tables, not one wide table.** Technical, commercial, dimensional, delivery,
operational and administrative data have different owners, different access rules
(procurement sees pricing, engineering does not) and different update cadences. Splitting
them lets RBAC and versioning work per group.

**Specs are versioned, never updated in place.** Writing a spec inserts a new row with
`version = previous + 1`; a database trigger retires the old row. That gives change
tracking for free and makes "what did the datasheet say in March?" answerable.

**A denormalised `search_index`.** Range filters over price, lead time, flow, head and
weight would otherwise join six versioned spec tables per query. One row per pump model,
refreshed by a worker, keeps filtering fast and gives a clean seam for moving to
OpenSearch later - a second consumer of the same table.

**Native PostgreSQL enums for the domain vocabulary.** API 610 types, API 682 seal
arrangements, area classifications and Incoterms are stable and finite. Storing them as
enums makes an invalid value a database error rather than a silent data-quality problem,
and the AI prompts are generated from the same Python enums, so the model cannot invent a
value the database will reject.

**`*_raw` columns beside every enum.** When a source says something the vocabulary does
not cover, the enum stays null and the original string is preserved for a human.

## Observability

* Structured JSON logs (`structlog`) with a request id, tenant id and user id bound to
  every line via context vars.
* Prometheus metrics at `/api/v1/metrics`; request counters and latency histograms are
  labelled with the **route template**, not the raw path, so cardinality stays bounded.
* `/api/v1/health` is dependency-free liveness. `/api/v1/ready` reports PostgreSQL,
  Redis, OpenRouter, Parallel AI and object storage, and returns 503 when a required
  dependency is down.
* `ai_jobs` is the audit log for the assistant layer: prompt name and version, model,
  tokens, cost, latency and the verbatim response.

## Scaling notes

| Pressure | Response |
| --- | --- |
| Ingestion volume | Scale the `ingest` queue workers; they are IO bound. |
| AI throughput | Scale the `ai` queue separately - it is rate limited, not CPU bound. |
| Search latency | `search_index` is already denormalised; add a read replica, then OpenSearch as a second consumer. |
| Audit volume | Partition `audit_logs` by month (bigint identity PK, always read in time order). |
| Tenant count | RLS is per-transaction, so tenants share one database until a large client justifies its own. |
