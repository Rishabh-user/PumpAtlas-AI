# Running PumpAtlas AI on localhost

Two supported shapes:

| | What runs where | When to use it |
| --- | --- | --- |
| **A. Hybrid** (recommended) | PostgreSQL, Redis and MinIO in containers; API, worker and frontend native with hot reload | Day-to-day development |
| **B. All containers** | Everything via `docker compose up` | Checking the deployed shape, or a demo |

Option A is recommended on Windows for a concrete reason: **Redis has no native Windows
build.** Running it in a container is far less work than WSL or a Redis-compatible
substitute.

Every command below was run on Windows 11 with Python 3.12, Node 24 and Docker Desktop.

Pointing at a **hosted** database instead (Render, RDS, Cloud SQL, Neon)? See
[docs/HOSTED_DATABASE.md](HOSTED_DATABASE.md) — it covers applying the schema without
`psql`, the owner-role trap that quietly disables tenant isolation, and why the region
you deploy to dominates response time.

---

## Option A: hybrid (recommended)

### 1. Configuration

```bash
cp .env.example .env
```

Then edit `.env`. The defaults are for Docker Compose, where services resolve each other
by name; for a native run they must point at `localhost`:

```ini
POSTGRES_HOST=localhost
POSTGRES_USER=pumpatlas_app
POSTGRES_PASSWORD=pumpatlas_app
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2
S3_ENDPOINT_URL=http://localhost:9000
SECRET_KEY=<openssl rand -hex 32>
```

`OPENROUTER_API_KEY` and `PARALLEL_API_KEY` are optional. Without them, ingestion, manual
entry, search, scoring, comparison, versioning and audit all work; only extraction and
enrichment return 503.

> **Use `pumpatlas_app`, not `pumpatlas`.** The bootstrap role is a PostgreSQL superuser,
> and superusers bypass row level security entirely - connect as it and every tenant
> isolation policy is silently inert. `db/app_role.sql` creates a `NOBYPASSRLS` role for
> the application; the Compose file applies it automatically.

### 2. Start PostgreSQL, Redis and MinIO

```bash
docker compose -f infra/docker-compose.deps.yml up -d
```

On first start the Postgres container applies, in order: `db/extensions.sql`,
`db/schema.sql`, `db/functions.sql`, `db/rls.sql`, `db/app_role.sql`. No local `psql`
needed. Confirm it landed:

```bash
docker compose -f infra/docker-compose.deps.yml logs postgres | grep -i error
```

Silence means all five applied. To inspect the database without installing a client:

```bash
docker exec -it pumpatlas-deps-postgres-1 psql -U pumpatlas -d pumpatlas
```

### 3. Backend environment

```bash
cd backend
python -m venv .venv
```

Activate it (`.venv\Scripts\activate` on Windows, `source .venv/bin/activate` elsewhere):

```bash
pip install -r requirements-dev.txt
```

### 4. Seed roles, the demo tenant and the administrator

```bash
python -m scripts.seed
```

Idempotent, so it is safe to re-run. It creates six roles, the platform administrator, and
a demo tenant with one user per role.

### 5. Start the API

```bash
python -m uvicorn app.main:app --reload --port 8000
```

Check every dependency at once:

```bash
curl http://localhost:8000/api/v1/ready
```

`postgres` and `redis` should read `ok`. `openrouter` and `parallel_ai` report
`not_configured` without API keys, which is not a failure.

### 6. Start the Celery worker

```bash
celery -A app.workers.celery_app.celery_app worker --loglevel=info --queues=default,ingest,ai,index --pool=solo
```

> **`--pool=solo` is required on Windows.** Celery's default prefork pool depends on
> `fork()`, which Windows does not have. On Linux and macOS drop it and use
> `--concurrency=4`.

Optionally, for scheduled crawls, in another terminal:

```bash
celery -A app.workers.celery_app.celery_app beat --loglevel=info
```

Run exactly one beat process. Two schedulers fire every crawl twice.

### 7. Start the frontend

```bash
cd frontend
npm install
```

```bash
API_INTERNAL_URL=http://localhost:8000 npm run dev
```

On PowerShell: `$env:API_INTERNAL_URL = "http://localhost:8000"` first, then `npm run dev`.

`API_INTERNAL_URL` is the **server-side** address of the API. The browser never calls the
API directly - requests go through the `/api/proxy/[...path]` route handler, which moves
the session token out of an httpOnly cookie and into an `Authorization` header.

### 8. Sign in

http://localhost:3000

Create your own platform administrator first — there is no default login:

```bash
python -m scripts.manage_user create --email you@example.com --name "Your Name"     --platform-admin
```

The seeder also creates the demo tenant's accounts, which share a password it prints
once when it runs:

| Account | Role |
| --- | --- |
| `admin@demo-operator.example` | Tenant administrator |
| `analyst@demo-operator.example` | Research analyst - ingestion and AI review |
| `engineer@demo-operator.example` | Engineering - technical specs |
| `buyer@demo-operator.example` | Procurement - commercial specs and comparisons |
| `vendors@demo-operator.example` | Vendor manager - qualification |

Lost that password? `python -m scripts.manage_user set-password --email <address>`.

Sign in as the analyst and use **Import queue** or the manual form to create your first
record; it appears in search immediately.

---

## Option B: all containers

```bash
cp .env.example .env
docker compose up --build
```

Keep the service-name hosts in `.env`; do not change them to `localhost`.

| Service | URL |
| --- | --- |
| Dashboard | http://localhost:3000 |
| API docs | http://localhost:8000/docs |
| MinIO console | http://localhost:9001 (`minioadmin` / `minioadmin`) |

`docker compose logs -f seed` confirms seeding. This stack connects as the `pumpatlas`
superuser unless you set `POSTGRES_USER=pumpatlas_app`, so switch it before testing
tenant isolation.

---

## Stopping and resetting

```bash
docker compose -f infra/docker-compose.deps.yml down
```

```bash
docker compose -f infra/docker-compose.deps.yml down -v
```

The first stops the containers and keeps the data; the second wipes it. After `down -v`
the next `up -d` re-applies the schema from scratch, so re-run `python -m scripts.seed`.

To clear the data without rebuilding the schema:

```bash
docker exec pumpatlas-deps-postgres-1 psql -U pumpatlas -d pumpatlas -c "TRUNCATE tenants, users, vendors, pumps, pump_models, sources, audit_logs, field_provenance, search_index, data_quality_flags, requirement_profiles, comparisons, duplicate_candidates, record_versions CASCADE;"
```

---

## Verifying the install

```bash
cd backend && pytest -q
```

162 tests. 130 run without a database; the other 32 exercise the live stack and skip
unless you point them at it:

```bash
PUMPATLAS_LIVE_API=http://127.0.0.1:8000/api/v1 pytest tests/test_live_integration.py -q
```

Those 32 matter most: they prove row level security really isolates tenants, that the
spec versioning triggers fire, and that provenance survives an edit.

---

## Problems you are likely to hit

| Symptom | Cause and fix |
| --- | --- |
| `error parsing value for field "CORS_ORIGINS"` | An old `.env` with a JSON-style list. It is a plain comma-separated string: `CORS_ORIGINS=http://localhost:3000` |
| Worker starts, then every task fails | Missing `--pool=solo` on Windows |
| `.delay()` raises `ConnectionRefused` on port 5672 | Something is reaching for RabbitMQ. `CELERY_BROKER_URL` must be a `redis://` URL |
| Tenants can see each other's data | The app is connecting as a superuser or a `BYPASSRLS` role. Use `pumpatlas_app` |
| `relation "..." already exists` at startup | The schema is already applied. Use `down -v` for a clean rebuild |
| `/ready` shows `redis: error` | The container is not up. Check `docker compose -f infra/docker-compose.deps.yml ps` |
| Frontend loads but every panel errors | `API_INTERNAL_URL` is unset or wrong, so the server cannot reach the API |
| Port 8000 already in use | Another API instance is running. `netstat -ano | findstr :8000` finds it |
| Extraction returns 503 | `OPENROUTER_API_KEY` is unset. Expected; everything else still works |
