# Do I need Docker?

Short answer: **no, not any more — but one of the three containers is doing real work, and
dropping it costs you something.**

Docker is used in two unrelated places. Treat them separately.

| Use | Needed? |
| --- | --- |
| **Local development** — `infra/docker-compose.deps.yml` (PostgreSQL, Redis, MinIO) | Optional, with caveats below |
| **Deployment** — `backend/Dockerfile`, `frontend/Dockerfile`, `render.yaml` | Optional; Render's native Python/Node runtimes work too |

---

## What the three containers are doing right now

With `.env` pointing at the Render database:

| Container | In use? | Without it |
| --- | --- | --- |
| **postgres** | **No** — idle since the database moved to Render | Nothing. Stop it |
| **redis** | **Yes** — Celery broker | No background jobs: ingestion, extraction, enrichment, reindexing, scheduled crawls |
| **minio** | **Yes** — `S3_ENDPOINT_URL` points at it | Documents fall back to local disk, which is fine for development |

So one container is pure waste, and two are load-bearing.

---

## Running with no Docker at all

Three changes.

### 1. PostgreSQL — already handled

`.env` points at Render. Nothing to do.

The cost is latency: **251 ms per query** from India to Oregon, versus 0.43 ms to a local
container. That is a real tax on development — the integration suite takes 8 seconds
against a local database and 4.5 minutes against Render, and a pump profile page takes
5.7 seconds instead of tens of milliseconds. See
[HOSTED_DATABASE.md](HOSTED_DATABASE.md).

### 2. Redis — the only genuine blocker

There is no native Windows build of Redis. Pick one:

**a. Run background jobs inline (no broker at all).** In `.env`:

```ini
CELERY_TASK_ALWAYS_EAGER=true
```

Tasks then execute in the process that dispatched them. No Redis, no worker process, no
`--pool=solo`. The trade-off is that the HTTP request blocks for the whole task, so an AI
extraction can hold a request open for a minute. Fine for development and tests; the
Celery app **refuses to start** with this set and `ENVIRONMENT=production`.

**b. Hosted Redis.** Render Key Value, Upstash and similar have free tiers. Point
`REDIS_URL` and `CELERY_BROKER_URL` at it and keep the real queue behaviour. Adds
network latency to job dispatch, which matters far less than it does for the database.

**c. Memurai or WSL2.** A native Windows Redis-compatible service, or `apt install
redis-server` inside WSL2. Both work; both are more setup than a container.

### 3. MinIO — just leave it unset

Clear the S3 settings in `.env`:

```ini
S3_ACCESS_KEY=
S3_SECRET_KEY=
```

Storage falls back to `./.data/documents` on local disk. `settings.use_s3` goes false and
`get_storage()` returns `LocalStorage`. **Development only** — it has no durability
guarantees, and on a platform with an ephemeral filesystem (Render included) uploaded
datasheets disappear on every deploy.

---

## My recommendation

**Keep the deps compose file, and stop the postgres container.**

```bash
docker compose -f infra/docker-compose.deps.yml stop postgres
```

Reasoning:

* Redis in a container is less work than Memurai, WSL or a hosted instance, and it keeps
  the local setup identical to production behaviour — a real queue, a real worker, real
  `acks_late` semantics. Eager mode is convenient but it does not exercise the code path
  that runs in production.
* MinIO in a container exercises the S3 path, which is what production uses. The local-disk
  fallback is a different code path, so testing on it proves less.
* PostgreSQL is the one to drop **only if** you accept the latency. If development starts
  feeling sluggish, switch `.env` back to `POSTGRES_HOST=localhost` and start the
  container again — that is a four-line change and a 584x latency improvement.

In other words: Docker is no longer required, but for two of the three services it is
still the cheapest way to get the behaviour you actually want.

---

## Deployment without Docker

`render.yaml` currently uses `runtime: docker`. Render also supports native runtimes,
which build faster and drop the Dockerfiles from the deploy path:

```yaml
- type: web
  name: pumpatlas-api
  runtime: python
  buildCommand: pip install -r backend/requirements.txt
  startCommand: cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

```yaml
- type: web
  name: pumpatlas-web
  runtime: node
  buildCommand: cd frontend && npm ci && npm run build
  startCommand: cd frontend && npm run start
```

The Dockerfiles are worth keeping regardless. They are the only artefact that pins the
system-level dependencies — `lxml` needs `libxml2-dev` and `libxslt1-dev`, which a native
buildpack may or may not provide. If you move to native runtimes and the build fails on
`lxml`, that is why.

---

## Reference: what breaks without a broker

Verified by stopping Redis and exercising the API.

| Still works | Needs the broker |
| --- | --- |
| Search, filters, facets, similar-pump matching | File upload with auto-extract |
| Manual data entry (`POST /ingest/manual`) | URL ingestion |
| Reading and writing specs, versioning, provenance | Parallel AI web search |
| Requirement profiles, scoring, comparison | AI enrichment and vendor summaries |
| Data quality dashboard and flags | Scheduled crawls |
| Audit trail, tenant and user management | Background reindexing |

A request that needs the broker now returns **503 with a clear message** rather than a
stack trace, and fails in about 4 seconds rather than hanging for 20. Getting there meant
dropping the Celery result backend from the dispatch path — nothing in the platform reads
task results, because job status is tracked durably in the `ai_jobs` table.
