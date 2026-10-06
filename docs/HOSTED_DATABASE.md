# Using a hosted PostgreSQL (Render, RDS, Cloud SQL, Neon)

PumpAtlas runs against any PostgreSQL 14+ with `pgcrypto`, `pg_trgm`, `unaccent` and
`btree_gin` available. Four things need attention on a managed instance.

---

## 1. Do not let the application connect as the owner role

This is the one that silently breaks tenant isolation.

A managed provider hands you one role — Render calls it `<db>_user` — which **owns** the
database. PostgreSQL exempts a table's owner from row level security unless the table is
marked `FORCE ROW LEVEL SECURITY`, and it exempts superusers unconditionally. Connect the
application as the owner and some or all of your isolation policies become decoration.

Two defences, both applied:

* `db/rls.sql` marks **all 36 tables** `FORCE ROW LEVEL SECURITY`, so even the owner is
  subject to the policies.
* `db/app_role.sql` creates `pumpatlas_app`, a `NOBYPASSRLS` non-owner role. Apply the
  schema as the owner; run the application as `pumpatlas_app`.

Verify it rather than trusting it:

```sql
SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user;
```

`rolsuper` and `rolbypassrls` must both be `f`. And confirm the policies actually bite:

```sql
SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND c.relforcerowsecurity;
```

Expect 36.

## 2. Apply the schema over a normal connection

A container reads `db/*.sql` from `docker-entrypoint-initdb.d` on first boot. A managed
database has no such hook, so use the helper — no local `psql` required:

```bash
python scripts/apply_schema.py --url "postgresql://OWNER:PASSWORD@HOST/DB?sslmode=require" --app-password "$(openssl rand -hex 24)"
```

It applies `extensions.sql`, `schema.sql`, `functions.sql`, `rls.sql` and `app_role.sql`
in order, one transaction per file, then reads back what landed. It refuses to run against
a database that already has tables unless you pass `--skip-schema` (re-apply only the
idempotent files) or `--reset` (destructive, drops the public schema first).

Then seed:

```bash
cd backend && python -m scripts.seed
```

## 3. TLS is required

Set `POSTGRES_SSLMODE=require` (or paste the provider's `DATABASE_URL`, which usually
includes it). `settings.sqlalchemy_url` rewrites a `postgresql://` URL to
`postgresql+psycopg://` and appends `sslmode` if it is missing, so a URL copied straight
from a provider dashboard works unchanged.

## 4. Size the pool against the connection cap, not against your hopes

Managed tiers cap connections tightly — Render's smaller plans allow about 100, shared
with their own monitoring. Every process opens its own pool: each API instance, each
Celery worker, and beat.

```
processes x (DB_POOL_SIZE + DB_MAX_OVERFLOW)  <  max_connections - headroom
```

The defaults are deliberately modest (`DB_POOL_SIZE=5`, `DB_MAX_OVERFLOW=5`), so eight
processes use at most 80 of ~100. Raise them only after checking:

```sql
SHOW max_connections;
SELECT count(*) FROM pg_stat_activity;
```

`pool_pre_ping` and `pool_recycle` (30 minutes) are on, because managed instances drop
idle connections and would otherwise hand a dead one to a request.

---

## Run the application in the same region as the database

This dominates everything else. PumpAtlas issues several queries per request, so response
time is round-trip time multiplied by query count.

Measured from a workstation in India against Render's Oregon region: **251 ms median
round trip**, and about **1 s** to open a new pooled connection through the TLS handshake.

| Endpoint | Same region (expected) | Cross-continent (measured) |
| --- | --- | --- |
| `GET /health` (no DB) | ~4 ms | 4 ms |
| `POST /search` | tens of ms | 2.1 s |
| `POST /search` with facets | tens of ms | 4.1 s |
| `GET /pump-models/{id}` | tens of ms | 5.7 s |
| `GET /quality/dashboard` | tens of ms | 5.0 s |

No amount of query tuning fixes this — a facet query is inherently a dozen or so round
trips. Two practical consequences:

* **Develop against a local database.** `docker compose -f infra/docker-compose.deps.yml
  up -d`. The integration suite takes 6 seconds locally and 4.5 minutes against Oregon.
* **Deploy the application beside the database.** `render.yaml` pins every service to
  `region: oregon` for exactly this reason.

Round trips were still worth reducing, and were: the two `set_config` calls that bind the
tenant became one statement, the connect-time `SET`s became one, user roles now load in
the same query as the user, and the pump profile loads its six spec rows once instead of
three times. That took the profile endpoint from 9.7 s to 5.7 s over the same link — and
helps just as much when co-located.

---

## Deploying to Render

`render.yaml` at the repository root describes the API, two workers split by queue, beat,
the dashboard and Redis. The database is deliberately **not** declared, so a blueprint
sync can never try to recreate the one you already have.

1. Apply the schema and seed from your workstation (above).
2. In Render, create a Blueprint from the repository.
3. Fill in the `sync: false` values: `DATABASE_URL` (the **Internal** URL, with the
   `pumpatlas_app` credentials) and optionally the OpenRouter, Parallel AI and S3
   settings. There is no administrator password among them — create the login against
   the database instead, with
   `python -m scripts.manage_user create --email you@example.com --name "You"
   --platform-admin`, which prompts for the password and stores only its hash.
4. Deploy. `pumpatlas-api` reports health at `/api/v1/health`; `/api/v1/ready` shows every
   dependency.

Use the **Internal** database URL for services running on Render — it stays on their
private network and skips the public TLS hop. The **External** URL is for your workstation.

Object storage matters here: Render's filesystem is ephemeral, so the local-disk fallback
loses uploaded datasheets on every deploy. Set the `S3_*` variables before ingesting
anything you care about.

## Rotating the database password

Because the credential ends up in several places, rotate it through one path:

1. Rotate in the provider's dashboard (or `ALTER ROLE pumpatlas_app WITH PASSWORD '...'`).
2. Update `DATABASE_URL` in the Render environment group, and `.env` locally.
3. Redeploy the API and all three worker services — they cache the URL at process start.

Rotate immediately if a password has ever appeared in a screenshot, a chat, a ticket or a
terminal transcript.
