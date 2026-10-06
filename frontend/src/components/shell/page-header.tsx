import Link from "next/link";
import { ChevronRight } from "lucide-react";

export type Crumb = { label: string; href?: string };

/**
 * One heading treatment for every screen: breadcrumbs, title, lede, and a slot for the
 * primary action. Consistency here is most of what separates a product from a set of
 * pages that happen to share a stylesheet.
 */
export function PageHeader({
  title,
  lede,
  crumbs,
  actions,
  meta,
}: {
  title: string;
  lede?: string;
  crumbs?: Crumb[];
  actions?: React.ReactNode;
  meta?: React.ReactNode;
}) {
  return (
    <header className="mb-4">
      {crumbs?.length ? (
        <nav
          aria-label="Breadcrumb"
          className="mb-1.5 flex items-center gap-1 text-2xs"
        >
          {crumbs.map((crumb, index) => (
            <span
              key={crumb.label + String(index)}
              className="flex items-center gap-1"
            >
              {index > 0 ? (
                <ChevronRight className="size-3 shrink-0 text-muted-foreground/50" />
              ) : null}
              {crumb.href ? (
                <Link
                  href={crumb.href}
                  className="text-muted-foreground transition-colors hover:text-primary"
                >
                  {crumb.label}
                </Link>
              ) : (
                <span className="text-foreground/70">{crumb.label}</span>
              )}
            </span>
          ))}
        </nav>
      ) : null}

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-lg font-semibold tracking-tight text-foreground">
            {title}
          </h1>
          {lede ? (
            <p className="mt-1 max-w-3xl text-xs leading-relaxed text-muted-foreground">
              {lede}
            </p>
          ) : null}
          {meta ? (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              {meta}
            </div>
          ) : null}
        </div>
        {actions ? (
          <div className="flex shrink-0 items-center gap-1.5">{actions}</div>
        ) : null}
      </div>
    </header>
  );
}
