"use client";

import { useState } from "react";
import Link from "next/link";

import { clientFetch } from "@/lib/api-client";
import { isCurrencyCompanion, specValue } from "@/components/format-spec";
import { fieldLabel, humanise } from "@/lib/labels";
import { scoreText } from "@/components/data/scorecard";
import { EmptyState, ErrorState } from "@/components/data/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Comparison } from "@/types/api";

interface RequirementProfile {
  id: string;
  name: string;
  project_name: string | null;
}

export function ComparisonBuilder({
  initialModelIds,
  profiles,
}: {
  initialModelIds: string[];
  profiles: RequirementProfile[];
}) {
  const [modelIds] = useState(initialModelIds);
  const [name, setName] = useState("");
  const [profileId, setProfileId] = useState("");
  const [narrative, setNarrative] = useState(false);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function build() {
    setBusy(true);
    setError(null);
    try {
      setComparison(
        await clientFetch<Comparison>("/comparisons", {
          method: "POST",
          body: {
            name: name.trim() || `Comparison of ${modelIds.length} candidates`,
            requirement_profile_id: profileId || null,
            pump_model_ids: modelIds,
            generate_narrative: narrative,
          },
        }),
      );
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Could not build the comparison",
      );
    } finally {
      setBusy(false);
    }
  }

  if (modelIds.length === 0) {
    return (
      <Card className="overflow-hidden">
        <CardHeader>
          <CardTitle>No candidates selected</CardTitle>
        </CardHeader>
        <EmptyState
          title="Pick pump models to compare"
          hint="Select rows on the search screen, then choose Compare selected."
        />
      </Card>
    );
  }

  return (
    <div className="space-y-5">
      <Card className="overflow-hidden">
        <CardHeader>
          <CardTitle>{modelIds.length} candidates</CardTitle>
        </CardHeader>
        <div className="grid gap-2 p-3 sm:grid-cols-[minmax(0,1fr)_auto_auto_auto]">
          <Input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Comparison name, e.g. P-1201 A/B crude export pumps"
          />
          <select
            value={profileId}
            onChange={(event) => setProfileId(event.target.value)}
            className="h-8 rounded-md border border-input bg-background px-2 text-xs focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
            aria-label="Requirement profile"
          >
            <option value="">Platform default weighting</option>
            {profiles.map((profile) => (
              <option key={profile.id} value={profile.id}>
                {profile.name}
                {profile.project_name ? ` (${profile.project_name})` : ""}
              </option>
            ))}
          </select>
          <label className="flex cursor-pointer items-center gap-2 whitespace-nowrap text-xs text-foreground/85">
            <Checkbox
              checked={narrative}
              onCheckedChange={(checked) => setNarrative(checked === true)}
            />
            AI narrative
          </label>
          <Button onClick={() => void build()} disabled={busy}>
            {busy ? "Scoring…" : "Score and compare"}
          </Button>
        </div>
        {error ? (
          <div className="px-3 pb-3">
            <ErrorState message={error} />
          </div>
        ) : null}
      </Card>

      {comparison ? <ComparisonGrid comparison={comparison} /> : null}
    </div>
  );
}

function ComparisonGrid({ comparison }: { comparison: Comparison }) {
  const ranked = [...comparison.items].sort(
    (a, b) => (a.rank ?? 999) - (b.rank ?? 999),
  );
  const fields = comparison.fields_shown;

  return (
    <div className="space-y-5">
      <Card className="overflow-hidden">
        <CardHeader>
          <CardTitle>Scorecards</CardTitle>
        </CardHeader>
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Rank</TableHead>
                <TableHead>Candidate</TableHead>
                <TableHead className="text-right">Technical</TableHead>
                <TableHead className="text-right">Commercial</TableHead>
                <TableHead className="text-right">Delivery</TableHead>
                <TableHead className="text-right">Data confidence</TableHead>
                <TableHead className="text-right">Overall</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {ranked.map((item) => (
                <TableRow key={item.id}>
                  <TableCell className="tabular-nums text-muted-foreground">
                    {item.rank ?? "\u2014"}
                  </TableCell>
                  <TableCell>
                    {item.pump_model_id ? (
                      <Link
                        href={`/pumps/${item.pump_model_id}`}
                        className="font-medium text-foreground hover:text-primary"
                      >
                        {item.label ?? item.pump_model_id}
                      </Link>
                    ) : (
                      <span className="text-foreground">{item.label}</span>
                    )}
                  </TableCell>
                  <ScoreCell value={item.technical_score} />
                  <ScoreCell value={item.commercial_score} />
                  <ScoreCell value={item.delivery_risk_score} />
                  <ScoreCell value={item.data_confidence_score} />
                  <TableCell
                    className={`text-right font-semibold tabular-nums ${scoreText(
                      item.overall_score,
                    )}`}
                  >
                    {item.overall_score === null
                      ? "\u2014"
                      : item.overall_score.toFixed(1)}
                  </TableCell>
                  <TableCell>
                    {item.disqualified ? (
                      <Badge variant="destructive">Disqualified</Badge>
                    ) : (
                      <Badge variant="success">Compliant</Badge>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>

        {ranked.some((item) => item.disqualified) ? (
          <div className="border-t border-border px-4 py-3">
            <p className="label-xs">Disqualification reasons</p>
            <ul className="mt-1 space-y-1">
              {ranked
                .filter((item) => item.disqualified)
                .map((item) => (
                  <li key={item.id} className="text-xs text-destructive">
                    <span className="text-foreground/85">{item.label}:</span>{" "}
                    {item.disqualification_reason}
                  </li>
                ))}
            </ul>
          </div>
        ) : null}
      </Card>

      {comparison.ai_narrative ? (
        <Card className="overflow-hidden">
          <CardHeader>
            <CardTitle>AI decision narrative</CardTitle>
          </CardHeader>
          <div className="space-y-2 p-4">
            <p className="text-sm leading-relaxed text-foreground/85">
              {comparison.ai_narrative}
            </p>
            <p className="text-xs text-muted-foreground/70">
              Written from the computed scores above. The scores themselves are
              deterministic and were not produced by the model.
            </p>
          </div>
        </Card>
      ) : null}

      <Card className="overflow-hidden">
        <CardHeader>
          <CardTitle>Field-by-field</CardTitle>
        </CardHeader>
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="sticky left-0 bg-card">Field</TableHead>
                {ranked.map((item) => (
                  <TableHead key={item.id} className="min-w-[10rem]">
                    {item.label}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {fields
                .filter(
                  (field) =>
                    // The currency is folded into the amount cell beside it.
                    !ranked.some((item) =>
                      isCurrencyCompanion(field, item.values),
                    ),
                )
                .map((field) => {
                  const values = ranked.map((item) => item.values[field]);
                  const distinct = new Set(
                    values.map((value) => JSON.stringify(value ?? null)),
                  );
                  const differs = distinct.size > 1;
                  return (
                    <TableRow key={field}>
                      <TableCell
                        className={`sticky left-0 bg-card text-xs ${
                          differs ? "text-primary" : "text-muted-foreground"
                        }`}
                      >
                        {fieldLabel(field)}
                      </TableCell>
                      {ranked.map((item, index) => (
                        <TableCell
                          key={item.id}
                          className="text-xs tabular-nums"
                        >
                          {specValue(field, values[index], item.values)}
                        </TableCell>
                      ))}
                    </TableRow>
                  );
                })}
            </TableBody>
          </Table>
        </div>
        <p className="border-t border-border px-4 py-2 text-xs text-muted-foreground/70">
          Amber field names differ between candidates. A blank cell means the
          value is not recorded, which is scored as missing data rather than as
          a good result.
        </p>
      </Card>
    </div>
  );
}

function ScoreCell({ value }: { value: number | null }) {
  return (
    <TableCell className={`text-right tabular-nums ${scoreText(value)}`}>
      {value === null ? "\u2014" : value.toFixed(1)}
    </TableCell>
  );
}
