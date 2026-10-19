"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { BadgeCheck, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { clientFetch } from "@/lib/api-client";

/**
 * Confirm a record by hand, and mean it.
 *
 * AI findings are written straight onto the record now, flagged AI-extracted and
 * unverified. This is the other half of that: a person says "I have checked this",
 * and from then on an enrichment run is refused permission to overwrite those fields.
 *
 * That refusal is the point and it did not previously work. The old endpoint set
 * `verification_status` on the row, while the guard that refuses an AI write reads
 * `field_provenance.confidence_level` — so 65 pump models sat badged "verified" with
 * zero protected fields between them, and the endpoint's own message promised
 * otherwise.
 */
export function VerifyButton({
  endpoint,
  verified,
  label = "Mark verified",
}: {
  /** e.g. `/pump-models/{id}/verify` or `/vendors/{id}/verify` */
  endpoint: string;
  verified: boolean;
  label?: string;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (verified && !done) {
    return (
      <span className="inline-flex items-center gap-1 text-2xs text-conf-verified">
        <BadgeCheck className="size-3.5" />
        Verified — AI runs cannot overwrite these fields
      </span>
    );
  }

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      const result = await clientFetch<{ detail: string }>(endpoint, {
        method: "POST",
      });
      setDone(result.detail);
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not verify");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        variant="outline"
        size="sm"
        disabled={busy}
        onClick={() => void confirm()}
      >
        {busy ? <Loader2 className="animate-spin" /> : <BadgeCheck />}
        {busy ? "Verifying…" : label}
      </Button>
      {done ? (
        <span className="text-2xs text-conf-verified">{done}</span>
      ) : null}
      {error ? <span className="text-2xs text-destructive">{error}</span> : null}
    </div>
  );
}
