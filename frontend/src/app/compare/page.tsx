import { redirect } from "next/navigation";

import { ComparisonBuilder } from "@/components/comparison-builder";
import { AppShell } from "@/components/shell/app-shell";
import { PageHeader } from "@/components/shell/page-header";
import { ErrorState } from "@/components/data/states";
import { ApiError, apiFetch, hasSession } from "@/lib/api";
import { loadShellContext } from "@/lib/session";
import type { Page } from "@/types/api";

interface RequirementProfile {
  id: string;
  name: string;
  project_name: string | null;
}

export const metadata = { title: "Comparison" };

export default async function ComparePage({
  searchParams,
}: {
  searchParams: Promise<{ models?: string }>;
}) {
  if (!(await hasSession())) redirect("/login");
  const { user, counts, authFailed } = await loadShellContext();
  if (authFailed) redirect("/login");

  const { models } = await searchParams;
  const modelIds = (models ?? "")
    .split(",")
    .map((id) => id.trim())
    .filter(Boolean);

  let profiles: RequirementProfile[] = [];
  let error: string | null = null;
  try {
    const response = await apiFetch<Page<RequirementProfile>>(
      "/requirement-profiles",
      {
        query: { limit: 100 },
        revalidate: 60,
      },
    );
    profiles = response.items;
  } catch (caught) {
    if (caught instanceof ApiError && caught.isAuthError) redirect("/login");
    error = caught instanceof Error ? caught.message : "Unknown error";
  }

  return (
    <AppShell user={user} counts={counts}>
      <PageHeader
        crumbs={[
          { label: "Pump intelligence", href: "/" },
          { label: "Comparison" },
        ]}
        title="Comparison"
        lede="Score candidates against a requirement profile. The result is frozen as a decision record, so the numbers stay reproducible after the underlying data moves on."
      />

      <div className="space-y-4">
        {error ? <ErrorState message={error} /> : null}
        <ComparisonBuilder initialModelIds={modelIds} profiles={profiles} />
      </div>
    </AppShell>
  );
}
