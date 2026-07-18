import { useMemo } from "react";
import { clsx } from "clsx";
import { ExternalLink } from "lucide-react";
import type { Citation } from "../../types";
import { useAppStore } from "../../store/useAppStore";
import {
  expandToSentenceWindow,
  findQuoteRanges,
  segmentByRanges,
  snapToSentence,
} from "../../lib/quoteHighlight";

interface Props {
  citation: Citation;
  index: number;
  isSelected: boolean;
  onClick: () => void;
  // Double-quoted spans from the answer text; any that appear verbatim in
  // this citation's full chunk text get highlighted on the card.
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
  const siteName = useAppStore((s) => s.siteName);
  const relevance = Math.max(0, Math.min(100, Math.round((1 - citation.distance) * 100)));
  const pov = citation.pov ? povColor(citation.pov) : null;

  // Deep-link into Loom's reader at this exact chapter. Loom resolves the
  // series (our site name) + book title + chapter *number* (prologue = 0) to
  // the chapter's cuid the same way the export manifest does — WriteAI has no
  // Loom ids to send. Only shown once we know the series name to build with.
  const loomUrl = import.meta.env.VITE_LOOM_URL ?? "http://localhost:3000";
  const loomHref = siteName
    ? `${loomUrl}/read/by-title/${encodeURIComponent(siteName)}/${encodeURIComponent(citation.book)}/${citation.chapter}`
    : null;

  // Prefer the full chunk text (new payloads) over the legacy 220-char
  // snippet so quotes deep in the chunk can still match.
  const chunkText = citation.text || citation.snippet;

  // When an answer quote lands in this chunk, show its enclosing sentence(s)
  // with the quote marked; null when no quote matches (compact card).
  const quotedSegments = useMemo(() => {
    if (!answerQuotes?.length || !chunkText) return null;
    const ranges = findQuoteRanges(chunkText, answerQuotes);
    if (!ranges.length) return null;
    // Window around the full span of matches, snapped to sentence boundaries.
    const span = { start: ranges[0].start, end: ranges[ranges.length - 1].end };
    const win = expandToSentenceWindow(chunkText, span, 400);
    const windowText = chunkText.slice(win.start, win.end);
    const shifted = ranges
      .filter((r) => r.end > win.start && r.start < win.end)
      .map((r) => ({
        start: Math.max(0, r.start - win.start),
        end: Math.min(windowText.length, r.end - win.start),
      }));
    return {
      segments: segmentByRanges(windowText, shifted),
      leadingEllipsis: win.leadingEllipsis,
      trailingEllipsis: win.trailingEllipsis,
    };
  }, [chunkText, answerQuotes]);

  // Compact form: a sentence-snapped snippet instead of the raw 220 prefix.
  const compactSnippet = useMemo(
    () => (quotedSegments || !chunkText ? null : snapToSentence(chunkText, 220)),
    [quotedSegments, chunkText]
  );

  return (
    <div
      className={clsx(
        "relative rounded-md border bg-surface overflow-hidden transition-colors",
        isSelected ? "border-white/50" : "border-surface-border"
      )}
    >
      {loomHref && (
        <a
          href={loomHref}
          target="_blank"
          rel="noopener noreferrer"
          title="Open this chapter in Loom"
          aria-label="Open this chapter in Loom"
          className="absolute right-1.5 top-1.5 z-10 flex h-6 w-6 items-center justify-center rounded-md text-ink-muted transition-colors hover:bg-surface-hover hover:text-accent"
        >
          <ExternalLink className="h-3.5 w-3.5" strokeWidth={1.5} />
        </a>
      )}
      <button
        onClick={onClick}
        className="flex w-full items-start gap-3 py-2.5 pl-3 pr-9 text-left hover:bg-surface-hover transition-colors"
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

          {/* Row 3 (optional): enclosing sentence(s) with the answer's
              verbatim quote marked — or a sentence-snapped snippet when no
              quote lands in this chunk */}
          {quotedSegments && (
            <p className="mt-1.5 text-[10px] leading-relaxed text-ink-secondary">
              {quotedSegments.leadingEllipsis && <span>… </span>}
              {quotedSegments.segments.map((seg, si) =>
                seg.marked ? (
                  <mark key={si} className="rounded-sm px-0.5 bg-yellow-300/25 text-ink-primary">
                    {seg.text}
                  </mark>
                ) : (
                  <span key={si}>{seg.text}</span>
                )
              )}
              {quotedSegments.trailingEllipsis && <span> …</span>}
            </p>
          )}
          {compactSnippet && (
            <p className="mt-1.5 text-[10px] leading-relaxed text-ink-secondary">
              {compactSnippet}
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
