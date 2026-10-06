import { redirect } from "next/navigation";

import { ErrorState } from "@/components/data/states";
import { Stat, StatStrip } from "@/components/data/stat";
import { SearchWorkspace } from "@/components/search/search-workspace";
import type { FilterOptions } from "@/components/search/filter-state";
import { AppShell } from "@/components/shell/app-shell";
import { PageHeader } from "@/components/shell/page-header";
import { ApiError, apiFetch, hasSession } from "@/lib/api";
import { loadShellContext } from "@/lib/session";
import type { QualityDashboardData } from "@/types/api";

export const metadata = { title: "Pump intelligence" };

export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>;
}) {
  if (!(await hasSession())) redirect("/login");
  const { q } = await searchParams;
  const { user, counts, authFailed } = await loadShellContext();
  if (authFailed) redirect("/login");

  let options: FilterOptions | null = null;
  let summary: QualityDashboardData | null = null;
  let error: string | null = null;

  try {
    [options, summary] = await Promise.all([
      // Vocabularies change with a deployment, not with data.
      apiFetch<FilterOptions>("/search/filters/options", { revalidate: 300 }),
      apiFetch<QualityDashboardData>("/quality/dashboard", {
        revalidate: false,
      }),
    ]);
  } catch (caught) {
    if (caught instanceof ApiError && caught.status === 401) redirect("/login");
    if (!(caught instanceof ApiError && caught.status === 403)) {
      error = caught instanceof Error ? caught.message : "Unknown error";
    }
  }

  const openFlags = summary
    ? Object.values(summary.open_flags_by_severity).reduce(
        (total, n) => total + n,
        0,
      )
    : 0;
  const critical = summary?.open_flags_by_severity.critical ?? 0;
  const high = summary?.open_flags_by_severity.high ?? 0;

  return (
    <AppShell user={user} counts={counts}>
      <PageHeader
        title="Pump intelligence"
        lede="Every vendor, pump model and specification held for your organisation, with the source behind each value."
      />

      {error ? (
        <div className="mb-4">
          <ErrorState message={error} />
        </div>
      ) : null}

      {summary ? (
        <div className="mb-4">
          <StatStrip>
            <Stat
              label="Pump models"
              value={summary.total_pump_models.toLocaleString("en-GB")}
            />
            <Stat
              label="Vendors"
              value={summary.total_vendors.toLocaleString("en-GB")}
            />
            <Stat
              label="Avg completeness"
              value={
                summary.avg_completeness_pct === null
                  ? "—"
                  : summary.avg_completeness_pct.toFixed(0) + "%"
              }
              hint="Share of tracked fields populated"
            />
            <Stat
              label="Awaiting review"
              value={summary.pending_ai_reviews.toLocaleString("en-GB")}
              tone={summary.pending_ai_reviews > 0 ? "warn" : "default"}
              hint="Extractions needing a human decision"
            />
            <Stat
              label="Open data flags"
              value={openFlags.toLocaleString("en-GB")}
              tone={critical > 0 ? "risk" : high > 0 ? "warn" : "good"}
              hint={
                summary.ai_field_share_pct === null
                  ? "No provenance recorded yet"
                  : summary.ai_field_share_pct.toFixed(0) +
                    "% of field values are AI-derived"
              }
            />
          </StatStrip>
        </div>
      ) : null}

      <SearchWorkspace options={options} initialQuery={q ?? ""} />
    </AppShell>
  );
}
