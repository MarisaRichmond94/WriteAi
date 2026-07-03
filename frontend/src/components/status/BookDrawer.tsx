import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, ChevronDown, ChevronRight, ChevronUp, ChevronsUpDown, Link, RefreshCw } from "lucide-react";
import { clsx } from "clsx";
import type { BookSummary, ChapterSummary, Citation, ExtractedChapter, ExtractedKnowledgeItem } from "../../types";
import { fetchBookSummary, fetchExtractedChapter, fetchMissingChapters, triggerBookUpdate } from "../../api/books";
import { bookSlug } from "../../api/settings";
import { chapterLabel } from "../../lib/format";
import { useAppStore } from "../../store/useAppStore";
import ConfirmModal from "../ui/ConfirmModal";
import ChapterViewer from "../chat/ChapterViewer";

interface Props {
  bookId: string | null;
  bookName: string;
  chapters: ChapterSummary[];
}

// ── Skeleton helpers ──────────────────────────────────────────────
function SkeletonLine({ className, style }: { className?: string; style?: React.CSSProperties }) {
  return <div className={clsx("animate-pulse rounded bg-surface-border", className)} style={style} />;
}

function SummarySkeleton({ bookName }: { bookName: string }) {
  const slug = bookSlug(bookName);
  const [coverExists, setCoverExists] = useState<boolean | null>(null);

  return (
    <div className="border-b border-surface-border p-6 flex items-start gap-4">
      {/* Hidden img purely to detect cover existence — never shown */}
      <img
        src={`/api/settings/book-cover/${slug}`}
        onLoad={() => setCoverExists(true)}
        onError={() => setCoverExists(false)}
        className="hidden"
      />
      {/* Skeleton placeholder shown while unknown or confirmed present */}
      {coverExists !== false && (
        <SkeletonLine className="flex-shrink-0 rounded" style={{ height: "204px", width: "136px" }} />
      )}

      {/* Text skeleton */}
      <div className="flex flex-1 flex-col gap-4 min-w-0">
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-1.5">
            <SkeletonLine className="h-4 w-40" />
            <SkeletonLine className="h-3 w-56" />
          </div>
          <SkeletonLine className="h-8 w-28 flex-shrink-0 rounded-md" />
        </div>
        <div className="grid grid-cols-3 gap-2">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="rounded-lg border border-surface-border bg-surface p-3 space-y-2">
              <SkeletonLine className="mx-auto h-5 w-1/2" />
              <SkeletonLine className="mx-auto h-2.5 w-2/3" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function ChapterSkeleton() {
  return (
    <div className="divide-y divide-surface-border">
      {/* Summary */}
      <div className="space-y-2 px-6 py-3">
        <SkeletonLine className="h-3 w-20" />
        {[...Array(3)].map((_, i) => (
          <div key={i} className="flex items-start gap-1.5">
            <SkeletonLine className="mt-1.5 h-1 w-1 flex-shrink-0 rounded-full" />
            <SkeletonLine className={`h-2.5 ${["w-full", "w-4/5", "w-3/4"][i]}`} />
          </div>
        ))}
      </div>

      {/* Characters */}
      <div className="space-y-3 px-6 py-3">
        <SkeletonLine className="h-3 w-28" />
        {[...Array(3)].map((_, i) => (
          <div key={i} className="space-y-1.5">
            <div className="flex items-center gap-2">
              <SkeletonLine className="h-3 w-32" />
              <SkeletonLine className="h-2.5 w-24" />
            </div>
            <SkeletonLine className={`h-2.5 ${i % 2 === 0 ? "w-3/4" : "w-1/2"}`} />
          </div>
        ))}
      </div>

      {/* Events */}
      <div className="space-y-3 px-6 py-3">
        <SkeletonLine className="h-3 w-20" />
        {[...Array(2)].map((_, i) => (
          <div key={i} className="space-y-1.5">
            <div className="flex items-center gap-2">
              <SkeletonLine className="h-3 w-48" />
              <SkeletonLine className="h-4 w-16 rounded" />
            </div>
            <SkeletonLine className="h-2.5 w-full" />
            <SkeletonLine className="h-2.5 w-4/5" />
          </div>
        ))}
      </div>

      {/* Facts */}
      <div className="space-y-0 px-6 py-3">
        <SkeletonLine className="mb-3 h-3 w-16" />
        <div className="mb-2 flex gap-3 border-b border-surface-border pb-1.5">
          <SkeletonLine className="h-2.5 w-20" />
          <SkeletonLine className="h-2.5 w-12" />
        </div>
        {[...Array(5)].map((_, i) => (
          <div key={i} className="flex items-center gap-3 py-2.5">
            <SkeletonLine className="h-5 w-20 flex-shrink-0 rounded" />
            <SkeletonLine className={`h-2.5 ${["w-full", "w-4/5", "w-full", "w-3/5", "w-4/5"][i]}`} />
          </div>
        ))}
      </div>

    </div>
  );
}

// ── Summary card ─────────────────────────────────────────────────
function StatChip({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-surface-border bg-surface p-3 text-center">
      <p className="text-base font-semibold text-ink-primary">{value.toLocaleString()}</p>
      <p className="text-[10px] text-ink-muted">{label}</p>
    </div>
  );
}

function SummaryCard({ bookName, summary, chapterCount, onRebuild }: { bookName: string; summary: BookSummary; chapterCount: number; onRebuild: () => void }) {
  const slug = bookSlug(bookName);
  const [coverState, setCoverState] = useState<"loading" | "loaded" | "error">("loading");

  return (
    <div className="border-b border-surface-border p-6 flex items-start gap-4">
      {/* Book cover — skeleton while loading, real image once ready, hidden on error */}
      {coverState !== "error" && (
        <div className="relative flex-shrink-0 rounded overflow-hidden" style={{ height: "204px", width: coverState === "loaded" ? "auto" : "136px" }}>
          {coverState === "loading" && (
            <div className="absolute inset-0 animate-pulse rounded bg-surface-border" />
          )}
          <img
            src={`/api/settings/book-cover/${slug}`}
            alt={bookName}
            onLoad={() => setCoverState("loaded")}
            onError={() => setCoverState("error")}
            className={clsx("h-full w-auto rounded", coverState !== "loaded" && "invisible")}
            style={{ height: "204px" }}
          />
        </div>
      )}

      {/* Title + stats */}
      <div className="flex flex-1 flex-col gap-4 min-w-0">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-2xl font-bold text-ink-primary">{bookName}</h2>
            {(summary.date_span.first || summary.date_span.last) && (
              <p className="mt-0.5 text-xs text-ink-muted">
                {summary.date_span.first}
                {summary.date_span.last && summary.date_span.last !== summary.date_span.first
                  ? ` - ${summary.date_span.last}`
                  : ""}
              </p>
            )}
          </div>
          <button
            onClick={onRebuild}
            className="flex flex-shrink-0 items-center gap-2 rounded-md border border-surface-border bg-surface px-3 py-2 text-xs text-ink-secondary transition-colors hover:border-accent hover:text-accent"
          >
            <RefreshCw className="h-3 w-3" />
            Rebuild Index
          </button>
        </div>

        <div className="grid grid-cols-3 gap-2">
          <StatChip label="Chapters" value={chapterCount} />
          <StatChip label="Characters" value={summary.character_count} />
          <StatChip label="Locations" value={summary.location_count} />
          <StatChip label="Events" value={summary.event_count} />
          <StatChip label="Facts" value={summary.fact_count} />
          <StatChip label="POV(s)" value={summary.pov_breakdown.length} />
        </div>
      </div>
    </div>
  );
}

// ── POV color palette ─────────────────────────────────────────────
const POV_COLORS = [
  "bg-emerald-600 text-white",
  "bg-rose-500 text-white",
  "bg-teal-500 text-white",
  "bg-violet-500 text-white",
  "bg-orange-500 text-white",
  "bg-blue-500 text-white",
  "bg-amber-500 text-white",
  "bg-cyan-600 text-white",
];

function buildPovColorMap(chapters: ChapterSummary[]): Record<string, string> {
  const seen: Record<string, string> = {};
  let i = 0;
  for (const ch of chapters) {
    if (ch.pov && !(ch.pov in seen)) {
      seen[ch.pov] = POV_COLORS[i % POV_COLORS.length];
      i++;
    }
  }
  return seen;
}

// ── Event type colors ─────────────────────────────────────────────
const EVENT_TYPE_PALETTE = [
  "border border-rose-500/40 bg-rose-500/15 text-rose-400",
  "border border-violet-500/40 bg-violet-500/15 text-violet-400",
  "border border-blue-500/40 bg-blue-500/15 text-blue-400",
  "border border-emerald-500/40 bg-emerald-500/15 text-emerald-400",
  "border border-amber-500/40 bg-amber-500/15 text-amber-400",
  "border border-pink-500/40 bg-pink-500/15 text-pink-400",
  "border border-orange-500/40 bg-orange-500/15 text-orange-400",
  "border border-cyan-500/40 bg-cyan-500/15 text-cyan-400",
  "border border-indigo-500/40 bg-indigo-500/15 text-indigo-400",
  "border border-teal-500/40 bg-teal-500/15 text-teal-400",
];

function eventTypeColor(type: string): string {
  const hash = type.toLowerCase().split("").reduce((acc, ch) => acc + ch.charCodeAt(0), 0);
  return EVENT_TYPE_PALETTE[hash % EVENT_TYPE_PALETTE.length];
}

// ── Section navigator ─────────────────────────────────────────────
function NavSection({
  sectionRef,
  onScrollUp,
  onScrollDown,
  children,
}: {
  sectionRef: React.RefObject<HTMLDivElement>;
  onScrollUp?: () => void;
  onScrollDown?: () => void;
  children: React.ReactNode;
}) {
  const [hovered, setHovered] = useState(false);
  return (
    <div
      ref={sectionRef}
      className="relative px-6 py-3"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {hovered && onScrollUp && (
        <button
          onClick={onScrollUp}
          className="absolute left-1/2 top-0 z-10 -translate-x-1/2 -translate-y-1/2 rounded-full border border-surface-border bg-surface p-0.5 text-ink-muted shadow-sm transition-colors hover:border-accent hover:text-accent"
        >
          <ChevronUp className="h-3 w-3" />
        </button>
      )}
      {children}
      {hovered && onScrollDown && (
        <button
          onClick={onScrollDown}
          className="absolute bottom-0 left-1/2 z-10 -translate-x-1/2 translate-y-1/2 rounded-full border border-surface-border bg-surface p-0.5 text-ink-muted shadow-sm transition-colors hover:border-accent hover:text-accent"
        >
          <ChevronDown className="h-3 w-3" />
        </button>
      )}
    </div>
  );
}

// ── Chapter row ───────────────────────────────────────────────────
const FACT_LABELS: Record<string, string> = {
  character_attribute: "Character",
  location: "Location",
  timeline: "Timeline",
  organization: "Org",
  other: "Other",
};

const FACT_CATEGORY_COLORS: Record<string, string> = {
  character_attribute: "border border-blue-500/40 bg-blue-500/15 text-blue-400",
  location:            "border border-emerald-500/40 bg-emerald-500/15 text-emerald-400",
  timeline:            "border border-amber-500/40 bg-amber-500/15 text-amber-400",
  organization:        "border border-violet-500/40 bg-violet-500/15 text-violet-400",
  other:               "border border-surface-border bg-surface text-ink-muted",
};

function factCategoryColor(category: string): string {
  return FACT_CATEGORY_COLORS[category.toLowerCase()] ?? FACT_CATEGORY_COLORS.other;
}

function SourceQuoteIcon({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      title="View source passage"
      className="mt-0.5 flex-shrink-0 text-ink-muted/50 hover:text-accent transition-colors opacity-0 group-hover:opacity-100"
    >
      <Link className="h-3 w-3" />
    </button>
  );
}

function KnowledgeGainedRow({ item, onSourceClick }: { item: ExtractedKnowledgeItem; onSourceClick?: () => void }) {
  return (
    <div className="group flex items-start gap-1.5">
      <p className="flex-1 text-[11px] italic text-ink-muted">{item.insight}</p>
      {item.source_quote && onSourceClick && <SourceQuoteIcon onClick={onSourceClick} />}
    </div>
  );
}

function ChapterRow({
  chapter,
  bookId,
  bookName,
  isExpanded,
  onToggle,
  povColor,
  isMissing,
  onOpenViewer,
}: {
  chapter: ChapterSummary;
  bookId: string;
  bookName: string;
  isExpanded: boolean;
  onToggle: () => void;
  povColor: string;
  isMissing: boolean;
  onOpenViewer: (citation: Citation) => void;
}) {
  const [data, setData] = useState<ExtractedChapter | null>(null);
  const [loading, setLoading] = useState(false);
  const [factsSort, setFactsSort] = useState<"asc" | "desc" | null>(null);
  const headerRef = useRef<HTMLButtonElement>(null);
  const summaryRef = useRef<HTMLDivElement>(null);
  const charRef = useRef<HTMLDivElement>(null);
  const eventsRef = useRef<HTMLDivElement>(null);
  const factsRef = useRef<HTMLDivElement>(null);

  const openQuote = useCallback((quote: string) => {
    onOpenViewer({
      book: bookName,
      chapter: chapter.chapter,
      chapter_heading: String(chapter.chapter),
      pov: chapter.pov,
      date: chapter.date ?? null,
      chunk_index: 0,
      snippet: quote,
      distance: 0,
    });
  }, [bookName, chapter, onOpenViewer]);

  useEffect(() => {
    if (!isExpanded) return;
    requestAnimationFrame(() => {
      headerRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }, [isExpanded]);

  useEffect(() => {
    if (!isExpanded || data) return;
    setLoading(true);
    Promise.all([
      fetchExtractedChapter(bookId, chapter.chapter),
      new Promise((r) => setTimeout(r, 1200)),
    ])
      .then(([result]) => setData(result as ExtractedChapter))
      .finally(() => setLoading(false));
  }, [isExpanded]);

  return (
    <div className="border-b border-surface-border last:border-0">
      {/* Row header */}
      <button
        ref={headerRef}
        onClick={onToggle}
        className="flex w-full items-center gap-3 px-6 py-2.5 text-left transition-colors hover:bg-surface-hover"
      >
        <span className="text-ink-muted">
          {isExpanded
            ? <ChevronDown className="h-3.5 w-3.5" />
            : <ChevronRight className="h-3.5 w-3.5" />
          }
        </span>
        <span className="flex flex-1 items-center gap-2">
          <span className="text-xs font-medium text-ink-secondary">{chapterLabel(chapter.chapter)}</span>
          <span className={clsx("rounded-full px-2.5 py-0.5 text-[10px] font-medium", povColor)}>
            {chapter.pov}
          </span>
          {isMissing && (
            <AlertTriangle className="h-3 w-3 flex-shrink-0 text-amber-400" />
          )}
        </span>
        {chapter.date && (
          <span className="flex-shrink-0 text-[10px] text-ink-muted">{chapter.date}</span>
        )}
      </button>

      {/* Expanded content */}
      {isExpanded && (
        <div className="bg-surface/50">
          {loading ? (
            <ChapterSkeleton />
          ) : !data ? (
            <p className="px-6 py-3 text-xs text-ink-muted">No data available.</p>
          ) : (() => {
            const sorted = factsSort
              ? [...data.facts].sort((a, b) => {
                  const la = FACT_LABELS[a.category] ?? a.category;
                  const lb = FACT_LABELS[b.category] ?? b.category;
                  return factsSort === "asc" ? la.localeCompare(lb) : lb.localeCompare(la);
                })
              : data.facts;
            const activeRefs = [
              data.summary.length > 0 ? summaryRef : null,
              data.characters.length > 0 ? charRef : null,
              data.events.length > 0 ? eventsRef : null,
              data.facts.length > 0 ? factsRef : null,
            ].filter(Boolean) as React.RefObject<HTMLDivElement>[];
            const scrollTo = (ref: React.RefObject<HTMLDivElement>) =>
              ref.current?.scrollIntoView({ behavior: "smooth", block: "start" });
            const prev = (ref: React.RefObject<HTMLDivElement>) => {
              const i = activeRefs.indexOf(ref);
              return i > 0 ? () => scrollTo(activeRefs[i - 1]) : undefined;
            };
            const next = (ref: React.RefObject<HTMLDivElement>) => {
              const i = activeRefs.indexOf(ref);
              return i < activeRefs.length - 1 ? () => scrollTo(activeRefs[i + 1]) : undefined;
            };
            return (
              <div className="divide-y divide-surface-border">
                {/* Summary */}
                {data.summary.length > 0 && (
                  <NavSection sectionRef={summaryRef} onScrollUp={prev(summaryRef)} onScrollDown={next(summaryRef)}>
                    <p className="mb-2 text-xs font-bold uppercase tracking-widest text-ink-primary">
                      Summary
                    </p>
                    <ul className="max-h-[200px] space-y-1 overflow-y-auto pr-1">
                      {data.summary.map((bullet, i) => (
                        <li key={i} className="flex items-start gap-1.5">
                          <span className="mt-1.5 h-1 w-1 flex-shrink-0 rounded-full bg-ink-muted/50" />
                          <p className="text-[11px] text-ink-secondary">{bullet}</p>
                        </li>
                      ))}
                    </ul>
                  </NavSection>
                )}

                {/* Characters */}
                {data.characters.length > 0 && (
                  <NavSection sectionRef={charRef} onScrollUp={prev(charRef)} onScrollDown={next(charRef)}>
                    <p className="mb-2 text-xs font-bold uppercase tracking-widest text-ink-primary">
                      Characters ({data.characters.length})
                    </p>
                    <div className="max-h-[200px] space-y-3 overflow-y-auto pr-1">
                      {data.characters.map((c, i) => {
                        // no POV badge: the chapter header already names the POV
                        const role = c.role.replace(/^POV character[;,]?\s*/i, "");
                        return (
                          <div key={i}>
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className="text-xs font-medium text-ink-primary">{c.name}</span>
                              {c.aliases && c.aliases.length > 0 && (
                                <span className="text-[10px] text-ink-muted">
                                  ({c.aliases.slice(0, 3).join(", ")})
                                </span>
                              )}
                            </div>
                            {role && <p className="mt-0.5 text-[11px] text-ink-secondary">{role}</p>}
                            {c.knowledge_gained && c.knowledge_gained.length > 0 && (
                              <div className="mt-1 space-y-1">
                                {c.knowledge_gained.map((item, j) => (
                                  <KnowledgeGainedRow
                                    key={j}
                                    item={item}
                                    onSourceClick={item.source_quote ? () => openQuote(item.source_quote!) : undefined}
                                  />
                                ))}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </NavSection>
                )}

                {/* Events */}
                {data.events.length > 0 && (
                  <NavSection sectionRef={eventsRef} onScrollUp={prev(eventsRef)} onScrollDown={next(eventsRef)}>
                    <p className="mb-2 text-xs font-bold uppercase tracking-widest text-ink-primary">
                      Events ({data.events.length})
                    </p>
                    <div className="max-h-[200px] space-y-2 overflow-y-auto pr-1">
                      {data.events.map((e, i) => (
                        <div key={i} className="group flex items-start gap-1.5">
                          <div className="flex-1 min-w-0">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className="text-xs font-medium text-ink-primary">{e.title}</span>
                              <span className={clsx("rounded px-1.5 py-0.5 text-[9px] capitalize font-medium", eventTypeColor(e.type))}>
                                {e.type.replace(/_/g, " ")}
                              </span>
                            </div>
                            <p className="text-[11px] text-ink-secondary">{e.summary}</p>
                          </div>
                          {e.source_quotes && e.source_quotes.length > 0 && (
                            <SourceQuoteIcon onClick={() => openQuote(e.source_quotes![0].quote)} />
                          )}
                        </div>
                      ))}
                    </div>
                  </NavSection>
                )}

                {/* Facts */}
                {data.facts.length > 0 && (
                  <NavSection sectionRef={factsRef} onScrollUp={prev(factsRef)} onScrollDown={next(factsRef)}>
                    <p className="mb-2 text-xs font-bold uppercase tracking-widest text-ink-primary">
                      Facts ({data.facts.length})
                    </p>
                    <div className="mb-1 flex items-center gap-3 border-b border-surface-border pb-1.5">
                      <button
                        onClick={() => setFactsSort((s) => s === "asc" ? "desc" : s === "desc" ? null : "asc")}
                        className="flex w-20 flex-shrink-0 items-center gap-1 text-[9px] font-semibold uppercase tracking-widest text-ink-muted hover:text-ink-secondary transition-colors"
                      >
                        Type
                        {factsSort === "asc"  ? <ChevronUp className="h-3 w-3" /> :
                         factsSort === "desc" ? <ChevronDown className="h-3 w-3" /> :
                                                <ChevronsUpDown className="h-3 w-3 opacity-40" />}
                      </button>
                      <span className="text-[9px] font-semibold uppercase tracking-widest text-ink-muted">Detail</span>
                    </div>
                    <div className="max-h-[200px] divide-y divide-surface-border/40 overflow-y-auto pr-1">
                      {sorted.map((f, i) => (
                        <div key={i} className="group flex items-center gap-3 py-2.5">
                          <span className={clsx("w-20 flex-shrink-0 rounded px-1.5 py-0.5 text-center text-[9px] font-medium", factCategoryColor(f.category))}>
                            {FACT_LABELS[f.category] ?? f.category}
                          </span>
                          <p className="flex-1 text-[11px] text-ink-secondary">{f.statement}</p>
                          {f.source_quote && (
                            <SourceQuoteIcon onClick={() => openQuote(f.source_quote!)} />
                          )}
                        </div>
                      ))}
                    </div>
                  </NavSection>
                )}

              </div>
            );
          })()}

          {/* Scroll to top */}
          <div className="flex justify-center border-t border-surface-border py-3">
            <button
              onClick={() => headerRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })}
              className="flex items-center gap-1.5 text-[11px] text-ink-muted transition-colors hover:text-ink-secondary"
            >
              <ChevronUp className="h-3 w-3" />
              Scroll To Top
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main drawer ───────────────────────────────────────────────────
export default function BookDrawer({ bookId, bookName, chapters }: Props) {
  const { showToast } = useAppStore();
  const [summary, setSummary] = useState<BookSummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [expandedChapter, setExpandedChapter] = useState<number | null>(null);
  const [missingChapters, setMissingChapters] = useState<Set<number>>(new Set());
  const [rebuildOpen, setRebuildOpen] = useState(false);
  const [viewerOpen, setViewerOpen] = useState(false);
  const [activeCitation, setActiveCitation] = useState<Citation | null>(null);
  const [lightMode, setLightMode] = useState(() => useAppStore.getState().appSettings?.viewer_light_mode ?? true);
  const povColorMap = buildPovColorMap(chapters);

  const handleRebuildConfirm = async () => {
    setRebuildOpen(false);
    try {
      await triggerBookUpdate(bookName);
      showToast(`Re-indexing "${bookName}" — this may take a minute.`);
    } catch {
      showToast(`Failed to start re-index for "${bookName}".`);
    }
  };

  const handleOpenViewer = useCallback((citation: Citation) => {
    setActiveCitation(citation);
    setViewerOpen(true);
  }, []);

  const handleCloseViewer = useCallback(() => {
    setViewerOpen(false);
    // activeCitation is intentionally kept alive so the viewer stays mounted
    // behind the chapter list — cleared only when the book changes.
  }, []);

  useEffect(() => {
    if (!viewerOpen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") handleCloseViewer(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [viewerOpen, handleCloseViewer]);

  useEffect(() => {
    if (!bookId) {
      setSummary(null);
      setExpandedChapter(null);
      setViewerOpen(false);
      setActiveCitation(null);
      return;
    }
    setSummary(null);
    setExpandedChapter(null);
    setViewerOpen(false);
    setActiveCitation(null);
    setMissingChapters(new Set());
    setSummaryLoading(true);
    Promise.all([
      fetchBookSummary(bookId),
      new Promise((r) => setTimeout(r, 1200)),
    ])
      .then(([result]) => setSummary(result as BookSummary))
      .finally(() => setSummaryLoading(false));
    fetchMissingChapters(bookId)
      .then((nums) => setMissingChapters(new Set(nums)))
      .catch(() => {/* silent — warning icons just won't show */});
  }, [bookId]);

  const handleChapterToggle = (num: number) => {
    setExpandedChapter((prev) => (prev === num ? null : num));
  };

  return (
    <div
      className={clsx(
        "flex flex-col overflow-hidden transition-all duration-300",
        bookId ? "w-1/2 border-l border-surface-border" : "w-0"
      )}
    >
      {bookId && (
        <>
          {/* Summary — always rendered */}
          {summaryLoading ? (
            <SummarySkeleton bookName={bookName} />
          ) : summary ? (
            <SummaryCard bookName={bookName} summary={summary} chapterCount={chapters.length} onRebuild={() => setRebuildOpen(true)} />
          ) : null}

          {/* Chapter list + viewer overlay share the remaining space */}
          <div className="relative flex-1 overflow-hidden">
            {/* Chapter list — always mounted, never unmounts on viewer open/close */}
            <div className="absolute inset-0 overflow-y-auto">
              {chapters.map((ch) => (
                <ChapterRow
                  key={ch.chapter}
                  chapter={ch}
                  bookId={bookId}
                  bookName={bookName}
                  isExpanded={expandedChapter === ch.chapter}
                  onToggle={() => handleChapterToggle(ch.chapter)}
                  povColor={povColorMap[ch.pov] ?? POV_COLORS[0]}
                  isMissing={missingChapters.has(ch.chapter)}
                  onOpenViewer={handleOpenViewer}
                />
              ))}
            </div>

            {/* Viewer — slides in over the chapter list, stays mounted once opened */}
            <div className={clsx(
              "absolute inset-0 transition-transform duration-300",
              viewerOpen ? "translate-x-0" : "translate-x-full"
            )}>
              {activeCitation && (
                <ChapterViewer
                  citation={activeCitation}
                  bookId={bookId}
                  lightMode={lightMode}
                  onToggleLightMode={() => setLightMode((m) => !m)}
                  onClose={handleCloseViewer}
                  onBack={handleCloseViewer}
                />
              )}
            </div>
          </div>

          <ConfirmModal
            open={rebuildOpen}
            title={`Re-index "${bookName}"?`}
            message={`This will re-read every chapter in "${bookName}", extract fresh data, and update its entries in the search index. It typically takes 1–2 minutes to complete. Search results for this book may return incomplete or outdated results while the update is running — all other books will continue working normally.`}
            confirmLabel="Re-index"
            onConfirm={handleRebuildConfirm}
            onCancel={() => setRebuildOpen(false)}
          />
        </>
      )}
    </div>
  );
}
