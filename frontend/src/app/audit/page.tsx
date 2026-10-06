import { redirect } from "next/navigation";

import { EmptyState, ErrorState } from "@/components/data/states";
import { AppShell } from "@/components/shell/app-shell";
import { PageHeader } from "@/components/shell/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
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
import type { AuditLogEntry, Page } from "@/types/api";

type Variant =
  "default" | "outline" | "secondary" | "destructive" | "success" | "warning";

/** Actions that change access or destroy data read as destructive; routine reads do not. */
const ACTION_VARIANT: Record<string, Variant> = {
  create: "success",
  update: "outline",
  delete: "destructive",
  login: "outline",
  login_failed: "destructive",
  logout: "outline",
  export: "warning",
  import: "outline",
  ai_suggestion_applied: "warning",
  ai_suggestion_rejected: "outline",
  permission_change: "destructive",
  tenant_change: "destructive",
  merge: "warning",
  read_sensitive: "warning",
};

export const metadata = { title: "Audit trail" };

export default async function AuditPage({
  searchParams,
}: {
  searchParams: Promise<{ action?: string; q?: string; page?: string }>;
}) {
  if (!(await hasSession())) redirect("/login");
  const { user, counts, authFailed } = await loadShellContext();
  if (authFailed) redirect("/login");

  const { action, q, page } = await searchParams;
  const offset = Math.max(0, (Number(page ?? "1") - 1) * 50);

  let logs: Page<AuditLogEntry> | null = null;
  let error: string | null = null;
  try {
    logs = await apiFetch<Page<AuditLogEntry>>("/audit-logs", {
      query: { action, q, limit: 50, offset },
      revalidate: false,
    });
  } catch (caught) {
    if (caught instanceof ApiError) {
      if (caught.isAuthError) {
        if (caught.status !== 403) redirect("/login");
        error = "The audit trail is restricted to administrators.";
      } else {
        error = caught.message;
      }
    } else {
      throw caught;
    }
  }

  return (
    <AppShell user={user} counts={counts}>
      <PageHeader
        title="Audit trail"
        lede="Append-only record of every change, sign-in, export and applied AI suggestion. Entries cannot be edited or removed, by anyone."
        actions={
          <form className="flex flex-wrap items-center gap-1.5" action="/audit">
            <Input
              type="search"
              name="q"
              defaultValue={q ?? ""}
              placeholder="Search summaries"
              aria-label="Search audit summaries"
              className="w-44"
            />
            {/* A plain select, not the Radix one: this form posts as a GET and needs a
                real form control with a name. */}
            <select
              name="action"
              defaultValue={action ?? ""}
              aria-label="Filter by action"
              className="h-8 rounded-md border border-input bg-background px-2 text-xs focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
            >
              <option value="">All actions</option>
              {Object.keys(ACTION_VARIANT).map((value) => (
                <option key={value} value={value}>
                  {humanise(value)}
                </option>
              ))}
            </select>
            <Button type="submit" variant="outline">
              Apply
            </Button>
          </form>
        }
      />

      <div className="space-y-4">
        {error ? <ErrorState message={error} /> : null}

        {logs ? (
          <Card className="overflow-hidden">
            <CardHeader>
              <CardTitle>
                {logs.total.toLocaleString("en-GB")} entries
              </CardTitle>
            </CardHeader>
            {logs.items.length === 0 ? (
              <EmptyState title="No audit entries match" />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>When</TableHead>
                    <TableHead>Action</TableHead>
                    <TableHead>Subject</TableHead>
                    <TableHead>Actor</TableHead>
                    <TableHead>Summary</TableHead>
                    <TableHead>Request</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {logs.items.map((entry) => (
                    <TableRow key={entry.id}>
                      <TableCell className="whitespace-nowrap font-mono text-[0.625rem] text-muted-foreground">
                        {dateTime(entry.occurred_at)}
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant={ACTION_VARIANT[entry.action] ?? "outline"}
                        >
                          {humanise(entry.action)}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <div className="text-xs text-foreground">
                          {entry.entity_label ?? "—"}
                        </div>
                        <div className="font-mono text-[0.625rem] text-muted-foreground">
                          {entry.entity_type ?? ""}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="text-xs text-foreground/80">
                          {entry.user_email ?? entry.actor_type}
                        </div>
                        <div className="font-mono text-[0.625rem] text-muted-foreground">
                          {entry.ip_address ?? ""}
                        </div>
                      </TableCell>
                      <TableCell className="max-w-sm text-xs text-foreground/80">
                        {entry.summary ?? "—"}
                        {Object.keys(entry.changes).length ? (
                          <details className="mt-1">
                            <summary className="cursor-pointer text-[0.625rem] text-primary">
                              {Object.keys(entry.changes).length} change(s)
                            </summary>
                            <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap rounded border border-border bg-background p-2 font-mono text-[0.625rem] text-muted-foreground">
                              {JSON.stringify(entry.changes, null, 2)}
                            </pre>
                          </details>
                        ) : null}
                      </TableCell>
                      <TableCell className="whitespace-nowrap font-mono text-[0.625rem] text-muted-foreground">
                        {entry.http_method
                          ? entry.http_method + " " + (entry.http_path ?? "")
                          : ""}
                        {entry.status_code
                          ? " · " + String(entry.status_code)
                          : ""}
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
