"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { CornerDownLeft, Search } from "lucide-react";

import {
  CommandDialog,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from "@/components/ui/command";
import { visibleSections } from "@/components/shell/nav-items";
import { clientFetch } from "@/lib/api-client";
import { pumpTypeCode, standardLabel } from "@/lib/labels";
import type { CurrentUser, SearchResponse } from "@/types/api";

const EM_DASH = "—";

/**
 * Command palette, opened with Cmd/Ctrl-K.
 *
 * In a tool people keep open all day, typing beats navigating. It searches pump models
 * live against the API and lists every screen the signed-in user is allowed to open, so
 * it doubles as the keyboard route to anywhere in the product.
 *
 * cmdk's own client-side filtering is switched off: the model list is already the
 * server's answer to the query, and re-filtering it locally would drop rows that matched
 * on a field the palette does not display. The screen list is filtered here instead.
 */
export function CommandPalette({ user }: { user: CurrentUser | null }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResponse["items"]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((current) => !current);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Debounced: a request per keystroke would hammer the search endpoint.
  useEffect(() => {
    const term = query.trim();
    if (!open || term.length < 2) {
      setResults([]);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    const timer = setTimeout(() => {
      clientFetch<SearchResponse>("/search", {
        method: "POST",
        body: { query: term, limit: 6, include_facets: false },
      })
        .then((response) => {
          if (!cancelled) setResults(response.items);
        })
        .catch(() => {
          if (!cancelled) setResults([]);
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 220);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query, open]);

  function go(href: string) {
    setOpen(false);
    setQuery("");
    router.push(href);
  }

  const term = query.trim().toLowerCase();

  const screens = useMemo(() => {
    const all = visibleSections(user).flatMap((section) =>
      section.items.map((item) => ({ ...item, section: section.heading })),
    );
    if (!term) return all;
    return all.filter(
      (screen) =>
        screen.label.toLowerCase().includes(term) ||
        screen.section.toLowerCase().includes(term),
    );
  }, [user, term]);

  const nothing = !loading && !results.length && !screens.length;

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex h-7 w-full max-w-sm items-center gap-2 rounded-md border border-input bg-background/60 px-2.5 text-left text-xs text-muted-foreground transition-colors hover:border-ring/50 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
      >
        <Search className="size-3.5 shrink-0" />
        <span className="flex-1 truncate">Search models, vendors, screens</span>
        <kbd className="hidden shrink-0 rounded border border-border bg-muted px-1 font-mono text-[0.625rem] leading-4 text-muted-foreground sm:block">
          ⌘K
        </kbd>
      </button>

      <CommandDialog open={open} onOpenChange={setOpen} shouldFilter={false}>
        <CommandInput
          value={query}
          onValueChange={setQuery}
          placeholder="Search pump models, or jump to a screen…"
        />
        <CommandList>
          {nothing ? (
            <p className="py-8 text-center text-xs text-muted-foreground">
              Nothing matched.
            </p>
          ) : null}

          {loading && !results.length ? (
            <p className="py-6 text-center text-xs text-muted-foreground">
              Searching…
            </p>
          ) : null}

          {results.length ? (
            <CommandGroup heading="Pump models">
              {results.map((row) => (
                <CommandItem
                  key={row.pump_model_id}
                  value={"model-" + row.pump_model_id}
                  onSelect={() => go("/pumps/" + row.pump_model_id)}
                >
                  <span className="font-mono text-foreground">
                    {row.model_code ?? row.label}
                  </span>
                  <span className="truncate text-muted-foreground">
                    {row.vendor_name}
                  </span>
                  <CommandShortcut>
                    {[
                      pumpTypeCode(row.pump_type),
                      standardLabel(row.applicable_standard),
                    ]
                      .filter((part) => part && part !== EM_DASH)
                      .join(" · ")}
                  </CommandShortcut>
                </CommandItem>
              ))}
            </CommandGroup>
          ) : null}

          {screens.length ? (
            <CommandGroup heading="Go to">
              {screens.map((screen) => {
                const Icon = screen.icon;
                return (
                  <CommandItem
                    key={screen.href}
                    value={"screen-" + screen.label}
                    onSelect={() => go(screen.href)}
                  >
                    <Icon />
                    <span className="text-foreground">{screen.label}</span>
                    <CommandShortcut>{screen.section}</CommandShortcut>
                  </CommandItem>
                );
              })}
            </CommandGroup>
          ) : null}

          {query.trim() ? (
            <CommandGroup heading="Full search">
              <CommandItem
                value="run-full-search"
                onSelect={() => go("/?q=" + encodeURIComponent(query.trim()))}
              >
                <CornerDownLeft />
                <span className="text-foreground">
                  Search all records for &ldquo;{query.trim()}&rdquo;
                </span>
              </CommandItem>
            </CommandGroup>
          ) : null}
        </CommandList>
      </CommandDialog>
    </>
  );
}
