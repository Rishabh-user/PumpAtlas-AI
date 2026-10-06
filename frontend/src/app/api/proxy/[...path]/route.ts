import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import {
  ACCESS_TOKEN_COOKIE,
  REFRESH_TOKEN_COOKIE,
  REFRESH_TOKEN_MAX_AGE,
  TENANT_COOKIE,
  sessionCookieOptions,
} from "@/lib/api-shared";

const INTERNAL_BASE = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

interface TokenPair {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

/**
 * Trade a refresh token for a new pair, or null if the API refuses it.
 *
 * A refused refresh is a real sign-out — the token is revoked, expired, or the user is
 * no longer active — so the caller passes the 401 on rather than retrying.
 */
async function renew(refreshToken: string): Promise<TokenPair | null> {
  const response = await fetch(`${INTERNAL_BASE}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
    cache: "no-store",
  });
  if (!response.ok) return null;
  return (await response.json()) as TokenPair;
}

/**
 * Browser -> API proxy.
 *
 * A plain Next.js rewrite cannot do this job: the session token lives in an httpOnly
 * cookie, and the API authenticates with an `Authorization` header. This handler moves
 * the token from cookie to header server-side, so the browser never holds it.
 *
 * It also renews the session. An access token lasts an hour and an AI sweep runs for
 * longer than that, so the poll used to start failing partway through a search that was
 * still working perfectly well — the page said "not signed in" while the run carried on
 * server-side. Refreshing here keeps a long job watchable, and keeps the renewed token
 * out of JavaScript exactly as the original one is.
 */
async function forward(request: Request, path: string[]): Promise<Response> {
  const store = await cookies();
  let token = store.get(ACCESS_TOKEN_COOKIE)?.value;
  const refreshToken = store.get(REFRESH_TOKEN_COOKIE)?.value;
  const tenantId = store.get(TENANT_COOKIE)?.value;

  if (!token && !refreshToken) {
    return NextResponse.json({ detail: "Not signed in" }, { status: 401 });
  }

  const incoming = new URL(request.url);
  const target = `${INTERNAL_BASE}/api/v1/${path.join("/")}${incoming.search}`;
  const method = request.method.toUpperCase();
  // Buffered once: a retry after renewal has to send the same body again.
  const body =
    method === "GET" || method === "HEAD"
      ? undefined
      : await request.arrayBuffer();
  const contentType = request.headers.get("content-type");

  const send = (bearer: string) => {
    const headers = new Headers();
    headers.set("Authorization", `Bearer ${bearer}`);
    if (tenantId) headers.set("X-Tenant-Id", tenantId);
    // Multipart uploads must keep their generated boundary, so copy the header verbatim.
    if (contentType) headers.set("Content-Type", contentType);
    return fetch(target, {
      method,
      headers,
      body,
      // Streaming duplex is unnecessary here and unsupported by some runtimes.
      cache: "no-store",
    });
  };

  // The access cookie expires with the token, so a missing one with a refresh token
  // present is the ordinary "been away an hour" case, not a sign-out.
  let renewed: TokenPair | null = null;
  if (!token && refreshToken) {
    renewed = await renew(refreshToken);
    if (!renewed) {
      return NextResponse.json({ detail: "Session expired" }, { status: 401 });
    }
    token = renewed.access_token;
  }

  let response = await send(token as string);

  // Renew and retry once. Only once: if the fresh token is also rejected the answer is
  // a genuine 401 and looping would just hammer the API.
  if (response.status === 401 && refreshToken && !renewed) {
    renewed = await renew(refreshToken);
    if (renewed) response = await send(renewed.access_token);
  }

  const payload = await response.arrayBuffer();
  const out = new NextResponse(payload, {
    status: response.status,
    headers: {
      "Content-Type":
        response.headers.get("content-type") ?? "application/json",
    },
  });
  if (renewed) {
    out.cookies.set(ACCESS_TOKEN_COOKIE, renewed.access_token, {
      ...sessionCookieOptions(),
      maxAge: renewed.expires_in,
    });
    out.cookies.set(REFRESH_TOKEN_COOKIE, renewed.refresh_token, {
      ...sessionCookieOptions(),
      maxAge: REFRESH_TOKEN_MAX_AGE,
    });
  }
  return out;
}

type Context = { params: Promise<{ path: string[] }> };

export async function GET(request: Request, context: Context) {
  return forward(request, (await context.params).path);
}

export async function POST(request: Request, context: Context) {
  return forward(request, (await context.params).path);
}

export async function PATCH(request: Request, context: Context) {
  return forward(request, (await context.params).path);
}

export async function PUT(request: Request, context: Context) {
  return forward(request, (await context.params).path);
}

export async function DELETE(request: Request, context: Context) {
  return forward(request, (await context.params).path);
}
