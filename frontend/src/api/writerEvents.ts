// Writer-authored timeline events — the writer's own events, distinct from
// the AI-extracted events served by /api/events.

export interface WriterEventTag {
  book: string;
  chapter: number;
}

export interface WriterEvent {
  id: string;
  title: string;
  date: string | null;
  time: string | null;
  description: string;
  characters: string[];
  location: string | null;
  book_chapters: WriterEventTag[];
  created_at: string;
  updated_at: string;
}

export interface WriterEventInput {
  title: string;
  date: string | null;
  time: string | null;
  description: string;
  characters: string[];
  location: string | null;
  /** Legacy title+positional chapter tagging, replaced by Loom's cuid-keyed
   *  join (LOOM-32) and removed outright in LOOM-40. Optional because nothing
   *  authors it any more — neither this form nor Loom sends it. */
  book_chapters?: WriterEventTag[];
}

/**
 * One Loom chapter that references an event (LOOM-32).
 *
 * Fully denormalised by Loom, so nothing here re-resolves anything. Loom owns
 * the join and keys it by chapter cuid — which is what makes a tag survive a
 * chapter being inserted above it, the failure that made `book_chapters`
 * unusable and went unnoticed because nothing ever reported it.
 */
export interface ChapterLink {
  seriesId: string;
  seriesTitle: string;
  bookId: string;
  bookTitle: string;
  chapterId: string;
  chapterTitle: string;
  /** Canon display number (0 = prologue), or null for a chapter with no canon
   *  address — still a real tag, just not a linkable one. */
  chapterNumber: number | null;
  /** RELATIVE — prefix with VITE_LOOM_URL via loomHref(). Null exactly when
   *  chapterNumber is. */
  readPath: string | null;
}

/** Keyed by event id. Every id asked for gets a key; an event tagged nowhere
 *  maps to [], so "no chapters" stays distinct from "lookup failed". */
export type ChapterLinks = Record<string, ChapterLink[]>;

/** Loom is closed. A normal condition, not a fault — the UI names it rather
 *  than rendering an empty row, which would claim the event is referenced
 *  nowhere. */
export class LoomUnreachableError extends Error {}

const BASE = "/api/writer-events";

/**
 * Which Loom chapters reference these events.
 *
 * One request for the whole page rather than one per card: the timeline shows
 * every event, and 144 round trips to answer one question is not a design.
 */
export async function fetchChapterLinks(ids: string[]): Promise<ChapterLinks> {
  if (ids.length === 0) return {};
  const res = await fetch(`${BASE}/chapter-links?ids=${encodeURIComponent(ids.join(","))}`);
  if (res.status === 503) throw new LoomUnreachableError("Loom is not reachable");
  if (!res.ok) throw new Error("Failed to fetch chapter links");
  return res.json();
}

export async function fetchWriterEvents(): Promise<{
  events: WriterEvent[];
  locations: string[];
}> {
  const res = await fetch(BASE);
  if (!res.ok) throw new Error("Failed to fetch writer events");
  return res.json();
}

export async function createWriterEvent(input: WriterEventInput): Promise<WriterEvent> {
  const res = await fetch(BASE, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error("Failed to create event");
  return res.json();
}

export async function updateWriterEvent(
  id: string,
  input: WriterEventInput,
): Promise<WriterEvent> {
  const res = await fetch(`${BASE}/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error("Failed to update event");
  return res.json();
}

export async function deleteWriterEvent(id: string): Promise<void> {
  const res = await fetch(`${BASE}/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to delete event");
}

export async function addWriterLocation(name: string): Promise<{ locations: string[] }> {
  const res = await fetch(`${BASE}/locations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) throw new Error("Failed to add location");
  return res.json();
}
