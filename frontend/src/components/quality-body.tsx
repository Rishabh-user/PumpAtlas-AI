import { SeverityChip } from "@/components/data/confidence";
import { Stat, StatStrip } from "@/components/data/stat";
import { EmptyState } from "@/components/data/states";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ratioAsPct } from "@/lib/format";
import { fieldLabel, humanise } from "@/lib/labels";
import type {
  FlagSeverity,
  Page,
  QualityDashboardData,
  QualityFlag,
} from "@/types/api";

const SEVERITY_ORDER: FlagSeverity[] = [
  "critical",
  "high",
  "medium",
  "low",
  "info",
];

function Distribution({ data }: { data: Record<string, number> }) {
  const entries = Object.entries(data).sort(([, a], [, b]) => b - a);
  const total = entries.reduce((sum, [, count]) => sum + count, 0);

  if (!entries.length) return <EmptyState title="No data yet" />;

  return (
    <ul className="space-y-2 p-3">
      {entries.map(([key, count]) => (
        <li key={key}>
          <div className="flex items-baseline justify-between gap-3 text-xs">
            <span className="truncate text-foreground/85">{humanise(key)}</span>
            <span className="figure shrink-0 text-muted-foreground">
              {count}
              <span className="text-muted-foreground/60">
                {" "}
                {Math.round((count / total) * 100)}%
              </span>
            </span>
          </div>
          <Progress value={(count / total) * 100} className="mt-1" />
        </li>
      ))}
    </ul>
  );
}

function FlagTable({ flags }: { flags: Page<QualityFlag> }) {
  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle>
          Open flags ({flags.total.toLocaleString("en-GB")})
        </CardTitle>
      </CardHeader>
      {flags.items.length === 0 ? (
        <EmptyState
          title="Nothing flagged"
          hint="The validators found no problems."
        />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Severity</TableHead>
              <TableHead>Field</TableHead>
              <TableHead>Problem</TableHead>
              <TableHead>Detected by</TableHead>
              <TableHead>Suggested fix</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {flags.items.map((flag) => (
              <TableRow key={flag.id}>
                <TableCell>
                  <SeverityChip severity={flag.severity} />
                </TableCell>
                <TableCell className="text-xs text-foreground/85">
                  {fieldLabel(flag.field_name)}
                </TableCell>
                <TableCell className="max-w-md text-xs text-foreground/80">
                  {flag.message}
                </TableCell>
                <TableCell className="text-[0.625rem] text-muted-foreground">
                  {flag.detected_by ?? "—"}
                </TableCell>
                <TableCell className="text-[0.625rem] text-muted-foreground">
                  {flag.suggested_fix ?? "—"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Card>
  );
}

export function QualityBody({
  dashboard,
  flags,
}: {
  dashboard: QualityDashboardData | null;
  flags: Page<QualityFlag> | null;
}) {
  if (!dashboard) return null;

  const totalFlags = Object.values(dashboard.open_flags_by_severity).reduce(
    (sum, count) => sum + count,
    0,
  );

  return (
    <>
      <StatStrip className="lg:grid-cols-6">
        <Stat label="Pump models" value={dashboard.total_pump_models} />
        <Stat label="Vendors" value={dashboard.total_vendors} />
        <Stat
          label="Avg completeness"
          value={
            dashboard.avg_completeness_pct === null
              ? "—"
              : dashboard.avg_completeness_pct.toFixed(0) + "%"
          }
        />
        <Stat
          label="Open flags"
          value={totalFlags}
          tone={totalFlags ? "warn" : "good"}
        />
        <Stat
          label="Duplicate pairs"
          value={dashboard.duplicate_candidates_open}
          tone={dashboard.duplicate_candidates_open ? "warn" : "good"}
        />
        <Stat
          label="AI-derived fields"
          value={
            dashboard.ai_field_share_pct === null
              ? "—"
              : ratioAsPct(dashboard.ai_field_share_pct)
          }
          hint="Share of current values written by the model"
        />
      </StatStrip>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Records by confidence</CardTitle>
          </CardHeader>
          <Distribution data={dashboard.records_by_confidence} />
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Records by verification</CardTitle>
          </CardHeader>
          <Distribution data={dashboard.records_by_verification} />
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Open flags by type</CardTitle>
          </CardHeader>
          <Distribution data={dashboard.open_flags_by_type} />
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="overflow-hidden">
          <CardHeader>
            <CardTitle>Most frequently missing fields</CardTitle>
          </CardHeader>
          {dashboard.top_missing_fields.length === 0 ? (
            <EmptyState title="No missing-field flags raised" />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Field</TableHead>
                  <TableHead className="text-right">Records affected</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {dashboard.top_missing_fields.map((entry) => (
                  <TableRow key={entry.field_name}>
                    <TableCell className="text-xs text-foreground/85">
                      {fieldLabel(entry.field_name)}
                    </TableCell>
                    <TableCell className="figure text-right">
                      {entry.count}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </Card>

        <Card className="overflow-hidden">
          <CardHeader>
            <CardTitle>Review workload</CardTitle>
          </CardHeader>
          <div className="grid grid-cols-2 divide-x divide-border border-b border-border">
            <Stat
              label="Awaiting AI review"
              value={dashboard.pending_ai_reviews}
              tone={dashboard.pending_ai_reviews ? "warn" : "good"}
            />
            <Stat
              label="Stale records"
              value={dashboard.stale_records}
              hint="No source captured in the last 12 months"
              tone={dashboard.stale_records ? "warn" : "good"}
            />
          </div>
          <CardContent>
            <p className="label-xs">Flags by severity</p>
            <div className="mt-2 flex flex-wrap items-center gap-2.5">
              {SEVERITY_ORDER.map((severity) => {
                const count = dashboard.open_flags_by_severity[severity] ?? 0;
                if (!count) return null;
                return (
                  <span key={severity} className="flex items-center gap-1.5">
                    <SeverityChip severity={severity} />
                    <span className="figure text-muted-foreground">
                      {count}
                    </span>
                  </span>
                );
              })}
              {totalFlags === 0 ? (
                <span className="text-xs text-conf-verified">
                  No open flags
                </span>
              ) : null}
            </div>
          </CardContent>
        </Card>
      </div>

      {flags ? <FlagTable flags={flags} /> : null}
    </>
  );
}
