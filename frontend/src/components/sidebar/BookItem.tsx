import { useState } from "react";
import { ChevronDown, ChevronRight, RefreshCw } from "lucide-react";
import { useAppStore } from "../../store/useAppStore";
import { triggerBookUpdate } from "../../api/books";
import ConfirmModal from "../ui/ConfirmModal";
import type { BookResponse } from "../../types";

interface Props {
  book: BookResponse;
}

export default function BookItem({ book }: Props) {
  const { showToast } = useAppStore();
  const [expanded, setExpanded] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const handleUpdateClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    setConfirmOpen(true);
  };

  const handleConfirm = async () => {
    setConfirmOpen(false);
    try {
      await triggerBookUpdate(book.name);
      showToast(`Re-indexing "${book.name}" started.`);
    } catch {
      showToast(`Failed to update "${book.name}".`);
    }
  };

  return (
    <li>
      <div
        className="group flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-ink-secondary transition-colors hover:bg-surface-hover hover:text-ink-primary"
        onClick={() => setExpanded((v) => !v)}
      >
        {/* Expand toggle */}
        <span className="h-4 w-4 flex-shrink-0 text-ink-muted">
          {expanded ? (
            <ChevronDown className="h-3.5 w-3.5" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5" />
          )}
        </span>

        {/* Book name */}
        <span className="flex-1 truncate text-sm font-medium">{book.name}</span>

        {/* Chapter count */}
        <span className="text-[10px] text-ink-muted">{book.chapter_count}ch</span>

        {/* Update button */}
        <button
          onClick={handleUpdateClick}
          title={`Re-index "${book.name}"`}
          className="flex h-5 w-5 items-center justify-center rounded text-ink-muted hover:text-accent"
        >
          <RefreshCw className="h-3 w-3" />
        </button>
      </div>

      {/* POV chips */}
      {expanded && (
        <div className="px-3 pb-2 pt-1">
          <p className="mb-1 text-[9px] uppercase tracking-widest text-ink-muted">POVs</p>
          <div className="flex flex-wrap gap-1">
            {book.povs.map((pov) => (
              <span
                key={pov}
                className="rounded-full bg-surface px-2 py-0.5 text-[10px] text-ink-muted border border-surface-border"
              >
                {pov.split(" ")[0]}
              </span>
            ))}
          </div>
        </div>
      )}

      <ConfirmModal
        open={confirmOpen}
        title={`Re-index "${book.name}"?`}
        message="This scans the book's chapters and rebuilds its search index. It may take a minute and will temporarily affect search results for this book."
        confirmLabel="Re-index"
        onConfirm={handleConfirm}
        onCancel={() => setConfirmOpen(false)}
      />
    </li>
  );
}
