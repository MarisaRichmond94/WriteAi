import { useEffect, useState } from "react";
import { Library, RefreshCw, Info, ChevronRight, FileDown } from "lucide-react";
import { clsx } from "clsx";
import type { BookResponse, BookSummary } from "../../types";
import { useAppStore } from "../../store/useAppStore";
import IndexStatusBar from "../sidebar/IndexStatusBar";
import ConfirmModal from "../ui/ConfirmModal";
import BookDrawer from "./BookDrawer";
import { fetchBookSummary, triggerRebuild, triggerBookUpdate, downloadStoryBible } from "../../api/books";
import { bookSlug } from "../../api/settings";

function BookListSkeleton() {
  return (
    <div className="flex flex-col gap-4 px-6">
      {[120, 80, 200, 150, 90].map((w, i) => (
        <div key={i} className="overflow-hidden rounded-lg border border-surface-border bg-surface-card">
          <div className="flex items-center gap-2 px-4 py-3">
            <div className="h-4 w-4 flex-shrink-0 rounded bg-surface-border animate-pulse" />
            <div className="h-4 rounded bg-surface-border animate-pulse" style={{ width: w }} />
            <div className="h-4 w-36 rounded bg-surface-border animate-pulse ml-2" />
            <div className="flex-1" />
            <div className="h-4 w-4 rounded bg-surface-border animate-pulse" />
          </div>
        </div>
      ))}
    </div>
  );
}

function formatLastSynced(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  const month = d.toLocaleDateString("en-US", { month: "long" });
  const day = d.getDate();
  const suffix = day % 10 === 1 && day !== 11 ? "st" : day % 10 === 2 && day !== 12 ? "nd" : day % 10 === 3 && day !== 13 ? "rd" : "th";
  const year = d.getFullYear();
  const time = d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }).toLowerCase();
  return `Last synced ${month} ${day}${suffix}, ${year} at ${time}`;
}


function CardStat({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="flex h-full flex-col items-center justify-center rounded-lg border border-surface-border bg-surface p-2.5 text-center">
      {value === null
        ? <div className="mx-auto h-4 w-8 animate-pulse rounded bg-surface-border" />
        : <p className="text-sm font-semibold text-ink-primary">{value.toLocaleString()}</p>}
      <p className="text-[10px] text-ink-muted">{label}</p>
    </div>
  );
}

function BookCard({ book, active, condensed, lastSynced, onClick, onRebuild }: {
  book: BookResponse;
  active: boolean;
  condensed: boolean;   // drawer open — column is half width, chips wrap to two rows
  lastSynced: string | null;
  onClick: () => void;
  onRebuild: () => void;
}) {
  const { showToast } = useAppStore();
  const [summary, setSummary] = useState<BookSummary | null>(null);
  const [coverState, setCoverState] = useState<"loading" | "loaded" | "error">("loading");
  const slug = bookSlug(book.name);

  useEffect(() => {
    fetchBookSummary(String(book.id)).then(setSummary).catch(() => {});
  }, [book.id]);

  const dates = summary?.date_span.first
    ? summary.date_span.first
      + (summary.date_span.last && summary.date_span.last !== summary.date_span.first
        ? ` - ${summary.date_span.last}` : "")
    : null;

  return (
    <div
      onClick={onClick}
      className={clsx(
        "flex cursor-pointer items-stretch gap-4 overflow-hidden rounded-lg border bg-surface-card p-5 transition-colors",
        active ? "border-accent/40" : "border-surface-border hover:border-accent/30"
      )}
    >
      {/* Cover */}
      {coverState !== "error" && (
        <div className="relative flex-shrink-0 overflow-hidden rounded" style={{ width: coverState === "loaded" ? "auto" : 100 }}>
          {coverState === "loading" && <div className="absolute inset-0 animate-pulse rounded bg-surface-border" />}
          <img
            src={`/api/settings/book-cover/${slug}`}
            alt={book.name}
            onLoad={() => setCoverState("loaded")}
            onError={() => setCoverState("error")}
            className={clsx("h-full w-auto rounded object-cover", coverState !== "loaded" && "invisible")}
          />
        </div>
      )}

      {/* Title + stats */}
      <div className="flex h-[180px] min-w-0 flex-1 flex-col gap-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className={clsx("truncate text-lg font-bold", active ? "text-accent" : "text-ink-primary")}>
              {book.name}
            </h2>
            {dates && <p className="mt-0.5 text-[11px] text-ink-muted">{dates}</p>}
            {lastSynced && <p className="mt-0.5 text-[10px] text-ink-muted/70">{lastSynced}</p>}
          </div>
          <div className="flex flex-shrink-0 items-center gap-1">
            <span
              role="button"
              title="Export story bible (.md)"
              onClick={(e) => {
                e.stopPropagation();
                showToast(`Exporting story bible for ${book.name}…`);
                downloadStoryBible(book.id).catch(() => showToast("Failed to export story bible."));
              }}
              className="rounded p-1 text-ink-muted transition-colors hover:bg-surface-hover hover:text-accent"
            >
              <FileDown className="h-3.5 w-3.5" />
            </span>
            <span
              role="button"
              title={`Re-index "${book.name}"`}
              onClick={(e) => { e.stopPropagation(); onRebuild(); }}
              className="rounded p-1 text-ink-muted transition-colors hover:bg-surface-hover hover:text-accent"
            >
              <RefreshCw className="h-3.5 w-3.5" />
            </span>
            <ChevronRight className={clsx("h-4 w-4 transition-transform", active ? "rotate-90 text-accent" : "text-ink-muted")} />
          </div>
        </div>

        <div className={clsx("grid min-h-0 flex-1 auto-rows-fr gap-2 transition-all duration-300", condensed ? "grid-cols-3" : "grid-cols-6")}>
          <CardStat label="Chapters" value={book.chapter_count} />
          <CardStat label="Characters" value={summary?.character_count ?? null} />
          <CardStat label="Locations" value={summary?.location_count ?? null} />
          <CardStat label="Events" value={summary?.event_count ?? null} />
          <CardStat label="Facts" value={summary?.fact_count ?? null} />
          <CardStat label="POV(s)" value={summary?.pov_breakdown.length ?? null} />
        </div>
      </div>
    </div>
  );
}

export default function StatusPane() {
  const { books, booksLoading, indexStatus, showToast } = useAppStore();
  const [activeBookId, setActiveBookId] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [rebuilding, setRebuilding] = useState(false);
  const [rebuildBook, setRebuildBook] = useState<string | null>(null);

  const handleBookRebuild = async () => {
    const name = rebuildBook;
    setRebuildBook(null);
    if (!name) return;
    try {
      await triggerBookUpdate(name);
      showToast(`Re-indexing "${name}" — this may take a minute.`);
    } catch {
      showToast(`Failed to start re-index for "${name}".`);
    }
  };

  const activeBook = books.find((b) => b.id === activeBookId) ?? null;

  const handleBookClick = (id: string) => {
    setActiveBookId((prev) => (prev === id ? null : id));
  };

  const handleConfirm = async () => {
    setConfirmOpen(false);
    setRebuilding(true);
    try {
      await triggerRebuild();
    } catch {
      showToast("Failed to start rebuild.");
    } finally {
      setRebuilding(false);
    }
  };

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Header — full width, static */}
      <div className="flex-shrink-0 px-6 pt-4 pb-3">
        <div className="flex items-center gap-2">
          <Library className="h-6 w-6 flex-shrink-0 text-accent" />
          <div>
            <div className="flex items-center gap-1">
              <p className="text-xs font-semibold uppercase tracking-widest text-ink-primary">
                Books
              </p>
              <div className="group relative">
                <Info className="h-3.5 w-3.5 text-ink-muted hover:text-ink-secondary transition-colors cursor-default" />
                <div className="pointer-events-none absolute left-0 top-5 z-50 w-72 rounded-md border border-surface-border bg-surface-card px-3 py-2 text-[11px] leading-relaxed text-ink-muted shadow-lg opacity-0 group-hover:opacity-100 transition-opacity duration-150">
                  The data shown here is representative of the data that has been extracted by AI when going over your book chapter to chapter to glean the valuable context needed to build an understanding of characters, events, facts, and significant locations
                </div>
              </div>
            </div>
            <p className="mt-0.5 text-[11px] text-ink-muted">
              Click on a book to view expanded details showing the insights that has been extracted
            </p>
          </div>
        </div>
        <div className="mt-3 border-t border-surface-border" />
      </div>

      {/* Body row — book list + drawer */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left column — full width when no book selected, w-64 when drawer is open */}
        <div className={clsx(
          "flex flex-shrink-0 flex-col overflow-hidden transition-all duration-300",
          activeBookId ? "w-1/2" : "w-full"
        )}>
          {/* Book list */}
          <div className="flex-1 overflow-y-auto">
            {booksLoading || rebuilding ? (
              <BookListSkeleton />
            ) : (
              <div className="flex flex-col gap-4 px-6">
                {books.map((book) => (
                  <BookCard
                    key={book.id}
                    book={book}
                    active={book.id === activeBookId}
                    condensed={activeBookId !== null}
                    lastSynced={formatLastSynced(indexStatus?.book_last_indexed?.[book.name])}
                    onClick={() => handleBookClick(book.id)}
                    onRebuild={() => setRebuildBook(book.name)}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex-shrink-0 border-t border-surface-border bg-surface-card p-4 space-y-3">
            <button
              onClick={() => setConfirmOpen(true)}
              disabled={rebuilding}
              className="flex w-full items-center justify-center gap-2 rounded-md border border-surface-border bg-surface px-3 py-[13px] text-xs text-ink-secondary hover:border-accent hover:text-accent transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <RefreshCw className={clsx("h-3 w-3", rebuilding && "animate-spin")} />
              {rebuilding ? "Rebuilding Index..." : "Rebuild Index"}
            </button>
            <div className="pl-5">
              <IndexStatusBar />
            </div>
          </div>
        </div>

        {/* Drawer */}
        <BookDrawer
          bookId={activeBookId}
          bookName={activeBook?.name ?? ""}
          chapters={activeBook?.chapters ?? []}
        />
      </div>

      <ConfirmModal
        open={rebuildBook !== null}
        title={`Re-index "${rebuildBook}"?`}
        message={`This will re-read every chapter in "${rebuildBook}", extract fresh data, and update its entries in the search index. It typically takes 1-2 minutes. Search results for this book may be incomplete while the update runs.`}
        confirmLabel="Re-index"
        onConfirm={handleBookRebuild}
        onCancel={() => setRebuildBook(null)}
      />

      <ConfirmModal
        open={confirmOpen}
        title="Rebuild the full index?"
        message="This re-processes every chapter across all 5 books and rebuilds the entire search index from scratch. It will take several minutes to complete and search results may be unavailable during that time."
        confirmLabel="Rebuild"
        onConfirm={handleConfirm}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  );
}
