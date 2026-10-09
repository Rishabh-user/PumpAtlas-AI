/**
 * Server-side API client.
 *
 * Reads the session token from the httpOnly cookie itself, so server components never
 * pass credentials around. Client components must use `@/lib/api-client` instead - this
 * module imports `next/headers` and cannot be bundled for the browser.
 */

import { cookies } from "next/headers";

import {
  ACCESS_TOKEN_COOKIE,
  TENANT_COOKIE,
  buildQuery,
  describeError,
  type RequestOptions,
} from "@/lib/api-shared";

export { ACCESS_TOKEN_COOKIE, ApiError, TENANT_COOKIE } from "@/lib/api-shared";
export type { RequestOptions } from "@/lib/api-shared";

/**
 * Where this server reaches the API.
 *
 * Render's blueprint supplies it from the API service's `hostport` property, which is
 * `pumpatlas-api:10000` — a host and a port, with no scheme, because that is what
 * private networking addresses look like there. `fetch()` rejects that, so every
 * server-rendered page would fail on the first deploy with nothing in the UI to say
 * why. A blueprint cannot concatenate strings, so the scheme is added here.
 *
 * Private traffic inside Render is plain HTTP; an address that already carries a scheme
 * is left exactly as given, so an external or TLS endpoint still works.
 */
function internalBase(): string {
  const configured = (process.env.API_INTERNAL_URL ?? "http://localhost:8000").trim();
  const withScheme = /^https?:\/\//i.test(configured)
    ? configured
    : `http://${configured}`;
  return withScheme.replace(/\/+$/, "");
}

const INTERNAL_BASE = internalBase();
const API_PREFIX = "/api/v1";

export async function apiFetch<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const store = await cookies();
  const token = options.token ?? store.get(ACCESS_TOKEN_COOKIE)?.value;
  const tenantId = store.get(TENANT_COOKIE)?.value;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (tenantId) headers["X-Tenant-Id"] = tenantId;

  const url = `${INTERNAL_BASE}${API_PREFIX}${path}${buildQuery(options.query)}`;
  const response = await fetch(url, {
    method: options.method ?? "GET",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    cache: options.revalidate === false ? "no-store" : undefined,
    next:
      typeof options.revalidate === "number"
        ? { revalidate: options.revalidate }
        : undefined,
  });

  if (!response.ok) {
    // Read the body once, as text, then try to parse it. A fetch body can only be
    // consumed once, so falling back from .json() to .text() throws "Body is unusable:
    // Body has already been read" — which replaced every non-JSON error with a message
    // about the error handler instead of the actual failure.
    const raw = await response.text().catch(() => "");
    let detail: unknown = raw || null;
    if (raw) {
      try {
        detail = JSON.parse(raw);
      } catch {
        // Not JSON: a proxy error page, a gateway timeout, an unhandled traceback.
        // The text is what tells you which.
        detail = raw;
      }
    }
    throw describeError(response.status, detail, path);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** True when a session cookie is present. Not a validity check - the API decides that. */
export async function hasSession(): Promise<boolean> {
  const store = await cookies();
  return Boolean(store.get(ACCESS_TOKEN_COOKIE)?.value);
}
