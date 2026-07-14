// Adapter: reference book/index API surface over this app's backend.
import type { BookResponse, IndexStatus, BookSummary, SeriesSummary, ExtractedChapter, RichParagraph } from "../types";

interface OurBooks {
  books: {
    id: number; name: string; chapter_count: number; chunk_count: number;
    word_count: number; povs: string[]; stats: Record<string, number>;
    chapters: { chapter: number; kind: string; pov: string | null; date: string | null;
                word_count: number; chunk_count: number }[];
  }[];
  last_synced: string | null;
}

let cache: OurBooks | null = null;

async function ourBooks(force = false): Promise<OurBooks> {
  if (cache && !force) return cache;
  const res = await fetch("/api/books");
  if (!res.ok) throw new Error(`Failed to fetch books: ${res.statusText}`);
  cache = (await res.json()) as OurBooks;
  return cache;
}

export async function fetchBooks(): Promise<BookResponse[]> {
  const data = await ourBooks(true);
  return data.books.map((b) => ({
    id: String(b.id),
    name: b.name,
    chapter_count: b.chapter_count,
    povs: b.povs,
    chapters: b.chapters.map((c) => ({
      chapter: c.chapter,
      chapter_heading: c.kind === "prologue" ? "Prologue" : `Chapter ${c.chapter}`,
      pov: c.pov ?? "",
      date: c.date,
      filename: "",
    })),
  }));
}

export async function fetchIndexStatus(): Promise<IndexStatus> {
  const data = await ourBooks();
  return {
    total_chunks: data.books.reduce((n, b) => n + b.chunk_count, 0),
    books_indexed: data.books.map((b) => b.name),
    last_built: data.last_synced,
    book_last_indexed: Object.fromEntries(data.books.map((b) => [b.name, data.last_synced])),
    collection_name: "series",
    is_ready: data.books.length > 0,
  };
}

function looseKey(s: string): string {
  // punctuation-insensitive: "Nobody's Hero", "nobodys-hero", and
  // "nobody-s-hero" all reduce to "nobodyshero"
  return s.toLowerCase().replace(/[^a-z0-9]/g, "");
}

async function bookNumber(bookId: string): Promise<number> {
  if (/^\d+$/.test(bookId)) return Number(bookId);
  const data = await ourBooks();
  const match = data.books.find((b) => looseKey(b.name) === looseKey(bookId));
  if (!match) throw new Error(`Unknown book: ${bookId}`);
  return match.id;
}

export async function downloadStoryBible(bookId: string | number): Promise<void> {
  const n = typeof bookId === "number" ? bookId : await bookNumber(bookId);
  const res = await fetch(`/api/books/${n}/bible`);
  if (!res.ok) throw new Error(`Failed to export story bible: ${res.statusText}`);
  const blob = await res.blob();
  const cd = res.headers.get("Content-Disposition") ?? "";
  const filename = /filename="?([^";]+)"?/.exec(cd)?.[1] ?? `story-bible-book-${n}.md`;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// full=false (default) syncs only changed chapters; full=true re-embeds and
// re-extracts every chapter from scratch (slower, full AI cost).
export async function triggerRebuild(full = false): Promise<void> {
  const res = await fetch(`/api/ingest/run${full ? "?full=true" : ""}`, { method: "POST" });
  if (!res.ok) throw new Error(`Failed to trigger rebuild: ${res.statusText}`);
}

export async function triggerBookUpdate(bookName: string, full = false): Promise<void> {
  const n = await bookNumber(bookName);
  const params = new URLSearchParams();
  if (n != null) params.set("book", String(n));
  if (full) params.set("full", "true");
  const qs = params.toString();
  const res = await fetch(`/api/ingest/run${qs ? `?${qs}` : ""}`, { method: "POST" });
  if (!res.ok) throw new Error(`Failed to update book: ${res.statusText}`);
}

export async function fetchBookSummary(bookId: string): Promise<BookSummary> {
  const n = await bookNumber(bookId);
  const res = await fetch(`/api/books/${n}/summary`);
  if (!res.ok) throw new Error(`Failed to fetch book summary: ${res.statusText}`);
  return res.json();
}

export async function fetchExtractedChapter(bookId: string, chapter: number): Promise<ExtractedChapter> {
  const n = await bookNumber(bookId);
  const res = await fetch(`/api/books/${n}/chapters/${chapter}/extracted`);
  if (!res.ok) throw new Error(`Failed to fetch chapter: ${res.statusText}`);
  return res.json();
}

export async function fetchMissingChapters(_bookId: string): Promise<number[]> {
  return [];
}

export async function fetchChapterText(bookId: string, chapterNum: number, _mockSnippet?: string): Promise<string> {
  const content = await fetchChapterContent(bookId, chapterNum);
  return content.text;
}

export interface ChapterContent {
  text: string;
  // formatting-preserving paragraphs from the ingest's rich-text sidecar;
  // null for books ingested before the sidecar existed (plain fallback)
  rich: RichParagraph[] | null;
}

export async function fetchChapterContent(bookId: string, chapterNum: number): Promise<ChapterContent> {
  const n = await bookNumber(bookId);
  const res = await fetch(`/api/books/${n}/chapters/${chapterNum}/text`);
  if (!res.ok) throw new Error(`Failed to fetch chapter text: ${res.statusText}`);
  const data = await res.json();
  return { text: data.text as string, rich: (data.rich as RichParagraph[] | null) ?? null };
}

export interface ChapterDraft extends ChapterContent {
  pov: string | null;
  date: string | null;
  // true when the index already matches the manuscript file's text
  in_sync: boolean;
}

// Chapter text read straight from the CURRENT manuscript file (no ingest,
// no LLM cost) — the review pane's draft mode. Slow-ish on the first call
// after a fresh export (a Pages round-trip), then content-hash cached.
export async function fetchChapterDraft(bookId: string, chapterNum: number): Promise<ChapterDraft> {
  const n = await bookNumber(bookId);
  const res = await fetch(`/api/books/${n}/chapters/${chapterNum}/draft`);
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`Failed to read the draft (${res.status}): ${detail || res.statusText}`);
  }
  const data = await res.json();
  return {
    text: data.text as string,
    rich: (data.rich as RichParagraph[] | null) ?? null,
    pov: data.pov ?? null,
    date: data.date ?? null,
    in_sync: Boolean(data.in_sync),
  };
}

export async function fetchSeriesSummary(): Promise<SeriesSummary> {
  const res = await fetch("/api/series/summary");
  if (!res.ok) throw new Error(`Failed to fetch series summary: ${res.statusText}`);
  return res.json();
}

// ── Loom drift detection ──────────────────────────────────────────
// Loom writes a manifest sidecar on every canon export; the backend
// compares it against the index. `behind` books have chapters in Loom
// that the index hasn't ingested (or stale numbering after an insertion).

export interface SyncBookStatus {
  book: number;
  title: string;
  manifest_found: boolean;
  exported_at?: string | null;
  manifest_chapters?: number;
  indexed_chapters?: number;
  missing_chapters?: number[];
  extra_chapters?: number[];
  behind?: boolean;
}

export interface SyncStatus {
  books: SyncBookStatus[];
  stale_count: number;
  last_synced: string | null;
}

export async function fetchSyncStatus(): Promise<SyncStatus> {
  const res = await fetch("/api/sync/status");
  if (!res.ok) throw new Error(`Failed to fetch sync status: ${res.statusText}`);
  return (await res.json()) as SyncStatus;
}
