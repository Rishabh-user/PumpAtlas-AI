# Project review — October 2026

A full pass over PumpAtlas AI: code, database, security posture and operations. Findings
are ordered by what they cost if left alone, each with the evidence behind it and what
fixing it involves. Everything here was measured against the running system on
2026-10-06, not inferred from the code.

**Verdict.** The engineering is sound and unusually disciplined in the places that are
hardest to retrofit — tenant isolation, provenance, and the write gate that refuses
unevidenced values. The risks are not in the architecture. They are that the whole thing
is unversioned, that a client's commercially sensitive documents sit unprotected in the
working tree, and that most of the data now in the database arrived through an import
path that bypasses the guarantees the rest of the system is built on.

---

## Status — 14 October 2026

A second pass, eight days on. Everything below was re-measured against the running
system today, through a platform-admin session: an unscoped connection sees 53 of 1,692
vendors, because row-level security is doing its job, and counting through one would
have understated this database by 97%.

### Closed since the first review

| | What changed |
| --- | --- |
| **C1** Version control | Done. A repository with history on `main`, pushed to a remote. |
| **H3** No rate limiting | Done. `app/core/rate_limit.py` bounds the two endpoints that spend provider money (20 AI questions and 10 enrichments per caller per hour) and login (10 per 5 minutes). Verified against a live instance: ten 401s, then 429 with `Retry-After: 280`. Counted **in memory, so per process** — two instances allow twice the rate and a restart forgets. That stops a runaway client, which is the failure that empties a provider account; it is not a cross-instance guarantee, and the module says so. |
| **`/metrics` was public** | Found in this pass, now closed. `infra/nginx.conf` restricted that path to private networks — and there is no nginx in front of a Render service, so the endpoint was answering the internet with every route name, its traffic and its latencies. Now: unset `METRICS_TOKEN` in production disables it, a wrong token is 401, compared with `secrets.compare_digest`. |
| **Credentialed CORS wildcard** | Found in this pass, now closed. `CORS_ORIGINS=*` with `allow_credentials=True` is not a wildcard — Starlette echoes back whatever `Origin` asked, which is consent to every origin individually. It is refused in production and reported by `/ready`. Latent rather than live, because the browser never calls this API directly: it goes through the Next proxy, which swaps an httpOnly cookie for a header. It would have stopped being latent the first time anything pointed a browser at the API — which is exactly what the two issued keys invite. |
| **Changing a password needed a database shell** | `POST /auth/change-password` existed from the start and nothing called it, so the only way to change one was psql. There is now an `/account` page. All six active users have since changed theirs. |

### Still open, verified today

| Finding | Measured now |
| --- | --- |
| **C2** Client documents in git | **Half closed, and the dangerous half is still open.** They are now in `.gitignore` and out of the index — and they are *already in the history that has already been pushed*. Ignoring a file does not remove it from the commits that carry it. This needs a history rewrite and a force-push, or a fresh repository; until then, treat the contents as disclosed. |
| **C3** Migration 002 | **Still unapplied.** `vendor_contacts` has none of `source_id`, `captured_at`, `origin`. |
| Migration 003 | **Still unapplied.** No `vendor_approvals` table, and `vendors` has none of the six new columns. The ORM carries them as `deferred=True` and `VendorOut` excludes them precisely so the application keeps working without them — that scaffolding is load-bearing until the migration runs. |
| **H1** Contacts trapped in JSON | **Unchanged: `vendor_contacts` holds 1 row.** 1,426 named contacts are still inside a JSON blob, unsearchable and outside provenance. |
| **H4** Completeness unset | Unchanged — `repair_vendor_data` still needs its `--commit` run. |
| Failed AI jobs | 9. |

Nothing in this section is blocked on code. Every one of them is a command to run against
the database, listed under *What I would do, in order*.

### Housekeeping done in this pass

- The rate-limit and metrics tests ran for **14 minutes 32 seconds** and failed one case,
  because they signed in twenty-four times over real HTTP to watch a limiter bite —
  against a database 300ms away, with bcrypt on every attempt, on the deployed system.
  Rewritten to test the counter where it lives: **1.9 seconds, 19 passing**, nothing
  touching the database. A test that hammers production to prove an in-memory counter
  works is a bad trade twice over.
- `METRICS_TOKEN` and `RATE_LIMIT_ENABLED` were added to the code and not to
  `.env.example`. The configuration test caught it, which is what it is for.
- `npm run lint` was wired up with ESLint installed and **no config file**, so it did not
  lint — it dropped into Next's interactive setup wizard, which hangs a terminal and
  fails CI for reasons unrelated to the code. Config added; the 18 real errors it then
  found are fixed (dead imports, an `<a>` doing a full page reload where `<Link>` belongs,
  a `require()` in an ES module). Lint, typecheck and build are clean.
- `frontend/tsconfig.tsbuildinfo` was tracked: machine-local build state, rewritten every
  build, a guaranteed merge conflict. Now ignored.

---

## What is working

Credit where it is due, because these are the parts that are expensive to add later.

| | Evidence |
| --- | --- |
| Tenant isolation | Row-level security **enabled and forced** on every tenant table, with policies — `vendors`, `pump_models`, `search_index`, `vendor_contacts`, `field_provenance`, `sources`, `audit_logs`, `users`, `api_keys`. The application connects as `pumpatlas_app`: not a superuser, and **does not bypass RLS**. Isolation cannot be undone by an application bug. |
| Tests | 961 passing, 32 skipped (all requiring a live stack), in 21 seconds. Lint clean across `app`, `tests` and `scripts`; frontend lint, typecheck and build clean. |
| Frontend | Compiles clean; the client/server boundary check passes across 98 files and 44 client modules. |
| Traceability | 1,634 field-provenance rows, 184 record versions, 508 audit entries. Every AI-written value carries a verbatim quote or it is refused. |
| Deduplication | **Zero** duplicate normalised names within any tenancy, across 1,684 vendors. |
| Dependencies | 24 pinned versions, no floating ranges. |
| Code hygiene | Zero `TODO`/`FIXME`/`HACK` markers in 30k lines of Python and 16.5k of TypeScript. |
| Known AI failures | The 9 failed provider jobs are all from 2–7 September; the "assistant prefill" 400s are already handled by a retry path that drops the unsupported feature. Not an open defect. |

---

## Critical

### C1 · The project is not under version control

`git rev-parse` reports no repository. 46,000 lines of code, a schema, and a fleet of
operational scripts, with **no history, no branches, no diffs, no blame and no way back**.

This is the finding that makes every other finding worse. Several agent sessions have
been editing these same files — this review found files changed since the last session
with no record of what changed or why. One bad overwrite is unrecoverable.

```bash
cd "D:/Targeticon/PumpAtlas AI"
# Do C2 FIRST — see below — then:
git init && git add -A && git commit -m "PumpAtlas AI: initial import"
```

### C2 · Client-confidential documents sit in the tree and are not ignored

`Approved Vendor List/` holds a **signed** approved suppliers list (ONGC KG-DWN-98/2) and
five SAP vendor-master exports. `.gitignore` does not mention them.

An approved vendor list tells a competitor who a client will buy from; the import script's
own docstring says so. The moment someone runs `git add .` — which C1 asks for — that
goes into history permanently, and history is what gets pushed to a remote.

**Do this before `git init`:**

```bash
printf '\n# Client documents: commercially sensitive, never committed.\nApproved Vendor List/\n*.XLSX\n' >> .gitignore
```

Also note there are two `.env` files (repo root and `backend/`). Both are matched by the
existing `.env` rule; confirm that after `git init` with `git check-ignore -v .env backend/.env`.

### C3 · Migration 002 has never been applied

```
migration 002 applied: False
```

`vendor_contacts` still lacks `source_id`, `captured_at` and `origin`. The guard built for
this behaves correctly — contact auto-recording is skipped rather than writing untraceable
values — but it means the feature has been inert since it was written, and it blocks H1
below.

```bash
python scripts/apply_schema.py --url "postgresql://OWNER:PASSWORD@HOST/DB?sslmode=require" \
    --file db/migrations/002_vendor_contact_provenance.sql
```

Restart the API afterwards; the column check is cached per process.

---

## High

### H1 · 1,426 contacts are trapped in a JSON blob

| | |
| --- | --- |
| Contacts inside `vendors.extra->'contacts'` | **1,426**, across 1,350 vendors |
| Rows in `vendor_contacts` | **1** |

The blobs already have the shape of the table:

```json
{ "role": "commercial", "email": "...@2hoffshore.com",
  "phone": "60327260500", "company_name": "2H OFFSHORE ENGINEERING SDN BHD" }
```

Because they are in `extra`, they are invisible to `GET /vendors/{id}/contacts`, to the
Contacts panel on the vendor page (which reads "No contacts recorded" for all 1,350), and
to the external API handed to the other project. They cannot be searched, deduplicated or
checked against the contact details found on the web.

This is the single highest-value fix in the review: the data is already there and correct,
it is simply in the wrong place. A migration script should move each entry into
`vendor_contacts` with `origin='manual'` and `source_id` pointing at the import document
that carried it — which requires **C3 first**, since those columns do not exist yet.

### H2 · 241 vendors are "approved" with nobody accountable

```
approval_status | n   | with approver | with expiry | with provenance
approved        | 241 | 0             | 0           | 2
```

These came from the client's approved supplier lists, so the *status* is legitimate — but
the record does not say who approved them, under what authority, or when it lapses. An
approval nobody can account for is the thing `approval_status` exists to prevent, and it
is now the state of 241 records rather than the 2 this review caught last month.

`POST /vendors/{id}/qualification` records all three and refuses a decision without a
reason. The import path writes the column directly and bypasses it. Either route the
import through that endpoint's logic, or have it stamp the approving document as the
provenance source and the list's own date as the expiry.

### H3 · No rate limiting, on an API that now spends money

There is no limiter anywhere in `app/main.py` or `app/core/`. Login lockout exists (5
attempts), but nothing else is bounded.

Two active API keys have been issued to another project. `POST /chat/ask` with
`use_web: true` triggers a web search and reads pages — real provider spend per call — and
`POST /vendors/{id}/enrich` starts a discovery run. A loop at the far end, or one leaked
key, is an unbounded bill with no ceiling and no alert.

At minimum: a per-key request limit on the AI endpoints, and a daily cap on provider spend.

### H4 · The quality dashboard is averaging 0.5% of the data

```
vendors      1684 rows, 8 with a completeness figure
pump_models   160 rows, 79 with a completeness figure
```

`repair_vendor_data` was never run at scale, so `data_completeness_pct` is unset on 1,676
vendors. The dashboard average, the "least complete" sort and the `completeness_min`
filter are all computed from the handful that have it — which is worse than showing
nothing, because it looks like an answer.

```bash
python -m scripts.repair_vendor_data            # dry run
python -m scripts.repair_vendor_data --commit
```

---

## Medium

### M1 · A quarter of all discovery runs die from API restarts

22 of 97 runs failed with *"Interrupted by an API restart. This run executed in the API
process."* Redis is absent, so `dispatch` falls back to running discovery inside the API
worker, and any reload kills it mid-flight.

The fallback is the right design for a developer machine; it is not a deployment. Running
Redis and a Celery worker turns a 23% loss rate into zero, and is the difference between
"the sweep is still going" and "the sweep died when you saved a file".

### M2 · The search index is going stale and nothing refreshes it

87 of 160 rows were last indexed more than a week ago. Nothing missing (0 models absent —
that gap was fixed), but nothing scheduled either: a row refreshes only when its record is
written. Vendor-level changes — a new name, a country, an approval — do not reach the index
until something touches the model.

### M3 · Two of the five scorecards cannot score

| group | current rows (of 160 models) |
| --- | --- |
| technical | 76 |
| delivery | 7 |
| commercial | **4** |
| administrative | 4 |
| dimensional | 3 |
| operational | **2** |

Commercial fit and delivery risk are structurally 0.0/E for almost every record, and will
stay that way until datasheets are read. `scripts.pending_pumps` lists exactly which
records are waiting and what each is missing; the "Find datasheet" button on a model is
the per-record action.

### M4 · 27 candidates are still waiting in the pump review queue

Some are the API-type-code category pages ("OH1", "VS6", "API 610 OH1") that are now
refused at screening. The cleanup for the ones already queued has not been run:

```bash
python -m scripts.clear_category_candidates    # then --commit
python -m scripts.flag_category_models         # 13 models named after a category
```

### M5 · One table has no row-level security

`ai_provider_configs` — the only table in `public` with RLS off. It is platform-scoped
(no `tenant_id` column), so this is defensible: there is no tenant boundary to enforce.
Its protection is that `encrypted_api_key` is Fernet-encrypted and the role reaching it is
`pumpatlas_app`. Worth a comment in the schema saying that is deliberate, so the next
person auditing does not have to work it out.

---

## Carried over, unverified

These were raised in earlier sessions and I cannot confirm their state from here:

* **Credential rotation.** Five credentials reached a chat transcript and should be treated
  as compromised: the Render owner database password, the `pumpatlas_app` password, and the
  OpenAI, Anthropic and Parallel API keys.
* **The default admin password.** `admin@targeticon.com` was created with a published
  default. `python -m scripts.manage_user set-password --email admin@targeticon.com`.

---

## What I would do, in order

Rewritten 14 October. Steps 1, 2 and 6 of the original list are done; what remains is
almost entirely database work, and none of it is blocked on code.

1. **Purge the client documents from git history** — the one finding that gets worse with
   time, because the repository is already pushed. They are ignored and untracked now, so
   nothing new is being added, but every existing commit still carries them. Either
   rewrite the history and force-push, or delete the remote repository and push a fresh
   one with no history. Until then the contents are disclosed: 1,426 named contacts with
   direct numbers, GST and PAN registrations for 691 suppliers, and bank details.

2. **Apply migrations 002 and 003**, then restart the API.

   From the repository root. `--file` is what applies one incremental migration to a
   database that already has tables; without it the script refuses to touch one.

   ```bash
   python scripts/apply_schema.py --url "$OWNER_DATABASE_URL" --file db/migrations/002_vendor_contact_provenance.sql
   ```

   ```bash
   python scripts/apply_schema.py --url "$OWNER_DATABASE_URL" --file db/migrations/003_client_vendor_structure.sql
   ```

   Connect as the database **owner**, not `pumpatlas_app` — the application role has no
   DDL rights by design, which is why these have to be run by hand. Omitting `--url`
   falls back to the app's own configuration, which is the role that cannot do it.
   003 brings its own forced row-level security; the vendor identifier tables are
   strictly tenant-private, with no shared-master read.

3. **Move the 1,426 contacts out of `extra`** — still the largest visible gain for the
   least work, and it needs 002 first so each contact can carry where it came from.
   These run as modules, so from `backend/`. Every one of them is a dry run until
   `--commit`; read what the dry run says it will do before passing it.

   ```bash
   python -m scripts.backfill_contact_details          # dry run first
   python -m scripts.backfill_contact_details --commit
   ```

4. **Structure the client records** (needs 003), then repair the derived figures:

   ```bash
   python -m scripts.structure_client_data --commit
   python -m scripts.repair_vendor_data --commit
   python -m scripts.clear_category_candidates --commit
   python -m scripts.flag_category_models --commit
   ```

5. **Give the imported approvals an approver and an expiry** (H2) — 241 vendors are
   approved with nobody accountable.

6. **Rotate the five credentials that reached a chat transcript**: the Render owner
   database password, the `pumpatlas_app` password, and the OpenAI, Anthropic and
   Parallel keys. Treat them as compromised regardless of how the transcript is stored.

7. **Set `METRICS_TOKEN`** in the Render dashboard if anything should scrape metrics;
   leave it empty and the endpoint stays off, which is the safe default.

8. **Stand up Redis and a worker** (M1) when discovery stops being something a person
   watches. Until then an API restart kills every run in flight.

Steps 2–4 are a few hours and close every finding that is currently costing something.
Step 1 is the one that cannot be deferred, because it is the only one where waiting
increases the damage.
