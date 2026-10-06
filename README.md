# PumpAtlas AI

**Oil & Gas Pump Intelligence Platform** — by Targeticon.

A multi-tenant SaaS platform that collects, stores, enriches and searches Oil & Gas pump
data from web sources and user submissions, producing structured **product intelligence**,
**vendor intelligence** and **procurement support** for client companies.

Two rules shape everything:

1. **PostgreSQL is the system of record.** Every intelligence value is a row with a
   version history.
2. **AI is an assistant layer.** OpenRouter-hosted Gemma extracts, normalises, classifies
   and quality-checks; Parallel AI orchestrates web discovery. Neither writes to the
   database. Every AI-derived value carries a `field_provenance` row naming its source,
   the verbatim evidence quote, the model and the confidence — and a write without that
   evidence is refused in code.

---

## What is here

| Path | Contents |
| --- | --- |
| `backend/` | FastAPI (113 operations), SQLAlchemy models, Celery workers, AI clients — [README](backend/README.md) |
| `frontend/` | Next.js 15 / TypeScript dashboard, 14 routes — [README](frontend/README.md) |
| `db/` | Generated schema, extensions, triggers, RLS policies, partitioning |
| `docs/` | Architecture, data dictionary, AI & provenance, multi-tenancy, API, roadmap |
| `infra/` | nginx, deployment guide |
| `scripts/` | Schema and data-dictionary generators, dev and CI scripts |

**Scale of the domain model:** 36 tables, 1,141 columns, 124 indexes, 415 tracked
intelligence fields across six spec groups. All 63 field groups named in the brief are
mapped to columns and verified present by a test.

## Running it

Three guides, depending on what you need:

* **[backend/README.md](backend/README.md)** — run the API and workers
* **[frontend/README.md](frontend/README.md)** — run the dashboard
* **[docs/LOCAL_SETUP.md](docs/LOCAL_SETUP.md)** — the whole stack end to end, including the
  Windows-specific details (Redis has no native Windows build; Celery needs `--pool=solo`)

The short version, with the infrastructure in containers and the app native:

```bash
docker compose -f infra/docker-compose.deps.yml up -d
```

```bash
cd backend && pip install -r requirements-dev.txt && python -m scripts.seed && python -m uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

## Quick start (Docker Compose)

```bash
cp .env.example .env
```

Set `SECRET_KEY`, `OPENROUTER_API_KEY` and `PARALLEL_API_KEY`, then:

```bash
docker compose up --build
```

| Service | URL |
| --- | --- |
| Dashboard | http://localhost:3000 |
| API + OpenAPI docs | http://localhost:8000/docs |
| MinIO console | http://localhost:9001 |

No account exists until you create one, and a login is never read from configuration:

```bash
docker compose exec api python -m scripts.manage_user create     --email you@example.com --name "Your Name" --platform-admin
```

It prompts for the password — not echoed, not stored, only its bcrypt hash kept — and
`python -m scripts.manage_user list` shows the accounts and tenants. In development the
seeder also creates `admin@`, `analyst@`, `engineer@`, `buyer@` and
`vendors@demo-operator.example`, one per role, sharing a generated password it prints
once.

The platform runs without AI credentials — set `AI_ENABLED=false` and ingestion, manual
entry, search, scoring, comparison, versioning and audit all keep working.

## Quick start (local, no Docker)

```bash
bash scripts/dev_up.sh
```

Requires PostgreSQL 16+ and Redis 7+ already running.

## The modules

| Module | Where it lives |
| --- | --- |
| **Data ingestion** — web pages, PDFs, documents, spreadsheets, APIs, manual forms; batch upload and scheduled crawling | `/imports`, `POST /ingest/*` |
| **Extraction and normalisation** — SI-normalised, evidence-cited, per-field confidence | `app/services/extraction.py` |
| **Search and intelligence** — full-text, structured filters, facets, similar-pump matching, vendor comparison, four scorecards, duplicate detection, version history | `/`, `/compare`, `POST /search` |
| **Multi-tenancy** — RLS isolation, shared master data, six roles, audit logs | `docs/MULTITENANCY.md` |
| **AI-assisted enrichment** — missing fields, normalised values, vendor summaries, structured JSON from unstructured web data, confidence levels, contradiction flags | `/review`, `POST /ai/*` |
| **Dashboard** — search, filters, vendor list, pump profile, comparison, data quality, import queue, AI review, audit trail, tenant management | `frontend/src/app/` |

## Verification

```bash
bash scripts/check.sh
```

Regenerates `db/schema.sql` and `docs/DATA_DICTIONARY.md` (failing if either is stale or
references a column that no longer exists), lints and formats the backend, runs the test
suite, then typechecks and builds the frontend.

**Current state:** 162 backend tests pass — 130 without a database, plus 32 integration
tests against live PostgreSQL. Backend lint and format clean; frontend typechecks and
builds. Verified end to end against a real stack: schema and RLS applied, tenant isolation
enforced, spec versioning triggers firing, provenance preserved across edits, Celery
dispatching through Redis, and the dashboard rendering live data.

Run the integration tests with:

```bash
PUMPATLAS_LIVE_API=http://127.0.0.1:8000/api/v1 pytest tests/test_live_integration.py -q
```

**Still unverified:** the AI and web-search paths, which need real `OPENROUTER_API_KEY`
and `PARALLEL_API_KEY` credentials — see [the roadmap](docs/ROADMAP.md).

## Documentation

- [Local setup](docs/LOCAL_SETUP.md) — running it on your machine, and what goes wrong
- [Do I need Docker?](docs/DO_I_NEED_DOCKER.md) — what each container does, and how to drop them
- [Hosted PostgreSQL](docs/HOSTED_DATABASE.md) — Render/RDS/Cloud SQL: the owner-role trap, TLS, pool sizing, and why region matters
- [Architecture](docs/ARCHITECTURE.md) — layers, pipeline, and why the schema looks like this
- [Data dictionary](docs/DATA_DICTIONARY.md) — every brief requirement mapped to its columns, plus all 36 tables
- [AI search and web discovery](docs/AI_SEARCH_AND_DISCOVERY.md) — where the AI runs, how to auto-capture vendors from the web, and what quality to expect
- [AI and provenance](docs/AI_AND_PROVENANCE.md) — the traceability contract and how it is enforced
- [Multi-tenancy and RBAC](docs/MULTITENANCY.md) — isolation, shared master data, the six roles
- [API overview](docs/API.md) — endpoints, conventions, worked examples
- [Roadmap](docs/ROADMAP.md) — Phase 1/2/3 status and known limitations
- [Deployment](infra/DEPLOYMENT.md) — Compose, Kubernetes, backup, encryption
