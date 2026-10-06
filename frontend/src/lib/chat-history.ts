/**
 * Conversations, kept in the browser.
 *
 * Deliberately not in the database, and the reason is the same one the chat page
 * has always given: a conversation is a way of interrogating the record, not part
 * of it. Nothing said here is evidence, and the only route from an answer to a
 * stored row runs through the capture pipeline, where a field is written with a
 * verbatim quote from a page PumpAtlas fetched. Persisting the transcript
 * server-side would put prose that was never evidence next to rows that are.
 *
 * What changed is only that the transcript now survives a reload, which is what a
 * sidebar of past conversations is for.
 *
 * Every access is guarded. `localStorage` throws in a private window, returns
 * nothing after a clear, and is absent entirely during a server render — and a
 * chat that cannot save its history should still answer questions.
 */

import type { ChatAnswer } from "@/types/api";

const KEY = "pumpatlas.chat.conversations.v1";

/** Kept small on purpose: a stored answer carries every cited record with all its
 *  fields, which is the point of being able to reopen one — and is also several
 *  kilobytes each. */
const MAX_CONVERSATIONS = 25;

export interface StoredTurn {
  question: string;
  answer: ChatAnswer | null;
  /** Set when the question failed, so a reopened conversation says so. */
  failed?: string;
}

export interface Conversation {
  id: string;
  title: string;
  updatedAt: number;
  turns: StoredTurn[];
}

export function newConversationId(): string {
  return `c-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

/** A conversation's name, taken from what was first asked. */
export function titleFor(question: string): string {
  const flat = question.trim().replace(/\s+/g, " ");
  if (!flat) return "New conversation";
  return flat.length > 52 ? `${flat.slice(0, 51)}…` : flat;
}

export function loadConversations(): Conversation[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    // Whatever is in storage was written by some version of this code, or by
    // nothing at all. Keep only what still has the shape the UI reads.
    return parsed.filter(
      (item): item is Conversation =>
        !!item &&
        typeof (item as Conversation).id === "string" &&
        Array.isArray((item as Conversation).turns),
    );
  } catch {
    return [];
  }
}

/**
 * Save, shedding the oldest conversations if the quota refuses the write.
 *
 * A stored answer is large — every cited record with every recorded field — so a
 * long history reaches the origin quota sooner than a transcript would suggest.
 * Failing the write silently would lose the conversation currently on screen,
 * which is the one that matters most, so the oldest are dropped until the newest
 * fits.
 */
export function saveConversations(conversations: Conversation[]): void {
  if (typeof window === "undefined") return;
  let candidate = conversations.slice(0, MAX_CONVERSATIONS);
  for (let attempt = 0; attempt < 6; attempt += 1) {
    try {
      window.localStorage.setItem(KEY, JSON.stringify(candidate));
      return;
    } catch {
      if (candidate.length <= 1) return; // Not a size problem; give up quietly.
      candidate = candidate.slice(0, Math.max(1, Math.floor(candidate.length / 2)));
    }
  }
}

/** The conversation list with `next` moved to the front, by id. */
export function upsert(
  conversations: Conversation[],
  next: Conversation,
): Conversation[] {
  return [next, ...conversations.filter((item) => item.id !== next.id)];
}
