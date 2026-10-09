# Deploying to Render

Frontend and backend live in one repository and deploy as **two separate Render services
from the same blueprint**. A monorepo needs nothing special: `rootDir` points each service
at its own folder, and Render builds only that one.

| Service | Runtime | rootDir | Build | Start |
| --- | --- | --- | --- | --- |
| `pumpatlas-api` | python | `backend` | `pip install -r requirements.txt` | `uvicorn app.main:app ...` |
| `pumpatlas-web` | node | `frontend` | `npm ci && npm run build` | `npm run start` |

`render.yaml` at the repository root declares both. Render reads it and creates them in
one go.

### Why there is no Docker in it

There is no need for one. Every Python dependency here ships a prebuilt Linux wheel —
psycopg, lxml, bcrypt and cryptography included — so nothing compiles, and the frontend is
a stock Next.js build. Render's native runtimes handle both, and they are the simpler
choice: dependency caching between builds, no image to maintain, and a shorter path from
push to running.

The Dockerfiles stay in the repository, and they are not wasted. They are what
`docker compose` uses locally, and they are what makes this deployable somewhere that is
not Render. If you would rather deploy the identical image you run locally — the strongest
argument for Docker — `infra/render.docker.yaml` is the same two services built from them;
copy it over `render.yaml` and re-sync.

The **database is deliberately not declared**. It already exists on Render, and a
blueprint sync that tried to recreate it would be the worst possible outcome. Its URL is
pasted in as a secret.

There is no Redis and there are no Celery workers in this blueprint. Without a broker,
`dispatch` probes, fails over, and runs discovery inside the API process — the same
behaviour you have in development. Everything works; a long sweep dies if the API
restarts or scales. When that starts to matter, copy `infra/render.full.yaml` over
`render.yaml` and re-sync: it adds Redis and three workers, at roughly three times the
cost.

---

## Before you deploy: the repository is public-facing now

A remote exists (`github.com/Rishabh-user/PumpAtlas-AI`) and the initial commit **contains
the client's documents**: the signed ONGC approved suppliers list, five SAP vendor-master
exports and the Kikeh package list. Those files carry 1,426 contact emails and phone
numbers, GST and PAN numbers, and bank account details for 691 suppliers.

Deleting them in a new commit does not help — git keeps history, and that history is what
Render clones.

**Settle this first.** For a two-commit repository the most reliable fix is to start the
history again:

```bash
# 1. stop them ever being committed again
printf '\n# Client documents: commercially sensitive, never committed.\nApproved Vendor List/\n*.XLSX\n' >> .gitignore

# 2. untrack them (they stay on your disk)
git rm -r --cached "Approved Vendor List"

# 3. start a clean history, then replace the remote's
git checkout --orphan clean-main
git add -A
git commit -m "PumpAtlas AI"
git branch -D main && git branch -m main
git push --force origin main
```

Then **delete the GitHub repository and create it again**, or ask GitHub Support to purge
the cached objects: a force-push leaves the old commits reachable by SHA on GitHub for a
time. And if the repository was ever public, treat the data as disclosed and tell whoever
owns the client relationship.

`.env` is already untracked — the secrets themselves are safe.

---

## 1. Point Render at the repository

Render → **New → Blueprint** → connect the GitHub repository → it reads `render.yaml`.

Set the region **to the same one as the database** before the first deploy. The blueprint
says `oregon`; change all six services if the database is elsewhere. This is the single
biggest performance decision here: PumpAtlas issues several queries per request, and at a
cross-continent round trip of ~250 ms a page costs seconds, while co-located it costs
milliseconds. The local database at ~312 ms per round trip is why the vendor list was
tuned to count on a key rather than a subquery.

## 2. Fill in the secrets

Render will prompt for every `sync: false` value.

| Key | Value |
| --- | --- |
| `DATABASE_URL` | The **Internal Database URL**, with the `pumpatlas_app` credentials — **not** the owner's |
| `SECRET_KEY` | Generated automatically — nothing to type |
| `S3_*` | Object storage. Without it, uploads go to the container's disk and vanish on restart |
| `OPENROUTER_API_KEY`, `PARALLEL_API_KEY` | Optional — provider keys live encrypted in the database and are set on the `/ai-settings` page |
| `CORS_ORIGINS` | Only if another application calls this API from a browser. The dashboard does not need it: its browser code goes through `/api/proxy` on its own origin |

The `DATABASE_URL` role matters more than anything else on this list. `pumpatlas_app` is
`NOBYPASSRLS` and owns nothing; connecting as the owner silently disables every
row-level-security policy, and one client's approved supplier list becomes readable by
another. There is no error when this is wrong — only a tenant boundary that stopped
existing.

`SECRET_KEY` signs session tokens and derives the Fernet key that decrypts the AI
provider keys held in the database. Render generates it. If you later add the workers, they
must carry the identical value or they cannot read what the API wrote.

## 3. Apply the schema

The application role has no DDL rights by design, so migrations are run by hand as the
**owner**, from your machine, against the Render database's external URL:

```bash
cd backend
python scripts/apply_schema.py --url "postgresql://OWNER:PASSWORD@HOST/DB?sslmode=require" --file ../db/extensions.sql
python scripts/apply_schema.py --url "..." --file ../db/schema.sql
python scripts/apply_schema.py --url "..." --file ../db/functions.sql
python scripts/apply_schema.py --url "..." --file ../db/rls.sql
python scripts/apply_schema.py --url "..." --file ../db/migrations/002_vendor_contact_provenance.sql
python scripts/apply_schema.py --url "..." --file ../db/migrations/003_client_vendor_structure.sql
```

On a database that already has the schema, only the two migrations are outstanding.

## 4. Create the first login

No account exists until you make one, and the password is typed at a prompt rather than
stored anywhere:

```bash
python -m scripts.manage_user create --email you@example.com --name "Your Name" --platform-admin
```

## 5. Deploy

`autoDeploy: false` on every service, so a push does not deploy by itself. Deploy the API
first, confirm `/api/v1/health`, then the dashboard.

---

## Two things in the blueprint that were wrong, and are now handled

Both were invisible until a deploy and would have looked like "the site is broken".

**`API_INTERNAL_URL` has no scheme.** It comes from the API service's `hostport` property,
which is `pumpatlas-api:10000` — Render's private-network address format. `fetch()` rejects
that, so every server-rendered page would have failed on the first deploy with nothing in
the UI to say why. A blueprint cannot concatenate strings, so `lib/api.ts` now adds
`http://` when the address arrives without one. This is true of either blueprint, Docker
or native.

**`CORS_ORIGINS` had no scheme either.** It comes from the web service's `host` property,
a bare hostname, while a browser sends `Origin: https://that-host`; the two never match.
`config.py` now turns a bare hostname into a real origin. This only affects *other*
applications calling the API directly — the dashboard's browser code goes through
`/api/proxy` on its own origin, so CORS never enters that path.

## What this costs, and when to add the rest

Two services on `starter` is about $14/month on top of the database you already pay for.
The full blueprint is six services — around $42.

What you give up by starting with two: discovery runs execute **inside the API process**,
because there is no broker for them to queue on. That is today's behaviour locally, and it
is why 22 of 97 runs died with *"Interrupted by an API restart"*. Short enrichments are
fine; a 60-country sweep is not, because any deploy or scale event kills it.

When that matters:

```bash
cp infra/render.full.yaml render.yaml
git commit -am "Add Redis and Celery workers" && git push
```

Re-sync the blueprint in Render. It adds `pumpatlas-redis` and three workers — `ingest`,
`ai` (kept apart so a 90-second model call cannot hold a slot a 200 ms reindex is waiting
for) and exactly one `beat`, because two schedulers fire every crawl twice. Copy
`SECRET_KEY` from the API into the `pumpatlas-shared` environment group, identically, or
the workers cannot decrypt the stored provider keys.

## After the first deploy

```bash
python -m scripts.audit_vendor_data --strict     # is the data sound
python -m scripts.pending_pumps                  # what still needs filling
```

Watch the API logs for `client_records.structure_missing` and
`vendor_discovery.contact_provenance_missing` — those name a migration that has not been
applied, and both features stay inert rather than failing until it is.
