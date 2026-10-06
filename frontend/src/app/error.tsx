"use client";

import { CircleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-6">
      <div className="w-full max-w-md text-center">
        <span className="mx-auto grid size-10 place-items-center rounded-lg border border-destructive/30 bg-destructive/10 text-destructive">
          <CircleAlert className="size-5" />
        </span>
        <h1 className="mt-4 text-base font-semibold tracking-tight text-foreground">
          Something went wrong
        </h1>
        <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
          {error.message}
        </p>
        {error.digest ? (
          <p className="mt-2 font-mono text-[0.625rem] text-muted-foreground/70">
            Reference {error.digest}
          </p>
        ) : null}
        <div className="mt-6 flex items-center justify-center gap-1.5">
          <Button onClick={reset}>Try again</Button>
          <Button variant="outline" asChild>
            <a href="/">Back to search</a>
          </Button>
        </div>
      </div>
    </div>
  );
}
