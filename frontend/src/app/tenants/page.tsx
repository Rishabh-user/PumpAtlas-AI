import { redirect } from "next/navigation";

import { EmptyState, ErrorState } from "@/components/data/states";
import { AppShell } from "@/components/shell/app-shell";
import { PageHeader } from "@/components/shell/page-header";
import { Badge } from "@/components/ui/badge";
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
import { num } from "@/lib/format";
import { humanise } from "@/lib/labels";
import { loadShellContext } from "@/lib/session";
import type { Page, Tenant } from "@/types/api";

type Variant =
  "default" | "outline" | "secondary" | "destructive" | "success" | "warning";

const STATUS_VARIANT: Record<string, Variant> = {
  active: "success",
  trial: "warning",
  suspended: "destructive",
  churned: "destructive",
};

export const metadata = { title: "Tenant management" };

export default async function TenantsPage() {
  if (!(await hasSession())) redirect("/login");
  const { user, counts, authFailed } = await loadShellContext();
  if (authFailed) redirect("/login");

  let tenants: Page<Tenant> | null = null;
  let error: string | null = null;
  try {
    tenants = await apiFetch<Page<Tenant>>("/tenants", {
      query: { limit: 100 },
      revalidate: false,
    });
  } catch (caught) {
    if (caught instanceof ApiError) {
      if (caught.status === 401) redirect("/login");
      error =
        caught.status === 403
          ? "Tenant management is restricted to Targeticon platform administrators."
          : caught.message;
    } else {
      throw caught;
    }
  }

  return (
    <AppShell user={user} counts={counts}>
      <PageHeader
        title="Tenant management"
        lede="Client companies on the platform. Each one is isolated by PostgreSQL row level security; shared master data is readable only where the entitlement allows it."
      />

      <div className="space-y-4">
        {error ? <ErrorState message={error} /> : null}

        {tenants ? (
          <Card className="overflow-hidden">
            <CardHeader>
              <CardTitle>
                {tenants.total.toLocaleString("en-GB")} tenants
              </CardTitle>
            </CardHeader>
            {tenants.items.length === 0 ? (
              <EmptyState title="No tenants provisioned" />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Client company</TableHead>
                    <TableHead>Plan</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Shared master</TableHead>
                    <TableHead className="text-right">Users</TableHead>
                    <TableHead className="text-right">Vendors</TableHead>
                    <TableHead className="text-right">Pump models</TableHead>
                    <TableHead className="text-right">Storage</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {tenants.items.map((tenant) => (
                    <TableRow key={tenant.id}>
                      <TableCell>
                        <div className="text-xs font-medium text-foreground">
                          {tenant.name}
                        </div>
                        <div className="font-mono text-[0.625rem] text-muted-foreground">
                          {tenant.slug}
                          {tenant.country ? " · " + tenant.country : ""}
                          {tenant.industry_segment
                            ? " · " + tenant.industry_segment
                            : ""}
                        </div>
                      </TableCell>
                      <TableCell className="text-xs">
                        {humanise(tenant.plan)}
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant={STATUS_VARIANT[tenant.status] ?? "outline"}
                        >
                          {humanise(tenant.status)}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-xs text-foreground/80">
                        {tenant.can_use_shared_master ? "Read" : "No access"}
                      </TableCell>
                      <TableCell className="figure text-right">
                        {tenant.user_count ?? "—"}
                        <span className="text-muted-foreground">
                          {" "}
                          / {tenant.max_users}
                        </span>
                      </TableCell>
                      <TableCell className="figure text-right">
                        {num(tenant.vendor_count ?? null, { decimals: 0 })}
                      </TableCell>
                      <TableCell className="figure text-right">
                        {num(tenant.pump_model_count ?? null, { decimals: 0 })}
                      </TableCell>
                      <TableCell className="figure text-right">
                        {tenant.storage_used_mb === undefined
                          ? "—"
                          : tenant.storage_used_mb.toFixed(1) + " MB"}
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
