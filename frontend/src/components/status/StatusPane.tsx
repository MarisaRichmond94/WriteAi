import { useState } from "react";
import { Library, RefreshCw, Info, BookOpen, ChevronRight, FileDown } from "lucide-react";
import { clsx } from "clsx";
import { useAppStore } from "../../store/useAppStore";
import IndexStatusBar from "../sidebar/IndexStatusBar";
import ConfirmModal from "../ui/ConfirmModal";
import BookDrawer from "./BookDrawer";
import { triggerRebuild, downloadStoryBible } from "../../api/books";

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

export default function StatusPane() {
  const { books, booksLoading, indexStatus, showToast } = useAppStore();
  const [activeBookId, setActiveBookId] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [rebuilding, setRebuilding] = useState(false);

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
      <div className="dark-zone bg-surface flex-shrink-0 px-6 pt-4 pb-3">
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
                {books.map((book) => {
                  const active = book.id === activeBookId;
                  return (
                    <div
                      key={book.id}
                      className={clsx(
                        "overflow-hidden rounded-lg border bg-surface-card transition-colors",
                        active ? "border-accent/40" : "border-surface-border"
                      )}
                    >
                      <button
                        onClick={() => handleBookClick(book.id)}
                        className="flex w-full items-center gap-2 px-4 py-3 hover:bg-surface-hover transition-colors"
                      >
                        <BookOpen className="h-3.5 w-3.5 flex-shrink-0 text-accent" />
                        <span className={clsx(
                          "text-left text-[11px] font-semibold uppercase tracking-widest",
                          active ? "text-accent" : "text-ink-secondary"
                        )}>
                          {book.name}
                        </span>
                        {formatLastSynced(indexStatus?.book_last_indexed?.[book.name]) && (
                          <span className="ml-2 flex-shrink-0 text-[10px] text-ink-muted">
                            {formatLastSynced(indexStatus?.book_last_indexed?.[book.name])}
                          </span>
                        )}
                        <span className="flex-1" />
                        <span
                          role="button"
                          title="Export story bible (.md)"
                          onClick={(e) => {
                            e.stopPropagation();
                            showToast(`Exporting story bible for ${book.name}…`);
                            downloadStoryBible(book.id)
                              .catch(() => showToast("Failed to export story bible."));
                          }}
                          className="mr-1 flex-shrink-0 p-1 rounded text-ink-muted hover:text-accent hover:bg-surface-hover transition-colors"
                        >
                          <FileDown className="h-3.5 w-3.5" />
                        </span>
                        <ChevronRight className="h-3.5 w-3.5 text-ink-muted" />
                      </button>
                    </div>
                  );
                })}
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
