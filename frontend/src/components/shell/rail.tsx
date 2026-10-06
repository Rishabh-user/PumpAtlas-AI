"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { LogoMark } from "@/components/brand";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { visibleSections, type NavSection } from "@/components/shell/nav-items";
import { cn } from "@/lib/utils";
import type { CurrentUser } from "@/types/api";

/**
 * Icon rail.
 *
 * The nav is eight destinations that never change, so it costs a strip of icons rather
 * than a 232px column of labels — that width is worth more to a 34-column results grid.
 * Every icon carries a tooltip and an aria-label, and the sections stay visually
 * separated by a rule so the grouping survives the loss of the headings.
 *
 * This is a client component so the icon *components* never cross a server boundary:
 * `user` is plain JSON and serialises fine, a Lucide component does not.
 */
export function Rail({
  user,
  counts,
}: {
  user: CurrentUser | null;
  counts?: Record<string, number>;
}) {
  const pathname = usePathname();
  const sections: NavSection[] = visibleSections(user);

  return (
    <nav
      aria-label="Main"
      className="fixed inset-y-0 left-0 z-30 hidden w-rail flex-col items-center border-r border-border bg-card lg:flex"
    >
      <Link
        href="/"
        aria-label="PumpAtlas AI home"
        className="flex h-topbar w-full shrink-0 items-center justify-center border-b border-border text-primary"
      >
        <LogoMark className="size-5" />
      </Link>

      <div className="flex w-full flex-1 flex-col items-center gap-1 overflow-y-auto py-2">
        {sections.map((section, sectionIndex) => (
          <div
            key={section.heading}
            className="flex w-full flex-col items-center gap-1"
          >
            {sectionIndex > 0 ? (
              <span className="my-1 h-px w-5 bg-border" />
            ) : null}
            {section.items.map((item) => {
              const active =
                item.href === "/"
                  ? pathname === "/"
                  : pathname.startsWith(item.href);
              const Icon = item.icon;
              const badge = item.badgeKey ? counts?.[item.badgeKey] : undefined;
              return (
                <Tooltip key={item.href} delayDuration={200}>
                  <TooltipTrigger asChild>
                    <Link
                      href={item.href}
                      aria-label={item.label}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "relative grid size-9 place-items-center rounded-md transition-colors",
                        active
                          ? "bg-primary/15 text-primary"
                          : "text-muted-foreground hover:bg-accent hover:text-foreground",
                      )}
                    >
                      <Icon className="size-[1.05rem]" />
                      {active ? (
                        <span className="absolute -left-2 h-4 w-0.5 rounded-full bg-primary" />
                      ) : null}
                      {badge ? (
                        <span className="absolute -right-0.5 -top-0.5 grid min-w-3.5 place-items-center rounded-full bg-sev-medium px-1 font-mono text-[0.5625rem] font-bold leading-[0.875rem] text-background">
                          {badge > 9 ? "9+" : badge}
                        </span>
                      ) : null}
                    </Link>
                  </TooltipTrigger>
                  <TooltipContent side="right">
                    {item.label}
                    {badge ? (
                      <span className="ml-1.5 text-sev-medium">
                        {badge} open
                      </span>
                    ) : null}
                  </TooltipContent>
                </Tooltip>
              );
            })}
          </div>
        ))}
      </div>
    </nav>
  );
}

/** The same nav with labels, for the mobile sheet where there is room for them. */
export function RailLabelled({
  user,
  counts,
  onNavigate,
}: {
  user: CurrentUser | null;
  counts?: Record<string, number>;
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  const sections: NavSection[] = visibleSections(user);

  return (
    <nav aria-label="Main" className="flex-1 overflow-y-auto p-2">
      {sections.map((section) => (
        <div key={section.heading} className="mb-4">
          <p className="label-xs px-2 pb-1">{section.heading}</p>
          <ul className="space-y-0.5">
            {section.items.map((item) => {
              const active =
                item.href === "/"
                  ? pathname === "/"
                  : pathname.startsWith(item.href);
              const Icon = item.icon;
              const badge = item.badgeKey ? counts?.[item.badgeKey] : undefined;
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    onClick={onNavigate}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "flex items-center gap-2.5 rounded-md px-2 py-1.5 text-xs transition-colors",
                      active
                        ? "bg-primary/15 font-medium text-primary"
                        : "text-muted-foreground hover:bg-accent hover:text-foreground",
                    )}
                  >
                    <Icon className="size-4 shrink-0" />
                    <span className="flex-1 truncate">{item.label}</span>
                    {badge ? (
                      <span className="rounded bg-sev-medium/15 px-1.5 font-mono text-2xs font-semibold text-sev-medium">
                        {badge}
                      </span>
                    ) : null}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}
