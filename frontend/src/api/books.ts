// Adapter: reference book/index API surface over this app's backend.
import type { BookResponse, IndexStatus, BookSummary, SeriesSummary, ExtractedChapter } from "../types";

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

async function bookNumber(bookId: string): Promise<number | null> {
  if (/^\d+$/.test(bookId)) return Number(bookId);
  const data = await ourBooks();
  const match = data.books.find(
    (b) => b.name.toLowerCase() === bookId.toLowerCase()
      || b.name.toLowerCase().replace(/[^a-z0-9]+/g, "-") === bookId.toLowerCase(),
  );
  return match ? match.id : null;
}

export async function triggerRebuild(): Promise<void> {
  const res = await fetch("/api/ingest/run", { method: "POST" });
  if (!res.ok) throw new Error(`Failed to trigger rebuild: ${res.statusText}`);
}

export async function triggerBookUpdate(bookName: string): Promise<void> {
  const n = await bookNumber(bookName);
  const res = await fetch(`/api/ingest/run${n != null ? `?book=${n}` : ""}`, { method: "POST" });
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
  const n = await bookNumber(bookId);
  const res = await fetch(`/api/books/${n}/chapters/${chapterNum}/text`);
  if (!res.ok) throw new Error(`Failed to fetch chapter text: ${res.statusText}`);
  const data = await res.json();
  return data.text as string;
}

export async function fetchSeriesSummary(): Promise<SeriesSummary> {
  const res = await fetch("/api/series/summary");
  if (!res.ok) throw new Error(`Failed to fetch series summary: ${res.statusText}`);
  return res.json();
}
