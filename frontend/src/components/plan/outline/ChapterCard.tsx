import { useState, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { Calendar, X } from "lucide-react";
import { clsx } from "clsx";
import type { OutlineChapter } from "../../../types";
import StoryDatePicker from "./StoryDatePicker";
import { chapterLabel } from "../../../lib/format";
import RichTextArea from "./RichTextArea";

const POV_COLORS = [
  "bg-violet-500/15 text-violet-300",
  "bg-blue-500/15 text-blue-300",
  "bg-emerald-500/15 text-emerald-300",
  "bg-amber-500/15 text-amber-300",
  "bg-rose-500/15 text-rose-300",
  "bg-cyan-500/15 text-cyan-300",
  "bg-orange-500/15 text-orange-300",
  "bg-pink-500/15 text-pink-300",
  "bg-teal-500/15 text-teal-300",
  "bg-indigo-500/15 text-indigo-300",
];

function povColorClass(pov: string): string {
  let hash = 0;
  for (let i = 0; i < pov.length; i++) {
    hash = (hash * 31 + pov.charCodeAt(i)) % POV_COLORS.length;
  }
  return POV_COLORS[Math.abs(hash)];
}

interface ChapterCardProps {
  chapter: OutlineChapter;
  sortedIndex: number;
  hasDiff: boolean;
  diffCount: number;
  povSuggestions: string[];
  onDiffClick: () => void;
  onDelete: () => void;
  onSave: (partial: Omit<OutlineChapter, "id"> & { id?: string }) => void;
  disabled?: boolean;
}

export default function ChapterCard({
  chapter,
  sortedIndex,
  hasDiff,
  diffCount,
  povSuggestions,
  onDiffClick,
  onDelete,
  onSave,
  disabled = false,
}: ChapterCardProps) {
  const [hovered, setHovered] = useState(false);
  const [inlinePov, setInlinePov] = useState(chapter.pov ?? "");
  const [povFocused, setPovFocused] = useState(false);
  const [viewDatePickerOpen, setViewDatePickerOpen] = useState(false);
  const [inlineDate, setInlineDate] = useState(chapter.date ?? "");
  const [inlineSummary, setInlineSummary] = useState(chapter.writer_summary ?? "");
  const calendarBtnRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const [popoverPos, setPopoverPos] = useState<{ top: number; left: number } | null>(null);

  useEffect(() => {
    if (!viewDatePickerOpen) return;
    const handler = (e: MouseEvent) => {
      if (
        popoverRef.current?.contains(e.target as Node) ||
        calendarBtnRef.current?.contains(e.target as Node)
      ) return;
      setViewDatePickerOpen(false);
      setPopoverPos(null);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [viewDatePickerOpen]);

  const isSynced = chapter.status === "synced";

  useEffect(() => { setInlinePov(chapter.pov ?? ""); }, [chapter.pov]);
  useEffect(() => { setInlineDate(chapter.date ?? ""); }, [chapter.date]);
  useEffect(() => { setInlineSummary(chapter.writer_summary ?? ""); }, [chapter.writer_summary]);

  return (
      <div
        className={clsx(
          "group relative rounded-lg h-[250px] flex flex-col overflow-hidden transition-colors",
          chapter.chapter == null
            ? "border-2 border-dashed border-accent/40 bg-surface-card/70 hover:border-accent/60"
            : "border border-surface-border bg-surface-card hover:border-surface-border/80"
        )}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => { setHovered(false); setViewDatePickerOpen(false); setPopoverPos(null); }}
      >
        <div className="flex flex-col flex-1 min-h-0 px-4 py-3">

          {/* Status + actions row */}
          <div className="flex items-center justify-between">
            <span
              className={clsx(
                "flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium",
                isSynced ? "bg-emerald-500/10 text-emerald-400" : "bg-amber-500/10 text-amber-400"
              )}
            >
              <span className={clsx("h-1.5 w-1.5 rounded-full", isSynced ? "bg-emerald-400" : "bg-amber-400")} />
              {isSynced ? "Synced" : "Unsynced"}
            </span>

            {!disabled && (
              <button
                onClick={(e) => { e.stopPropagation(); onDelete(); }}
                className={clsx(
                  "rounded p-0.5 text-ink-muted hover:text-red-400 transition-colors",
                  hovered ? "opacity-100" : "opacity-0"
                )}
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>

          {/* Chapter name + inline POV combobox */}
          <div className="flex items-center gap-2 min-w-0 mt-3 leading-none">
            <span className="text-sm font-bold text-ink-primary flex-shrink-0 leading-none">
              {chapter.chapter != null ? chapterLabel(chapter.chapter) : `Chapter ${sortedIndex + 1}`}
            </span>
            <div className="relative flex-shrink-0">
              <input
                type="text"
                value={inlinePov}
                onChange={(e) => { setInlinePov(e.target.value); setPovFocused(true); }}
                onFocus={() => setPovFocused(true)}
                onBlur={() => {
                  setTimeout(() => setPovFocused(false), 150);
                  const trimmed = inlinePov.trim();
                  if (!disabled && trimmed !== chapter.pov) {
                    onSave({ ...chapter, pov: trimmed });
                  }
                }}
                placeholder="Enter POV"
                autoComplete="off"
                disabled={disabled}
                className={clsx(
                  "rounded-full px-2 py-0.5 text-[10px] font-medium border-none outline-none w-28 transition-colors cursor-text",
                  "focus:ring-1 focus:ring-accent/40",
                  povFocused ? "text-left" : "text-center",
                  inlinePov
                    ? povColorClass(inlinePov)
                    : "bg-surface-hover text-ink-muted",
                )}
              />
              {povFocused && (() => {
                const filtered = povSuggestions.filter(
                  (s) => s.toLowerCase().includes(inlinePov.toLowerCase()) && s !== inlinePov
                );
                return filtered.length > 0 ? (
                  <ul className="absolute z-20 left-0 mt-0.5 min-w-[120px] rounded border border-surface-border bg-surface-card shadow-lg overflow-hidden">
                    {filtered.map((s) => (
                      <li
                        key={s}
                        onMouseDown={() => {
                          setInlinePov(s);
                          setPovFocused(false);
                          onSave({ ...chapter, pov: s });
                        }}
                        className="px-3 py-1.5 text-[11px] text-ink-primary cursor-pointer hover:bg-surface-hover transition-colors"
                      >
                        {s}
                      </li>
                    ))}
                  </ul>
                ) : null;
              })()}
            </div>
          </div>

          {/* Date */}
          {(chapter.date || hovered) && (
            <div className="mt-1">
              <div className="flex items-center gap-2">
                <span className="text-[11px] text-ink-muted">
                  {inlineDate || <span className="text-ink-muted/40">No date</span>}
                </span>
                <button
                  ref={calendarBtnRef}
                  disabled={disabled}
                  onClick={(e) => {
                    e.stopPropagation();
                    if (viewDatePickerOpen) {
                      setViewDatePickerOpen(false);
                      setPopoverPos(null);
                    } else {
                      const rect = calendarBtnRef.current?.getBoundingClientRect();
                      if (rect) setPopoverPos({ top: rect.bottom + 6, left: rect.left });
                      setViewDatePickerOpen(true);
                    }
                  }}
                  className={clsx(
                    "transition-opacity transition-colors",
                    hovered ? "opacity-100" : "opacity-0",
                    viewDatePickerOpen ? "text-accent" : "text-ink-muted hover:text-ink-secondary"
                  )}
                  title="Pick date"
                >
                  <Calendar className="h-3.5 w-3.5" />
                </button>
              </div>

              {viewDatePickerOpen && popoverPos && createPortal(
                <div
                  ref={popoverRef}
                  className="fixed z-50 rounded-lg border border-surface-border bg-surface-card p-3 shadow-xl"
                  style={{ top: popoverPos.top, left: popoverPos.left }}
                >
                  <StoryDatePicker
                    value={inlineDate}
                    onChange={(val) => {
                      setInlineDate(val);
                      onSave({ ...chapter, date: val || null });
                    }}
                  />
                </div>,
                document.body
              )}
            </div>
          )}

          {/* Diff badge */}
          {hasDiff && (
            <button
              onClick={(e) => { e.stopPropagation(); onDiffClick(); }}
              className="mt-1 self-start rounded-full bg-yellow-500/10 px-2 py-0.5 text-[10px] font-medium text-yellow-400 hover:bg-yellow-500/20 transition-colors"
            >
              {diffCount} field{diffCount !== 1 ? "s" : ""} changed
            </button>
          )}

          {/* Summary — fills remaining height */}
          <div className="flex flex-col flex-1 min-h-0 mt-2">
            <RichTextArea
              value={inlineSummary}
              onChange={(html) => { if (!disabled) setInlineSummary(html); }}
              onBlur={() => {
                if (!disabled && inlineSummary !== chapter.writer_summary) {
                  onSave({ ...chapter, writer_summary: inlineSummary });
                }
              }}
              editable={!disabled}
              placeholder="Plan / summary…"
              className="flex-1 rounded border border-surface-border bg-surface/60 focus-within:border-accent/40 transition-colors"
            />
          </div>
        </div>
      </div>
  );
}
