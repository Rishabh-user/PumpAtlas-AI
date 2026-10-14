"use client";

import { useState } from "react";
import { Check, KeyRound, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { clientFetch } from "@/lib/api-client";

/** The API's own rule, mirrored here so the message arrives before the request does. */
const MIN_CHARS = 12;

/**
 * Change your own password.
 *
 * The API has accepted `POST /auth/change-password` all along and nothing called it, so
 * the only way to change a password was a shell on the server with the database
 * credentials to hand. That is a poor reason to hand out database access, and it is why
 * the administrator account kept its published default long after anyone wanted it gone.
 *
 * The current password is required by the endpoint, not just as a formality: it is what
 * stops a borrowed session from locking the owner out of their own account.
 */
export function ChangePassword() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Checked before the request so the reason is immediate, and again by the API so a
  // client that skips this cannot set a weak one anyway.
  const tooShort = next.length > 0 && next.length < MIN_CHARS;
  const mismatch = confirm.length > 0 && next !== confirm;
  const unchanged = next.length > 0 && next === current;
  const ready =
    current.length > 0 &&
    next.length >= MIN_CHARS &&
    next === confirm &&
    next !== current &&
    !saving;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await clientFetch("/auth/change-password", {
        method: "POST",
        body: { current_password: current, new_password: next },
      });
      setDone(true);
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Could not change the password",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="max-w-sm space-y-3">
      <label className="block">
        <span className="label-xs text-muted-foreground">Current password</span>
        <Input
          type="password"
          autoComplete="current-password"
          value={current}
          onChange={(event) => {
            setCurrent(event.target.value);
            setDone(false);
          }}
          className="mt-0.5"
        />
      </label>

      <label className="block">
        <span className="label-xs text-muted-foreground">New password</span>
        <Input
          type="password"
          autoComplete="new-password"
          value={next}
          onChange={(event) => {
            setNext(event.target.value);
            setDone(false);
          }}
          className="mt-0.5"
        />
        <span className="mt-0.5 block text-[0.625rem] text-muted-foreground">
          At least {MIN_CHARS} characters. A long phrase beats a short, clever one.
        </span>
      </label>

      <label className="block">
        <span className="label-xs text-muted-foreground">Confirm new password</span>
        <Input
          type="password"
          autoComplete="new-password"
          value={confirm}
          onChange={(event) => setConfirm(event.target.value)}
          className="mt-0.5"
        />
      </label>

      {tooShort ? (
        <p className="text-2xs text-destructive">
          {MIN_CHARS - next.length} more character
          {MIN_CHARS - next.length === 1 ? "" : "s"} needed.
        </p>
      ) : null}
      {mismatch ? (
        <p className="text-2xs text-destructive">The two entries differ.</p>
      ) : null}
      {unchanged ? (
        <p className="text-2xs text-destructive">
          The new password must differ from the current one.
        </p>
      ) : null}
      {error ? <p className="text-2xs text-destructive">{error}</p> : null}
      {done ? (
        <p className="flex items-center gap-1.5 text-2xs text-conf-verified">
          <Check className="size-3" />
          Password changed. It applies the next time you sign in.
        </p>
      ) : null}

      <Button type="submit" size="sm" disabled={!ready}>
        {saving ? <Loader2 className="animate-spin" /> : <KeyRound />}
        {saving ? "Changing…" : "Change password"}
      </Button>
    </form>
  );
}
