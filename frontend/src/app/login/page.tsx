import { CircleCheck, FileText, ShieldHalf } from "lucide-react";

import { ByTargeticon, WordmarkLarge } from "@/components/brand";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export const metadata = { title: "Sign in" };

const ASSURANCES = [
  {
    Icon: FileText,
    title: "Every value carries its source",
    body: "Each field records where it came from, who confirmed it and when — vendor datasheet, third-party report or AI extraction.",
  },
  {
    Icon: ShieldHalf,
    title: "Your data stays yours",
    body: "Tenant isolation is enforced in PostgreSQL itself, not in application code, so one client can never read another.",
  },
  {
    Icon: CircleCheck,
    title: "Nothing is published unreviewed",
    body: "AI-extracted candidates wait in a review queue with verbatim quotes until a person accepts them.",
  },
];

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const { error } = await searchParams;

  return (
    <div className="grid min-h-screen lg:grid-cols-[1fr_26rem]">
      {/* The pitch. Hidden on small screens so the form is never below the fold on a
          phone in a plant. */}
      <aside className="relative hidden flex-col justify-between overflow-hidden border-r border-border bg-card p-10 lg:flex">
        <div
          aria-hidden
          className="pointer-events-none absolute -right-40 -top-40 size-[32rem] rounded-full bg-primary/[0.07] blur-3xl"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-[0.35] [background-image:linear-gradient(hsl(var(--border))_1px,transparent_1px),linear-gradient(90deg,hsl(var(--border))_1px,transparent_1px)] [background-size:2.5rem_2.5rem]"
        />

        <div className="relative">
          <WordmarkLarge />
        </div>

        <div className="relative max-w-xl">
          <h2 className="text-2xl font-semibold leading-snug tracking-tight text-foreground">
            The specification record for rotating equipment procurement.
          </h2>
          <ul className="mt-8 space-y-5">
            {ASSURANCES.map(({ Icon, title, body }) => (
              <li key={title} className="flex gap-3">
                <span className="mt-px grid size-7 shrink-0 place-items-center rounded-md border border-primary/25 bg-primary/10 text-primary">
                  <Icon className="size-3.5" />
                </span>
                <div>
                  <p className="text-xs font-medium text-foreground">{title}</p>
                  <p className="mt-0.5 text-2xs leading-relaxed text-muted-foreground">
                    {body}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </div>

        <p className="relative text-2xs text-muted-foreground">
          PostgreSQL is the system of record. AI is an assistant layer, never
          the source.
        </p>
      </aside>

      <main className="flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-xs">
          <div className="mb-8 lg:hidden">
            <WordmarkLarge />
          </div>

          <h1 className="text-base font-semibold tracking-tight text-foreground">
            Sign in
          </h1>
          <p className="mt-1 text-xs text-muted-foreground">
            Use the work email your organisation was provisioned with.
          </p>

          <form
            action="/api/auth/login"
            method="post"
            className="mt-6 space-y-3.5"
          >
            {error ? (
              <p
                role="alert"
                className="rounded-md border border-destructive/30 bg-destructive/[0.07] px-2.5 py-2 text-2xs text-destructive"
              >
                {error}
              </p>
            ) : null}

            <div className="space-y-1.5">
              <Label htmlFor="email">Work email</Label>
              <Input
                id="email"
                name="email"
                type="email"
                required
                autoComplete="username"
                placeholder="analyst@client.com"
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                name="password"
                type="password"
                required
                minLength={8}
                autoComplete="current-password"
              />
            </div>

            <Button type="submit" size="lg" className="mt-1 w-full">
              Sign in
            </Button>
          </form>

          <p className="mt-5 text-2xs leading-relaxed text-muted-foreground">
            Access is scoped to your organisation. Sign-ins and record access
            are written to the audit trail.
          </p>

          <div className="mt-8 border-t border-border pt-4">
            <ByTargeticon />
          </div>
        </div>
      </main>
    </div>
  );
}
