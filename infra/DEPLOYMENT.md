# Deployment

## MVP: Docker Compose on one host

```bash
cp .env.example .env
# set SECRET_KEY, POSTGRES_PASSWORD, OPENROUTER_API_KEY, PARALLEL_API_KEY
docker compose up --build -d
docker compose logs -f seed     # confirm the roles were created

# Then create the first login. No account exists until you do, and the password is
# typed at the prompt rather than stored in configuration.
docker compose exec api python -m scripts.manage_user create     --email you@example.com --name "Your Name" --platform-admin
```

The `postgres` service applies `db/extensions.sql`, `db/schema.sql`, `db/functions.sql`
and `db/rls.sql` in order on first start. They run **only** on an empty data volume; for
an existing database, apply them by hand or use Alembic.

Put `infra/nginx.conf` in front for TLS. It terminates HTTPS, serves the API and frontend
from one origin (which removes CORS from the browser path), rate-limits `/auth/login`, and
restricts `/metrics` to private networks.

## Before this is production

| Item | Why |
| --- | --- |
| `SECRET_KEY` from `openssl rand -hex 32` | The default signs tokens anyone can forge |
| Create the admin with `scripts.manage_user`, not configuration | A password in `.env` is readable by anything that reads the environment, is copied into every backup, and cannot be rotated without a redeploy |
| A dedicated `NOBYPASSRLS` application role | Owning the tables or holding `BYPASSRLS` disables every tenant policy |
| Managed PostgreSQL with PITR | The Compose volume is not a backup |
| Real S3, not local storage | Local mode has no durability guarantees |
| `ENVIRONMENT=production` | Switches logs to JSON and enables the seeder's safety checks |
| Restrict `CORS_ORIGINS` | The default allows localhost |

## The application database role

```sql
CREATE ROLE pumpatlas_app LOGIN PASSWORD '...' NOBYPASSRLS;
GRANT CONNECT ON DATABASE pumpatlas TO pumpatlas_app;
GRANT USAGE ON SCHEMA public TO pumpatlas_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO pumpatlas_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO pumpatlas_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO pumpatlas_app;
```

Migrations run as the owner; the application runs as `pumpatlas_app`. If the application
owns the tables, `FORCE ROW LEVEL SECURITY` is the only thing standing between one client
and another's data - and a single missed `FORCE` becomes a breach.

## Kubernetes

The containers are stateless and horizontally scalable. A workable shape:

| Workload | Kind | Replicas | Notes |
| --- | --- | --- | --- |
| `api` | Deployment | 3+ | HPA on CPU; readiness probe `/api/v1/ready`, liveness `/api/v1/health` |
| `worker-ingest` | Deployment | 2-10 | `--queues=ingest,default`, higher concurrency; IO bound |
| `worker-ai` | Deployment | 1-4 | `--queues=ai`, concurrency 2; rate limited by the provider, not CPU |
| `worker-index` | Deployment | 1-2 | `--queues=index`; short, cheap tasks |
| `beat` | Deployment | **exactly 1** | Two schedulers means every crawl fires twice |
| `frontend` | Deployment | 2+ | |
| PostgreSQL | managed service | | Not in-cluster |
| Redis | managed service | | Broker plus result backend |

Split the workers by queue rather than running one pool across all of them: a 90-second
Gemma call must not occupy a slot that a 200-millisecond reindex is waiting for.

Secrets (`SECRET_KEY`, database URL, `OPENROUTER_API_KEY`, `PARALLEL_API_KEY`, S3
credentials) belong in a Secret or an external secrets operator, never in the image.

## Backup and recovery

* **PostgreSQL** is the system of record - continuous archiving with point-in-time
  recovery. Everything else can be rebuilt from it.
* **Object storage** holds the original documents. Versioning on, lifecycle rules to
  cold storage. Losing these loses the evidence behind the provenance chain, so they are
  not disposable.
* **Redis** is a queue, not a store. Losing it loses in-flight jobs; sources stay
  ingested and can be re-extracted with `POST /ingest/sources/{id}/extract`.
* **`search_index`** is derived. `pumpatlas.nightly_maintenance` rebuilds it, and it can
  be rebuilt in full at any time.

## Encryption

* **In transit** - TLS at nginx or the ingress; `sslmode=require` on the database URL.
* **At rest** - encrypted volumes for PostgreSQL, SSE-S3 for object storage (the S3
  client sets `ServerSideEncryption=AES256` on every upload).
* **Secrets** - bcrypt for passwords and API keys; only hashes are stored.

Field-level encryption for commercial terms is listed in
[the roadmap](../docs/ROADMAP.md) as not built.

## Health checks

| Endpoint | Use |
| --- | --- |
| `/api/v1/health` | Liveness. Dependency-free, so a database blip never restarts a healthy pod |
| `/api/v1/ready` | Readiness. Reports PostgreSQL, Redis, OpenRouter, Parallel AI and storage; 503 when a required dependency is down |
| `/api/v1/metrics` | Prometheus scrape target |
