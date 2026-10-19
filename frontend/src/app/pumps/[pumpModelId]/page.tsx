import { notFound, redirect } from "next/navigation";

import { PumpProfileBody } from "@/components/pump-profile-body";
import { ConfidenceChip, SeverityChip } from "@/components/data/confidence";
import { VerifyButton } from "@/components/data/verify-button";
import { ScoreCard } from "@/components/data/scorecard";
import { ExplainableScore } from "@/components/data/scorecard-explainer";
import { ErrorState } from "@/components/data/states";
import { AppShell } from "@/components/shell/app-shell";
import { PageHeader } from "@/components/shell/page-header";
import { PumpEnrichPanel } from "@/components/pumps/enrich-panel";
import { Badge } from "@/components/ui/badge";
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
          /* AI findings land on the record unverified. This is where a person says
           * they have checked them, which is what stops the next run rewriting them. */
          <VerifyButton
            endpoint={`/pump-models/${pumpModelId}/verify`}
            verified={model.verification_status === "verified"}
          />
        }
      />

      <div className="space-y-4">
        <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-5">
          {/* Each card opens its own arithmetic. A number somebody has to defend in a
            * tender review needs to show what it was computed from — which criteria
            * were answerable, what each one read, and what recording the rest would
            * change. */}
          {profile.scorecards
            .filter((card) => card.kind !== "overall")
            .map((card) => (
              <ExplainableScore key={card.kind} card={card}>
                <ScoreCard
                  label={humanise(card.kind)}
                  score={card.score}
                  grade={card.grade}
                  missing={card.fields_missing}
                />
              </ExplainableScore>
            ))}
          {overall ? (
            <ExplainableScore card={overall}>
              <ScoreCard
                label="Overall"
                score={overall.score}
                grade={overall.grade}
                missing={overall.fields_missing}
              />
            </ExplainableScore>
          ) : null}
        </div>

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

        {/* Below the record, not above it. The specification panels are empty on most
          * models because the page one was discovered from named the product and said
          * nothing about its duty point — but the first thing a page shows should be
          * what is known, not an offer to go and look. */}
        <PumpEnrichPanel
          pumpModelId={pumpModelId}
          vendorName={text(vendor?.name)}
          modelCode={text(model.model_code)}
          kind={
            (profile.model_kind ?? "product") as Parameters<
              typeof PumpEnrichPanel
            >[0]["kind"]
          }
        />
      </div>
    </AppShell>
  );
}
