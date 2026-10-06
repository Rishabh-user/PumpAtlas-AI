import Link from "next/link";
import { DatabaseZap } from "lucide-react";

import { Button } from "@/components/ui/button";

export const metadata = { title: "Not found" };

export default function NotFound() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-6">
      <div className="w-full max-w-md text-center">
        <span className="mx-auto grid size-10 place-items-center rounded-lg border border-primary/25 bg-primary/10 text-primary">
          <DatabaseZap className="size-5" />
        </span>
        <p className="label-xs mt-4">404</p>
        <h1 className="mt-1 text-base font-semibold tracking-tight text-foreground">
          Record not found
        </h1>
        <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
          It may have been merged into another record, soft-deleted, or it
          belongs to a different tenant than the one you are signed in to.
        </p>
        <Button asChild className="mt-6">
          <Link href="/">Back to search</Link>
        </Button>
      </div>
    </div>
  );
}
