import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { PumpProfileBody } from "@/components/pump-profile-body";
import { ConfidenceChip, SeverityChip } from "@/components/data/confidence";
import { ScoreCard } from "@/components/data/scorecard";
import { ErrorState } from "@/components/data/states";
import { AppShell } from "@/components/shell/app-shell";
import { PageHeader } from "@/components/shell/page-header";
import { PumpEnrichPanel } from "@/components/pumps/enrich-panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError, apiFetch, hasSession } from "@/lib/api";
import { text } from "@/lib/format";
import {
  fieldLabel,
  humanise,
  pumpTypeCode,
  standardLabel,
} from "@/lib/labels";
import { loadShellContext } from "@/lib/session";
import type { ConfidenceLevel, PumpProfile } from "@/types/api";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ pumpModelId: string }>;
}) {
  const { pumpModelId } = await params;
  try {
    const profile = await apiFetch<PumpProfile>(`/pump-models/${pumpModelId}`, {
      revalidate: false,
    });
    return { title: text(profile.pump_model.model_code) };
  } catch {
    return { title: "Pump model" };
  }
}

export default async function PumpProfilePage({
  params,
}: {
  params: Promise<{ pumpModelId: string }>;
}) {
  if (!(await hasSession())) redirect("/login");
  const { user, counts, authFailed } = await loadShellContext();
  if (authFailed) redirect("/login");

  const { pumpModelId } = await params;

  let profile: PumpProfile;
  try {
    profile = await apiFetch<PumpProfile>(`/pump-models/${pumpModelId}`, {
      revalidate: false,
    });
  } catch (caught) {
    if (caught instanceof ApiError) {
      if (caught.isAuthError) redirect("/login");
      if (caught.status === 404) notFound();
      return (
        <AppShell user={user} counts={counts}>
          <ErrorState message={caught.message} />
        </AppShell>
      );
    }
    throw caught;
  }

  const model = profile.pump_model;
  const pump = profile.pump;
  const vendor = profile.vendor;
  const overall = profile.scorecards.find((card) => card.kind === "overall");

  return (
    <AppShell user={user} counts={counts}>
      <PageHeader
        crumbs={[
          { label: "Pump intelligence", href: "/" },
          {
            label: text(vendor.name),
            href: `/vendors/${String(vendor.id ?? "")}`,
          },
          { label: text(model.model_code) },
        ]}
        title={text(model.model_code)}
        lede={[
          text(pump.name),
          pumpTypeCode(String(pump.pump_type ?? "")),
          standardLabel(String(pump.applicable_standard ?? "")),
        ]
          .filter((part) => part && part !== "—")
          .join(" · ")}
        meta={
          <>
            <ConfidenceChip level={model.confidence_level as ConfidenceLevel} />
            <Badge
              variant={
                model.verification_status === "verified" ? "success" : "outline"
              }
            >
              {humanise(String(model.verification_status ?? "unverified"))}
            </Badge>
            {model.is_shared_master ? (
              <Badge variant="secondary">Shared master</Badge>
            ) : null}
            {profile.provenance_summary.ai_share_pct !== null ? (
              <Badge variant="warning">
                {profile.provenance_summary.ai_share_pct.toFixed(0)}% AI-derived
              </Badge>
            ) : null}
          </>
        }
        actions={
          <Button variant="outline" asChild>
            <Link href={`/compare?models=${pumpModelId}`}>
              Add to comparison
            </Link>
          </Button>
        }
      />

      <div className="space-y-4">
        <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-5">
          {profile.scorecards
            .filter((card) => card.kind !== "overall")
            .map((card) => (
              <ScoreCard
                key={card.kind}
                label={humanise(card.kind)}
                score={card.score}
                grade={card.grade}
                missing={card.fields_missing}
              />
            ))}
          {overall ? (
            <ScoreCard
              label="Overall"
              score={overall.score}
              grade={overall.grade}
              missing={overall.fields_missing}
            />
          ) : null}
        </div>

        {/* The specification panels below are empty on most records because the page a
          * model was discovered from named the product and said nothing about its duty
          * point or its commercial terms. This is how a person fills that in. */}
        <PumpEnrichPanel
          pumpModelId={pumpModelId}
          vendorName={text(vendor?.name)}
          modelCode={text(model.model_code)}
        />

        {overall?.disqualified ? (
          <div className="rounded-lg border border-destructive/30 bg-destructive/[0.07] px-3 py-2.5">
            <p className="text-xs font-medium text-destructive">
              Disqualified against the default requirement profile
            </p>
            <p className="mt-0.5 text-2xs text-muted-foreground">
              {overall.disqualification_reason}
            </p>
          </div>
        ) : null}

        {profile.open_flags.length ? (
          <Card className="overflow-hidden">
            <CardHeader>
              <CardTitle>
                Data quality flags ({profile.open_flags.length})
              </CardTitle>
            </CardHeader>
            <ul className="divide-y divide-border">
              {profile.open_flags.map((flag) => (
                <li
                  key={flag.id}
                  className="flex items-start gap-2.5 px-3 py-2.5"
                >
                  <SeverityChip severity={flag.severity} />
                  <div className="min-w-0">
                    <p className="text-xs text-foreground">{flag.message}</p>
                    <p className="mt-0.5 text-[0.625rem] text-muted-foreground">
                      {flag.field_name
                        ? `${fieldLabel(flag.field_name)} \u00b7 `
                        : ""}
                      {humanise(flag.flag_type)}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          </Card>
        ) : null}

        <PumpProfileBody profile={profile} pumpModelId={pumpModelId} />
      </div>
    </AppShell>
  );
}
