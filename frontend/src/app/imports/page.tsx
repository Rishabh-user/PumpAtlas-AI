import { redirect } from "next/navigation";

import { EmptyState, ErrorState } from "@/components/data/states";
import { IngestForms } from "@/components/ingest-forms";
import { AppShell } from "@/components/shell/app-shell";
import { PageHeader } from "@/components/shell/page-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ApiError, apiFetch, hasSession } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { humanise } from "@/lib/labels";
import { loadShellContext } from "@/lib/session";
import type { ImportBatch, Page } from "@/types/api";

type Variant =
  "default" | "outline" | "secondary" | "destructive" | "success" | "warning";

const STATUS_VARIANT: Record<string, Variant> = {
  queued: "outline",
  fetching: "outline",
  parsing: "outline",
  parsed: "outline",
  extracting: "warning",
  extracted: "warning",
  needs_review: "warning",
  promoted: "success",
  failed: "destructive",
  rejected: "destructive",
};

export const metadata = { title: "Import queue" };

export default async function ImportsPage() {
  if (!(await hasSession())) redirect("/login");
  const { user, counts, authFailed } = await loadShellContext();
  if (authFailed) redirect("/login");

  let batches: Page<ImportBatch> | null = null;
  let error: string | null = null;
  try {
    batches = await apiFetch<Page<ImportBatch>>("/ingest/batches", {
      query: { limit: 40 },
      revalidate: false,
    });
  } catch (caught) {
    if (caught instanceof ApiError && caught.isAuthError) redirect("/login");
    error = caught instanceof Error ? caught.message : "Unknown error";
  }

  return (
    <AppShell user={user} counts={counts}>
      <PageHeader
        title="Import queue"
        lede="Everything entering the platform lands in a source record first. Extraction runs as a separate, retryable step, so a parsing failure never loses the captured evidence."
      />

      <div className="space-y-4">
        {error ? <ErrorState message={error} /> : null}

        <IngestForms />

        {batches ? (
          <Card className="overflow-hidden">
            <CardHeader>
              <CardTitle>
                Batches ({batches.total.toLocaleString("en-GB")})
              </CardTitle>
            </CardHeader>
            {batches.items.length === 0 ? (
              <EmptyState
                title="No imports yet"
                hint="Upload a datasheet, queue some URLs, or run a web-search discovery above."
              />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Batch</TableHead>
                    <TableHead>Mode</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="w-32">Progress</TableHead>
                    <TableHead className="text-right">Promoted</TableHead>
                    <TableHead className="text-right">Review</TableHead>
                    <TableHead className="text-right">Failed</TableHead>
                    <TableHead>Started</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {batches.items.map((batch) => (
                    <TableRow key={batch.id}>
                      <TableCell className="max-w-xs">
                        <div className="truncate text-xs font-medium text-foreground">
                          {batch.name}
                        </div>
                        {batch.error_summary ? (
                          <div className="mt-0.5 truncate text-[0.625rem] text-destructive">
                            {batch.error_summary}
                          </div>
                        ) : null}
                      </TableCell>
                      <TableCell className="text-xs text-foreground/80">
                        {humanise(batch.import_mode)}
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant={STATUS_VARIANT[batch.status] ?? "outline"}
                        >
                          {humanise(batch.status)}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <span className="figure block text-muted-foreground">
                          {batch.processed_items}/{batch.total_items || "?"}
                        </span>
                        <Progress
                          value={Math.min(100, batch.progress_pct)}
                          className="mt-1.5 w-24"
                        />
                      </TableCell>
                      <TableCell className="figure text-right text-conf-verified">
                        {batch.promoted_items}
                      </TableCell>
                      <TableCell className="figure text-right text-sev-medium">
                        {batch.needs_review_items}
                      </TableCell>
                      <TableCell className="figure text-right text-destructive">
                        {batch.failed_items}
                      </TableCell>
                      <TableCell className="whitespace-nowrap font-mono text-[0.625rem] text-muted-foreground">
                        {dateTime(batch.started_at ?? batch.created_at)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </Card>
        ) : null}
      </div>
    </AppShell>
  );
}
