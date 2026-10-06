import { redirect } from "next/navigation";

import { ProviderManager } from "@/components/ai-settings/provider-manager";
import { ErrorState } from "@/components/data/states";
import { AppShell } from "@/components/shell/app-shell";
import { PageHeader } from "@/components/shell/page-header";
import { Badge } from "@/components/ui/badge";
import { ApiError, apiFetch, hasSession } from "@/lib/api";
import { loadShellContext } from "@/lib/session";
import type { AiProviderList, AiSettingsOptions } from "@/types/api";

export const metadata = { title: "AI settings" };

/**
 * Which AI the platform uses, configured here rather than in a file.
 *
 * Several providers can be stored and exactly one is active per role, so switching
 * model is a click instead of a deploy. Keys are held encrypted and are write-only —
 * the screen shows a prefix, which is enough to recognise a key and useless otherwise.
 */
export default async function AiSettingsPage() {
  if (!(await hasSession())) redirect("/login");
  const { user, counts, authFailed } = await loadShellContext();
  if (authFailed) redirect("/login");

  // The API is the boundary that matters; this only avoids drawing a shell around a 403.
  if (user && !user.is_platform_admin) redirect("/");

  let list: AiProviderList | null = null;
  let options: AiSettingsOptions | null = null;
  let error: string | null = null;
  try {
    const [listResult, optionsResult] = await Promise.all([
      apiFetch<AiProviderList>("/ai-settings/providers", { revalidate: false }),
      apiFetch<AiSettingsOptions>("/ai-settings/options", {
        revalidate: false,
      }),
    ]);
    list = listResult;
    options = optionsResult;
  } catch (caught) {
    if (caught instanceof ApiError && caught.isAuthError) redirect("/login");
    error = caught instanceof Error ? caught.message : "Unknown error";
  }

  return (
    <AppShell user={user} counts={counts}>
      <PageHeader
        title="AI settings"
        lede="Which AI finds pages and which reads them. Add as many as you like; one of each is active, and that pair does the work for every AI search on the platform."
        meta={
          list ? (
            <Badge variant={list.ready ? "success" : "destructive"}>
              {list.ready ? "ready" : "not ready"}
            </Badge>
          ) : null
        }
      />

      <div className="space-y-4">
        {error ? <ErrorState message={error} /> : null}

        <p className="text-2xs leading-relaxed text-muted-foreground">
          Keys are encrypted before they are stored and are never sent back to
          this screen — you can replace one, but not read it. The encryption key
          is derived from{" "}
          <span className="font-mono text-foreground">SECRET_KEY</span>, which
          stays in the environment: something has to be able to decrypt the
          others, and if it lived in the database too then obtaining the
          database would be enough. Changing it means re-entering every key
          here.
        </p>

        <ProviderManager initial={list} options={options} />
      </div>
    </AppShell>
  );
}
