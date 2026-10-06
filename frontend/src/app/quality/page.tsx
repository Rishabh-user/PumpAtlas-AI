import { redirect } from "next/navigation";

import { QualityBody } from "@/components/quality-body";
import { AppShell } from "@/components/shell/app-shell";
import { PageHeader } from "@/components/shell/page-header";
import { ErrorState } from "@/components/data/states";
import { ApiError, apiFetch, hasSession } from "@/lib/api";
import { loadShellContext } from "@/lib/session";
import type { Page, QualityDashboardData, QualityFlag } from "@/types/api";

export const metadata = { title: "Data quality" };

export default async function QualityPage() {
  if (!(await hasSession())) redirect("/login");
  const { user, counts, authFailed } = await loadShellContext();
  if (authFailed) redirect("/login");

  let dashboard: QualityDashboardData | null = null;
  let flags: Page<QualityFlag> | null = null;
  let error: string | null = null;

  try {
    [dashboard, flags] = await Promise.all([
      apiFetch<QualityDashboardData>("/quality/dashboard", {
        revalidate: false,
      }),
      apiFetch<Page<QualityFlag>>("/quality/flags", {
        query: { limit: 50, is_resolved: false },
        revalidate: false,
      }),
    ]);
  } catch (caught) {
    if (caught instanceof ApiError && caught.isAuthError) redirect("/login");
    error = caught instanceof Error ? caught.message : "Unknown error";
  }

  return (
    <AppShell user={user} counts={counts}>
      <PageHeader
        title="Data quality"
        lede="Completeness, confidence and contradictions across the intelligence base. A high score sitting on incomplete data is the failure mode this screen exists to catch."
      />

      <div className="space-y-4">
        {error ? <ErrorState message={error} /> : null}
        <QualityBody dashboard={dashboard} flags={flags} />
      </div>
    </AppShell>
  );
}
