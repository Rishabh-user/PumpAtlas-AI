"use client";

import { useState } from "react";

import { SpecForm, SpecFormToggle } from "@/components/pumps/spec-form";

/**
 * The "enter data" affordance on a specification panel.
 *
 * Only this part is a client component. The panels themselves render on the server,
 * which is why the form could not simply live inside them.
 */
export function SpecPanelEditor({
  pumpModelId,
  group,
  groupLabel,
  headlineFields,
  current,
  empty = false,
}: {
  pumpModelId: string;
  group: string;
  groupLabel: string;
  headlineFields: string[];
  current: Record<string, unknown> | null;
  /** An empty panel leads with the invitation; a populated one offers a quiet edit. */
  empty?: boolean;
}) {
  const [open, setOpen] = useState(false);

  if (!open) {
    return (
      <div className={empty ? "pb-3 text-center" : "border-t border-border px-3 py-2"}>
        <SpecFormToggle
          open={false}
          onToggle={() => setOpen(true)}
          label={empty ? `Enter ${groupLabel.toLowerCase()} data` : "Add or correct values"}
        />
      </div>
    );
  }

  return (
    <div className="border-t border-border">
      <div className="flex items-center justify-between px-3 pt-2">
        <span className="label-xs text-muted-foreground">
          {groupLabel} — typed by hand, recorded against you
        </span>
        <SpecFormToggle open onToggle={() => setOpen(false)} />
      </div>
      <SpecForm
        pumpModelId={pumpModelId}
        group={group}
        groupLabel={groupLabel}
        headlineFields={headlineFields}
        current={current}
        onDone={() => setOpen(false)}
      />
    </div>
  );
}
