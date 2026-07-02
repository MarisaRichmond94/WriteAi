import { useState, useRef, useEffect } from "react";
import { X } from "lucide-react";
import { clsx } from "clsx";
import type { OutlineChapter } from "../../../types";

interface ChapterSelectModalProps {
  open: boolean;
  chapters: OutlineChapter[];
  onReview: (chapterIds: string[]) => void;
  onCancel: () => void;
}

export default function ChapterSelectModal({
  open,
  chapters,
  onReview,
  onCancel,
}: ChapterSelectModalProps) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const lastClickedIndex = useRef<number | null>(null);
  const shiftHeld = useRef(false);

  const sorted = [...chapters].sort((a, b) => a.position - b.position);

  // Reset selection each time modal opens
  useEffect(() => {
    if (open) {
      setSelected(new Set());
      lastClickedIndex.current = null;
    }
  }, [open]);

  // Track shift key state independently — checkbox click events don't reliably carry shiftKey
  useEffect(() => {
    if (!open) return;
    const onDown = (e: KeyboardEvent) => { if (e.key === "Shift") shiftHeld.current = true; };
    const onUp = (e: KeyboardEvent) => { if (e.key === "Shift") shiftHeld.current = false; };
    window.addEventListener("keydown", onDown);
    window.addEventListener("keyup", onUp);
    return () => {
      window.removeEventListener("keydown", onDown);
      window.removeEventListener("keyup", onUp);
    };
  }, [open]);

  if (!open) return null;

  const toggleOne = (id: string, index: number) => {
    const shift = shiftHeld.current;
    setSelected((prev) => {
      const next = new Set(prev);
      if (shift && lastClickedIndex.current !== null) {
        const start = Math.min(lastClickedIndex.current, index);
        const end = Math.max(lastClickedIndex.current, index);
        for (let i = start; i <= end; i++) {
          next.add(sorted[i].id);
        }
      } else {
        if (next.has(id)) next.delete(id);
        else next.add(id);
      }
      return next;
    });
    // Only move the anchor on plain clicks — shift-clicks extend from the same anchor
    if (!shift) {
      lastClickedIndex.current = index;
    }
  };

  const allSelected = selected.size === sorted.length && sorted.length > 0;
  const toggleAll = () => {
    setSelected(allSelected ? new Set() : new Set(sorted.map((c) => c.id)));
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="flex flex-col w-full max-w-lg rounded-xl border border-surface-border bg-surface-card shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="border-b border-surface-border px-5 py-4 flex-shrink-0">
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-semibold uppercase tracking-widest text-ink-primary">
              Select Chapter(s) to Review
            </h2>
            <button
              onClick={onCancel}
              className="rounded p-1 text-ink-muted hover:text-ink-secondary transition-colors"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <p className="mt-1 text-[11px] text-ink-muted leading-relaxed">
            Choose one or more chapters and the AI will review them for structure, pacing, and continuity — drawing on your full extracted series data.
          </p>
        </div>

        {/* Select all row */}
        <div className="flex items-center justify-between bg-surface px-5 py-2 flex-shrink-0">
          <button
            onClick={toggleAll}
            className="text-[11px] text-ink-muted hover:text-ink-secondary transition-colors"
          >
            {allSelected ? "Deselect All" : "Select All"}
          </button>
          <span className="text-[11px] text-ink-muted">{selected.size} selected</span>
        </div>

        {/* Chapter list — max 10.5 cards tall then scrollable */}
        <div className="overflow-y-auto bg-surface px-5 py-2" style={{ maxHeight: "441px" }}>
          <div className="space-y-2.5">
            {sorted.map((ch, i) => {
              const isSelected = selected.has(ch.id);
              return (
                <div
                  key={ch.id}
                  onClick={(e) => {
                    if ((e.target as HTMLElement).tagName !== "INPUT") {
                      toggleOne(ch.id, i);
                    }
                  }}
                  className={clsx(
                    "flex items-center gap-3 px-3 py-2.5 rounded-lg cursor-pointer select-none transition-colors border border-surface-border",
                    isSelected
                      ? "bg-accent/10 border-accent/40"
                      : "bg-surface-card hover:bg-surface-hover"
                  )}
                >
                  {/* Checkbox — handles its own click to preserve shiftKey */}
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => {}}
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleOne(ch.id, i);
                    }}
                    className="h-3.5 w-3.5 flex-shrink-0 accent-accent cursor-pointer"
                  />

                  {/* Chapter label + dot + date */}
                  <div className="flex flex-1 items-center gap-2 min-w-0">
                    <span className="text-xs font-medium text-ink-primary flex-shrink-0">
                      {`Chapter ${ch.chapter ?? i + 1}`}
                    </span>
                    {ch.date && (
                      <>
                        <span className="h-1 w-1 flex-shrink-0 rounded-full bg-ink-muted/50" />
                        <span className="text-[11px] text-ink-muted truncate">{ch.date}</span>
                      </>
                    )}
                  </div>

                  {/* POV pill */}
                  {ch.pov && (
                    <span className="flex-shrink-0 rounded-full bg-surface-hover px-2 py-0.5 text-[10px] text-ink-secondary">
                      {ch.pov}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end border-t border-surface-border px-5 py-3 flex-shrink-0" style={{ gap: "8px" }}>
          <button
            onClick={onCancel}
            className="rounded-md px-3 py-1.5 text-xs text-ink-muted hover:text-ink-secondary transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => onReview([...selected])}
            disabled={selected.size === 0}
            className="rounded-md bg-accent px-4 py-1.5 text-xs font-medium text-white hover:bg-accent/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Review Selected ({selected.size})
          </button>
        </div>
      </div>
    </div>
  );
}
