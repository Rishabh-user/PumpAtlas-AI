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
  appendTurn,
  type Conversation,
  createConversation,
  deleteConversation,
  loadConversation,
  loadConversations,
  newConversationId,
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
/** Only reached if the context call fails; the real list comes from the API, chosen
 *  against what the catalogue can actually answer. */
const FALLBACK_EXAMPLES: ChatExample[] = [
  {
    mode: "record",
    label: "Suppliers in Singapore",
    query: "Which suppliers do we hold in Singapore, and how many are approved?",
  },
  {
    mode: "record",
    label: "OH2 overhung pumps",
    query: "Which API 610 OH2 pump models do we hold, and who makes them?",
  },
  {
    mode: "web",
    label: "Barrel pumps for crude export",
    query: "Who makes API 610 BB5 barrel pumps suitable for crude export duty?",
  },
  {
    mode: "web",
    label: "Sour service compliance",
    query: "Which pump manufacturers state NACE MR0175 compliance for sour service, and where do they say it?",
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
 * - **The transcript is not evidence.** It is stored per user so it survives a reload
 *   and follows a person between machines, but nothing stored is read back into the
 *   record. See `lib/chat-history`.
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
  const [opening, setOpening] = useState<string | null>(null);
  const [saveFailed, setSaveFailed] = useState(false);
  const [historyUnavailable, setHistoryUnavailable] = useState(false);

  // A thread starts under a throwaway local id and gets the server's once its first
  // turn is written. The local id stays the React key for the life of the page, so
  // nothing that closed over it goes stale; this maps it to the real one.
  const conversationsRef = useRef<Conversation[]>([]);
  const serverIds = useRef(new Map<string, string>());
  // The write for the most recent turn, so the next question waits for it rather than
  // racing it to create the same thread twice.
  const pendingSave = useRef<Promise<void>>(Promise.resolve());

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

  // The history is fetched after mount: it needs the signed-in session, and a
  // server render has no browser to ask from.
  useEffect(() => {
    let cancelled = false;
    void loadConversations().then((items) => {
      if (items === null) {
        // Unreachable, not empty. Saying so matters: the two look identical in the
        // sidebar, and answers keep working either way, so nothing else gives it away.
        if (!cancelled) setHistoryUnavailable(true);
        return;
      }
      // Merge rather than replace: a question asked before this resolved is already
      // on screen and is not in the list yet.
      if (!cancelled) {
        setConversations((current) => [
          ...current,
          ...items.filter((item) => !current.some((other) => other.id === item.id)),
        ]);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    conversationsRef.current = conversations;
  }, [conversations]);

  const active = useMemo(
    () => conversations.find((item) => item.id === activeId) ?? null,
    [conversations, activeId],
  );
  const turns = useMemo(() => active?.turns ?? [], [active]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns, asking]);

  const ask = useCallback(
    async (text: string, conversationId?: string) => {
      const trimmed = text.trim();
      if (trimmed.length < 3 || asking) return;

      await pendingSave.current;

      // A thread another application asked is a record of what that tenant searched;
      // a follow-up starts a thread of its own rather than writing into it.
      const readOnly = conversationsRef.current.find((item) => item.id === activeId)?.source === "api_key";
      const id = conversationId ?? (readOnly ? null : activeId) ?? newConversationId();
      setQuestion("");
      setAsking(true);
      setActiveId(id);

      let title = titleFor(trimmed);
      setConversations((current) => {
        const existing = current.find((item) => item.id === id);
        title = existing?.title ?? title;
        return upsert(current, {
          id,
          title,
          updatedAt: Date.now(),
          turns: [...(existing?.turns ?? []), { question: trimmed, answer: null }],
          tenant: existing?.tenant ?? null,
          source: "app",
          sourceLabel: null,
          loaded: true,
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

      setConversations((current) =>
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

      // Written after the answer is on screen, so saving never delays it. A failed
      // save leaves the thread usable for this visit and says so.
      const turn = { question: trimmed, answer, failed };
      pendingSave.current = (async () => {
        const known = serverIds.current.get(id) ?? (id.startsWith("new-") ? null : id);
        if (known) {
          setSaveFailed(!(await appendTurn(known, turn)));
          return;
        }
        const created = await createConversation(title, turn);
        if (created) serverIds.current.set(id, created);
        setSaveFailed(created === null);
      })();
    },
    [activeId, asking, useWeb],
  );

  async function open(id: string) {
    setActiveId(id);
    const target = conversations.find((item) => item.id === id);
    if (!target || target.loaded) return;
    setOpening(id);
    const full = await loadConversation(id);
    setOpening((current) => (current === id ? null : current));
    if (full) {
      setConversations((current) => current.map((item) => (item.id === id ? full : item)));
    }
  }

  function startNew() {
    setActiveId(null);
    setQuestion("");
    inputRef.current?.focus();
  }

  async function remove(id: string) {
    setConversations((current) => current.filter((item) => item.id !== id));
    if (activeId === id) setActiveId(null);
    await pendingSave.current;
    const known = serverIds.current.get(id) ?? (id.startsWith("new-") ? null : id);
    if (known) await deleteConversation(known);
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
                onClick={() => void open(conversation.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    void open(conversation.id);
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
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-2xs">{conversation.title}</span>
                  {conversation.tenant ? (
                    <span
                      title={
                        conversation.source === "api_key"
                          ? `Asked through ${conversation.sourceLabel ?? "an API key"}`
                          : `Asked by your account in ${conversation.tenant.name}`
                      }
                      className={cn(
                        "mt-0.5 inline-flex max-w-full items-center gap-1 truncate rounded px-1 py-px text-[0.5625rem] font-medium",
                        conversation.source === "api_key"
                          ? "bg-primary/10 text-primary"
                          : "bg-muted text-muted-foreground",
                      )}
                    >
                      {conversation.tenant.name}
                      {conversation.source === "api_key" ? " · API" : ""}
                    </span>
                  ) : null}
                </span>
                <button
                  type="button"
                  aria-label="Delete conversation"
                  onClick={(event) => {
                    event.stopPropagation();
                    void remove(conversation.id);
                  }}
                  className="opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100"
                >
                  <Trash2 className="size-3" />
                </button>
              </div>
            ))}
          </div>
          <p
            className={`border-t border-border px-2.5 py-2 text-[0.625rem] leading-relaxed ${
              historyUnavailable || saveFailed
                ? "text-sev-medium"
                : "text-muted-foreground"
            }`}
          >
            {historyUnavailable
              ? "Chat history is unavailable — the conversation store could not be reached, so nothing is being saved. Answers are unaffected."
              : saveFailed
                ? "The last question could not be saved to your history."
                : "Your conversations are saved to your account. Asking writes nothing to the record."}
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
            {opening !== null && opening === activeId ? (
              <p className="flex items-center gap-2 py-6 text-2xs text-muted-foreground">
                <Loader2 className="size-3.5 animate-spin text-primary" />
                Opening conversation…
              </p>
            ) : null}

            {turns.length === 0 && opening !== activeId ? (
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
                {/* Grouped, because the two kinds of question behave differently and
                  * the difference is not obvious until you have asked a few. A
                  * question about what we hold is answered from the index and cites
                  * [R1]; one the record cannot answer goes to the web and cites [W1].
                  * Asking the web for a price still returns nothing - nobody
                  * publishes one - and seeing the groups apart makes that legible. */}
                <div className="mx-auto mt-5 max-w-2xl space-y-4 text-left">
                  {(
                    [
                      ["record", "From your records", "Answered from the 1,684 suppliers and 160 models held here."],
                      ["web", "From the web", "The record cannot answer these, so the search provider reads pages for them."],
                    ] as const
                  ).map(([mode, heading, lede]) => {
                    const group = examples.filter(
                      (example) => (example.mode ?? "record") === mode,
                    );
                    if (!group.length) return null;
                    return (
                      <div key={mode}>
                        <p className="label-xs text-foreground">{heading}</p>
                        <p className="mt-0.5 text-2xs text-muted-foreground">{lede}</p>
                        <div className="mt-1.5 grid gap-1.5 sm:grid-cols-2">
                          {group.map((example) => (
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
                    );
                  })}
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
