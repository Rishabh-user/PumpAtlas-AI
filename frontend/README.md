# PumpAtlas AI — Frontend

Next.js 15 dashboard (App Router, React 19, TypeScript, Tailwind). Ten screens over the
FastAPI backend: search, vendors, pump profile, comparison, import queue, AI review, data
quality, audit trail and tenant management.

---

## Prerequisites

* Node 20+ (Node 24 used here)
* **The backend running.** This app has no data of its own — start the API first, per
  [backend/README.md](../backend/README.md).

---

## Run it

```bash
npm install
```

```bash
API_INTERNAL_URL=http://localhost:8000 npm run dev
```

On PowerShell, set the variable first:

```powershell
$env:API_INTERNAL_URL = "http://localhost:8000"; npm run dev
```

Then http://localhost:3000 and sign in with `analyst@demo-operator.example` /
the password you chose when you created the account with the backend's
`python -m scripts.manage_user create` (there is no default login).

### `API_INTERNAL_URL`

The **server-side** address of the API — used by server components and by the proxy route
handler. It defaults to `http://localhost:8000`, so the plain `npm run dev` works for the
standard setup; set it explicitly when the API is elsewhere (`http://api:8000` under
Docker Compose, or a Render internal hostname).

The browser never learns this value, and never calls the API directly.

---

## How authentication works

Worth understanding before changing anything in `src/lib/`:

```
Browser                    Next.js server                     FastAPI
   |                             |                               |
   |-- POST /api/auth/login ---->|                               |
   |                             |-- POST /api/v1/auth/login --->|
   |                             |<-- access + refresh token ----|
   |<-- 303 + httpOnly cookie ---|                               |
   |                             |                               |
   |-- POST /api/proxy/search -->|                               |
   |                             |  reads cookie, sets            |
   |                             |  Authorization: Bearer ...     |
   |                             |------------------------------>|
```

The token lives in an **httpOnly cookie**, so no JavaScript on the page can read it — which
is the point. Two consequences:

* A plain Next.js rewrite cannot serve as the proxy: the API authenticates with an
  `Authorization` header, and only server code can read the cookie. That is why
  `src/app/api/proxy/[...path]/route.ts` is a route handler rather than a rewrite.
* Server components use `apiFetch` from `@/lib/api` (reads the cookie itself). Client
  components use `clientFetch` from `@/lib/api-client` (goes through the proxy).

**Do not import `@/lib/api` from a client component.** It imports `next/headers` and the
build will fail. The split into `api.ts` / `api-client.ts` / `api-shared.ts` exists for
exactly this reason.

---

## Screens

| Route | Screen | Rendering |
| --- | --- | --- |
| `/` | Search: KPI row, filter sidebar, results, multi-select to compare | Server shell + client search panel |
| `/login` | Sign in | Server |
| `/pumps` | Every pump model with its duty point and terms, plus **AI pump search** | Server + client discovery sheet |
| `/vendors` | Vendor list with qualification and track record, plus **AI vendor search** | Server + client discovery sheet |
| `/vendors/[vendorId]` | Vendor profile: AI briefing, financials, governance, contacts, portfolio | Server |
| `/pumps/[pumpModelId]` | Pump profile: six spec groups, scorecards, flags, provenance, sources, similar pumps | Server + client provenance drawer |
| `/compare` | Scorecard comparison with a frozen snapshot | Client |
| `/imports` | Import queue; upload, URL and web-search forms | Server + client forms |
| `/review` | AI review queue with per-field evidence and inline correction | Client |
| `/quality` | Data quality dashboard | Server |
| `/audit` | Audit trail with diffs | Server |
| `/tenants` | Tenant management (platform admins) | Server |

Server components fetch with `cache: 'no-store'` by default — intelligence data should not
be served stale. Only the filter vocabularies are cached (300 s), because they change with
deployments rather than with data.

---

## Layout

| Path | Contains |
| --- | --- |
| `src/app/` | Routes (App Router). One directory per screen |
| `src/app/api/auth/` | Login and logout route handlers — set and clear the session cookie |
| `src/app/api/proxy/[...path]/` | Browser → API proxy; moves the token from cookie to header |
| `src/app/globals.css` | **The whole brand.** Every colour as a CSS variable, light and dark |
| `src/components/ui/` | shadcn/ui primitives. Owned source, edit freely |
| `src/components/data/` | Domain primitives: confidence and severity chips, scorecard, stat strip, states |
| `src/components/shell/` | The app chrome: icon rail, topbar, command palette, theme toggle, page header |
| `src/components/search/` | The search workspace: filter rail, results table, filter state |
| `src/components/discovery/` | AI search for vendors and pumps: the sheet, the two-provider progress panel, the candidate list, the per-kind config |
| `src/components/brand.tsx` | Logo mark and wordmark |
| `src/lib/utils.ts` | `cn()` — `clsx` + `tailwind-merge` |
| `src/lib/api.ts` | **Server-only** fetch. Imports `next/headers` |
| `src/lib/api-client.ts` | **Browser** fetch, through the proxy |
| `src/lib/api-shared.ts` | Cookie names, `ApiError`, query building — safe on both sides |
| `src/lib/format.ts` | Units, money, dates, byte sizes |
| `src/lib/labels.ts` | Domain vocabulary → the label an engineer expects (`BB3`, `API 610`) |
| `src/lib/session.ts` | Loads the signed-in user and nav badge counts for the shell |
| `src/types/api.ts` | Hand-written types for the API responses the UI reads |

### Conventions

**Always show units.** A bare number is a procurement hazard. Numeric table columns
carry their unit in the header; `fieldValue(field, value)` applies the unit for a field
list. Never render a raw number.

**Missing data must look missing.** Everything renders an em dash for `null`, never `0`
and never a blank cell. A pump with no recorded price must not read as free.

**Colour never carries meaning alone.** A confidence chip shows a coloured dot *and* its
label; a severity chip shows an icon *and* its name. Confidence is the field a buyer
leans on hardest, so it must survive a colour-blind reader and a monochrome print.

**A score is shown with what it does not know.** `ScoreCard` prints the missing-field
count beside the number. A high score resting on thin data is the single most misleading
thing this product could put in front of a buyer.

**Use the domain's vocabulary.** `labels.ts` turns `between_bearings_bb3` into `BB3` and
`api_610` into `API 610`. `fieldLabel()` also strips the unit suffix baked into a column
name, because the value beside it already carries the unit — `Rated capacity  305 m³/h`,
not `Rated capacity m3h  305 m³/h`.

**AI output is a candidate, never a record.** The discovery sheet shows what *would*
be written, with the verbatim quote and confidence behind every field, and writes nothing
until someone ticks it. Screening one real page, Gemma offered a marketplace unit price
(`US$680.00-695.00 / Set`) as `annual_revenue_usd`. Surfacing the quote next to the value
is what lets a reviewer catch that.

**The nav only offers what the user can open.** `shell/nav-items.ts` mirrors the API's
own permission guards. An entry that always 403s reads as a broken product rather than
as a permission the user does not hold.

---

## Design system

Built on **shadcn/ui** — Radix primitives, Tailwind, `class-variance-authority` — with
the component source owned in `src/components/ui/`. Those files are ours: edit them
rather than wrapping them.

The direction is a **dark data terminal**: near-black surfaces, a single electric-cyan
accent, monospace figures, 4px radii, hairline rules. The product's job is 400-column
specification tables read for long stretches, so density and legibility win over
decoration. Light and dark palettes are both defined; the choice is remembered per
browser by `next-themes` and switched from the topbar.

Every colour resolves to a variable in `src/app/globals.css` — a rebrand or a palette
change is an edit to that one file. Token names follow shadcn (`--background`,
`--primary`, `--muted`, …) so any component copied from shadcn works unmodified, plus
three domain scales: `--conf-*` (data confidence), `--sev-*` (flag severity) and
`--grade-*` (score grades).

**Colours are stored as bare HSL channels, not hex.** That is what lets Tailwind inject
an alpha: `bg-primary/20` compiles to `hsl(var(--primary) / 0.2)`. Written as hex the
opacity modifier is silently dropped and the colour resolves to transparent — the bug
that once made every confidence-chip border and the mobile drawer's scrim invisible. If
you add a colour token, add it as channels, and keep the `<alpha-value>` placeholder in
`tailwind.config.ts`.

There are exactly **two component classes** in the stylesheet — `.label-xs` for micro
labels and `.figure` for comparable numbers. Everything else is a real component,
because a class in a stylesheet cannot carry a variant, a disabled state or a ref.

Layout constants (`--rail-width`, `--topbar-height`, `--content-max`) are tokens too,
exposed as `w-rail`, `h-topbar`, `pl-rail` and `max-w-content`, so the shell's geometry
is stated once.

### Two things that will bite you

**Icon components cannot cross a server boundary.** `nav-items.ts` holds `LucideIcon`
references, so `Rail` is a client component that calls `visibleSections(user)` itself —
`user` is plain JSON and serialises, a React component does not. Passing an icon from a
server component throws *"Functions cannot be passed directly to Client Components"*.
`discovery/kinds.ts` has the same shape for the same reason: a page passes
`<AiSearch kind="pump" />` and the client component resolves the config, because the
config holds an icon.

**The command palette turns cmdk's filtering off.** `shouldFilter={false}`: the model
list is already the server's answer to the query, and re-filtering locally would drop
rows that matched on a field the palette does not display. The screen list is filtered
in the component instead.

---

## Commands

```bash
npm run dev
```

Development server with hot reload.

```bash
npm run typecheck
```

`tsc --noEmit`. `strict` and `noUncheckedIndexedAccess` are both on.

```bash
npm run build
```

Production build. Run this before pushing — it catches server/client boundary violations
that `typecheck` does not, such as importing `next/headers` into a client component.

The build writes to `.next-build`, not `.next` (see `next.config.mjs`). They used to
share a directory, so building while `npm run dev` was running left the dev server
serving a half-replaced cache and failing with `Cannot find module './NNN.js'`.

```bash
npm run start
```

Serve the production build.

```bash
npx prettier --check "src/**/*.{ts,tsx,css}"
```

Formatting. `npm run lint` opens an interactive ESLint setup — this project has no
ESLint config, so `typecheck` plus `build` are the gates that actually run.

---

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| Every panel shows "Could not load this view" | The API is not reachable. Check `API_INTERNAL_URL` and `curl http://localhost:8000/api/v1/health` |
| Redirected to `/login` immediately after signing in | The API rejected the token, or `SECRET_KEY` changed since it was issued. Sign in again |
| `You're importing a component that needs "next/headers"` | A client component imported `@/lib/api`. Use `@/lib/api-client` |
| Proxy calls return 401 but you are signed in | The cookie is missing. `clientFetch` sends `credentials: 'include'`; check it was not dropped |
| Uploads fail with a parsing error | The upload form posts `FormData` straight to `/api/proxy/...` so the multipart boundary survives. Do not route it through `clientFetch`, which sets a JSON content type |
| Pages take several seconds | Not the frontend. The database is probably in another region — see [docs/HOSTED_DATABASE.md](../docs/HOSTED_DATABASE.md) |
| Port 3000 in use | `npm run dev -- --port 3001` |
| A `bg-*/50` or `border-*/25` renders transparent | The colour token is stored as hex, or its Tailwind entry is missing `<alpha-value>`. Tokens must be bare HSL channels — see **Design system** |
| `Functions cannot be passed directly to Client Components` | A server component passed a component or callback across the boundary — most likely a Lucide icon. See **Two things that will bite you** |
| `Cannot find module './NNN.js'` from the dev server | An older build overwrote the dev cache. `rm -rf .next` and restart `npm run dev` |

---

## Further reading

* [backend/README.md](../backend/README.md) — start the API first
* [docs/LOCAL_SETUP.md](../docs/LOCAL_SETUP.md) — the whole stack end to end
* [docs/API.md](../docs/API.md) — endpoints these screens consume
