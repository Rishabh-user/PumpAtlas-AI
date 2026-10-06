# Using this platform's data from another application

Vendors, pumps and the AI chat are already HTTP endpoints. Another application reads them
with a machine key — it does not need a copy of the database, a user login, or any code
from this repository.

This is the integration guide. `docs/API.md` is the internal overview of the whole
surface; this covers the three areas you asked for and the decisions that surround them.

---

## 1. Get a key

```bash
cd backend
python -m scripts.manage_api_key create \
    --name "Portal (read only)" --shared-only --read-only
```

That is a dry run: it prints what the key would be able to see and do. Add `--commit` to
issue it, and the key is printed **once**. Only its hash is stored, so there is no command
that shows it again — if it is lost, revoke it and issue another.

```bash
python -m scripts.manage_api_key list
python -m scripts.manage_api_key revoke --prefix pa_1c4f9a2b --commit
```

### What the key can see

This decision matters more than any other in this document, because it is what stops one
client's supplier list appearing in an application built for someone else.

| Flag | The key sees |
| --- | --- |
| `--shared-only` | The shared master catalogue only — the curated records, and nothing belonging to any client |
| `--tenant <uuid>` | That client's records **plus** the shared master catalogue, exactly as one of their users sees it |

It is enforced in PostgreSQL by row-level security, not by the application: the session
is bound to the key's tenant before any query runs, so a bug in a filter cannot widen it.
A key never carries platform-admin rights, which is the only thing that bypasses those
policies.

A shared-only key is not an empty one — most of this catalogue is shared master. To see
exactly what it would return before handing it over, issue it and call the endpoints; or
ask the database directly:

```sql
SELECT count(*) FILTER (WHERE tenant_id IS NULL) AS shared_only_sees,
       count(*) FILTER (WHERE tenant_id IS NOT NULL) AS belongs_to_a_client
FROM vendors WHERE deleted_at IS NULL;
```

### What the key can do

`--read-only` grants `vendor:read`, `pump:read`, `search:read` and `data_quality:read` —
everything below. Write scopes exist (`vendor:write`, `pump:write`) and are worth a
deliberate decision each time: a key is a password living in someone else's codebase, and
a read-only one cannot change a record however the far end misbehaves.

The script refuses to issue a wildcard (`*`) key.

---

## 2. Call it

Every request carries the key as a header. No login, no token refresh.

```bash
curl http://localhost:8000/api/v1/vendors?limit=5 \
  -H 'X-API-Key: pa_...'
```

Check a key is working, and see what it resolved to:

```bash
curl http://localhost:8000/api/v1/auth/identity -H 'X-API-Key: pa_...'
```

```json
{
  "actor_type": "api_key",
  "tenant_id": null,
  "sees": "shared master catalogue only",
  "scopes": ["vendor:read", "pump:read", "search:read", "data_quality:read"],
  "key": { "name": "Portal (read only)", "prefix": "pa_1c4f9a2b",
           "expires_at": null, "last_used_at": "2026-09-16T08:14:22Z" }
}
```

Not `/auth/me` — that answers for a signed-in person and refuses a key, which is correct:
a key has no profile, no email and no roles.

Lists are paginated with the same envelope everywhere:

```json
{ "items": [ ... ], "total": 77, "limit": 25, "offset": 0 }
```

`total` is the row count ignoring pagination, so the far end can page without guessing.

---

## 3. Vendors

| What | Endpoint |
| --- | --- |
| List, filter, paginate | `GET /api/v1/vendors?q=&approval_status=&limit=&offset=` |
| One vendor, full profile in a single call | `GET /api/v1/vendors/{id}/profile` |
| Contacts | `GET /api/v1/vendors/{id}/contacts` |
| Where each field came from | `GET /api/v1/vendors/{id}/provenance` |
| What the record looked like after each change | `GET /api/v1/vendors/{id}/versions` |

`/profile` is the one to build a page on: it returns the vendor, its contacts, its product
lines, open data-quality flags and a provenance summary together, rather than four calls
against a database a third of a second away.

```bash
curl http://localhost:8000/api/v1/vendors/b4fb3fd2-.../profile -H 'X-API-Key: pa_...'
```

---

## 4. Pumps

| What | Endpoint |
| --- | --- |
| List pump models | `GET /api/v1/pump-models?limit=&offset=` |
| One model: specs, scores, flags, sources | `GET /api/v1/pump-models/{id}` |
| One specification group | `GET /api/v1/pump-models/{id}/specs/{group}` |
| Field-by-field lineage | `GET /api/v1/pump-models/{id}/provenance` |
| Search across everything, with facets | `POST /api/v1/search` |
| Comparable alternatives at a duty point | `POST /api/v1/search/similar/{id}` |

`group` is one of `technical`, `commercial`, `dimensional`, `delivery`, `operational`,
`administrative`.

`POST /search` is the right endpoint for a catalogue screen — it filters, facets and sorts
in one call:

```bash
curl -X POST http://localhost:8000/api/v1/search \
  -H 'X-API-Key: pa_...' -H 'Content-Type: application/json' \
  -d '{"query":"API 610 offshore","sort":"completeness_desc","limit":20}'
```

`GET /api/v1/search/filters/options` returns the vocabularies — pump types, standards,
countries, approval statuses — so the far end builds its filter controls from this
platform's vocabulary instead of hard-coding a list that drifts.

---

## 5. AI chat

```bash
curl -X POST http://localhost:8000/api/v1/chat/ask \
  -H 'X-API-Key: pa_...' -H 'Content-Type: application/json' \
  -d '{"question":"Which suppliers make API 610 OH2 pumps for offshore duty?","use_web":true}'
```

The answer comes back as data, not a rendered page:

```jsonc
{
  "answer": "prose, with [R1] and [W1] citation markers",
  "model": "gemma-3-27b",          // which model answered
  "records": [ /* held records, each with its fields grouped as the profile page groups */ ],
  "record_total": 12,
  "web": [ { "marker": "W1", "url": "...", "title": "...", "excerpt": "..." } ],
  "new_on_web": [ /* pages naming a supplier this platform does not hold */ ],
  "web_error": null,
  "error": null
}
```

Three things worth knowing before you build on it:

* **The markers are the citations.** `[R1]` is the first entry in `records`, `[W1]` the
  first in `web`. Render them as links and the answer is checkable; drop them and it is
  just prose.
* **`use_web: false` is much faster** and answers only from held records. Use it where the
  question is about the catalogue rather than the market.
* **`records` is the evidence, `answer` is not.** Every field in `records` carries what it
  came from. Nothing in `new_on_web` has been stored — those are offers, and capturing one
  is a decision a person makes in this application, not something the far end can do with
  a read-only key.

`GET /api/v1/chat/context` tells you whether a web provider is configured, so the far end
can set expectations before the first question.

---

## 6. Two things that will bite otherwise

**CORS.** If the other application calls this API *from the browser*, add its origin:

```bash
# backend/.env
CORS_ORIGINS=http://localhost:3000,https://portal.example.com
```

But think before doing that: an API key in browser JavaScript is readable by anyone who
opens the developer tools, and it is a credential for this platform's data. For a browser
application, call this API **from that application's own server** and let its frontend talk
to its backend. CORS is then irrelevant and the key never leaves your infrastructure.

**Expiry is real now.** `--expires-in-days` sets a date, and an expired key is refused with
a 401 saying when it lapsed. It used to be recorded and never checked, so a key issued
"for 30 days" worked for good; that is fixed. `list` shows the date, and the last time each
key was used.

---

## 7. A client for the other project

Server-side, so the key stays out of the browser. Nothing here is specific to this
platform beyond the header and the base URL.

```ts
// pumpatlas.ts — runs on the other project's server, never in its browser
const BASE = process.env.PUMPATLAS_URL!;        // http://localhost:8000/api/v1
const KEY = process.env.PUMPATLAS_API_KEY!;     // pa_...

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "X-API-Key": KEY,
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
    // This data changes when a capture runs, not per request.
    next: { revalidate: 300 },
  });
  if (!response.ok) {
    // The body carries a `detail` string saying what was wrong — an expired key, a
    // scope the key does not have, a record in another tenancy. Log it; it is the
    // difference between "broken" and "not allowed".
    throw new Error(`${response.status}: ${(await response.text()).slice(0, 300)}`);
  }
  return response.json() as Promise<T>;
}

export const vendors = {
  list: (limit = 25, offset = 0) =>
    call<{ items: unknown[]; total: number }>(`/vendors?limit=${limit}&offset=${offset}`),
  profile: (id: string) => call(`/vendors/${id}/profile`),
};

export const pumps = {
  list: (limit = 25, offset = 0) =>
    call<{ items: unknown[]; total: number }>(`/pump-models?limit=${limit}&offset=${offset}`),
  model: (id: string) => call(`/pump-models/${id}`),
  search: (body: Record<string, unknown>) =>
    call("/search", { method: "POST", body: JSON.stringify(body) }),
};

export const chat = {
  ask: (question: string, useWeb = true) =>
    call<{ answer: string; records: unknown[]; web: unknown[] }>("/chat/ask", {
      method: "POST",
      body: JSON.stringify({ question, use_web: useWeb }),
    }),
};
```

One caution on `chat.ask`: with `use_web: true` it searches the web and reads pages, so it
takes tens of seconds and costs a provider call. Do not put it behind a page load — call
it from a route handler the user triggers, and consider `use_web: false` for anything that
should feel instant.

---

## 8. The whole contract, generated

The OpenAPI document is the authority and never drifts from the code:

* `http://localhost:8000/docs` — interactive, try a call with your key
* `http://localhost:8000/openapi.json` — generate a typed client from it

Column comments become field descriptions and database enums become enumerated values, so
the spec documents the domain rather than restating the endpoint list.
