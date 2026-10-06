import {
  ArrowLeftRight,
  BrainCircuit,
  Building2,
  Cog,
  Database,
  Download,
  FileClock,
  MessagesSquare,
  Search,
  ShieldCheck,
  Sparkles,
  Users,
  type LucideIcon,
} from "lucide-react";

import type { CurrentUser } from "@/types/api";

export type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  badgeKey?: string;
  /** Mirrors the API's own guard, so the nav never offers a screen that will 403. */
  needs?: [resource: string, action: string];
  platformAdminOnly?: boolean;
};

export type NavSection = { heading: string; items: NavItem[] };

const SECTIONS: NavSection[] = [
  {
    heading: "Intelligence",
    items: [
      { href: "/", label: "Search", icon: Search, needs: ["search", "read"] },
      {
        href: "/chat",
        label: "Ask",
        icon: MessagesSquare,
        needs: ["search", "read"],
      },
      { href: "/pumps", label: "Pumps", icon: Cog, needs: ["pump", "read"] },
      {
        href: "/vendors",
        label: "Vendors",
        icon: Building2,
        needs: ["vendor", "read"],
      },
      {
        href: "/compare",
        label: "Comparison",
        icon: ArrowLeftRight,
        needs: ["comparison", "read"],
      },
    ],
  },
  {
    heading: "Data operations",
    items: [
      {
        href: "/imports",
        label: "Import queue",
        icon: Download,
        needs: ["ingestion", "read"],
      },
      {
        href: "/review",
        label: "AI review",
        icon: Sparkles,
        badgeKey: "ai_review",
        needs: ["ai_review", "read"],
      },
      {
        href: "/quality",
        label: "Data quality",
        icon: ShieldCheck,
        badgeKey: "open_flags",
        needs: ["data_quality", "read"],
      },
    ],
  },
  {
    heading: "Governance",
    items: [
      {
        href: "/audit",
        label: "Audit trail",
        icon: FileClock,
        needs: ["audit", "read"],
      },
      {
        href: "/tenants",
        label: "Tenants",
        icon: Users,
        platformAdminOnly: true,
      },
      {
        href: "/ai-settings",
        label: "AI settings",
        icon: BrainCircuit,
        platformAdminOnly: true,
      },
      {
        href: "/admin/database",
        label: "Database",
        icon: Database,
        platformAdminOnly: true,
      },
    ],
  },
];

function permits(user: CurrentUser | null, item: NavItem): boolean {
  if (item.platformAdminOnly) return user?.is_platform_admin === true;
  if (!item.needs) return true;
  if (user?.is_platform_admin) return true;
  const [resource, action] = item.needs;
  return user?.permissions?.[resource]?.includes(action) === true;
}

/**
 * The nav this user can actually use.
 *
 * An entry that always 403s is worse than no entry: it reads as a broken product rather
 * than as a permission the user does not hold.
 */
export function visibleSections(user: CurrentUser | null): NavSection[] {
  return SECTIONS.map((section) => ({
    ...section,
    items: section.items.filter((item) => permits(user, item)),
  })).filter((section) => section.items.length > 0);
}
