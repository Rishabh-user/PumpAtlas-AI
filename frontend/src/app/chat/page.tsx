import { redirect } from "next/navigation";

import { ChatWorkspace } from "@/components/chat/chat-workspace";
import { ErrorState } from "@/components/data/states";
import { AppShell } from "@/components/shell/app-shell";
import { ApiError, apiFetch, hasSession } from "@/lib/api";
import { loadShellContext } from "@/lib/session";
import type { ChatContext } from "@/types/api";

export const metadata = { title: "Ask" };

/**
 * Ask a question and get an answer from the record and the web.
 *
 * The conversation lives in the browser rather than the database. It is a way of
 * interrogating the record, not part of it: nothing said here is evidence, and the only
 * route from an answer to a stored row runs through the ordinary capture pipeline,
 * where a field is written with a verbatim quote from a page PumpAtlas fetched.
 *
 * Rendered full-bleed because the workspace owns its own height: a history rail, a
 * thread that scrolls on its own, and a composer pinned to the bottom.
 */
export default async function ChatPage() {
  if (!(await hasSession())) redirect("/login");
  const { user, counts, authFailed } = await loadShellContext();
  if (authFailed) redirect("/login");

  let context: ChatContext | null = null;
  let error: string | null = null;
  try {
    context = await apiFetch<ChatContext>("/chat/context", {
      revalidate: false,
    });
  } catch (caught) {
    if (caught instanceof ApiError && caught.isAuthError) redirect("/login");
    error = caught instanceof Error ? caught.message : "Unknown error";
  }

  return (
    <AppShell user={user} counts={counts} fullBleed>
      {error ? (
        <div className="px-4 py-4">
          <ErrorState message={error} />
        </div>
      ) : null}
      <ChatWorkspace context={context} />
    </AppShell>
  );
}
