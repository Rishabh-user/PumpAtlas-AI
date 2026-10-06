"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import {
  CircleCheck,
  CircleX,
  Copy,
  Loader2,
  Plus,
  Trash2,
  Zap,
} from "lucide-react";

import { ErrorState, SuccessNote } from "@/components/data/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { clientFetch } from "@/lib/api-client";
import { ApiError } from "@/lib/api-shared";
import { cn } from "@/lib/utils";
import type {
  AiProviderConfig,
  AiProviderList,
  AiRole,
  AiSettingsOptions,
} from "@/types/api";

const ROLE_TITLE: Record<AiRole, string> = {
  search: "Web search",
  reading: "Page reading",
};

const ROLE_BLURB: Record<AiRole, string> = {
  search: "Finds candidate pages for AI search. One active at a time.",
  reading:
    "Reads each captured page and extracts fields with an evidence quote. One active at a time.",
};

/** Which action is in flight, so the spinner lands on the button that was pressed. */
type Pending = { id: string; action: "activate" | "check" | "delete" } | null;

export function ProviderManager({
  initial,
  options,
}: {
  initial: AiProviderList | null;
  options: AiSettingsOptions | null;
}) {
  const router = useRouter();
  const [pending, setPending] = useState<Pending>(null);
  const [adding, setAdding] = useState<AiRole | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, startRefresh] = useTransition();

  const busy = pending !== null || saving || refreshing;
  const items = initial?.items ?? [];
  // Nothing can be saved before the table exists, so the controls that would try are
  // disabled rather than left to fail with a 503 after the key has been typed in.
  const notInstalled = initial?.installed === false;

  async function act(
    config: AiProviderConfig,
    action: "activate" | "check" | "delete",
  ) {
    setPending({ id: config.id, action });
    setError(null);
    setMessage(null);
    try {
      if (action === "delete") {
        const result = await clientFetch<{ detail: string }>(
          `/ai-settings/providers/${config.id}`,
          { method: "DELETE" },
        );
        setMessage(result.detail);
      } else if (action === "activate") {
        await clientFetch(`/ai-settings/providers/${config.id}/activate`, {
          method: "POST",
        });
        setMessage(
          `${config.label} is now doing ${ROLE_TITLE[config.role].toLowerCase()}.`,
        );
      } else {
        // One real call against the provider. Worth it: the alternative is finding out
        // an hour into a sweep, having already paid for the searches it made.
        const result = await clientFetch<{ ok: boolean; detail: string }>(
          `/ai-settings/providers/${config.id}/check`,
          { method: "POST" },
        );
        setMessage(`${config.label}: ${result.detail}`);
      }
      startRefresh(() => router.refresh());
    } catch (caught) {
      setError(describe(caught));
    } finally {
      setPending(null);
    }
  }

  async function add(role: AiRole, form: HTMLFormElement) {
    const data = new FormData(form);
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      await clientFetch("/ai-settings/providers", {
        method: "POST",
        body: {
          label: String(data.get("label") ?? "").trim(),
          provider: String(data.get("provider") ?? ""),
          role,
          api_key: String(data.get("api_key") ?? ""),
          model: String(data.get("model") ?? "").trim() || null,
          base_url: String(data.get("base_url") ?? "").trim() || null,
          activate: data.get("activate") === "on",
        },
      });
      setMessage("Added. The key is stored encrypted and cannot be read back.");
      setAdding(null);
      form.reset();
      startRefresh(() => router.refresh());
    } catch (caught) {
      setError(describe(caught));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-4">
      {error ? <ErrorState message={error} /> : null}
      {message ? <SuccessNote>{message}</SuccessNote> : null}

      {initial && initial.installed === false ? (
        <div className="space-y-2 rounded-lg border border-primary/30 bg-primary/[0.06] px-3 py-2.5">
          <p className="text-xs font-medium text-primary">
            One setup step first
          </p>
          <p className="text-2xs leading-relaxed text-muted-foreground">
            The table these settings live in has not been created yet. The
            application role has no permission to create tables — deliberately,
            so the running service cannot alter its own schema — so apply it as
            the database owner:
          </p>
          <div className="flex items-start gap-2">
            <pre className="min-w-0 flex-1 overflow-x-auto rounded border border-border bg-background px-2 py-1.5 text-2xs text-foreground">
              {initial.setup_command ?? initial.setup_hint}
            </pre>
            {initial.setup_command ? (
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  // Best effort: clipboard access is denied in some contexts, and a
                  // failed copy must not look like a failed action.
                  void navigator.clipboard
                    ?.writeText(initial.setup_command ?? "")
                    .then(() => setMessage("Command copied."))
                    .catch(() =>
                      setMessage(
                        "Could not copy — select the command instead.",
                      ),
                    );
                }}
              >
                <Copy />
                Copy
              </Button>
            ) : null}
          </div>
          <p className="text-2xs text-muted-foreground/70">
            Host and database are already filled in — replace{" "}
            <span className="font-mono text-foreground">OWNER:PASSWORD</span>{" "}
            with your database owner credentials. Not the ones in{" "}
            <span className="font-mono">.env</span>: those are the application
            role, which cannot create tables.
          </p>
        </div>
      ) : null}

      {initial && initial.installed !== false && !initial.ready ? (
        <div
          role="alert"
          className="rounded-lg border border-destructive/30 bg-destructive/[0.07] px-3 py-2.5 text-2xs leading-relaxed text-muted-foreground"
        >
          <span className="font-medium text-destructive">
            AI search cannot run yet.
          </span>{" "}
          It needs one active provider for each role — something to find pages
          and something to read them. A run started without both fails at the
          first stage.
        </div>
      ) : null}

      {(options?.roles ?? (["search", "reading"] as AiRole[])).map((role) => {
        const forRole = items.filter((item) => item.role === role);
        const allowed = options?.providers_by_role[role] ?? [];
        return (
          <Card key={role} className="overflow-hidden">
            <CardHeader>
              <CardTitle>{ROLE_TITLE[role]}</CardTitle>
              <div className="flex items-center gap-2">
                {initial?.active[role] ? (
                  <Badge variant="success">{initial.active[role]?.label}</Badge>
                ) : (
                  <Badge variant="destructive">none active</Badge>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy}
                  onClick={() => setAdding(adding === role ? null : role)}
                >
                  <Plus />
                  Add
                </Button>
              </div>
            </CardHeader>

            <p className="border-b border-border px-4 py-2 text-2xs text-muted-foreground">
              {ROLE_BLURB[role]}
            </p>

            {adding === role ? (
              <form
                className="grid gap-3 border-b border-border bg-accent/40 px-4 py-3 sm:grid-cols-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  void add(role, event.currentTarget);
                }}
              >
                <Field label="Name">
                  <Input
                    name="label"
                    required
                    placeholder="GPT-4o mini (cheap)"
                  />
                </Field>
                <Field label="Provider">
                  <select
                    name="provider"
                    required
                    defaultValue={allowed[0] ?? ""}
                    onChange={(event) => {
                      // Fill in that provider's default model, so an operator does not
                      // have to remember identifiers like "google/gemma-3-27b-it".
                      const form = event.currentTarget.form;
                      const field = form?.elements.namedItem("model");
                      if (field instanceof HTMLInputElement) {
                        field.value =
                          options?.default_models[event.currentTarget.value] ??
                          "";
                      }
                    }}
                    className="h-8 rounded-md border border-input bg-background px-2 text-xs focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                  >
                    {allowed.map((name) => (
                      <option key={name} value={name}>
                        {options?.labels[name] ?? name}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Model" hint="Leave empty for Parallel AI">
                  <Input
                    name="model"
                    defaultValue={
                      options?.default_models[allowed[0] ?? ""] ?? ""
                    }
                    placeholder="claude-sonnet-5"
                  />
                </Field>
                <Field
                  label="Base URL"
                  hint="Optional — for a gateway or region"
                >
                  <Input
                    name="base_url"
                    placeholder="https://api.openai.com/v1"
                  />
                </Field>
                <Field
                  label="API key"
                  hint={
                    notInstalled
                      ? "Wait until the migration has run — a key typed now cannot be stored."
                      : "Stored encrypted. It cannot be read back — only replaced."
                  }
                >
                  <Input
                    name="api_key"
                    type="password"
                    required
                    autoComplete="off"
                    placeholder="paste the key"
                  />
                </Field>
                <div className="flex items-end justify-between gap-3">
                  <label className="flex items-center gap-1.5 text-2xs text-muted-foreground">
                    <input
                      type="checkbox"
                      name="activate"
                      className="accent-primary"
                    />
                    Make it active now
                  </label>
                  <div className="flex items-center gap-2">
                    {notInstalled ? (
                      <span className="text-2xs text-destructive">
                        Run the migration above to enable saving
                      </span>
                    ) : null}
                    <Button
                      type="submit"
                      size="sm"
                      disabled={saving || notInstalled}
                    >
                      {saving ? <Loader2 className="animate-spin" /> : null}
                      {saving ? "Saving…" : "Save"}
                    </Button>
                  </div>
                </div>
              </form>
            ) : null}

            {forRole.length ? (
              <ul className="divide-y divide-border">
                {forRole.map((config) => (
                  <li
                    key={config.id}
                    className="flex flex-wrap items-center gap-2 px-4 py-2.5"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-xs text-foreground">
                          {config.label}
                        </span>
                        {config.is_active ? (
                          <Badge variant="success">active</Badge>
                        ) : null}
                        <CheckMark config={config} />
                      </div>
                      <p className="truncate text-2xs text-muted-foreground">
                        {options?.labels[config.provider] ?? config.provider}
                        {config.model ? ` · ${config.model}` : ""}
                        {config.key_hint ? ` · key ${config.key_hint}` : ""}
                      </p>
                      {config.last_check_detail ? (
                        <p
                          className={cn(
                            "truncate text-2xs",
                            config.last_check_ok
                              ? "text-conf-verified"
                              : "text-destructive",
                          )}
                        >
                          {config.last_check_detail}
                        </p>
                      ) : null}
                    </div>

                    <div className="flex items-center gap-1.5">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={busy}
                        onClick={() => void act(config, "check")}
                        title="Make one small real call to confirm the key works"
                      >
                        {pending?.id === config.id &&
                        pending.action === "check" ? (
                          <Loader2 className="animate-spin" />
                        ) : null}
                        Test
                      </Button>
                      {config.is_active ? null : (
                        <Button
                          size="sm"
                          disabled={busy}
                          onClick={() => void act(config, "activate")}
                        >
                          {pending?.id === config.id &&
                          pending.action === "activate" ? (
                            <Loader2 className="animate-spin" />
                          ) : (
                            <Zap />
                          )}
                          Use this
                        </Button>
                      )}
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={busy}
                        onClick={() => void act(config, "delete")}
                        title={
                          config.is_active
                            ? "Deleting the active provider leaves this role unfilled"
                            : "Delete"
                        }
                      >
                        {pending?.id === config.id &&
                        pending.action === "delete" ? (
                          <Loader2 className="animate-spin" />
                        ) : (
                          <Trash2 />
                        )}
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="px-4 py-6 text-center text-2xs text-muted-foreground">
                Nothing configured for {ROLE_TITLE[role].toLowerCase()} yet.
              </p>
            )}
          </Card>
        );
      })}
    </div>
  );
}

function CheckMark({ config }: { config: AiProviderConfig }) {
  if (config.last_check_ok === null) return null;
  // Wrapped: a Lucide icon takes no title, and the tooltip is the whole point of
  // showing a bare tick beside the name.
  return (
    <span
      title={config.last_check_ok ? "Last test passed" : "Last test failed"}
    >
      {config.last_check_ok ? (
        <CircleCheck className="size-3.5 shrink-0 text-conf-verified" />
      ) : (
        <CircleX className="size-3.5 shrink-0 text-destructive" />
      )}
    </span>
  );
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
    <div className="space-y-1">
      <Label>{label}</Label>
      {children}
      {hint ? (
        <p className="text-2xs text-muted-foreground/70">{hint}</p>
      ) : null}
    </div>
  );
}

/** Field-level validation from the API reads better than "Request failed". */
function describe(caught: unknown): string {
  if (caught instanceof ApiError) {
    if (caught.fieldErrors.length) {
      return caught.fieldErrors
        .map((entry) => `${entry.field}: ${entry.message}`)
        .join("; ");
    }
    return caught.message;
  }
  return caught instanceof Error ? caught.message : "Something went wrong";
}
