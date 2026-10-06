"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AtSign, Check, Loader2, Phone, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { clientFetch } from "@/lib/api-client";
import type { VendorContactDetails, VendorContactSighting } from "@/types/api";

/**
 * Contact details seen on the captured pages that are not recorded yet.
 *
 * What the company's own site states about itself is recorded automatically, each
 * contact carrying the page it was read from — so those appear in the list above, not
 * here. What lands here is the remainder, which is mostly details belonging to somebody
 * else: a supplier's page routinely lists its distributors, and one Amarinth page
 * carried a partner's address and a Brazilian number. Writing those onto Amarinth would
 * put another company's switchboard in this company's file.
 *
 * So these stay a person's decision, which the audit log captures. The panel disappears
 * once there is nothing left to judge.
 */
export function ContactDetails({
  vendorId,
  details,
}: {
  vendorId: string;
  details: VendorContactDetails;
}) {
  const router = useRouter();
  const [saving, setSaving] = useState<string | null>(null);
  const [saved, setSaved] = useState<string[]>([]);
  const [failed, setFailed] = useState<string | null>(null);

  const items = [...details.emails, ...details.phones];
  if (!items.length) return null;

  const anyOffDomain = items.some((item) => !item.seen_on.same_domain);

  async function record(item: VendorContactSighting, kind: "email" | "phone") {
    setSaving(item.value);
    setFailed(null);
    try {
      await clientFetch(`/vendors/${vendorId}/contacts`, {
        method: "POST",
        body: {
          contact_role: "commercial",
          full_name: "General enquiries",
          [kind]: item.value,
        },
      });
      setSaved((current) => [...current, item.value]);
      router.refresh();
    } catch (caught) {
      setFailed(
        caught instanceof Error
          ? caught.message
          : "Could not record that contact",
      );
    } finally {
      setSaving(null);
    }
  }

  return (
    <div className="mt-2 border-t border-border pt-2">
      <p className="label-xs text-muted-foreground">
        Also found, not recorded
      </p>
      <p className="mt-0.5 text-[0.625rem] leading-relaxed text-muted-foreground">
        {anyOffDomain
          ? "These were read from pages belonging to other companies — usually distributors and agents. Add the ones that really are this company's."
          : "Read from the captured pages and not recorded yet. Add the ones that belong."}
      </p>

      <ul className="mt-1.5 space-y-1">
        {details.emails.map((item) => (
          <Sighting
            key={item.value}
            item={item}
            icon={<AtSign className="size-3 shrink-0 text-muted-foreground" />}
            saving={saving === item.value}
            saved={saved.includes(item.value)}
            onRecord={() => void record(item, "email")}
          />
        ))}
        {details.phones.map((item) => (
          <Sighting
            key={item.value}
            item={item}
            icon={<Phone className="size-3 shrink-0 text-muted-foreground" />}
            saving={saving === item.value}
            saved={saved.includes(item.value)}
            onRecord={() => void record(item, "phone")}
          />
        ))}
      </ul>

      {failed ? (
        <p className="mt-1 text-[0.625rem] text-destructive">{failed}</p>
      ) : null}
    </div>
  );
}

function Sighting({
  item,
  icon,
  saving,
  saved,
  onRecord,
}: {
  item: VendorContactSighting;
  icon: React.ReactNode;
  saving: boolean;
  saved: boolean;
  onRecord: () => void;
}) {
  return (
    <li className="flex items-center gap-1.5 text-2xs">
      {icon}
      <span className="font-mono text-foreground">{item.value}</span>
      {item.seen_on.url ? (
        <a
          href={item.seen_on.url}
          target="_blank"
          rel="noreferrer noopener"
          className="truncate text-[0.625rem] text-muted-foreground hover:text-primary hover:underline"
          title={
            item.seen_on.same_domain
              ? item.seen_on.url
              : `Another company's page: ${item.seen_on.url}`
          }
        >
          {hostOf(item.seen_on.url)}
        </a>
      ) : null}
      <span className="ml-auto">
        {saved ? (
          <span className="flex items-center gap-1 text-[0.625rem] text-conf-verified">
            <Check className="size-3" />
            Recorded
          </span>
        ) : (
          <Button
            size="sm"
            variant="ghost"
            disabled={saving}
            onClick={onRecord}
          >
            {saving ? <Loader2 className="animate-spin" /> : <Plus />}
            Add
          </Button>
        )}
      </span>
    </li>
  );
}

function hostOf(url: string): string {
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return url;
  }
}
