import { useState, useRef, useEffect, useCallback } from "react";
import type { OutlineChapterDiff } from "../../../types";
import { chapterLabel } from "../../../lib/format";

interface DiffChapterRowProps {
  diff: OutlineChapterDiff;
  approved: boolean;
  onToggle: (shiftKey: boolean) => void;
}

function renderDiffValue(field: string, value: string | null): string {
  if (value === null || value === undefined) return "(none)";
  if (field === "extracted_bullets") {
    try {
      const bullets = JSON.parse(value) as string[];
      return bullets.map((b) => `• ${b}`).join("\n");
    } catch {
      return value;
    }
  }
  return value;
}

const FIELD_LABELS: Record<string, string> = {
  pov: "POV",
  date: "In-Universe Date",
  extracted_bullets: "Chapter Summary",
  heading: "Heading",
};

function ScrollableDiffValue({ value }: { value: string }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = useState(false);

  const check = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const hasOverflow = el.scrollHeight > el.clientHeight;
    const reachedBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 4;
    setAtBottom(hasOverflow && reachedBottom);
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const ro = new ResizeObserver(check);
    ro.observe(el);
    return () => ro.disconnect();
  }, [check]);

  return (
    <div>
      <div className="relative">
        <div
          ref={scrollRef}
          onScroll={check}
          className="max-h-[100px] overflow-y-auto"
        >
          <p className="text-ink-muted whitespace-pre-wrap leading-relaxed">{value}</p>
          {atBottom && (
            <button
              onClick={() => scrollRef.current?.scrollTo({ top: 0, behavior: "smooth" })}
              className="mt-1 w-full text-center text-[10px] text-ink-muted/60 hover:text-ink-muted transition-colors"
            >
              scroll to top
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function ScrollableDiffValueAfter({ value }: { value: string }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = useState(false);

  const check = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const hasOverflow = el.scrollHeight > el.clientHeight;
    const reachedBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 4;
    setAtBottom(hasOverflow && reachedBottom);
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const ro = new ResizeObserver(check);
    ro.observe(el);
    return () => ro.disconnect();
  }, [check]);

  return (
    <div>
      <div className="relative">
        <div
          ref={scrollRef}
          onScroll={check}
          className="max-h-[100px] overflow-y-auto"
        >
          <p className="text-ink-secondary whitespace-pre-wrap leading-relaxed">{value}</p>
          {atBottom && (
            <button
              onClick={() => scrollRef.current?.scrollTo({ top: 0, behavior: "smooth" })}
              className="mt-1 w-full text-center text-[10px] text-ink-muted/60 hover:text-ink-muted transition-colors"
            >
              scroll to top
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default function DiffChapterRow({ diff, approved, onToggle }: DiffChapterRowProps) {
  return (
    <div className="rounded-lg border border-surface-border bg-surface-card overflow-hidden">
      {/* Chapter header */}
      <div className="flex w-full items-center px-4 py-2.5">
        <div className="flex items-center gap-2">
          <label className="flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={approved}
              onChange={(e) => onToggle((e.nativeEvent as MouseEvent).shiftKey)}
              className="h-3 w-3 accent-accent"
            />
          </label>
          <span className="text-xs font-medium text-ink-secondary ml-[4px]">
            {chapterLabel(diff.chapter)}
          </span>
          <span className="rounded-full bg-yellow-500/10 px-2 py-0.5 text-[10px] font-medium text-yellow-400">
            {diff.diffs.length} field{diff.diffs.length !== 1 ? "s" : ""} changed
          </span>
        </div>
      </div>

      {/* Field diffs */}
      <div className="border-t border-surface-border divide-y divide-surface-border">
          {diff.diffs.map((d, i) => (
            <div key={i} className="grid grid-cols-2 gap-0 text-[11px]">
              <div className="px-4 py-2.5 bg-red-500/5 border-r border-surface-border">
                <p className="text-[10px] font-medium text-ink-muted mb-1 uppercase tracking-wide">
                  {FIELD_LABELS[d.field] ?? d.field} — Before
                </p>
                {d.field === "extracted_bullets" ? (
                  <ScrollableDiffValue value={renderDiffValue(d.field, d.old)} />
                ) : (
                  <p className="text-ink-muted whitespace-pre-wrap leading-relaxed">
                    {renderDiffValue(d.field, d.old)}
                  </p>
                )}
              </div>
              <div className="px-4 py-2.5 bg-emerald-500/5">
                <p className="text-[10px] font-medium text-ink-muted mb-1 uppercase tracking-wide">
                  {FIELD_LABELS[d.field] ?? d.field} — After
                </p>
                {d.field === "extracted_bullets" ? (
                  <ScrollableDiffValueAfter value={renderDiffValue(d.field, d.new)} />
                ) : (
                  <p className="text-ink-secondary whitespace-pre-wrap leading-relaxed">
                    {renderDiffValue(d.field, d.new)}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
    </div>
  );
}
