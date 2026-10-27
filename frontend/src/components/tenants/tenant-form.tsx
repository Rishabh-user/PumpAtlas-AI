"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Check, Loader2, Pencil, Plus, ShieldOff } from "lucide-react";

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
import type { Tenant } from "@/types/api";

/**
 * Provision a client company, or change its terms.
 *
 * The platform could create and amend tenants from the day it had tenants — `POST` and
 * `PATCH /tenants` have always been there — and the only way to reach them was curl.
 * Onboarding a customer by hand-writing JSON is fine for the first one and untenable by
 * the fourth, which is roughly where this product now is.
 */

const PLANS = ["trial", "standard", "professional", "enterprise"] as const;
const STATUSES = ["trial", "active", "suspended", "churned"] as const;

/** The API's own rule, mirrored so the message arrives before the request does. */
const SLUG_RULE = /^[a-z0-9][a-z0-9-]*[a-z0-9]$/;
const MIN_PASSWORD = 12;

interface Draft {
  slug: string;
  name: string;
  country: string;
  plan: string;
  status: string;
  primary_contact_email: string;
  can_use_shared_master: boolean;
  can_contribute_shared_master: boolean;
  max_users: string;
  admin_email: string;
  admin_full_name: string;
  admin_password: string;
}

function draftFrom(tenant?: Tenant): Draft {
  return {
    slug: tenant?.slug ?? "",
    name: tenant?.name ?? "",
    country: tenant?.country ?? "",
    plan: tenant?.plan ?? "trial",
    status: tenant?.status ?? "trial",
    primary_contact_email: tenant?.primary_contact_email ?? "",
    can_use_shared_master: tenant?.can_use_shared_master ?? true,
    can_contribute_shared_master: tenant?.can_contribute_shared_master ?? false,
    max_users: String(tenant?.max_users ?? 25),
    admin_email: "",
    admin_full_name: "",
    admin_password: "",
  };
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block min-w-0">
      <span className="label-xs block text-muted-foreground">{label}</span>
      {children}
      {hint ? (
        <span className="mt-0.5 block text-[0.625rem] text-muted-foreground">
          {hint}
        </span>
      ) : null}
    </label>
  );
}

export function TenantForm({ tenant }: { tenant?: Tenant }) {
  const router = useRouter();
  const editing = Boolean(tenant);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<Draft>(() => draftFrom(tenant));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function set<K extends keyof Draft>(key: K, value: Draft[K]) {
    setDraft((prev) => ({ ...prev, [key]: value }));
    setError(null);
  }

  // The admin trio is all-or-nothing in the API; saying so here beats a 422.
  const adminParts = [
    draft.admin_email,
    draft.admin_full_name,
    draft.admin_password,
  ];
  const adminStarted = adminParts.some(Boolean);
  const adminComplete = adminParts.every(Boolean);
  const slugBad = !editing && draft.slug !== "" && !SLUG_RULE.test(draft.slug);
  const passwordShort =
    draft.admin_password !== "" && draft.admin_password.length < MIN_PASSWORD;

  const ready =
    draft.name.trim().length >= 2 &&
    (editing || (draft.slug.length >= 2 && !slugBad)) &&
    (!adminStarted || (adminComplete && !passwordShort)) &&
    !saving;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      // `legal_name` and `industry_segment` are deliberately absent. Both were stored,
      // shown as a caption under the tenant name, and read by nothing - no filter, no
      // entitlement, no report. As free text the segment had already drifted across two
      // rows ("Upstream FPSO operator" against "upstream FPSO operator / EPC
      // contractor"), so it could not answer the one question a segment is for. The
      // columns stay for the values already in them; if segmentation earns its place
      // later it belongs as a controlled list that can be filtered, not a text box.
      const common = {
        name: draft.name.trim(),
        country: draft.country.trim().toUpperCase() || null,
        plan: draft.plan,
        primary_contact_email: draft.primary_contact_email.trim() || null,
        can_use_shared_master: draft.can_use_shared_master,
        can_contribute_shared_master: draft.can_contribute_shared_master,
        max_users: Number(draft.max_users) || 25,
      };
      if (editing && tenant) {
        await clientFetch(`/tenants/${tenant.id}`, {
          method: "PATCH",
          body: { ...common, status: draft.status },
        });
      } else {
        await clientFetch("/tenants", {
          method: "POST",
          body: {
            ...common,
            slug: draft.slug.trim(),
            ...(adminComplete
              ? {
                  admin_email: draft.admin_email.trim(),
                  admin_full_name: draft.admin_full_name.trim(),
                  admin_password: draft.admin_password,
                }
              : {}),
          },
        });
      }
      setOpen(false);
      setDraft(draftFrom(editing ? tenant : undefined));
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        {editing ? (
          <button
            type="button"
            className="inline-flex items-center gap-1 text-2xs text-primary hover:underline"
          >
            <Pencil className="size-3" />
            Edit
          </button>
        ) : (
          <Button>
            <Plus />
            New tenant
          </Button>
        )}
      </SheetTrigger>

      <SheetContent className="flex w-full flex-col gap-0 overflow-y-auto sm:max-w-xl">
        <SheetHeader>
          <SheetTitle>
            {editing ? `Edit ${tenant?.name}` : "Provision a client company"}
          </SheetTitle>
          <SheetDescription>
            {editing
              ? "Commercial terms and entitlements. The slug cannot change — it identifies the tenant everywhere, including in issued API keys."
              : "Creates the tenant and, optionally, its first administrator. Everything this client stores is isolated by row level security from the moment it exists."}
          </SheetDescription>
        </SheetHeader>

        <form onSubmit={(e) => void submit(e)} className="space-y-4 px-4 py-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Client company">
              <Input
                value={draft.name}
                onChange={(e) => set("name", e.target.value)}
                className="mt-0.5 h-8 text-xs"
                placeholder="SP Energy"
              />
            </Field>

            {editing ? null : (
              <Field
                label="Slug"
                hint="Lower case, digits and hyphens. Permanent once set."
              >
                <Input
                  value={draft.slug}
                  onChange={(e) => set("slug", e.target.value.toLowerCase())}
                  className="mt-0.5 h-8 font-mono text-xs"
                  placeholder="sp-energy"
                />
              </Field>
            )}

            <Field label="Country" hint="Two-letter ISO code">
              <Input
                value={draft.country}
                onChange={(e) => set("country", e.target.value.toUpperCase())}
                maxLength={2}
                className="mt-0.5 h-8 font-mono text-xs"
                placeholder="IN"
              />
            </Field>

            <Field label="Primary contact email">
              <Input
                type="email"
                value={draft.primary_contact_email}
                onChange={(e) => set("primary_contact_email", e.target.value)}
                className="mt-0.5 h-8 text-xs"
              />
            </Field>

            <Field label="Plan">
              <select
                value={draft.plan}
                onChange={(e) => set("plan", e.target.value)}
                className="mt-0.5 h-8 w-full rounded border border-border bg-background px-1.5 text-xs"
              >
                {PLANS.map((plan) => (
                  <option key={plan} value={plan}>
                    {plan}
                  </option>
                ))}
              </select>
            </Field>

            {editing ? (
              <Field label="Status">
                <select
                  value={draft.status}
                  onChange={(e) => set("status", e.target.value)}
                  className="mt-0.5 h-8 w-full rounded border border-border bg-background px-1.5 text-xs"
                >
                  {STATUSES.map((status) => (
                    <option key={status} value={status}>
                      {status}
                    </option>
                  ))}
                </select>
              </Field>
            ) : null}

            <Field label="Maximum users">
              <Input
                type="number"
                min={1}
                value={draft.max_users}
                onChange={(e) => set("max_users", e.target.value)}
                className="mt-0.5 h-8 text-xs"
              />
            </Field>
          </div>

          <div className="space-y-1.5 rounded-md border border-border p-2.5">
            <p className="label-xs text-foreground">Shared master catalogue</p>
            <label className="flex items-start gap-2 text-2xs text-muted-foreground">
              <input
                type="checkbox"
                checked={draft.can_use_shared_master}
                onChange={(e) => set("can_use_shared_master", e.target.checked)}
                className="mt-0.5 size-3"
              />
              <span>
                <span className="text-foreground">May read it.</span> Targeticon&rsquo;s
                curated records appear alongside this client&rsquo;s own. Their data
                never travels the other way.
              </span>
            </label>
            <label className="flex items-start gap-2 text-2xs text-muted-foreground">
              <input
                type="checkbox"
                checked={draft.can_contribute_shared_master}
                onChange={(e) =>
                  set("can_contribute_shared_master", e.target.checked)
                }
                className="mt-0.5 size-3"
              />
              <span>
                <span className="text-foreground">May contribute to it.</span> What this
                client records can become visible to every other tenant — rarely what you
                want for a client&rsquo;s own supply chain.
              </span>
            </label>
          </div>

          {editing ? null : (
            <div className="space-y-2 rounded-md border border-border p-2.5">
              <p className="label-xs text-foreground">
                First administrator{" "}
                <span className="font-normal text-muted-foreground">(optional)</span>
              </p>
              <p className="text-2xs text-muted-foreground">
                Without one, the tenant exists but nobody can sign in to it. All three
                fields are required together.
              </p>
              <div className="grid gap-2 sm:grid-cols-2">
                <Input
                  value={draft.admin_full_name}
                  onChange={(e) => set("admin_full_name", e.target.value)}
                  className="h-8 text-xs"
                  placeholder="Full name"
                />
                <Input
                  type="email"
                  value={draft.admin_email}
                  onChange={(e) => set("admin_email", e.target.value)}
                  className="h-8 text-xs"
                  placeholder="name@client.com"
                />
                <Input
                  type="password"
                  autoComplete="new-password"
                  value={draft.admin_password}
                  onChange={(e) => set("admin_password", e.target.value)}
                  className="h-8 text-xs sm:col-span-2"
                  placeholder={`Initial password — at least ${MIN_PASSWORD} characters`}
                />
              </div>
            </div>
          )}

          {slugBad ? (
            <p className="text-2xs text-destructive">
              A slug is lower-case letters, digits and hyphens, starting and ending with
              a letter or digit.
            </p>
          ) : null}
          {adminStarted && !adminComplete ? (
            <p className="text-2xs text-destructive">
              Name, email and password are needed together, or leave all three empty.
            </p>
          ) : null}
          {passwordShort ? (
            <p className="text-2xs text-destructive">
              {MIN_PASSWORD - draft.admin_password.length} more character
              {MIN_PASSWORD - draft.admin_password.length === 1 ? "" : "s"} needed.
            </p>
          ) : null}
          {error ? <p className="text-2xs text-destructive">{error}</p> : null}

          <Button type="submit" disabled={!ready}>
            {saving ? <Loader2 className="animate-spin" /> : <Check />}
            {saving
              ? "Saving…"
              : editing
                ? "Save changes"
                : "Provision tenant"}
          </Button>
        </form>
      </SheetContent>
    </Sheet>
  );
}

/**
 * Suspend, which is what this platform does instead of deleting a client.
 *
 * `DELETE /tenants/{id}` suspends and deactivates every user: client data is retained
 * for the contract term. Labelling the control "Delete" would promise something the
 * API deliberately does not do.
 */
export function SuspendTenant({ tenant }: { tenant: Tenant }) {
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (tenant.status === "suspended") return null;

  async function suspend() {
    setBusy(true);
    setError(null);
    try {
      await clientFetch(`/tenants/${tenant.id}`, { method: "DELETE" });
      setConfirming(false);
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not suspend");
    } finally {
      setBusy(false);
    }
  }

  if (!confirming) {
    return (
      <button
        type="button"
        onClick={() => setConfirming(true)}
        className="inline-flex items-center gap-1 text-2xs text-muted-foreground hover:text-destructive"
      >
        <ShieldOff className="size-3" />
        Suspend
      </button>
    );
  }

  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="text-2xs text-muted-foreground">
        Sign-in stops for all users. Data is kept.
      </span>
      <button
        type="button"
        onClick={() => void suspend()}
        disabled={busy}
        className="text-2xs font-medium text-destructive hover:underline"
      >
        {busy ? "Suspending…" : "Confirm"}
      </button>
      <button
        type="button"
        onClick={() => setConfirming(false)}
        className="text-2xs text-muted-foreground hover:underline"
      >
        Cancel
      </button>
      {error ? <span className="text-2xs text-destructive">{error}</span> : null}
    </span>
  );
}
