/**
 * Browser-side API client.
 *
 * Every request goes through the /api/proxy route handler, which swaps the httpOnly
 * session cookie for an Authorization header. The token is therefore never readable
 * from JavaScript.
 */

import {
  buildQuery,
  describeError,
  type RequestOptions,
} from "@/lib/api-shared";

export { ApiError } from "@/lib/api-shared";
export type { RequestOptions } from "@/lib/api-shared";

export async function clientFetch<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const response = await fetch(
    `/api/proxy${path}${buildQuery(options.query)}`,
    {
      method: options.method ?? "GET",
      headers: { "Content-Type": "application/json" },
      body:
        options.body === undefined ? undefined : JSON.stringify(options.body),
      credentials: "include",
    },
  );

  if (!response.ok) {
    // One read, then parse — see the note in lib/api.ts. Keeping the raw text when it
    // is not JSON matters: a 500 from an unhandled exception is plain text, and
    // discarding it left nothing to act on.
    const raw = await response.text().catch(() => "");
    let detail: unknown = raw || null;
    if (raw) {
      try {
        detail = JSON.parse(raw);
      } catch {
        detail = raw;
      }
    }
    throw describeError(response.status, detail, path);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
