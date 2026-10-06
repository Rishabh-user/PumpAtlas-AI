# API overview

FastAPI serves 113 operations across 89 paths under `/api/v1`. Interactive documentation
is at `/docs`, the OpenAPI document at `/openapi.json`. Column comments from the models
become field descriptions and database enums become enumerated values, so the spec
documents the domain rather than restating it.

## Authentication

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"<your password>"}'
```

Returns an access and refresh token pair. Then:

* `Authorization: Bearer <access_token>` for users
* `X-API-Key: pa_...` for machine integrations
* `X-Tenant-Id: <uuid>` for platform staff acting inside a tenant

Five failed logins lock the account for 15 minutes. Every attempt, successful or not, is
written to `audit_logs`.

## The endpoints that carry the product

| Purpose | Endpoint |
| --- | --- |
| Search everything, with filters and facets | `POST /search` |
| Shareable search link | `GET /search?q=...&pump_type=...` |
| Filter vocabularies for the sidebar | `GET /search/filters/options` |
| Alternatives at a comparable duty point | `POST /search/similar/{pump_model_id}` |
| Full pump profile in one call | `GET /pump-models/{id}` |
| Read one spec group, any version | `GET /pump-models/{id}/specs/{group}` |
| Write a spec group as a new version | `PUT /pump-models/{id}/specs/{group}` |
| Version history for a spec group | `GET /pump-models/{id}/specs/{group}/versions` |
| Field-by-field lineage | `GET /pump-models/{id}/provenance` |
| Mark a record human-verified | `POST /pump-models/{id}/verify` |
| Vendor page data | `GET /vendors/{id}/profile` |
| Vendor duplicate candidates | `GET /vendors/{id}/duplicates` |
| Merge a duplicate vendor | `POST /vendors/merge` |
| Start an AI vendor search | `POST /vendor-discovery` |
| Start an AI pump search | `POST /pump-discovery` |
| Poll a run (stages, per-provider jobs, candidates) | `GET /{vendor,pump}-discovery/{run_id}` |
| Store or discard the candidates a person picked | `POST /{vendor,pump}-discovery/{run_id}/select` |
| Stop a running discovery at its next checkpoint | `POST /{vendor,pump}-discovery/{run_id}/cancel` |
| Discard every undecided candidate | `POST /{vendor,pump}-discovery/{run_id}/reject-all` |
| Recent discovery runs | `GET /{vendor,pump}-discovery` |
| Upload documents | `POST /ingest/upload` (multipart) |
| Queue URLs | `POST /ingest/urls` |
| Discover sources via Parallel AI | `POST /ingest/web-search` |
| Manual data entry | `POST /ingest/manual` |
| Import queue | `GET /ingest/batches` |
| Re-run extraction on a stored source | `POST /ingest/sources/{id}/extract` |
| AI review queue | `GET /ai/review-queue` |
| Accept, edit, reject or escalate a candidate | `POST /ai/review-queue/{id}/decide` |
| Bulk decision | `POST /ai/review-queue/bulk` |
| Field suggestions | `GET /ai/suggestions` |
| Queue enrichment | `POST /ai/enrich/{pump_model_id}` |
| AI job audit and cost | `GET /ai/jobs`, `GET /ai/usage` |
| Data quality dashboard | `GET /quality/dashboard` |
| Flags and resolution | `GET /quality/flags`, `POST /quality/flags/{id}/resolve` |
| Duplicate review | `GET /quality/duplicates` |
| Requirement profiles | `GET` / `POST /requirement-profiles` |
| Score one candidate | `POST /pump-models/{id}/score` |
| Build a comparison | `POST /comparisons` |
| Compare vendors | `GET /vendor-comparison` |
| Audit trail | `GET /audit-logs` |
| Row snapshots | `GET /record-versions` |
| Tenant management | `GET` / `POST /tenants` |
| Health and readiness | `GET /health`, `GET /ready` |
| Prometheus metrics | `GET /metrics` |
| Every controlled vocabulary | `GET /meta/vocabularies` |
| Every tracked intelligence field | `GET /meta/fields` |

## Conventions

**Pagination.** List endpoints take `limit` (max 200) and `offset`, and return
`{items, total, limit, offset}`. `total` ignores pagination.

**Errors.** `422` carries per-field validation detail. `409` means a constraint conflict -
usually a duplicate vendor, model code or spec version - and names it. `503` means a
dependency (database, OpenRouter, Parallel AI) is unavailable, and says which.

**Writes are versioned.** `PUT /pump-models/{id}/specs/{group}` inserts a new version and
retires the previous one; it never mutates in place. Fields absent from the request body
are carried forward from the previous version, so a partial write is not a data-loss event.

**Every write reports what it did.** Spec writes return `applied`, `unchanged` and
`refused` field lists plus the count of quality flags raised. A field refused because an
AI value lacked evidence, or because it would overwrite verified data, appears in the
response rather than being silently dropped.

**Route ordering.** Static segments are declared ahead of `{uuid}` siblings, and
`GET /vendor-comparison` deliberately avoids `/comparisons/vendors`, which
`/comparisons/{comparison_id}` would capture. A test asserts that no route is shadowed.

## Example: search with filters

```bash
curl -X POST http://localhost:8000/api/v1/search \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
        "query": "crude export multistage",
        "standards": ["api_610"],
        "pump_types": ["between_bearings_bb3"],
        "capacity_min": 250,
        "capacity_max": 400,
        "head_min": 120,
        "npshr_max": 5,
        "lead_time_max": 30,
        "certifications": ["ATEX", "DNV"],
        "fpso_experience": true,
        "sort": "lead_time_asc",
        "include_facets": true
      }'
```

## Example: writing a technical spec

```bash
curl -X PUT \
  "http://localhost:8000/api/v1/pump-models/$MODEL_ID/specs/technical?mark_verified=true" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
        "rated_capacity_m3h": 272.5,
        "rated_head_m": 137.2,
        "npsh_required_m": 3.2,
        "material_class": "S-6",
        "seal_piping_plan": "Plan 11 + Plan 52",
        "area_classification": "zone_1",
        "nace_mr0175_compliant": true
      }'
```

`mark_verified=true` records the values as human-verified, which protects them from being
overwritten by a later crawl.
