# AI and provenance

## The contract

> No intelligence field may be written by AI without a `field_provenance` row naming the
> source, the evidence quote, the model and the confidence.

This is enforced in `app/services/provenance.py`. `apply_field()` raises
`ProvenanceError` when the origin is AI-derived and no evidence quote is supplied, so an
untraceable AI value cannot reach the database even by mistake.

## Where each model is used

| Task | Provider | Prompt | Output |
| --- | --- | --- | --- |
| Structured extraction from unstructured text | OpenRouter / Gemma | `extract_structured` | `extracted_entities` |
| Normalising free text to the controlled vocabulary | Gemma | `normalize_values` | Suggested enum values |
| Classification (pump type, standard, tier) | Gemma | `classify_record` | Suggested values + confidence |
| Vendor summarisation | Gemma | `summarize_vendor` | `vendors.ai_summary` |
| Missing-field detection | Gemma | `detect_missing_fields` | `ai_suggestions` |
| Data quality / contradiction checks | Gemma | `quality_check` | `data_quality_flags` |
| Duplicate adjudication | Gemma | `dedupe_candidate` | Advisory verdict on `duplicate_candidates` |
| Comparison narrative | Gemma | `comparison_narrative` | `comparisons.ai_narrative` |
| Web discovery and result aggregation | Parallel AI | search recipes | `sources` |

Scores are **never** produced by a model. `app/services/scoring.py` is deterministic
arithmetic with an explainable per-criterion breakdown; the model only writes prose
around numbers that already exist.

## Making a small open model behave

Gemma is capable but not naturally disciplined about structured output. Four measures:

1. **JSON mode plus a re-assertion in the prompt**, then defensive parsing that recovers
   from fenced blocks, leading prose and trailing commas (`ai/openrouter.py`).
2. **One repair round-trip.** Unparseable output is sent back with "re-emit valid JSON
   only" before the job is failed.
3. **Temperature 0 for extraction**, so re-running the same source is reproducible.
4. **Field groups.** Extraction runs per group (technical, commercial, and so on) rather
   than over 400 fields at once. Responses stay inside the reliable output length, and a
   partial failure only retries the group that failed.

## Refusing bad candidates before a human sees them

`app/services/extraction.py` drops a field when:

* its confidence is below `MIN_FIELD_CONFIDENCE` (0.4) - that is noise, not intelligence;
* it has no evidence quote - unverifiable, therefore unpromotable;
* its unit cannot be converted - a number in an unknown unit is worse than a blank.

Whatever survives is stored with per-field confidence and the quote supporting it.

## The prompt rules that matter

From `app/ai/prompts.py`:

* **Never invent.** Return `null` for anything the source does not state. A guessed NPSH
  figure is worse than a blank, because a blank is visible on the data-quality dashboard
  and a guess is not.
* **Always cite.** Every non-null field needs a verbatim quote of 240 characters or less.
* **Normalise to SI, and record what the source said.** `"rated_capacity_m3h": 272.5`
  alongside `"source_units": {"rated_capacity_m3h": "1200 USgpm"}`.
* **Use the controlled vocabulary or nothing.** The vocabulary block is generated from
  `app/models/enums.py`, so the prompt and the database cannot disagree. If a value does
  not map, the enum field stays null and the raw string goes to the matching `*_raw`
  column.

Domain guidance is included because it changes output quality materially: API 610 type
codes belong in `api_610_type_code`; "Plan 52" is an API 682 flush plan; "S-6" is an
API 610 Table H.1 material class; rated duty and best efficiency point are different
things and must not be merged.

## Confidence and verification are two different axes

`confidence_level` says **how the value was obtained**:

| Level | Meaning |
| --- | --- |
| `verified` | Confirmed against an authoritative document by a human |
| `vendor_declared` | The vendor stated it; unverified |
| `third_party` | Trade press, distributor, registry |
| `ai_extracted` | Pulled from unstructured text by the model |
| `estimated` | Inferred or interpolated |
| `unknown` | No basis recorded |

`verification_status` says **where it sits in the review workflow**: `unverified`,
`in_review`, `verified`, `disputed`, `superseded`.

Both feed the data-confidence scorecard, which is what stops a beautifully ranked
candidate with no real data behind it from winning a comparison.

## Verified fields are protected from the crawler

The most damaging failure mode in a platform like this is a fresh crawl silently
overwriting a figure an engineer confirmed by phone. `apply_field()` refuses an AI-origin
write against a field whose current provenance is `verified`, unless a human passes
`overwrite_verified` explicitly - and that override is recorded in the audit log.

## Auditing a number

Three endpoints answer three different questions:

| Question | Endpoint |
| --- | --- |
| Where did this value come from? | `GET /pump-models/{id}/provenance` |
| What did this record look like before? | `GET /pump-models/{id}/history` |
| What did the model actually return? | `GET /ai/jobs/{id}?include_raw=true` |

`GET /ai/usage` accounts for tokens, cost and latency per job type, so the assistant
layer's cost is visible rather than assumed.

## Running without AI

Set `AI_ENABLED=false`, or leave `OPENROUTER_API_KEY` unset. Ingestion, parsing, manual
entry, search, scoring, comparison, versioning and audit all keep working; extraction and
enrichment endpoints return a clear 503 naming what is not configured. The platform
degrades to a well-structured manual intelligence database rather than breaking.
