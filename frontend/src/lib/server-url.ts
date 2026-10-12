import { NextResponse } from "next/server";

/**
 * Where this server reaches the API, and how it sends a browser somewhere else.
 *
 * Both answers were duplicated across three route handlers and `lib/api.ts`, and the
 * copies disagreed — which is how a deployment reached production with one of them
 * normalising its address and the others not. One definition each, here.
 */

/**
 * The API's base URL, with a scheme guaranteed.
 *
 * Render's blueprint supplies `API_INTERNAL_URL` from the API service's `hostport`
 * property, which is `pumpatlas-api:10000` — a host and a port, with no scheme, because
 * that is what private networking addresses look like there. `fetch()` rejects that with
 * a bare `TypeError: fetch failed`, which says nothing about the cause.
 *
 * The fallback is for local development only. On a deployed instance it is a sign that
 * `API_INTERNAL_URL` was never set: nothing listens on localhost:8000 inside the
 * frontend's own container, so every call fails with the same unhelpful TypeError.
 */
export function internalBase(): string {
  const configured = (process.env.API_INTERNAL_URL ?? "http://localhost:8000").trim();
  const withScheme = /^https?:\/\//i.test(configured) ? configured : `http://${configured}`;
  return withScheme.replace(/\/+$/, "");
}

/** True when the API address is still the development default. */
export function usingFallbackApi(): boolean {
  return !process.env.API_INTERNAL_URL;
}

/**
 * Redirect to a path on this same site.
 *
 * Deliberately a **relative** Location. Building an absolute URL from `request.url` sends
 * the browser to the address the container sees itself as — on Render that is
 * `localhost:10000`, so a failed sign-in redirected to `https://localhost:10000/login`
 * and the browser had nowhere to go.
 *
 * The usual fix is to read `x-forwarded-host`, but that is a header a client can set, and
 * trusting it to build a redirect is how an open redirect gets written. A relative
 * Location needs no host at all: the browser resolves it against the URL it actually
 * requested, which is the public one by definition.
 */
export function redirectTo(path: string, status: 303 | 307 = 303): NextResponse {
  if (!path.startsWith("/") || path.startsWith("//")) {
    throw new Error(`redirectTo expects a path on this site, got ${path}`);
  }
  return new NextResponse(null, { status, headers: { Location: path } });
}
