import { redirect } from "next/navigation";

import { ChangePassword } from "@/components/account/change-password";
import { AppShell } from "@/components/shell/app-shell";
import { PageHeader } from "@/components/shell/page-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { dateTime, text } from "@/lib/format";
import { hasSession } from "@/lib/api";
import { loadShellContext } from "@/lib/session";

export const metadata = { title: "Your account" };

/**
 * Your own account: who the platform thinks you are, and how to change your password.
 *
 * The password endpoint existed from the start and nothing called it, so changing one
 * meant a shell on the server with the database credentials to hand. That is a poor
 * reason to hand out database access, and it is why the administrator account kept its
 * published default long after anyone wanted it gone.
 */
export default async function AccountPage() {
  if (!(await hasSession())) redirect("/login");
  const { user, counts, authFailed } = await loadShellContext();
  if (authFailed) redirect("/login");

  return (
    <AppShell user={user} counts={counts}>
      <PageHeader
        crumbs={[{ label: "Your account" }]}
        title="Your account"
        lede="Who you are signed in as, and your password."
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="overflow-hidden">
          <CardHeader>
            <CardTitle>Signed in as</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1.5 text-xs">
            <p className="text-foreground">{text(user?.full_name)}</p>
            <p className="font-mono text-2xs text-muted-foreground">
              {text(user?.email)}
            </p>
            <div className="flex flex-wrap gap-1 pt-1">
              {(user?.roles ?? []).map((role) => (
                <Badge key={role.name} variant="secondary">
                  {role.display_name}
                </Badge>
              ))}
              {user?.is_platform_admin ? <Badge>Platform admin</Badge> : null}
            </div>
            {user?.password_changed_at ? (
              <p className="pt-1 text-2xs text-muted-foreground">
                Password last changed {dateTime(user.password_changed_at)}
              </p>
            ) : (
              <p className="pt-1 text-2xs text-sev-medium">
                This password has never been changed. If the account was created from a
                documented default, change it now.
              </p>
            )}
          </CardContent>
        </Card>

        <Card className="overflow-hidden">
          <CardHeader>
            <CardTitle>Change password</CardTitle>
          </CardHeader>
          <CardContent>
            <ChangePassword />
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}
