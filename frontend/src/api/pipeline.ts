// Adapter: the reference app's "pipeline" maps onto this app's ingestion +
// enrichment runs. Only the surface the ported panes actually use.
import type { PipelineCostEstimate } from "../types";

function looseKey(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]/g, "");
}

/** Accepts a book number ("2"), exact name, or slug; returns the number
 * as a string, or null for "all books". */
async function resolveBookParam(book?: string): Promise<string | null> {
  if (!book) return null;
  if (/^\d+$/.test(book)) return book;
  const res = await fetch("/api/books");
  if (!res.ok) return null;
  const data = (await res.json()) as { books: { id: number; name: string }[] };
  const match = data.books.find((b) => looseKey(b.name) === looseKey(book));
  return match ? String(match.id) : null;
}

export async function fetchPipelineStatus(): Promise<{ running: boolean }> {
  const [ingest, enrich] = await Promise.all([
    fetch("/api/ingest/status").then((r) => (r.ok ? r.json() : { running: false })),
    fetch("/api/enrich/status").then((r) => (r.ok ? r.json() : { state: "idle" })),
  ]);
  return { running: Boolean(ingest.running) || enrich.state === "running" };
}

export async function fetchCostEstimate(
  _phases?: unknown,
  _models?: unknown,
  bookName?: string,
): Promise<PipelineCostEstimate> {
  const params = new URLSearchParams();
  const bookParam = await resolveBookParam(bookName);
  if (bookParam) params.set("book", bookParam);
  const res = await fetch(`/api/ingest/preview?${params}`);
  if (!res.ok) throw new Error(`Failed to fetch cost estimate: ${res.statusText}`);
  const data = (await res.json()) as { changed_chunks: number; estimated_cost_usd: number };
  return {
    phases: {
      extraction: {
        input_tokens_est: data.changed_chunks * 800,
        output_tokens_est: data.changed_chunks * 450,
        cost_usd_est: data.estimated_cost_usd,
      },
    },
    total_cost_usd_est: data.estimated_cost_usd,
  };
}

export async function runPipeline(
  payload?: string | { phases?: string[]; force?: boolean; book?: string; model_a?: string },
): Promise<void> {
  const bookName = typeof payload === "string" ? payload : payload?.book;
  const params = new URLSearchParams();
  const bookParam = await resolveBookParam(bookName);
  if (bookParam) params.set("book", bookParam);
  const res = await fetch(`/api/ingest/run?${params}`, { method: "POST" });
  if (!res.ok) throw new Error(`Failed to start ingestion: ${res.statusText}`);
}
