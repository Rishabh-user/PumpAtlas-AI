# Project review — October 2026

A full pass over PumpAtlas AI: code, database, security posture and operations. Findings
are ordered by what they cost if left alone, each with the evidence behind it and what
fixing it involves. Everything here was measured against the running system rather than
inferred from the code.

Three passes so far, newest first: **26 October** (read against the SOW and the
multi-tenant product the code has become), **14 October**, and the original on
**6 October**. Each section says what it re-measured, so a number in an older section is
a record of what was true then, not a claim about today.

**Verdict, as at 26 October.** The engineering is sound and unusually disciplined in the
places that are hardest to retrofit — tenant isolation enforced by the database rather
than by application code, field-level provenance, and a write gate that refuses an
unevidenced value. Those are what make a multi-tenant product possible at all, and they
are already there.

The risks are not in the architecture. They are, in order: that SOW §9 asks for 80%
completeness on commercial and delivery data that no web source publishes and the Client
has not yet supplied; that a client's commercially sensitive documents remain in a git
history that has already been pushed; and that two migrations have been waiting on owner
credentials for three weeks, holding 1,426 contacts and 664 registration identifiers in
a JSON blob and leaving 93 of 160 "pump models" as approved-suppliers lines wearing a
product's clothes.

The first of those is a conversation, not a sprint.

---

## Status — 26 October 2026

A third pass, re-measured against the running system today. This one is read against two
documents rather than one: the signed SOW, and the product the code has actually become.

**They are not the same thing, and the code is following the product.** The SOW is a
single-client deliverable for Shapoorji Pallonji Energy — pilot category pumps, two or
three nominated packages, UAT, training, complete. What exists is a multi-tenant master
database serving per-customer API keys, with SP Energy as tenant one. That is the right
direction and the architecture supports it, but it raises a question the SOW does not
answer, recorded under *Contract* below.

### The product model holds, and the database is what enforces it

Tested by connecting as each issued key would, rather than by reading the code:

| Key | Reads |
| --- | --- |
| No tenant | **55** — the shared master catalogue only |
| Demo Offshore Operator | **86** = 31 of its own + 55 shared |
| SP Energy | **1,656** = 1,601 of its own + 55 shared |
| Platform admin | 1,687 — everything |

36 of 37 tables carry `FORCE ROW LEVEL SECURITY`; only `ai_provider_configs` does not,
which is platform-level credential storage and correct as it stands. An API key resolves
to `is_platform_admin=False`, so no key can bypass RLS whatever its scopes say. A
customer key holding the four read scopes is refused `vendor:write`, `ingestion:write`,
`tenant:write` and `ai_review:approve`.

That is "one master database, per-customer access", enforced by PostgreSQL rather than by
application code, and it is the part of this system least worth rebuilding.

### The acceptance criterion that cannot be met on the current path

> **SOW §9** — "Vendor database populated with the agreed minimum vendor count and **≥80%
> field completeness for core technical, commercial and delivery fields** in the pilot
> vendor set."

Measured today across 160 live pump models:

| Group | Models holding any data | |
| --- | --- | --- |
| Technical | 86 | 54% |
| **Commercial** | **4** | **2%** |
| **Delivery** | **7** | **4%** |

Average model completeness is **2.1%**; vendors **24.0%**.

More web collection will not move the second and third rows. Measured directly over ten
enrichment runs: six of ten models gained technical specifications and **none** gained
commercial, delivery, dimensional, operational or administrative data. A manufacturer
publishes duty curves, materials and configuration. Nobody publishes a price, a lead
time, a warranty or an on-time delivery record — those live in a quotation.

The SOW already names the sources that would close it. §5.1 assigns *Client executed
project records* (price paid, actual delivery) and *vendor self-declaration via
questionnaire* to the Client. **Neither has been delivered.** Until one of them is, §9 is
unreachable however much effort goes into collection.

This is a dependency, not a defect, and it needs raising with the Client rather than
engineered around. It is the most consequential item in this review.

### Contract — whose database is this

SP Energy's 1,601 supplier records, their GST and PAN registrations and their signed
approved-suppliers list sit in a database whose shared-master catalogue other tenants
read. The separation is correct today: their rows are tenant-scoped and the 55 shared
records are distinct. But the SOW assigns ownership of *data sourcing* (§5.1) and says
nothing about ownership of the *resulting database*. Worth settling before a second
customer signs, not after.

### Closed since 14 October

| | |
| --- | --- |
| Verification protected nothing | 65 models were badged "verified" with **zero** protected fields: the endpoint set `verification_status` on the row while the guard reads `field_provenance.confidence_level`. `provenance.mark_verified` now records the confirmation where the guard looks, vendors gained the verify endpoint they never had, and both pages have the button. |
| Vendor creation was broken outright | Migration 003's columns are mapped but absent from the database. `deferred=True` protects SELECT; an INSERT names every column, so creating any vendor failed — taking out the discovery Store button, `POST /vendors` and every sweep that found something. The six columns are declared only when `VENDOR_STRUCTURE_READY` is set, and `/ready` reports a mismatch in either direction. |
| A serialiser loaded columns the database lacks | `audit.snapshot` read every column by name, killing `repair_vendor_data` on its first record. It now skips unloaded attributes. Fourth occurrence of this failure class, first on a write path. |
| Empty scorecards scored zero | Commercial fit and delivery risk are unscorable on almost every record; scoring them 0.0/E read as "assessed and failed". They now abstain and the overall redistributes their weight — one record reads 67.0/C where it read 36.9/E. |
| Duty data was invisible | The list asked for `rated_capacity_m3h` while 56 of 78 records hold `max_capacity_m3h`: a model sold in 45 sizes has an envelope, not a rated point. Capacity visible across the catalogue went 6 → 63, head 3 → 58. |
| The manual form the UI advertised did not exist | Every empty panel said "submit the data through the manual form" and nothing ever called `PUT /pump-models/{id}/specs/{group}`. For five of six groups that was the only possible route in. |
| `/compare` and `/review` | Removed at the Client's direction, with the scoring engine and requirement profiles kept — `score_pump_model` lives in `services/comparison.py` despite the name and powers every scorecard. |

### Still open, verified today

| Finding | Measured now |
| --- | --- |
| **C2** Client documents in git history | **Unchanged, and still the only finding that worsens with time.** Ignored and untracked, but present in every commit already pushed. |
| **C3** Migrations 002 and 003 | **Still unapplied.** Owner credentials are not on this machine — the application role is `NOBYPASSRLS` with no DDL by design, which is correct and also means nobody here can apply them. |
| **H1** Contacts trapped in JSON | `vendor_contacts` holds 1 row against 1,426 named contacts. Blocked on 002. |
| 93 of 160 "pump models" are not pumps | 65 approved-suppliers lines, 15 resolver placeholders, 13 bare API 610 type codes. Blocked on 003, which adds the table they belong in. |
| API keys never expire | All four active keys have `expires_at = NULL`. Expiry is enforced; nothing sets it. A key issued to a customer today works for good. |
| A key with no owner | "Shapoorji vendor database" has no tenant. It leaks nothing — it reads the 55 shared records only — but a key nobody owns is a key nobody will think to revoke. |

### What a product needs that an engagement did not

Recorded here because the shift from deliverable to product changes what counts as
missing. None of these are SOW items:

* **Per-key usage accounting.** Rate limits are per process and held in memory: two
  instances allow twice the stated rate and a restart forgets. Billing a customer needs
  counters that survive both.
* **Key lifecycle.** Issue, expire, rotate and revoke, with the customer visible on the
  key. Today a key is a row and a CLI script.
* **A tenant onboarding path.** Four tenants exist; two are suspended duplicates both
  named "Rival EPC Contractor". Creating a customer is a manual insert.
* **Redis and a worker.** Enrichment runs in the API process, so a restart kills
  everything in flight; 226 vendors took six hours of a browser tab staying open.

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
| Tests | 1,000 passing, 31 skipped (all requiring a live stack), in 26 seconds. Lint clean across `app`, `tests` and `scripts`; frontend lint, typecheck and build clean. |
| Frontend | Compiles clean; the client/server boundary check passes across 98 files and 44 client modules. |
| Traceability | 13,059 field-provenance rows, 1,449 of them verified and so protected from AI overwrite, across 2,567 captured sources and 709 audit entries. Every AI-written value carries a verbatim quote or it is refused. |
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

Revised 26 October. Steps 1, 2 and 6 of the original list are done. What remains divides
into three kinds, and only one of them is engineering:

* **A conversation with the Client** — step 0 below, and the largest item in this review.
* **Database work needing the owner** — steps 2 to 4, which nobody on the development
  machine can do, by design.
* **Product work that the SOW never asked for** — steps 7 and 8, which exist because this
  is becoming a product rather than a deliverable.

0. **Raise the commercial and delivery data gap with SP Energy.** SOW §9 requires ≥80%
   field completeness across technical, commercial and delivery. Commercial sits at 2%
   and delivery at 4%, and no amount of web collection will move them: ten measured
   enrichment runs returned none of price, lead time, warranty or on-time delivery,
   because manufacturers do not publish them. §5.1 already assigns the sources that
   would — executed project records and vendor questionnaires — to the Client, and
   neither has arrived. Everything else on this list is cheaper than this conversation,
   and none of it substitutes for it.

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
   watches. Until then an API restart kills every run in flight, and a 226-record
   enrichment means six hours of a browser tab staying open.

9. **Give customer API keys a lifecycle.** All four active keys have `expires_at = NULL`,
   so a key issued to a customer works for good; expiry is enforced but nothing sets it.
   Retire the "Shapoorji vendor database" key, which has no tenant — it reads only the
   55 shared records, so it leaks nothing, but a key nobody owns is a key nobody will
   think to revoke.

10. **Add per-key usage accounting** before anyone is billed. The rate limits are held in
    memory per process: two instances allow twice the stated rate and a restart forgets
    everything. That is adequate for stopping a runaway client and useless as a meter.

11. **Settle who owns the aggregated database.** The SOW assigns ownership of data
    *sourcing* and is silent on the resulting database. Worth answering before a second
    customer signs rather than after.

Steps 2–4 are a few hours and close every finding that is currently costing something.
Step 1 is the one that cannot be deferred, because waiting increases the damage. Step 0
is the one that decides whether the engagement can be accepted at all.
