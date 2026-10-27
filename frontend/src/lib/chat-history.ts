/**
 * Conversations, kept in the database.
 *
 * They used to live in `localStorage`, which meant a history that vanished with the
 * browser, never followed a person to another machine, and was capped by a quota that
 * shed the oldest thread whenever an answer got large. They are now stored per user on
 * the server (`/chat/conversations`).
 *
 * What has not changed is what a conversation *is*: a way of interrogating the record,
 * not part of it. Nothing said here is evidence, and nothing stored here is read back
 * into search, scoring or a field. The only route from an answer to a stored fact is the
 * capture pipeline, where a field is written with a verbatim quote from a page PumpAtlas
 * fetched. That is why the transcript sits in its own tables and `/chat/ask` still
 * writes nothing.
 *
 * Saving is best effort. A chat that cannot save its history should still answer
 * questions, so every call here reports failure to the caller rather than throwing into
 * the middle of an answer.
 */

import { clientFetch } from "@/lib/api-client";
import type { ChatAnswer } from "@/types/api";

export interface StoredTurn {
  question: string;
  answer: ChatAnswer | null;
  /** Set when the question failed, so a reopened conversation says so. */
  failed?: string | null;
}

/** Which tenant had a conversation. `name` is "Shared catalogue" for a tenant-less key. */
export interface TenantTag {
  id: string | null;
  name: string;
  slug: string | null;
}

export interface Conversation {
  id: string;
  title: string;
  updatedAt: number;
  turns: StoredTurn[];
  /** The tenant that asked, so a history spanning tenants says whose each thread is. */
  tenant: TenantTag | null;
  /** `app` for a person's own thread; `api_key` for one another application asked. */
  source: "app" | "api_key";
  /** The API key's name, for a thread it asked. */
  sourceLabel: string | null;
  /** False for a summary from the list: its turns have not been fetched yet. */
  loaded: boolean;
}

interface ConversationSummary {
  id: string;
  title: string;
  updated_at: string;
  turn_count: number;
  tenant?: TenantTag | null;
  source?: "app" | "api_key";
  source_label?: string | null;
}

interface ConversationDetail extends ConversationSummary {
  turns: StoredTurn[];
}

/** A throwaway id for a thread that has not been saved yet. */
export function newConversationId(): string {
  return `new-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

/** A conversation's name, taken from what was first asked. */
export function titleFor(question: string): string {
  const flat = question.trim().replace(/\s+/g, " ");
  if (!flat) return "New conversation";
  return flat.length > 52 ? `${flat.slice(0, 51)}…` : flat;
}

function fromSummary(item: ConversationSummary): Conversation {
  return {
    id: item.id,
    title: item.title,
    updatedAt: Date.parse(item.updated_at) || Date.now(),
    turns: [],
    tenant: item.tenant ?? null,
    source: item.source ?? "app",
    sourceLabel: item.source_label ?? null,
    loaded: false,
  };
}

/**
 * The signed-in user's conversations, newest first, without their turns.
 *
 * `null` means the store could not be reached; an empty array means there is nothing
 * to show. Collapsing the two into `[]` is what hid a dead history for as long as it
 * was dead: with the `chat_conversations` tables missing from the database every call
 * here 500'd, and the sidebar rendered the same reassuring "no conversations yet" it
 * shows a brand new account. Nothing anywhere said the history was not working.
 */
export async function loadConversations(): Promise<Conversation[] | null> {
  try {
    const rows = await clientFetch<ConversationSummary[]>("/chat/conversations");
    return rows.map(fromSummary);
  } catch {
    return null;
  }
}

/** One conversation with its turns, or null if it could not be read. */
export async function loadConversation(id: string): Promise<Conversation | null> {
  try {
    const detail = await clientFetch<ConversationDetail>(`/chat/conversations/${id}`);
    return { ...fromSummary(detail), turns: detail.turns, loaded: true };
  } catch {
    return null;
  }
}

/**
 * Write a first turn, creating the thread. Resolves to the server's id, or null if the
 * write failed — the thread then stays on screen for this visit but is not kept.
 */
export async function createConversation(
  title: string,
  turn: StoredTurn,
): Promise<string | null> {
  try {
    const created = await clientFetch<ConversationSummary>("/chat/conversations", {
      method: "POST",
      body: { title, turn },
    });
    return created.id;
  } catch {
    return null;
  }
}

/** Append a turn to a saved thread. Resolves to whether it was kept. */
export async function appendTurn(id: string, turn: StoredTurn): Promise<boolean> {
  try {
    await clientFetch(`/chat/conversations/${id}/turns`, {
      method: "POST",
      body: turn,
    });
    return true;
  } catch {
    return false;
  }
}

export async function deleteConversation(id: string): Promise<boolean> {
  try {
    await clientFetch(`/chat/conversations/${id}`, { method: "DELETE" });
    return true;
  } catch {
    return false;
  }
}

/** The conversation list with `next` moved to the front, by id. */
export function upsert(conversations: Conversation[], next: Conversation): Conversation[] {
  return [next, ...conversations.filter((item) => item.id !== next.id)];
}
