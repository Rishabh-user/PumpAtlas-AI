import Link from "next/link";
import { redirect } from "next/navigation";

import { EmptyState, ErrorState } from "@/components/data/states";
import { AppShell } from "@/components/shell/app-shell";
import { PageHeader } from "@/components/shell/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ApiError, apiFetch, hasSession } from "@/lib/api";
import { loadShellContext } from "@/lib/session";
import { cn } from "@/lib/utils";
import type { DatabaseTableList, DatabaseTablePage } from "@/types/api";

export const metadata = { title: "Database" };

const PAGE_SIZE = 50;

/** Long values are clipped in the cell; the full value is on the title attribute. */
const MAX_CELL_CHARS = 120;

function tableHref(name: string, page = 1) {
  return {
    pathname: "/admin/database",
    query: { table: name, ...(page > 1 ? { page } : {}) },
  };
}

/**
 * Read-only view of every table, for platform staff.
 *
 * Exists for the question no purpose-built screen answers: what is actually stored
 * after an import, an AI promotion or a migration. It is deliberately not a SQL console
 * — see the route module for why — and the page says plainly what it withholds and
 * whose data it shows, because a viewer that looks tenant-scoped while showing every
 * tenant is worse than one that admits it.
 */
export default async function AdminDatabasePage({
  searchParams,
}: {
  searchParams: Promise<{ table?: string; page?: string }>;
}) {
  if (!(await hasSession())) redirect("/login");
  const { user, counts, authFailed } = await loadShellContext();
  if (authFailed) redirect("/login");

  // Checked here as well as by the API. The API is the boundary that matters; this
  // just avoids rendering a shell around a 403.
  if (user && !user.is_platform_admin) redirect("/");

  const params = await searchParams;
  const selected = params.table?.trim() || null;
  const currentPage = Math.max(1, Number(params.page ?? "1") || 1);
  const offset = (currentPage - 1) * PAGE_SIZE;

  let list: DatabaseTableList | null = null;
  let rows: DatabaseTablePage | null = null;
  let error: string | null = null;
  try {
    // Together: the sidebar list is needed whichever table is open.
    const [listResult, rowsResult] = await Promise.all([
      apiFetch<DatabaseTableList>("/admin/database/tables", {
        revalidate: false,
      }),
      selected
        ? apiFetch<DatabaseTablePage>(
            `/admin/database/tables/${encodeURIComponent(selected)}`,
            { query: { limit: PAGE_SIZE, offset }, revalidate: false },
          ).catch((caught) => {
            // A bad table name in the URL should not blank the whole page.
            if (caught instanceof ApiError && caught.status === 404)
              return null;
            throw caught;
          })
        : Promise.resolve(null),
    ]);
    list = listResult;
    rows = rowsResult;
  } catch (caught) {
    if (caught instanceof ApiError && caught.isAuthError) redirect("/login");
    error = caught instanceof Error ? caught.message : "Unknown error";
  }

  const lastPage = rows ? Math.max(1, Math.ceil(rows.total / PAGE_SIZE)) : 1;
  const shown = rows ? rows.offset + rows.items.length : 0;

  return (
    <AppShell user={user} counts={counts}>
      <PageHeader
        title="Database"
        lede="Every table in the schema, read-only. For confirming what was actually stored — corrections go through the record screens, so they keep their provenance and audit trail."
        meta={
          list ? (
            <Badge variant="warning">{list.tables.length} tables</Badge>
          ) : null
        }
      />

      <div className="space-y-4">
        {error ? <ErrorState message={error} /> : null}

        {list ? (
          <p className="text-2xs leading-relaxed text-muted-foreground">
            Shows{" "}
            <span className="text-foreground">every tenant&rsquo;s rows</span> —
            platform staff see across tenant boundaries by design. Password
            hashes, MFA secrets and API key hashes are never read from the
            database. Row counts in the list are PostgreSQL estimates; the count
            on an open table is exact. Every table opened here is written to the
            audit trail.
          </p>
        ) : null}

        <div className="grid gap-4 lg:grid-cols-[16rem_1fr]">
          <Card className="overflow-hidden">
            <CardHeader>
              <CardTitle>Tables</CardTitle>
            </CardHeader>
            <div className="max-h-[36rem] overflow-y-auto">
              {list?.tables.map((entry) => (
                <Link
                  key={entry.name}
                  href={tableHref(entry.name)}
                  className={cn(
                    "flex items-baseline justify-between gap-2 border-b border-border/60 px-3 py-1.5 transition-colors last:border-0 hover:bg-accent",
                    entry.name === rows?.table && "bg-accent",
                  )}
                >
                  <span
                    className={cn(
                      "truncate font-mono text-2xs",
                      entry.name === rows?.table
                        ? "text-primary"
                        : "text-foreground",
                    )}
                  >
                    {entry.name}
                  </span>
                  <span className="figure shrink-0 text-muted-foreground">
                    {entry.estimated_rows.toLocaleString("en-GB")}
                  </span>
                </Link>
              )) ?? null}
            </div>
          </Card>

          {rows ? (
            <Card className="min-w-0 overflow-hidden">
              <CardHeader>
                <CardTitle>{rows.table}</CardTitle>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="figure text-muted-foreground">
                    {rows.total.toLocaleString("en-GB")} rows &middot;{" "}
                    {rows.columns.length} columns
                  </span>
                  {rows.redacted_columns.length ? (
                    <Badge variant="outline">
                      {rows.redacted_columns.length} withheld
                    </Badge>
                  ) : null}
                  {rows.ordered_by ? null : (
                    <Badge
                      variant="outline"
                      title="This table has no single-column primary key, so the database does not guarantee a stable order between pages."
                    >
                      unordered
                    </Badge>
                  )}
                </div>
              </CardHeader>

              {rows.items.length ? (
                // The only horizontally scrolling region on the page: a 161-column spec
                // table cannot be made to fit, and the page body must never scroll
                // sideways.
                <div className="max-h-[36rem] overflow-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        {rows.columns.map((column) => (
                          <TableHead
                            key={column.name}
                            className="whitespace-nowrap"
                            title={`${column.data_type}${column.nullable ? "" : " · not null"}`}
                          >
                            <span
                              className={
                                column.redacted
                                  ? "text-muted-foreground/60"
                                  : undefined
                              }
                            >
                              {column.name}
                            </span>
                          </TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {rows.items.map((row, index) => (
                        <TableRow key={index}>
                          {rows.columns.map((column) => {
                            // Indexed access is `| undefined` under
                            // noUncheckedIndexedAccess. The API sends a key for every
                            // column, so an absent one means the row and the column
                            // list disagree — shown as null rather than crashing.
                            const value = row[column.name] ?? null;
                            return (
                              <TableCell
                                key={column.name}
                                className="max-w-sm truncate font-mono text-2xs"
                                title={value ?? undefined}
                              >
                                {value === null ? (
                                  <span className="text-muted-foreground/50">
                                    null
                                  </span>
                                ) : column.redacted ? (
                                  <span className="text-muted-foreground/60">
                                    {value}
                                  </span>
                                ) : (
                                  value.slice(0, MAX_CELL_CHARS)
                                )}
                              </TableCell>
                            );
                          })}
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ) : (
                <EmptyState
                  title="No rows"
                  hint="The table exists but holds nothing yet."
                />
              )}

              {rows.total > PAGE_SIZE ? (
                <div className="flex items-center justify-between border-t border-border px-3 py-2 text-2xs text-muted-foreground">
                  <span className="font-mono">
                    {rows.offset + 1}&ndash;{shown} of{" "}
                    {rows.total.toLocaleString("en-GB")}
                  </span>
                  <div className="flex items-center gap-1.5">
                    <span className="mr-1 font-mono">
                      Page {currentPage} of {lastPage}
                    </span>
                    {currentPage <= 1 ? (
                      <Button variant="outline" size="sm" disabled>
                        Previous
                      </Button>
                    ) : (
                      <Button variant="outline" size="sm" asChild>
                        <Link href={tableHref(rows.table, currentPage - 1)}>
                          Previous
                        </Link>
                      </Button>
                    )}
                    {shown >= rows.total ? (
                      <Button variant="outline" size="sm" disabled>
                        Next
                      </Button>
                    ) : (
                      <Button variant="outline" size="sm" asChild>
                        <Link href={tableHref(rows.table, currentPage + 1)}>
                          Next
                        </Link>
                      </Button>
                    )}
                  </div>
                </div>
              ) : null}
            </Card>
          ) : (
            <Card>
              <EmptyState
                title={
                  selected ? `No table named "${selected}"` : "Pick a table"
                }
                hint={
                  selected
                    ? "It is not a base table in the public schema."
                    : "Choose one from the list to read its rows."
                }
              />
            </Card>
          )}
        </div>
      </div>
    </AppShell>
  );
}
