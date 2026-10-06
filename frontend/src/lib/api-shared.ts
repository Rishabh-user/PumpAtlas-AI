/**
 * Pieces shared by the server and browser API helpers.
 *
 * This module must stay free of `next/headers` and of anything else that only exists on
 * one side, because both a server component and a client component import from it.
 */

export const ACCESS_TOKEN_COOKIE = "pumpatlas_access";
export const REFRESH_TOKEN_COOKIE = "pumpatlas_refresh";
export const TENANT_COOKIE = "pumpatlas_tenant";

/**
 * Mirrors `REFRESH_TOKEN_EXPIRE_DAYS` in the backend settings.
 *
 * The API does not report the refresh token's lifetime, so this is the one place the
 * number is repeated. Erring short is harmless — the cookie would be dropped while the
 * token is still valid and the person signs in again; erring long only means a dead
 * token is sent once and refused.
 */
export const REFRESH_TOKEN_MAX_AGE = 14 * 24 * 60 * 60;

/** Cookie flags shared by every session cookie, so none of them drifts. */
export function sessionCookieOptions() {
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: process.env.NODE_ENV === "production",
    path: "/",
  };
}

/** One field-level complaint from the API's 422 handler. */
export interface FieldError {
  field: string;
  message: string;
  type: string;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly detail?: unknown,
    /** Populated for a 422, so a form can point at the offending input. */
    readonly fieldErrors: FieldError[] = [],
  ) {
    super(message);
    this.name = "ApiError";
  }

  get isAuthError(): boolean {
    return this.status === 401 || this.status === 403;
  }

  get isValidationError(): boolean {
    return this.status === 422;
  }
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  query?: Record<
    string,
    string | number | boolean | string[] | undefined | null
  >;
  /** Intelligence data is not cached by default; pass a number of seconds to opt in. */
  revalidate?: number | false;
  token?: string;
}

export function buildQuery(query: RequestOptions["query"]): string {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) {
      for (const entry of value) params.append(key, String(entry));
    } else {
      params.append(key, String(value));
    }
  }
  const encoded = params.toString();
  return encoded ? `?${encoded}` : "";
}

/** A humane label for a field name the API rejected. */
function fieldLabel(field: string): string {
  const leaf = field.split(".").pop() ?? field;
  const words = leaf.replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function readFieldErrors(detail: unknown): FieldError[] {
  if (typeof detail !== "object" || detail === null || !("errors" in detail))
    return [];
  const raw = (detail as { errors: unknown }).errors;
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((entry) => {
    if (typeof entry !== "object" || entry === null) return [];
    const { field, message, type } = entry as Partial<FieldError>;
    if (typeof message !== "string") return [];
    return [{ field: String(field ?? ""), message, type: String(type ?? "") }];
  });
}

export function describeError(
  status: number,
  detail: unknown,
  path: string,
): ApiError {
  const fieldErrors = readFieldErrors(detail);

  // A 422 carries the useful part in `errors`, not in `detail`. Surfacing only
  // `detail` turns every validation failure into "Request validation failed", which
  // tells the person nothing about which input to change or what the limit is.
  if (fieldErrors.length) {
    const message = fieldErrors
      .map((error) =>
        error.field
          ? `${fieldLabel(error.field)}: ${error.message}`
          : error.message,
      )
      .join("; ");
    return new ApiError(status, message, detail, fieldErrors);
  }

  const message =
    typeof detail === "object" && detail !== null && "detail" in detail
      ? String((detail as { detail: unknown }).detail)
      : `Request to ${path} failed with ${status}`;
  return new ApiError(status, message, detail);
}
