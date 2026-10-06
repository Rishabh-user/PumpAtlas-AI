import { ApiError, apiFetch } from "@/lib/api";
import type { CurrentUser } from "@/types/api";

/**
 * The signed-in user plus the nav badge counts, fetched once per request for the shell.
 *
 * Neither is allowed to break a page: if the counts endpoint is unavailable the nav
 * simply renders without badges, and a screen that only needed its own data still works.
 */
export async function loadShellContext(): Promise<{
  user: CurrentUser | null;
  counts: Record<string, number>;
  authFailed: boolean;
}> {
  let user: CurrentUser | null = null;
  let counts: Record<string, number> = {};
  let authFailed = false;

  // Together, not one after the other. These are independent questions, and the shell
  // renders on every page in the app: run sequentially against a hosted database they
  // cost about five seconds before a page starts fetching its own data, which is most
  // of why every screen felt slow. The badge request does not depend on the user — an
  // unauthenticated one simply fails and leaves the badges off, which is what the
  // catch below already does.
  const [userResult, countsResult] = await Promise.allSettled([
    apiFetch<CurrentUser>("/auth/me", { revalidate: false }),
    apiFetch<Record<string, number>>("/quality/suggestions/pending-count", {
      revalidate: false,
    }),
  ]);

  if (userResult.status === "fulfilled") {
    user = userResult.value;
  } else if (
    userResult.reason instanceof ApiError &&
    userResult.reason.status === 401
  ) {
    authFailed = true;
  }

  // Badges are optional: a client user is not permitted to read these, and they are
  // never worth failing a page over.
  if (countsResult.status === "fulfilled" && user) {
    counts = countsResult.value;
  }

  return { user, counts, authFailed };
}
