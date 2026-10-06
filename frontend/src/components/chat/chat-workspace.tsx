"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Database,
  Globe2,
  Loader2,
  MessageSquare,
  PanelLeft,
  PanelLeftClose,
  Plus,
  Send,
  Sparkles,
  Trash2,
  User,
} from "lucide-react";

import { AnswerBlock } from "@/components/chat/answer-block";
import { ErrorState } from "@/components/data/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { clientFetch } from "@/lib/api-client";
import {
  type Conversation,
  loadConversations,
  newConversationId,
  saveConversations,
  titleFor,
  upsert,
} from "@/lib/chat-history";
import { cn } from "@/lib/utils";
import type { ChatAnswer, ChatContext, ChatExample } from "@/types/api";

/**
 * Shown only if `/chat/context` could not be reached.
 *
 * The screen's copy is served so that this app and every client deployment ask
 * the same questions — see `ASK_SCREEN` in the backend. These exist so a
 * failed context call yields a usable screen rather than an empty one.
 */
const FALLBACK_EXAMPLES: ChatExample[] = [
  {
    label: "Sulzer multistage pumps",
    query: "Which Sulzer multistage pumps do we hold and what is their rated head?",
  },
  {
    label: "API 675 metering pumps",
    query: "Do we have any API 675 metering pumps for chemical injection?",
  },
  {
    label: "BB3 barrel pumps",
    query: "Who makes BB3 barrel pumps for crude export duty?",
  },
  {
    label: "NACE MR0175 for sour service",
    query: "What NACE MR0175 compliant pumps are recorded for sour service?",
  },
];

/**
 * Ask, as a conversation you can come back to.
 *
 * The screen is a thread with its history beside it, because that is what asking
 * a series of questions about a catalogue actually looks like — the third
 * question is usually about the answer to the second, and losing the first two on
 * reload made every session start from nothing.
 *
 * Two things are deliberately unchanged from the single-pane version:
 *
 * - **Asking writes nothing.** Reading a page into a record is the discovery
 *   pipeline, and it lives on Pumps and Vendors — not inside an answer.
 * - **The transcript stays in the browser.** See `lib/chat-history` for why.
 *
 * One thing is not carried over: the question is sent on its own, with no prior
 * turns attached, so an answer never depends on a transcript this platform did
 * not keep. A follow-up has to name its subject.
 */
export function ChatWorkspace({ context }: { context: ChatContext | null }) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);


  /**
   * The web is searched whenever a provider is active — there is no opt-in.
   *
   * The checkbox asked a question the person asking cannot answer yet: whether
   * the catalogue alone can cover their question is exactly what they are about
   * to find out. Leaving it unticked produced thin answers that looked like the
   * platform knew nothing, and ticking it every time is a step with only one
   * sensible setting.
   *
   * The cost is honest and bounded: the answer says how many pages it read, and
   * a provider that is not configured simply means records only, which the header
   * badge states before the first question.
   *
   * While `/chat/context` is still in flight, `context` is null and the old
   * `?? false` sent `use_web: false` — so a question asked in that window came
   * back records-only with an empty `web` array and *no* `web_error` to say why.
   * Clicking a suggestion chip on a fresh page did exactly that, because the
   * chips render from the fallback list precisely when context has not arrived.
   *
   * Unknown now means "ask for it". If no provider is active the server says so
   * in `web_error`, which is a stated problem rather than a silent omission.
   */
  const useWeb = context === null ? true : context.web_available;

  // Served copy, with a local fallback so a failed context call still gives a
  // usable screen rather than an empty one.
  const examples = context?.examples?.length ? context.examples : FALLBACK_EXAMPLES;

  // Read after mount, never during render: `localStorage` does not exist on the
  // server, and reading it in the initialiser makes the first client render
  // disagree with the server's and throws a hydration error.
  useEffect(() => {
    setConversations(loadConversations());
  }, []);

  const active = useMemo(
    () => conversations.find((item) => item.id === activeId) ?? null,
    [conversations, activeId],
  );
  const turns = useMemo(() => active?.turns ?? [], [active]);

  /**
   * Apply a change and persist it in one step.
   *
   * Storage is written here rather than in an effect keyed on the list. Such an
   * effect has to tell "nothing has loaded yet" apart from "the user deleted the
   * last conversation" — both are an empty array — and it gets that wrong on
   * mount, where StrictMode runs effects twice and the second pass would save
   * the empty initial state over what the first pass had just loaded.
   *
   * The updater is pure apart from this write, which is idempotent: the same
   * list serialises to the same string however many times StrictMode calls it.
   */
  const commit = useCallback(
    (update: (current: Conversation[]) => Conversation[]) => {
      setConversations((current) => {
        const next = update(current);
        saveConversations(next);
        return next;
      });
    },
    [],
  );

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns, asking]);

  const ask = useCallback(
    async (text: string, conversationId?: string) => {
      const trimmed = text.trim();
      if (trimmed.length < 3 || asking) return;

      const id = conversationId ?? activeId ?? newConversationId();
      setQuestion("");
      setAsking(true);
      setActiveId(id);

      commit((current) => {
        const existing = current.find((item) => item.id === id);
        return upsert(current, {
          id,
          title: existing?.title ?? titleFor(trimmed),
          updatedAt: Date.now(),
          turns: [...(existing?.turns ?? []), { question: trimmed, answer: null }],
        });
      });

      let answer: ChatAnswer | null = null;
      let failed: string | undefined;
      try {
        answer = await clientFetch<ChatAnswer>("/chat/ask", {
          method: "POST",
          body: { question: trimmed, use_web: useWeb },
        });
      } catch (caught) {
        failed = caught instanceof Error ? caught.message : "The question failed";
      }

      commit((current) =>
        current.map((item) =>
          item.id === id
            ? {
                ...item,
                updatedAt: Date.now(),
                turns: item.turns.map((turn, index) =>
                  index === item.turns.length - 1 ? { ...turn, answer, failed } : turn,
                ),
              }
            : item,
        ),
      );
      setAsking(false);
    },
    [activeId, asking, useWeb, commit],
  );

  function startNew() {
    setActiveId(null);
    setQuestion("");
    inputRef.current?.focus();
  }

  function remove(id: string) {
    commit((current) => current.filter((item) => item.id !== id));
    if (activeId === id) setActiveId(null);
  }

  return (
    <div className="flex h-[calc(100vh-var(--topbar-height))] overflow-hidden">
      {sidebarOpen ? (
        <aside className="flex w-56 flex-shrink-0 flex-col border-r border-border bg-card/40">
          <div className="p-2.5">
            <Button size="sm" className="w-full" onClick={startNew}>
              <Plus className="size-3.5" />
              New chat
            </Button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-1.5 pb-2">
            {conversations.length === 0 ? (
              <p className="px-2 py-3 text-2xs text-muted-foreground">
                No conversations yet.
              </p>
            ) : null}
            {conversations.map((conversation) => (
              <div
                key={conversation.id}
                role="button"
                tabIndex={0}
                onClick={() => setActiveId(conversation.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    setActiveId(conversation.id);
                  }
                }}
                className={cn(
                  "group flex cursor-pointer items-center gap-1.5 rounded-md px-2 py-1.5 transition-colors",
                  conversation.id === activeId
                    ? "bg-background text-foreground"
                    : "text-muted-foreground hover:bg-background/60 hover:text-foreground",
                )}
              >
                <MessageSquare className="size-3 flex-shrink-0" />
                <span className="flex-1 truncate text-2xs">{conversation.title}</span>
                <button
                  type="button"
                  aria-label="Delete conversation"
                  onClick={(event) => {
                    event.stopPropagation();
                    remove(conversation.id);
                  }}
                  className="opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100"
                >
                  <Trash2 className="size-3" />
                </button>
              </div>
            ))}
          </div>
          <p className="border-t border-border px-2.5 py-2 text-[0.625rem] leading-relaxed text-muted-foreground">
            Conversations are kept in this browser. Asking writes nothing to the
            record.
          </p>
        </aside>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-2 border-b border-border px-3 py-2">
          <button
            type="button"
            onClick={() => setSidebarOpen((value) => !value)}
            aria-label={sidebarOpen ? "Hide conversations" : "Show conversations"}
            className="text-muted-foreground transition-colors hover:text-foreground"
          >
            {sidebarOpen ? (
              <PanelLeftClose className="size-4" />
            ) : (
              <PanelLeft className="size-4" />
            )}
          </button>
          <Sparkles className="size-4 text-primary" />
          <h1 className="text-xs font-medium">Ask</h1>
          <Badge
            variant={context?.web_available ? "success" : "outline"}
            className="ml-auto text-2xs"
          >
            {context === null
              ? "checking web search…"
              : context.web_available
                ? "web search available"
                : "records only"}
          </Badge>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl px-4 py-5">
            {turns.length === 0 ? (
              <div className="pt-8 text-center">
                <div className="mx-auto flex size-10 items-center justify-center rounded-lg bg-primary/10">
                  <Sparkles className="size-5 text-primary" />
                </div>
                <p className="mt-3 text-sm font-medium">
                  {context?.title ?? "Ask about pumps, vendors, duties or standards"}
                </p>
                <p className="mx-auto mt-1.5 max-w-xl text-2xs leading-relaxed text-muted-foreground">
                  {context?.lede ??
                    "Answers are built from the records this platform holds. Every claim is marked with where it came from — [R1] for a held record, [W1] for a web page."}
                </p>
                <div className="mx-auto mt-5 grid max-w-2xl gap-1.5 sm:grid-cols-2">
                  {examples.map((example) => (
                    <button
                      key={example.query}
                      type="button"
                      onClick={() => void ask(example.query)}
                      disabled={asking}
                      className="rounded-lg border border-border bg-card px-3 py-2 text-left transition-colors hover:border-primary/40 disabled:opacity-50"
                    >
                      <span className="block text-2xs font-medium text-foreground">
                        {example.label}
                      </span>
                      <span className="mt-0.5 block line-clamp-2 text-2xs text-muted-foreground">
                        {example.query}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            <div className="space-y-5">
              {turns.map((turn, index) => (
                <div key={index} className="space-y-3">
                  <div className="flex items-start justify-end gap-2">
                    <p className="max-w-[80%] whitespace-pre-wrap rounded-lg rounded-tr-sm bg-primary px-3 py-2 text-xs leading-relaxed text-primary-foreground">
                      {turn.question}
                    </p>
                    <span className="mt-0.5 flex size-6 flex-shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
                      <User className="size-3" />
                    </span>
                  </div>

                  <div className="flex items-start gap-2">
                    <span className="mt-0.5 flex size-6 flex-shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                      <Sparkles className="size-3" />
                    </span>
                    <div className="min-w-0 flex-1">
                      {turn.failed ? (
                        <ErrorState message={turn.failed} />
                      ) : turn.answer ? (
                        <AnswerBlock
                          answer={turn.answer}
                          question={turn.question}
                          enrich={index === turns.length - 1}
                        />
                      ) : (
                        <p className="flex items-center gap-2 py-1 text-2xs text-muted-foreground">
                          <Loader2 className="size-3.5 animate-spin text-primary" />
                          {useWeb
                            ? "Searching the records and the web…"
                            : "Searching the records…"}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <div ref={endRef} />
          </div>
        </div>

        <form
          className="border-t border-border bg-background px-4 py-3"
          onSubmit={(event) => {
            event.preventDefault();
            void ask(question);
          }}
        >
          <div className="mx-auto max-w-3xl">
            <div className="relative">
              <Textarea
                ref={inputRef}
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void ask(question);
                  }
                }}
                placeholder={
                  context?.placeholder ??
                  "Ask about a pump, a duty, a vendor or a standard…"
                }
                aria-label="Your question"
                disabled={asking}
                rows={1}
                className="max-h-40 min-h-[2.75rem] resize-none pr-11 text-xs"
              />
              <Button
                type="submit"
                size="icon"
                aria-label="Ask"
                disabled={asking || question.trim().length < 3}
                className="absolute bottom-1.5 right-1.5 size-7"
              >
                {asking ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <Send className="size-3.5" />
                )}
              </Button>
            </div>

            <p
              className="mt-2 flex w-fit items-center gap-1.5 text-2xs text-muted-foreground"
              title={
                useWeb
                  ? "Every question searches the records and the web together."
                  : "No web search provider is active — set one at /ai-settings"
              }
            >
              {useWeb ? (
                <>
                  <Globe2 className="size-3" />
                  Searching our records and the web
                </>
              ) : (
                <>
                  <Database className="size-3" />
                  Records only — no web search provider is active
                </>
              )}
            </p>
          </div>
        </form>
      </div>
    </div>
  );
}
