"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Check, Loader2, ShieldCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { clientFetch } from "@/lib/api-client";
import { approvalLabel } from "@/lib/labels";
import { dateOnly, text } from "@/lib/format";

/** The decisions a buyer can record, in the order a supplier moves through them. */
const STATUSES = [
  "pending_qualification",
  "under_review",
  "conditionally_approved",
  "approved",
  "not_approved",
  "suspended",
  "blacklisted",
] as const;

const APPROVALS = new Set(["approved", "conditionally_approved"]);

/**
 * Whether this supplier may be used, and who decided.
 *
 * `approval_status` was readable everywhere — a badge above, a filter on the vendor
 * list, a column in search — and settable nowhere. No screen wrote it, so every record
 * sat at "Pending qualification" unless the extractor had written a supplier's own claim
 * into it: one record read "Approved" because its website used the word, another because
 * it quoted an ISO 9001 certificate, which is a quality certification and not an
 * approval to supply. Neither had an approver or an expiry.
 *
 * So the decision is made here, by a person, with a reason that is stored as the
 * evidence behind the status — the same gate every other value on this page passes. What
 * the supplier claims about itself is kept separately, as a claim.
 */
export function QualificationPanel({
  vendorId,
  status,
  expiry,
  approvedBy,
  claims,
}: {
  vendorId: string;
  status: string | null;
  expiry: string | null;
  approvedBy: string | null;
  /** What the supplier's own pages said, kept as claims rather than as our status. */
  claims?: Record<string, { value?: unknown; quote?: string | null }> | null;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [choice, setChoice] = useState(status ?? "pending_qualification");
  const [expires, setExpires] = useState(expiry ? expiry.slice(0, 10) : "");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const claimEntries = Object.entries(claims ?? {});

  async function submit() {
    setSaving(true);
    setFailed(null);
    try {
      await clientFetch(`/vendors/${vendorId}/qualification`, {
        method: "POST",
        body: {
          approval_status: choice,
          approval_expiry: APPROVALS.has(choice) && expires ? expires : null,
          note,
        },
      });
      setDone(true);
      setOpen(false);
      setNote("");
      router.refresh();
    } catch (caught) {
      setFailed(
        caught instanceof Error
          ? caught.message
          : "Could not record that decision",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mt-2 border-t border-border pt-2">
      <div className="flex items-center gap-2">
        <ShieldCheck className="size-3.5 shrink-0 text-muted-foreground" />
        <span className="text-xs text-foreground">
          {approvalLabel(status)}
        </span>
        {expiry ? (
          <span className="text-[0.625rem] text-muted-foreground">
            until {dateOnly(expiry)}
          </span>
        ) : null}
        {approvedBy ? null : APPROVALS.has(status ?? "") ? (
          <Badge variant="warning">No approver recorded</Badge>
        ) : null}
        <span className="ml-auto">
          <Button size="sm" variant="ghost" onClick={() => setOpen(!open)}>
            {done ? <Check className="size-3" /> : null}
            {open ? "Cancel" : "Change"}
          </Button>
        </span>
      </div>

      {/* What the supplier says about itself. Worth knowing, and not the same thing as
       * this organisation's decision, so it is shown apart from it. */}
      {claimEntries.length ? (
        <div className="mt-1.5 rounded-sm bg-muted/40 px-2 py-1.5">
          <p className="label-xs text-muted-foreground">
            Claimed by the supplier
          </p>
          {claimEntries.map(([field, claim]) => (
            <p
              key={field}
              className="mt-0.5 text-[0.625rem] leading-relaxed text-muted-foreground"
            >
              <span className="text-foreground">
                {approvalLabel(String(claim?.value ?? ""))}
              </span>
              {claim?.quote ? ` — “${text(claim.quote)}”` : ""}
            </p>
          ))}
        </div>
      ) : null}

      {open ? (
        <div className="mt-2 space-y-2">
          <label className="block">
            <span className="label-xs text-muted-foreground">Decision</span>
            <select
              className="mt-0.5 w-full rounded-sm border border-border bg-background px-2 py-1 text-xs"
              value={choice}
              onChange={(event) => setChoice(event.target.value)}
            >
              {STATUSES.map((value) => (
                <option key={value} value={value}>
                  {approvalLabel(value)}
                </option>
              ))}
            </select>
          </label>

          {APPROVALS.has(choice) ? (
            <label className="block">
              <span className="label-xs text-muted-foreground">
                Requalify by
              </span>
              <input
                type="date"
                className="mt-0.5 w-full rounded-sm border border-border bg-background px-2 py-1 text-xs"
                value={expires}
                onChange={(event) => setExpires(event.target.value)}
              />
            </label>
          ) : null}

          <label className="block">
            <span className="label-xs text-muted-foreground">
              Reason (stored as the evidence for this status)
            </span>
            <textarea
              rows={3}
              className="mt-0.5 w-full rounded-sm border border-border bg-background px-2 py-1 text-xs"
              placeholder="Audited 12 Aug; API 610 11th ed. certificate on file; two FPSO references checked."
              value={note}
              onChange={(event) => setNote(event.target.value)}
            />
          </label>

          <Button
            size="sm"
            disabled={saving || note.trim().length < 8}
            onClick={() => void submit()}
          >
            {saving ? <Loader2 className="animate-spin" /> : null}
            Record decision
          </Button>
          {note.trim().length < 8 ? (
            <p className="text-[0.625rem] text-muted-foreground">
              A decision needs a reason somebody can defend in a tender review.
            </p>
          ) : null}
        </div>
      ) : null}

      {failed ? (
        <p className="mt-1 text-[0.625rem] text-destructive">{failed}</p>
      ) : null}
    </div>
  );
}
