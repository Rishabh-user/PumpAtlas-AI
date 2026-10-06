# PumpAtlas AI — Backend

FastAPI service, SQLAlchemy models, Celery workers and the AI clients. Serves **113
operations across 89 paths** under `/api/v1`, with interactive docs at `/docs`.

PostgreSQL is the system of record. Gemma (via OpenRouter) and Parallel AI are an
assistant layer that proposes candidates; they never write to the database directly.

---

## Prerequisites

| | Needed for |
| --- | --- |
| Python 3.11+ (3.12 used here) | the service |
| PostgreSQL 14+ | the system of record |
| Redis 7+ | Celery broker and result backend |
| S3-compatible storage | documents (optional — falls back to local disk) |

Both PostgreSQL and Redis run from `infra/docker-compose.deps.yml`. On Windows this is
not just convenience: **Redis has no native Windows build.**

---

## Run it, start to finish

All commands run from this `backend/` directory unless noted.

### 1. Start PostgreSQL, Redis and MinIO

```bash
docker compose -f ../infra/docker-compose.deps.yml up -d
```

On the **first** start the Postgres container applies `db/extensions.sql`,
`db/schema.sql`, `db/functions.sql`, `db/rls.sql` and `db/app_role.sql` in that order.
No local `psql` needed. Confirm it worked:

```bash
docker compose -f ../infra/docker-compose.deps.yml logs postgres | grep -i error
```

Silence means all five applied.

### 2. Configuration

`.env` lives at the **repository root**, not here. Create it once:

```bash
cp ../.env.example ../.env
```

For a native run, the hosts must be `localhost` rather than the Compose service names:

```ini
POSTGRES_HOST=localhost
POSTGRES_USER=pumpatlas_app
POSTGRES_PASSWORD=pumpatlas_app
POSTGRES_SSLMODE=prefer
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2
S3_ENDPOINT_URL=http://localhost:9000
SECRET_KEY=<openssl rand -hex 32>
```

`OPENROUTER_API_KEY` and `PARALLEL_API_KEY` are optional. Without them, ingestion, manual
entry, search, scoring, comparison, versioning and audit all work; only extraction and
enrichment return 503.

> **Connect as `pumpatlas_app`, not `pumpatlas`.** The bootstrap role is a PostgreSQL
> superuser, and superusers bypass row level security entirely — connect as it and every
> tenant isolation policy is silently inert.

### 3. Virtual environment

```bash
python -m venv .venv
```

Activate it — `.venv\Scripts\activate` on Windows, `source .venv/bin/activate` elsewhere:

```bash
pip install -r requirements-dev.txt
```

### 4. Seed roles, the demo tenant and the administrator

```bash
python -m scripts.seed
```

Idempotent, so re-running it is safe. Creates six roles and, outside production, a demo
tenant with one user per role sharing a generated password it prints once.

It does **not** create an administrator: a login is a database row, not configuration.

```bash
python -m scripts.manage_user create --email you@example.com --name "Your Name"     --platform-admin
```

The password is typed at a prompt — never an argument, which shell history and `ps` both
expose — and only its bcrypt hash is stored. `manage_user list` shows the accounts,
`manage_user set-password --email ...` rotates one.

### 5. Start the API

```bash
python -m uvicorn app.main:app --reload --port 8000
```

```bash
curl http://localhost:8000/api/v1/ready
```

`postgres` and `redis` should read `ok`. `openrouter` and `parallel_ai` reporting
`not_configured` is expected without API keys, and is not a failure.

Then http://localhost:8000/docs for the interactive API.

### 6. Start the Celery worker

Background jobs — ingestion, extraction, enrichment, reindexing — need a worker:

```bash
celery -A app.workers.celery_app.celery_app worker --loglevel=info --queues=default,ingest,ai,index --pool=solo
```

> **`--pool=solo` is required on Windows.** Celery's default prefork pool needs `fork()`,
> which Windows does not have; without it the worker starts and then fails every task. On
> Linux and macOS drop it and use `--concurrency=4`.

To skip the worker and Redis entirely during development, set
`CELERY_TASK_ALWAYS_EAGER=true` in `.env`. Background jobs then run inline in the process
that dispatched them — no broker, no worker. The request blocks for the whole task, so an
AI extraction can hold it open for a minute, and the Celery app refuses to start with this
set and `ENVIRONMENT=production`. See
[docs/DO_I_NEED_DOCKER.md](../docs/DO_I_NEED_DOCKER.md).

For scheduled crawls, in a separate terminal:

```bash
celery -A app.workers.celery_app.celery_app beat --loglevel=info
```

Run **exactly one** beat process — two schedulers fire every crawl twice.

---

## Pointing at a hosted database instead

To use Render, RDS, Cloud SQL or Neon rather than the local container, set in `../.env`:

```ini
POSTGRES_HOST=<provider-host>
POSTGRES_DB=<database>
POSTGRES_USER=pumpatlas_app
POSTGRES_PASSWORD=<password>
POSTGRES_SSLMODE=require
```

Or paste the provider's URL wholesale — `settings.sqlalchemy_url` rewrites
`postgresql://` to `postgresql+psycopg://` and appends `sslmode` if missing:

```ini
DATABASE_URL=postgresql://user:password@host:5432/dbname
```

A managed database has no init-scripts hook, so apply the schema over a normal connection:

```bash
python ../scripts/apply_schema.py --url "postgresql://OWNER:PW@HOST/DB?sslmode=require" --app-password "$(openssl rand -hex 24)"
```

**Keep Redis local.** Only the database moves; the broker stays on localhost unless you
host that too.

**Expect it to be slow if the database is far away.** Response time is round-trip time
multiplied by queries per request. Measured from India to Render's Oregon region: 251 ms
per round trip, so a pump profile takes ~5.7 s instead of tens of milliseconds. Develop
against the local container and deploy the app beside the database — see
[docs/HOSTED_DATABASE.md](../docs/HOSTED_DATABASE.md).

---

## Layout

| Path | Contains |
| --- | --- |
| `app/main.py` | App construction, middleware, exception handlers |
| `app/api/v1/` | Routers: HTTP shape, status codes, RBAC guards. No business logic |
| `app/core/` | Settings, DB engine and tenant binding, security, RBAC matrix, dependencies, logging |
| `app/models/` | SQLAlchemy models — the single definition of the schema |
| `app/schemas/` | Pydantic models. Spec schemas are **derived from the models** in `derive.py` |
| `app/services/` | All business logic: ingestion, extraction, promotion, scoring, dedupe, quality, indexing, search |
| `app/ai/` | OpenRouter and Parallel AI clients, prompts, JSON recovery |
| `app/workers/` | Celery app and tasks. Each task opens its own tenant-scoped session |
| `app/utils/units.py` | Unit conversion to the SI baseline |
| `scripts/seed.py` | Roles, demo tenant, bootstrap administrator |
| `tests/` | 130 offline tests plus 32 live integration tests |

Two conventions worth knowing before you edit anything:

* **`db/schema.sql` is generated**, not hand-written. Change a model, then run
  `python ../scripts/gen_schema.py`. CI fails if the file is stale.
* **Never assign a spec attribute directly.** Write through
  `app/services/provenance.py:apply_field`, which records where the value came from. That
  is what makes every field traceable to a source.

---

## Tests

```bash
pytest -q
```

130 tests, no database required — unit conversion, quality validators, the scoring engine,
schema integrity, the API surface, RBAC separation, Celery wiring, audit serialisation and
requirements traceability.

A further 32 exercise a live stack and skip unless you point them at one:

```bash
PUMPATLAS_LIVE_API=http://127.0.0.1:8000/api/v1 pytest tests/test_live_integration.py -q
```

Those are the ones that matter most: they prove row level security really isolates
tenants, that the spec versioning triggers fire, and that provenance survives an edit.
Every one of them caught a real bug the first time it ran.

---

## Common tasks

```bash
python ../scripts/gen_schema.py
```

Regenerate `db/schema.sql` after a model change.

```bash
python ../scripts/gen_data_dictionary.py
```

Regenerate the data dictionary. Fails if a documented column no longer exists.

```bash
ruff check app tests && ruff format app tests
```

Lint and format.

```bash
alembic revision --autogenerate -m "add field X" && alembic upgrade head
```

Create and apply a migration. Note that autogenerate does **not** manage RLS policies,
triggers or the text-search configuration — those live in `db/*.sql`; add them to the
migration by hand with `op.execute()` if a change touches them.

---

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `error parsing value for field "CORS_ORIGINS"` | It is a plain comma-separated string, not JSON: `CORS_ORIGINS=http://localhost:3000` |
| Worker starts, then every task fails | Missing `--pool=solo` on Windows |
| `.delay()` raises `ConnectionRefused` on port 5672 | Something is reaching for RabbitMQ. `CELERY_BROKER_URL` must be a `redis://` URL |
| Tenants can see each other's data | Connected as a superuser or `BYPASSRLS` role. Use `pumpatlas_app` |
| `new row violates row-level security policy` | The session has no tenant bound. Requests do this automatically; a script must use `tenant_session(...)` |
| `relation "..." already exists` at startup | Schema already applied. `down -v` the deps stack for a clean rebuild |
| `/ready` reports `redis: error` | The container is not running: `docker compose -f ../infra/docker-compose.deps.yml ps` |
| Extraction returns 503 | `OPENROUTER_API_KEY` is unset. Expected; everything else still works |
| Requests take seconds | The database is probably in another region. See [docs/HOSTED_DATABASE.md](../docs/HOSTED_DATABASE.md) |

---

## Further reading

* [docs/LOCAL_SETUP.md](../docs/LOCAL_SETUP.md) — the whole stack, both options
* [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) — layers, pipeline, schema rationale
* [docs/AI_AND_PROVENANCE.md](../docs/AI_AND_PROVENANCE.md) — the traceability contract
* [docs/MULTITENANCY.md](../docs/MULTITENANCY.md) — isolation and the six roles
* [docs/API.md](../docs/API.md) — endpoints and conventions
