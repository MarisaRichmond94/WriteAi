// Reference-compatible plan API surface, wired to this app's backend.
import type {
  Citation,
  OutlineBook,
  OutlineChapter,
  ResyncPreviewResponse,
  WriterCharacter,
} from "../types";

export type PlanSSEEvent =
  | { type: "chunk"; content: string }
  | { type: "citations"; sources: Citation[] }
  | { type: "done" }
  | { type: "error"; message: string };

async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  return res.json();
}

async function* _streamSSE(url: string, body: unknown): AsyncGenerator<PlanSSEEvent> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok || !response.body) {
    throw new Error(`Request failed: ${response.status}`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const line = frame.trim();
      if (!line.startsWith("data:")) continue;
      try {
        yield JSON.parse(line.slice(5)) as PlanSSEEvent;
      } catch {
        /* skip malformed frame */
      }
    }
  }
}

// ── Outline ──────────────────────────────────────────────────────────────────

export async function fetchOutline(bookId: string): Promise<OutlineBook> {
  const data = await jsonFetch<{ book: number; chapters: OutlineChapter[] }>(
    `/api/plan/outline/${bookId}`,
  );
  return { book: String(data.book), chapters: data.chapters };
}

export async function saveOutline(
  bookId: string,
  chapters: OutlineChapter[],
): Promise<OutlineBook> {
  const data = await jsonFetch<{ book: number; chapters: OutlineChapter[] }>(
    `/api/plan/outline/${bookId}`,
    { method: "PUT", body: JSON.stringify({ chapters }) },
  );
  return { book: String(data.book), chapters: data.chapters };
}

export async function deleteChapter(bookId: string, chapterId: string): Promise<void> {
  await jsonFetch(`/api/plan/outline/${bookId}/chapter/${chapterId}`, {
    method: "DELETE",
  });
}

export async function fetchResyncPreview(bookId: string): Promise<ResyncPreviewResponse> {
  return jsonFetch<ResyncPreviewResponse>(`/api/plan/resync/${bookId}`);
}

export async function approveResync(
  bookId: string,
  body: { book: string; approved_diff_ids: string[] },
): Promise<OutlineBook> {
  const data = await jsonFetch<{ book: number; chapters: OutlineChapter[] }>(
    `/api/plan/resync/${bookId}/approve`,
    { method: "POST", body: JSON.stringify(body) },
  );
  return { book: String(data.book), chapters: data.chapters };
}

// ── Writer characters ────────────────────────────────────────────────────────

export async function fetchWriterCharacters(): Promise<WriterCharacter[]> {
  const data = await jsonFetch<{ characters: (Omit<WriterCharacter, "books"> & { books: (string | number)[] })[] }>(
    "/api/plan/characters",
  );
  // books arrive as names (the UI matches by book name)
  return data.characters.map((c) => ({
    ...c,
    books: (c.books ?? []).map(String),
    photo_url: c.photo_url ?? null,
  }));
}

export async function replaceAllWriterCharacters(
  characters: WriterCharacter[],
): Promise<WriterCharacter[]> {
  await jsonFetch("/api/plan/characters", {
    method: "PUT",
    body: JSON.stringify({ characters }),
  });
  return characters;
}

export async function upsertWriterCharacter(
  character: WriterCharacter,
): Promise<WriterCharacter> {
  return jsonFetch<WriterCharacter>(`/api/plan/characters/${character.id}`, {
    method: "PUT",
    body: JSON.stringify(character),
  });
}

export async function deleteWriterCharacter(characterId: string): Promise<void> {
  await jsonFetch(`/api/plan/characters/${characterId}`, { method: "DELETE" });
}

export async function uploadWriterCharacterPhoto(
  characterId: string,
  file: File,
): Promise<string> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`/api/plan/characters/${characterId}/photo`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
  const data = (await res.json()) as { photo_url: string };
  return data.photo_url;
}

export async function fetchExtractedCharacter(
  characterId: string,
): Promise<Record<string, unknown>> {
  return jsonFetch<Record<string, unknown>>(`/api/plan/characters/${characterId}/extracted`);
}

// ── AI review streams ────────────────────────────────────────────────────────

export interface OutlineReviewRequest {
  book: string;
  chapter_ids: string[];
  message: string;
  conversation_history: { role: "user" | "assistant"; content: string }[];
  model?: string;
}

export async function* streamOutlineReview(
  req: OutlineReviewRequest,
): AsyncGenerator<PlanSSEEvent> {
  yield* _streamSSE("/api/plan/outline/review/stream", {
    ...req,
    book: Number(req.book),
  });
}

export interface CharacterReviewRequest {
  character_id: string;
  message: string;
  conversation_history: { role: "user" | "assistant"; content: string }[];
  model?: string;
}

export async function* streamCharacterReview(
  req: CharacterReviewRequest,
): AsyncGenerator<PlanSSEEvent> {
  yield* _streamSSE("/api/plan/character/review/stream", req);
}

// ── Helpers ──────────────────────────────────────────────────────────────────

export function slugify(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

export function bookNameToId(name: string): string {
  return slugify(name);
}
