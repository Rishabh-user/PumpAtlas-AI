"use client";

import { useCallback, useEffect, useState } from "react";
import { Check, Copy, KeyRound, Loader2, ShieldOff } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { clientFetch } from "@/lib/api-client";
import { dateOnly } from "@/lib/format";
import type { Tenant } from "@/types/api";

/**
 * The credential a customer integrates with.
 *
 * Provisioning a tenant used to leave you with no way to give anybody access: the only
 * key endpoint binds a key to the *caller's* tenant, so platform staff issuing one got
 * a key belonging to nobody that reads the shared catalogue and nothing else. One of
 * those is still in this database.
 *
 * A key carries its tenant for its whole life, so the integrator sends it alone — no
 * tenant header, no bearer token. Row level security does the scoping, which is why
 * this is the only thing they need and why it must never be mailed around casually.
 */

/** What a consuming application almost always wants, and nothing more. */
const READ_SCOPES = [
  "vendor:read",
  "pump:read",
  "search:read",
  "data_quality:read",
] as const;

const WRITE_SCOPES = ["vendor:write", "pump:write", "ingestion:write"] as const;

interface ApiKeyRow {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  is_active: boolean;
  expires_at: string | null;
  last_used_at: string | null;
  created_at?: string | null;
}

export function TenantApiKeys({ tenant }: { tenant: Tenant }) {
  const [open, setOpen] = useState(false);
  const [keys, setKeys] = useState<ApiKeyRow[] | null>(null);
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>([...READ_SCOPES]);
  const [days, setDays] = useState("365");
  const [issuing, setIssuing] = useState(false);
  const [issued, setIssued] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setKeys(await clientFetch<ApiKeyRow[]>(`/tenants/${tenant.id}/api-keys`));
    } catch {
      setKeys([]);
    }
  }, [tenant.id]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  function toggle(scope: string) {
    setScopes((prev) =>
      prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope],
    );
  }

  async function issue(event: React.FormEvent) {
    event.preventDefault();
    setIssuing(true);
    setError(null);
    try {
      const result = await clientFetch<{ api_key: string }>(
        `/tenants/${tenant.id}/api-keys`,
        {
          method: "POST",
          body: {
            name: name.trim(),
            scopes,
            expires_in_days: days === "" ? null : Number(days),
          },
        },
      );
      setIssued(result.api_key);
      setName("");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not issue the key");
    } finally {
      setIssuing(false);
    }
  }

  async function revoke(key: ApiKeyRow) {
    try {
      await clientFetch(`/tenants/${tenant.id}/api-keys/${key.id}`, {
        method: "DELETE",
      });
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not revoke");
    }
  }

  const ready = name.trim().length >= 2 && scopes.length > 0 && !issuing;
  const active = (keys ?? []).filter((k) => k.is_active);

  return (
    <Sheet
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        // The plaintext is shown once and never retrievable; closing is the moment it
        // is gone, so it should not reappear if the panel is opened again.
        if (!next) {
          setIssued(null);
          setCopied(false);
          setError(null);
        }
      }}
    >
      <SheetTrigger asChild>
        <button
          type="button"
          className="inline-flex items-center gap-1 text-2xs text-primary hover:underline"
        >
          <KeyRound className="size-3" />
          API keys
        </button>
      </SheetTrigger>

      <SheetContent className="flex w-full flex-col gap-0 overflow-y-auto sm:max-w-xl">
        <SheetHeader>
          <SheetTitle>API keys — {tenant.name}</SheetTitle>
          <SheetDescription>
            A key carries this client&rsquo;s tenant for its whole life. The integrator
            sends it alone, as <code className="font-mono">X-API-Key</code> — no tenant
            header and no bearer token — and sees this client&rsquo;s records plus
            whatever shared master data their entitlement allows.
          </SheetDescription>
        </SheetHeader>

        <div className="space-y-4 px-4 py-3">
          {issued ? (
            <div className="space-y-1.5 rounded-md border border-conf-verified/40 bg-conf-verified/[0.06] p-2.5">
              <p className="text-xs font-medium text-foreground">
                Copy this now — it is never shown again
              </p>
              <p className="text-2xs text-muted-foreground">
                Only a hash is stored. If it is lost, issue another and revoke this one.
              </p>
              <div className="flex items-center gap-1.5">
                <code className="min-w-0 flex-1 overflow-x-auto rounded bg-background px-2 py-1 font-mono text-2xs text-foreground">
                  {issued}
                </code>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    void navigator.clipboard.writeText(issued);
                    setCopied(true);
                  }}
                >
                  {copied ? <Check /> : <Copy />}
                  {copied ? "Copied" : "Copy"}
                </Button>
              </div>
            </div>
          ) : null}

          <form onSubmit={(e) => void issue(e)} className="space-y-2.5">
            <p className="label-xs text-foreground">Issue a key</p>
            <div className="grid gap-2 sm:grid-cols-[1fr_8rem]">
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="h-8 text-xs"
                placeholder="What will use it — e.g. Valvesheet vendor browser"
              />
              <Input
                type="number"
                min={1}
                max={3650}
                value={days}
                onChange={(e) => setDays(e.target.value)}
                className="h-8 text-xs"
                placeholder="days"
                title="Days until it expires. Leave empty for no expiry."
              />
            </div>

            <div className="space-y-1 rounded-md border border-border p-2">
              <p className="text-2xs text-muted-foreground">
                Scopes. Read is what a consuming application needs; a write scope lets
                it change this client&rsquo;s records.
              </p>
              <div className="flex flex-wrap gap-x-3 gap-y-1">
                {[...READ_SCOPES, ...WRITE_SCOPES].map((scope) => (
                  <label
                    key={scope}
                    className="flex items-center gap-1 font-mono text-2xs text-muted-foreground"
                  >
                    <input
                      type="checkbox"
                      checked={scopes.includes(scope)}
                      onChange={() => toggle(scope)}
                      className="size-3"
                    />
                    <span
                      className={
                        scope.endsWith(":write") ? "text-sev-medium" : undefined
                      }
                    >
                      {scope}
                    </span>
                  </label>
                ))}
              </div>
            </div>

            {error ? <p className="text-2xs text-destructive">{error}</p> : null}

            <Button type="submit" size="sm" disabled={!ready}>
              {issuing ? <Loader2 className="animate-spin" /> : <KeyRound />}
              {issuing ? "Issuing…" : "Issue key"}
            </Button>
          </form>

          <div>
            <p className="label-xs text-foreground">
              Issued ({active.length} active
              {keys && keys.length > active.length
                ? `, ${keys.length - active.length} revoked`
                : ""}
              )
            </p>
            {keys === null ? (
              <p className="mt-1 flex items-center gap-1.5 text-2xs text-muted-foreground">
                <Loader2 className="size-3 animate-spin" /> Loading…
              </p>
            ) : keys.length === 0 ? (
              <p className="mt-1 text-2xs text-muted-foreground">
                None yet. This client cannot reach the API until one is issued.
              </p>
            ) : (
              <ul className="mt-1">
                {keys.map((key) => (
                  <li
                    key={key.id}
                    className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 border-b border-border/50 py-1.5 last:border-0"
                  >
                    <span className="text-xs text-foreground">{key.name}</span>
                    <code className="font-mono text-[0.625rem] text-muted-foreground">
                      {key.prefix}…
                    </code>
                    {key.is_active ? null : (
                      <Badge variant="outline">revoked</Badge>
                    )}
                    {key.is_active && !key.expires_at ? (
                      <Badge
                        variant="warning"
                        title="A key with no expiry works for good unless someone revokes it"
                      >
                        no expiry
                      </Badge>
                    ) : null}
                    <span className="w-full text-[0.625rem] text-muted-foreground">
                      {key.scopes.join(" · ") || "no scopes"}
                      {key.expires_at
                        ? ` · expires ${dateOnly(key.expires_at)}`
                        : ""}
                      {key.last_used_at
                        ? ` · last used ${dateOnly(key.last_used_at)}`
                        : " · never used"}
                    </span>
                    {key.is_active ? (
                      <button
                        type="button"
                        onClick={() => void revoke(key)}
                        className="ml-auto inline-flex items-center gap-1 text-2xs text-muted-foreground hover:text-destructive"
                      >
                        <ShieldOff className="size-3" />
                        Revoke
                      </button>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
