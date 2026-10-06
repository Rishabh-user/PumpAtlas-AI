import { NextResponse } from "next/server";

import {
  ACCESS_TOKEN_COOKIE,
  REFRESH_TOKEN_COOKIE,
  TENANT_COOKIE,
} from "@/lib/api-shared";

export async function POST(request: Request) {
  const redirect = NextResponse.redirect(new URL("/login", request.url), 303);
  redirect.cookies.delete(ACCESS_TOKEN_COOKIE);
  // Leaving this behind would let the proxy renew a session the person just ended.
  redirect.cookies.delete(REFRESH_TOKEN_COOKIE);
  redirect.cookies.delete(TENANT_COOKIE);
  return redirect;
}
