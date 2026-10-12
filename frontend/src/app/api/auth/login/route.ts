import { NextResponse } from "next/server";

import { internalBase, redirectTo, usingFallbackApi } from "@/lib/server-url";
import {
  ACCESS_TOKEN_COOKIE,
  REFRESH_TOKEN_COOKIE,
  REFRESH_TOKEN_MAX_AGE,
  sessionCookieOptions,
} from "@/lib/api-shared";


/**
 * Exchanges credentials for a token and stores it in an httpOnly cookie.
 * Keeping the token out of JavaScript is the point of proxying login through here.
 */
export async function POST(request: Request) {
  const form = await request.formData();
  const email = String(form.get("email") ?? "");
  const password = String(form.get("password") ?? "");

  // An API that says no and an API that is not running are different failures, and
  // only the first one was handled. `fetch` *throws* on a refused connection rather
  // than returning a response, so with the backend down the rejection escaped this
  // handler and Next turned it into a bare 500 - which says nothing about what to do
  // about it. Signing in is where someone meets this first, so it says so here.
  let response: Response;
  try {
    response = await fetch(`${internalBase()}/api/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
  } catch (cause) {
    // Two different failures wear the same `TypeError: fetch failed`, and the advice
    // differs completely: locally the API is not running; deployed, API_INTERNAL_URL was
    // never set and this is talking to its own container.
    const advice = usingFallbackApi()
      ? "API_INTERNAL_URL is not set, so this is trying its own container. Set it to " +
        "the API service's internal address."
      : "Check the API is running (uvicorn app.main:app --reload --port 8000).";
    const message = encodeURIComponent(
      `Could not reach the API at ${internalBase()}. ${advice} (${String(cause)})`.slice(
        0,
        300,
      ),
    );
    return redirectTo(`/login?error=${message}`);
  }

  if (!response.ok) {
    const detail = await response
      .json()
      .catch(() => ({ detail: "Sign in failed" }));
    const message = encodeURIComponent(
      String(detail.detail ?? "Sign in failed"),
    );
    return redirectTo(`/login?error=${message}`);
  }

  const tokens = (await response.json()) as {
    access_token: string;
    refresh_token: string;
    expires_in: number;
  };
  const redirect = redirectTo("/");
  redirect.cookies.set(ACCESS_TOKEN_COOKIE, tokens.access_token, {
    ...sessionCookieOptions(),
    maxAge: tokens.expires_in,
  });
  // The access token lasts an hour; an AI sweep runs for longer. Keeping the refresh
  // token lets the proxy renew the session silently instead of dropping the person out
  // of a search that is still running.
  redirect.cookies.set(REFRESH_TOKEN_COOKIE, tokens.refresh_token, {
    ...sessionCookieOptions(),
    maxAge: REFRESH_TOKEN_MAX_AGE,
  });
  return redirect;
}
