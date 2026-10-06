"use client";

import { useState } from "react";
import Link from "next/link";
import { Database, LogOut, Menu } from "lucide-react";

import { ByTargeticon, LogoMark, Wordmark } from "@/components/brand";
import { CommandPalette } from "@/components/shell/command-palette";
import { RailLabelled } from "@/components/shell/rail";
import { ThemeToggle } from "@/components/shell/theme-toggle";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Sheet,
  SheetContent,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import type { CurrentUser } from "@/types/api";

/** Initials for the avatar. Falls back to the email when there is no full name. */
function initials(user: CurrentUser): string {
  const source = user.full_name?.trim() || user.email;
  const parts = source.split(/[\s@._-]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}

export function Topbar({
  user,
  counts,
}: {
  user: CurrentUser | null;
  counts?: Record<string, number>;
}) {
  const [navOpen, setNavOpen] = useState(false);

  const roleLabel = user?.is_platform_admin
    ? "Platform administrator"
    : (user?.roles?.[0]?.display_name ?? "");

  return (
    <header className="fixed inset-x-0 top-0 z-20 flex h-topbar items-center gap-2 border-b border-border bg-card px-3 lg:left-rail">
      <Sheet open={navOpen} onOpenChange={setNavOpen}>
        <SheetTrigger asChild>
          <Button
            variant="ghost"
            size="icon-sm"
            className="lg:hidden"
            aria-label="Open navigation"
          >
            <Menu />
          </Button>
        </SheetTrigger>
        <SheetContent side="left" hideClose className="p-0">
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <div className="flex h-topbar shrink-0 items-center gap-2 border-b border-border px-3">
            <LogoMark className="size-5 text-primary" />
            <Wordmark />
          </div>
          <RailLabelled
            user={user}
            counts={counts}
            onNavigate={() => setNavOpen(false)}
          />
          <div className="border-t border-border px-3 py-2.5">
            <ByTargeticon />
          </div>
        </SheetContent>
      </Sheet>

      <Wordmark className="mr-1 lg:hidden" />

      <CommandPalette user={user} />

      <div className="ml-auto flex items-center gap-1.5">
        {user?.tenant_name ? (
          <Badge
            variant="outline"
            className="hidden md:inline-flex"
            title="Every record on screen is scoped to this organisation"
          >
            <Database />
            {user.tenant_name}
          </Badge>
        ) : null}

        <ThemeToggle />

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="flex items-center gap-2 rounded-md px-1 py-1 transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
            >
              <Avatar>
                <AvatarFallback>{user ? initials(user) : "?"}</AvatarFallback>
              </Avatar>
              <span className="hidden text-left leading-tight md:block">
                <span className="block text-2xs font-medium text-foreground">
                  {user?.full_name ?? "Signed in"}
                </span>
                <span className="block text-[0.625rem] leading-3 text-muted-foreground">
                  {roleLabel}
                </span>
              </span>
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <div className="px-2 py-1.5">
              <p className="truncate text-xs font-medium text-foreground">
                {user?.full_name ?? "—"}
              </p>
              <p className="truncate text-2xs text-muted-foreground">
                {user?.email}
              </p>
              {user?.job_title ? (
                <p className="mt-0.5 truncate text-2xs text-muted-foreground">
                  {user.job_title}
                </p>
              ) : null}
            </div>
            <DropdownMenuSeparator />
            <DropdownMenuLabel>Roles</DropdownMenuLabel>
            <div className="flex flex-wrap gap-1 px-2 pb-2">
              {(user?.roles ?? []).map((role) => (
                <Badge key={role.name} variant="secondary">
                  {role.display_name}
                </Badge>
              ))}
              {user?.is_platform_admin ? <Badge>Platform admin</Badge> : null}
            </div>
            <DropdownMenuSeparator />
            <form action="/api/auth/logout" method="post">
              <DropdownMenuItem asChild>
                <button type="submit" className="w-full">
                  <LogOut />
                  Sign out
                </button>
              </DropdownMenuItem>
            </form>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}

/** Used by the login screen, which has no shell around it. */
export function TopbarBrandOnly() {
  return (
    <div className="flex items-center gap-2">
      <LogoMark className="size-5 text-primary" />
      <Link href="/">
        <Wordmark />
      </Link>
    </div>
  );
}
