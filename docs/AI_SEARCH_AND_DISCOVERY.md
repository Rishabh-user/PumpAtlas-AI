# AI search and web discovery

Where the AI actually runs, how to trigger web discovery, and what to expect from it.

Both providers are configured and were exercised against live keys.

| Provider | Role | Verified |
| --- | --- | --- |
| **OpenRouter / `google/gemma-3-27b-it`** | Extraction, normalisation, classification, summarisation, quality checks, dedupe adjudication | Real call: 3.5 s, 153 prompt + 52 completion tokens, $0.000036 |
| **Parallel AI** (`/v1beta/search`) | Web discovery and result aggregation | Real search: 1.8 s, 5 ranked results with excerpts |

---

## 1. Where the AI runs

Nothing in the platform searches with AI at read time. **`POST /search` is pure
PostgreSQL** — full-text `tsvector` plus structured filters. That is deliberate: search
must be fast, deterministic and explainable.

The AI runs on the **write** side, turning unstructured sources into rows:

| Task | Trigger | Prompt | Writes to |
| --- | --- | --- | --- |
| Structured extraction | Any ingested source | `extract_structured` | `extracted_entities` |
| Normalise to the vocabulary | Enrichment | `normalize_values` | Suggested enum values |
| Classification | Enrichment | `classify_record` | Suggested values + confidence |
| Vendor briefing | `POST /vendors/{id}/summarise` | `summarize_vendor` | `vendors.ai_summary` |
| Missing-field detection | `POST /ai/enrich/{id}` | `detect_missing_fields` | `ai_suggestions` |
| Data quality review | Promotion, `POST /quality/validate/{id}` | `quality_check` | `data_quality_flags` |
| Duplicate adjudication | `POST /quality/duplicates/{id}/adjudicate` | `dedupe_candidate` | Advisory verdict |
| Comparison narrative | `POST /comparisons` with `generate_narrative` | `comparison_narrative` | `comparisons.ai_narrative` |

Scores are never produced by a model. `app/services/scoring.py` is deterministic
arithmetic; the model only writes prose around numbers that already exist.

Every call is recorded in `ai_jobs` with the prompt name and version, model, tokens, cost,
latency and verbatim response. `GET /ai/usage` totals it.

---

## 2. Running web discovery

### From the Vendors screen — AI vendor search

**Vendors → AI vendor search.** The screen for finding Oil & Gas pump suppliers and
choosing which of them to keep.

Type a pump type or duty (`API 610 BB3 multistage`, `ESP electrical submersible`),
optionally a country, and how many pages to read. Then watch both providers work:

| Stage | Provider | What it does |
| --- | --- | --- |
| Web search | Parallel AI | Turns the duty into a research objective and returns ranked pages |
| Capture sources | — | Stores every hit in `sources` before anything reads it |
| Screen and profile | Gemma | Per page: is this an Oil & Gas pump supplier, and what is its profile |

The panel shows each stage's status, the provider working on it, a per-page counter, and
every provider call with its model and latency. A page Gemma rules out is reported as
ruled out, not as a failure — "6 pages found, 2 suppliers" is a result.

When it finishes you get a candidate list. Each candidate carries the supplier name, the
reason Gemma judged it Oil & Gas relevant, the verbatim quote behind that judgement, its
source URL, and every field that *would* be written with the quote and confidence for
each. Tick the ones you want and press **Store**. Nothing reaches the `vendors` table
before that.

A candidate whose name matches a vendor you already hold is labelled — storing it
enriches that record rather than creating a duplicate.

**Why a person still picks.** Screening a real page, Gemma read
`US$680.00-695.00 / Set` — a unit price on a marketplace listing — and offered it as
`annual_revenue_usd: 680`. The value was traceable, refusable and visible next to its
quote, which is exactly why it is a candidate and not a record. Read the quotes.

### From the Pumps screen — AI pump search

**Pumps → AI pump search.** The same flow, aimed at models rather than companies.

The search objective is biased hard toward datasheets and performance curves, because a
product landing page names a model but rarely states a duty point, and a model without
one is not worth a row. Gemma then has to find **both** a manufacturer and a model
designation before a page becomes a candidate: `"BB3"`, `"OH2"` and `"API 610"` are pump
types and standards, never model codes, so a category page is ruled out rather than
stored as a record called "BB3".

Storing a pump candidate does more than storing a vendor. One datasheet carries technical,
commercial, dimensional and delivery values at once, so all four spec groups are written
as new versions — through the same `promote_extracted_entity` the AI review queue uses,
not a second promotion path that could drift from it.

Measured on a real run for "Sulzer MSD multistage datasheet": Parallel AI 2.2s, four Gemma
calls between 15.6s and 67.8s, three candidates. Storing two wrote `min_capacity_m3h`,
`max_capacity_m3h`, `max_head_m`, `driver_type`, `fluid_handled` and `wear_parts_material`
into `technical_specs` v1, each with its own verbatim quote.

**What the model got wrong on that run**, and why the human gate matters: it labelled an
MSD as `centrifugal_oh1` (it is a BB3) and gave `api_682` as the applicable standard
(API 682 is the *seal* standard). Both are valid enum values, so the vocabulary gate had
no reason to refuse them — only a person reading the quote catches that. It also read
"Up to 1,600 m³/h" into both the min and the max.

### "Search every pump type" — why there is still an input

There is no call that returns the whole web. Parallel AI, like every retrieval API,
answers an *objective*: give it a question, get ranked pages. So "fetch everything" has
to be built, not requested.

The **Search every pump type** toggle is the honest version of it. Instead of asking you
to imagine every duty, it generates one search per pump type in the platform's own
controlled vocabulary — 23 of them, from the same `PumpType` enum the database enforces.
Coverage becomes a property of the domain model rather than of what anyone remembered to
type, and adding a pump type to the enum widens the sweep automatically.

What a sweep actually costs, and why the panel says so before you start:

| | |
| --- | --- |
| Parallel AI searches | one per pump type (23) |
| Pages | `max_results` **per type**, capped at 150 in total |
| Gemma calls | one per *unique* page |
| Time | roughly 30s per page — about 75 minutes at the cap |

Duplicate URLs are skipped within a run. Twenty-plus overlapping searches return the same
OEM page again and again, and skipping it is the difference between one Gemma call for
that page and twenty; the capture stage reports how many it skipped.

**You can stop a sweep.** The Stop button asks the runner to finish at its next
checkpoint — between segments, and between pages. Everything it already found stays
reviewable, and the run is badged *Stopped* rather than *Failed*, because you meant it.

**A restart still ends an in-process run.** The API marks any such run interrupted on the
next startup rather than leaving it claiming to be in progress forever. For sweeps this
matters more than for single searches, because an hour-long run is far more likely to
meet a restart — start a Celery worker for them.

### A candidate that cannot be stored says so

A page Gemma judged in scope but could not pull a manufacturer or a model designation
from is still listed — with the reason, and with its checkbox disabled. That check
(`blocked_reason`) runs the same rules the write does, so the panel is a preview rather
than a guess, and a doomed selection is never submitted.

### From the Import queue

**Import queue → Web search.** The older, unattended path: same providers, but it feeds
the AI review queue and can auto-promote. Use it for bulk crawls; use AI vendor search
when you want to see and choose.

### From the API

Three calls make the vendor-search flow. `POST` starts it and returns immediately;
`GET` is polled while it runs; `select` writes the picks.

```bash
# 1. start
curl -X POST http://localhost:8000/api/v1/vendor-discovery   -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json'   -d '{"pump_type": "API 610 BB3 multistage", "country": "DE", "max_results": 8}'

# 2. poll — stages, per-provider jobs, candidates so far
curl http://localhost:8000/api/v1/vendor-discovery/$RUN_ID   -H "Authorization: Bearer $TOKEN"

# 3. store the ones you want
curl -X POST http://localhost:8000/api/v1/vendor-discovery/$RUN_ID/select   -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json'   -d '{"store": [{"candidate_id": "..."}], "reject": ["..."]}'
```

The older unattended crawl:

```bash
curl -X POST http://localhost:8000/api/v1/ingest/web-search \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"recipe":"vendor_discovery","pump_type":"API 610 BB3 multistage","country":"NO","max_results":10,"fetch_full_pages":true,"auto_extract":true}'
```

Three recipes, in `app/ai/parallel_search.py`, so the Oil & Gas framing stays consistent:

| Recipe | Needs | Finds |
| --- | --- | --- |
| `vendor_discovery` | `pump_type`, optional `country` | Manufacturers of a pump type |
| `vendor_intelligence` | `vendor_name` | Legal entity, plants, certifications, references, financials, HSE, ESG |
| `pump_model` | `vendor_name`, `model_code` | The datasheet and performance data for one model |

Or supply your own `objective` and `queries` and skip the recipes.

`fetch_full_pages` matters. Search excerpts came back between 116 and 4,849 characters;
the short ones are nowhere near enough to extract a specification from, so the pipeline
fetches the page itself (3,890–5,611 characters in the verified run).

### Without a Celery worker

Discovery takes minutes, so it cannot run inside the request. Celery is where it belongs
and where it runs in production — but a local checkout has no Redis, and dispatching to
an unreachable broker raises, which would make the feature look broken rather than
unconfigured.

So `services/dispatch.py` probes the broker once per process. If it answers, the run goes
to Celery. If not, it runs on a daemon thread inside the API process and the run record
is stamped `transport: in_process`, which the progress panel shows as an `in-process`
badge.

That fallback is genuinely weaker: the work dies with the API process, does not retry and
does not spread across workers. It exists so the feature works on a laptop. Start a
worker for anything else:

```bash
celery -A app.workers.celery_app worker --loglevel=info --pool=solo -Q default,ingest,ai,index
```

### What happens next

```
POST /ingest/web-search
   └─ import_batches row, status queued
      └─ [ai queue]     Parallel AI search        -> sources (one per hit, with excerpt)
         └─ [ingest]    fetch each URL            -> sources (full page text, robots.txt respected)
            └─ [ai]     Gemma, 7 field groups     -> extracted_entities (+ per-field confidence + evidence quote)
               ├─ auto_promote and confident      -> vendors / pumps / pump_models / specs
               └─ otherwise                       -> /ai/review-queue
                  └─ [index]                      -> search_index, data_quality_flags
```

---

## 3. Storing vendor data automatically

Set `auto_promote`:

```bash
curl -X POST http://localhost:8000/api/v1/ingest/web-search \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"recipe":"vendor_discovery","pump_type":"API 610 BB3 multistage crude export","max_results":10,"fetch_full_pages":true,"auto_extract":true,"auto_promote":true,"min_confidence_to_promote":0.75}'
```

Records are then written straight to the database with no human step. They still carry
full provenance, still get validated, and still appear on the data-quality dashboard.

To run it on a schedule, create a crawl schedule with `target_type: parallel_query`:

```bash
curl -X POST http://localhost:8000/api/v1/ingest/schedules \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"Weekly BB3 vendor sweep","target_type":"parallel_query","target":"Identify manufacturers of API 610 BB3 multistage pumps for Oil & Gas service","cron_expression":"0 3 * * 1","max_pages":25,"auto_extract":true}'
```

Celery beat dispatches due schedules every 15 minutes.

---

## 4. What a real unattended run actually produced

A `vendor_discovery` run against live keys, `auto_promote: true`, threshold 0.6, two
results. Verified in the database afterwards:

| Table | Rows |
| --- | --- |
| `sources` | 4 (2 search hits + 2 fetched pages) |
| `ai_jobs` | 10 |
| `extracted_entities` | 6 |
| `vendors` | 1 — **PumpWorks, created with no human involvement** |
| `pumps` / `pump_models` | 2 / 3 |
| `technical_specs` | 1 |
| `field_provenance` | 13 |
| `search_index` | 3 |

The mechanism works. **The data quality from a general web page does not.** Same run:

* A pump was created named `"610"` — Gemma put the standard number in the product-name
  field.
* Another got `pump_type_raw = "1"`.
* A placeholder `"PumpWorks unspecified line"` record appeared where no product name was
  extracted at all.
* `country` was left empty.
* Only one of three pump models got a technical spec; most field groups produced nothing
  usable.

This is what a marketing or catalogue page yields: it is prose about capability, not a
datasheet. Two guards were added as a result, and both are visible in that run:

* **Vocabulary coercion.** Gemma returned `"610"` for `applicable_standard`, which as a
  native PostgreSQL enum raised `LookupError` and aborted the whole promotion.
  `app/services/vocabulary.py` now maps `"610"`, `"API 610"`, `"api-610"` onto `api_610`,
  refuses anything ambiguous, and diverts an unmappable value to the `*_raw` column —
  which is why `pump_type_raw` holds `"centrifugal"` instead of the run dying.
* **Weak-subject refusal.** Unattended promotion now rejects a subject name that is
  purely numeric or under three alphanumeric characters, so `"610"` and `"1"` go back to
  the review queue instead of becoming records someone has to find and merge away.

### So how should you use it

| Source | Recommendation |
| --- | --- |
| Vendor datasheet or quotation (PDF) | **Auto-promote at 0.85.** Structured, tabular, high-yield — this is what the extractor is good at |
| Vendor product page | Extract, then **review**. Good for discovering that a vendor and product line exist; poor for specifications |
| Search excerpt only | Discovery only. Too short to extract from |
| Reference lists, certificates | Auto-promote at 0.85 |

The honest summary: use web discovery to **find vendors and their documents**, then
auto-promote from the **documents**. Pointing auto-promotion at general web pages fills
the database with thin records that cost more to clean than they save.

Two settings control this trade-off:

* `min_confidence_to_promote` (per request, default 0.85) — lower captures more and
  reviews more.
* `auto_promote` (per request, default false) — off means everything lands in
  `/ai/review-queue`, where each field shows its evidence quote and can be corrected
  inline before acceptance.

---

## 5. Cost and latency, measured

| | Observed |
| --- | --- |
| One Gemma extraction call | 3.5 s typical, $0.000036 for a small prompt |
| A degenerate call | 119 s, 4,096 completion tokens, $0.002 — Gemma emitting trailing whitespace on a large HTML-derived prompt |
| Parallel AI search | 1.8 s for 5 results |
| Full pipeline, 2 URLs, 7 field groups each | roughly 5 minutes |

Extraction runs **one call per field group** (seven groups), which keeps each response
inside Gemma's reliable output length and means a partial failure only retries the group
that failed. It also means a source costs seven calls, so a 25-result discovery run is
around 175 calls.

That 119-second call is worth knowing about: it is what exposed the transaction bug below.

---

## 6. The bug that made this impossible until now

Extraction held a database transaction open across the provider call. With
`idle_in_transaction_session_timeout = 60s` set on every connection, a call slower than a
minute meant PostgreSQL closed the connection and the task died with
`PendingRollbackError` — **after** the model had been paid for. Any AI call over 60
seconds killed the run, and nothing reached the database.

`extraction.execute_ai_job` now commits the `ai_jobs` row, releases the transaction, makes
the call with no database resources held, and writes the result in a fresh transaction.
The tenant GUC is re-applied automatically on that new transaction, so RLS still applies.
All six provider call sites go through it, and a test fails the build if a new
`client.complete(...)` appears anywhere else.
