import {
  AlertTriangle,
  Info,
  ShieldAlert,
  ShieldX,
  TriangleAlert,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { confidenceLabel, humanise } from "@/lib/labels";
import type { ConfidenceLevel, FlagSeverity } from "@/types/api";

/*
 * Confidence and severity are the two fields a buyer leans on hardest, so neither is
 * ever expressed by colour alone: both carry a shape or a label a colour-blind reader
 * and a monochrome print both survive.
 */

const CONFIDENCE_CLASS: Record<ConfidenceLevel, string> = {
  verified: "border-conf-verified/30 bg-conf-verified/10 text-conf-verified",
  vendor_declared:
    "border-conf-declared/30 bg-conf-declared/10 text-conf-declared",
  third_party:
    "border-conf-thirdparty/30 bg-conf-thirdparty/10 text-conf-thirdparty",
  ai_extracted: "border-conf-ai/30 bg-conf-ai/10 text-conf-ai",
  estimated:
    "border-conf-estimated/30 bg-conf-estimated/10 text-conf-estimated",
  unknown: "border-conf-unknown/25 bg-conf-unknown/10 text-conf-unknown",
};

export function ConfidenceChip({
  level,
  className,
}: {
  level: ConfidenceLevel | null | undefined;
  className?: string;
}) {
  const key = (level ?? "unknown") as ConfidenceLevel;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded border px-1.5 py-px text-2xs font-medium leading-4 whitespace-nowrap",
        CONFIDENCE_CLASS[key] ?? CONFIDENCE_CLASS.unknown,
        className,
      )}
    >
      <span className="size-1.5 shrink-0 rounded-full bg-current" />
      {confidenceLabel(key)}
    </span>
  );
}

const SEVERITY: Record<FlagSeverity, { className: string; Icon: typeof Info }> =
  {
    info: {
      className: "border-sev-info/25 bg-sev-info/10 text-sev-info",
      Icon: Info,
    },
    low: {
      className: "border-sev-low/30 bg-sev-low/10 text-sev-low",
      Icon: Info,
    },
    medium: {
      className: "border-sev-medium/30 bg-sev-medium/10 text-sev-medium",
      Icon: AlertTriangle,
    },
    high: {
      className: "border-sev-high/30 bg-sev-high/10 text-sev-high",
      Icon: ShieldAlert,
    },
    critical: {
      className: "border-sev-critical/30 bg-sev-critical/10 text-sev-critical",
      Icon: ShieldX,
    },
  };

export function SeverityChip({
  severity,
  className,
}: {
  severity: FlagSeverity;
  className?: string;
}) {
  const entry = SEVERITY[severity] ?? {
    className: "border-border text-muted-foreground",
    Icon: TriangleAlert,
  };
  const { Icon } = entry;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded border px-1.5 py-px text-2xs font-medium leading-4 whitespace-nowrap",
        entry.className,
        className,
      )}
    >
      <Icon className="size-3 shrink-0" />
      {humanise(severity)}
    </span>
  );
}
