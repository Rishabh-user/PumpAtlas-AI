import { Rail } from "@/components/shell/rail";
import { Topbar } from "@/components/shell/topbar";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { CurrentUser } from "@/types/api";

/**
 * The chrome every signed-in screen sits inside.
 *
 * Rendered on the server so the identity and the nav badge counts arrive with the first
 * paint — chrome that pops in after hydration is most of what makes an app feel like an
 * admin panel rather than a product.
 */
export function AppShell({
  user,
  counts,
  children,
  fullBleed = false,
}: {
  user: CurrentUser | null;
  counts?: Record<string, number>;
  children: React.ReactNode;
  /**
   * Drop the centred, padded content column.
   *
   * Almost every screen is a document and wants that column. A screen that owns
   * its own full height and manages its own scrolling — the chat, with its
   * history rail and pinned composer — cannot live inside a wrapper that pads it
   * and lets the page scroll instead.
   */
  fullBleed?: boolean;
}) {
  return (
    <TooltipProvider>
      <Rail user={user} counts={counts} />
      <Topbar user={user} counts={counts} />
      <main className={fullBleed ? "pt-topbar lg:pl-rail" : "min-h-screen pt-topbar lg:pl-rail"}>
        {fullBleed ? (
          children
        ) : (
          <div className="mx-auto max-w-content px-3 py-4 sm:px-4 lg:px-5">
            {children}
          </div>
        )}
      </main>
    </TooltipProvider>
  );
}
