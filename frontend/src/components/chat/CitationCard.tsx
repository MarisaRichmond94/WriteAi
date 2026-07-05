import { useMemo } from "react";
import { clsx } from "clsx";
import type { Citation } from "../../types";
import { findQuoteRanges, segmentByRanges } from "../../lib/quoteHighlight";

interface Props {
  citation: Citation;
  index: number;
  isSelected: boolean;
  onClick: () => void;
  // Double-quoted spans from the answer text; any that appear verbatim in
  // this citation's snippet get highlighted on the card.
  answerQuotes?: string[];
}

const POV_PALETTE = [
  { bg: "bg-rose-500/25",   text: "text-rose-300",   ring: "ring-rose-500/40"   },
  { bg: "bg-sky-500/25",    text: "text-sky-300",    ring: "ring-sky-500/40"    },
  { bg: "bg-violet-500/25", text: "text-violet-300", ring: "ring-violet-500/40" },
  { bg: "bg-amber-500/25",  text: "text-amber-300",  ring: "ring-amber-500/40"  },
  { bg: "bg-teal-500/25",   text: "text-teal-300",   ring: "ring-teal-500/40"   },
  { bg: "bg-fuchsia-500/25",text: "text-fuchsia-300",ring: "ring-fuchsia-500/40"},
];

function povColor(pov: string) {
  let hash = 0;
  for (let i = 0; i < pov.length; i++) hash = (hash * 31 + pov.charCodeAt(i)) & 0xffff;
  return POV_PALETTE[hash % POV_PALETTE.length];
}

export default function CitationCard({ citation, index, isSelected, onClick, answerQuotes }: Props) {
  const relevance = Math.max(0, Math.min(100, Math.round((1 - citation.distance) * 100)));
  const pov = citation.pov ? povColor(citation.pov) : null;

  // Snippet segments with the answer's verbatim quotes marked; null when no
  // quote lands in this snippet (the card then stays in its compact form).
  const quotedSegments = useMemo(() => {
    if (!answerQuotes?.length || !citation.snippet) return null;
    const ranges = findQuoteRanges(citation.snippet, answerQuotes);
    return ranges.length ? segmentByRanges(citation.snippet, ranges) : null;
  }, [citation.snippet, answerQuotes]);

  return (
    <div
      className={clsx(
        "rounded-md border bg-surface overflow-hidden transition-colors",
        isSelected ? "border-white/50" : "border-surface-border"
      )}
    >
      <button
        onClick={onClick}
        className="flex w-full items-start gap-3 px-3 py-2.5 text-left hover:bg-surface-hover transition-colors"
      >
        {/* Rank badge */}
        <span className="mt-1 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-md bg-accent-subtle text-sm font-bold text-accent">
          {index}
        </span>

        {/* Content */}
        <div className="flex-1 min-w-0">
          {/* Row 1: book title + POV pill */}
          <div className="flex items-center gap-4 flex-wrap">
            <span className="text-base font-semibold text-ink-primary truncate">
              {citation.book}
            </span>
            {pov && (
              <span className={clsx("inline-flex items-center rounded-full px-1.5 py-px text-[9px] font-medium ring-1", pov.bg, pov.text, pov.ring)}>
                {citation.pov}
              </span>
            )}
          </div>

          {/* Row 2: chapter */}
          <p className="mt-1.5 text-[10px] text-ink-secondary">
            {citation.chapter === 0 ? "Prologue" : `Chapter ${citation.chapter}`}
            {citation.chapter_heading !== String(citation.chapter) &&
              ` · "${citation.chapter_heading}"`}
          </p>

          {/* Row 3 (optional): snippet with the answer's verbatim quote marked */}
          {quotedSegments && (
            <p className="mt-1.5 text-[10px] leading-relaxed text-ink-secondary">
              {quotedSegments.map((seg, si) =>
                seg.marked ? (
                  <mark key={si} className="rounded-sm px-0.5 bg-yellow-300/25 text-ink-primary">
                    {seg.text}
                  </mark>
                ) : (
                  <span key={si}>{seg.text}</span>
                )
              )}
            </p>
          )}

          {/* Row 4: relevance bar */}
          <div className="mt-1.5 flex items-center gap-2">
            <div className="h-0.5 w-16 rounded-full bg-surface-border overflow-hidden">
              <div
                className={clsx(
                  "h-full rounded-full transition-all",
                  relevance >= 75 ? "bg-green-400" : relevance > 50 ? "bg-yellow-400" : "bg-red-500"
                )}
                style={{ width: `${relevance}%` }}
              />
            </div>
            <span className="text-[9px] text-ink-muted">{relevance}% match</span>
          </div>
        </div>
      </button>
    </div>
  );
}
