import { useEffect, useMemo, useRef, useState } from "react";
import clsx from "clsx";
import {
  ArrowDown,
  ArrowUp,
  Calendar,
  ChevronLeft,
  ChevronRight,
  Clock,
  MapPin,
  Sparkles,
  X,
  Zap,
} from "lucide-react";
import { useApp } from "../../store";
import type { TimelineEvent } from "../../types";
import { api } from "../../lib/api";
import { bookColor, EVENT_DOT_HEX, EVENT_TYPE_COLORS, initials, povColor } from "../../lib/palette";
import { Button, Spinner } from "../ui";
import { Dropdown, PaneHeader, Segmented } from "../shared";

// chart geometry (matches the reference)
const CARD_W = 160;
const CARD_GAP = 48;
const AXIS_Y = 176;
const CHART_H = 340;

const ZOOMS = [
  { value: "0", label: "Overview" },
  { value: "1", label: "Mid" },
  { value: "2", label: "Detailed" },
];

export function TimelinePane() {
  const { books, toast, setPane } = useApp();
  const [events, setEvents] = useState<TimelineEvent[] | null>(null);
  const [view, setView] = useState<"chart" | "list">("chart");
  const [zoom, setZoom] = useState("1");
  const [newestFirst, setNewestFirst] = useState(false);
  const [povFilter, setPovFilter] = useState("all");
  const [bookFilter, setBookFilter] = useState("all");
  const [selected, setSelected] = useState<TimelineEvent | null>(null);
  const [source, setSource] = useState<{ chunkId: string } | null>(null);

  useEffect(() => {
    const params = new URLSearchParams();
    if (bookFilter !== "all") params.set("book", bookFilter);
    setEvents(null);
    setSelected(null);
    api<{ events: TimelineEvent[] }>(`/api/events?${params}`)
      .then((d) => setEvents(d.events))
      .catch((e) => toast(String(e), "error"));
  }, [bookFilter]);

  const povs = Array.from(new Set(books.flatMap((b) => b.povs))).sort();

  const visible = useMemo(() => {
    let evs = events ?? [];
    if (povFilter !== "all") evs = evs.filter((e) => e.participants.includes(povFilter));
    if (zoom === "0") evs = evs.filter((e) => e.granularity === "major");
    else if (zoom === "1") evs = evs.filter((e) => e.granularity !== "minor");
    return newestFirst ? [...evs].reverse() : evs;
  }, [events, povFilter, zoom, newestFirst]);

  const index = selected ? visible.findIndex((e) => e.id === selected.id) : -1;
  const nav = (dir: 1 | -1) => {
    if (!visible.length) return;
    setSelected(visible[Math.min(visible.length - 1, Math.max(0, index + dir))]);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.altKey && e.key === "ArrowRight") nav(1);
      if (e.altKey && e.key === "ArrowLeft") nav(-1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (events !== null && events.length === 0 && bookFilter === "all") {
    return (
      <div className="flex h-full flex-col">
        <PaneHeader icon={Clock} title="Timeline" subtitle="Significant events extracted from the series. Select an event to view expanded details." />
        <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
          <Zap className="h-8 w-8 text-ink-muted" strokeWidth={1} />
          <p className="text-sm font-medium text-ink-secondary">No timeline events yet</p>
          <p className="text-xs text-ink-muted">
            Run the enrichment pass to distill events from your extracted metadata.
          </p>
          <Button onClick={() => setPane("books")}>
            <Sparkles className="h-3.5 w-3.5" strokeWidth={1.5} /> Open Books → Enrich
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full">
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <PaneHeader
          icon={Clock}
          title="Timeline"
          info="Events are curated from extraction notes by the enrichment pass. Zoom filters by how consequential an event is."
          subtitle="Significant events extracted from the series. Select an event to view expanded details."
        />

        {/* controls */}
        <div className="flex flex-shrink-0 items-center justify-between gap-3 px-6 pb-4">
          <div className="flex items-center gap-2">
            <Segmented
              options={[
                { value: "chart", label: "Chart" },
                { value: "list", label: "List" },
              ]}
              value={view}
              onChange={(v) => setView(v as "chart" | "list")}
            />
            {view === "chart" && <Segmented options={ZOOMS} value={zoom} onChange={setZoom} />}
            <button
              onClick={() => setNewestFirst((v) => !v)}
              className="flex items-center gap-1 rounded border border-surface-border bg-surface px-2.5 py-1 text-[11px] text-ink-secondary transition-colors hover:border-accent hover:text-ink-primary"
            >
              {newestFirst ? (
                <>
                  <ArrowDown className="h-3 w-3" strokeWidth={1.5} /> Newest First
                </>
              ) : (
                <>
                  <ArrowUp className="h-3 w-3" strokeWidth={1.5} /> Oldest First
                </>
              )}
            </button>
          </div>
          <div className="flex items-center gap-2">
            <Dropdown
              label="All POVs"
              value={povFilter}
              onChange={setPovFilter}
              align="right"
              options={[{ value: "all", label: "All POVs" }, ...povs.map((p) => ({ value: p, label: p }))]}
            />
            <Dropdown
              label="All Books"
              value={bookFilter}
              onChange={setBookFilter}
              align="right"
              options={[
                { value: "all", label: "All Books" },
                ...books.map((b) => ({ value: String(b.id), label: b.name })),
              ]}
            />
          </div>
        </div>

        {events === null ? (
          <div className="flex flex-1 items-center justify-center">
            <Spinner className="h-5 w-5" />
          </div>
        ) : (
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
            <div className="flex-shrink-0">
              {view === "chart" ? (
                <ChartView events={visible} selectedId={selected?.id ?? null} onSelect={setSelected} />
              ) : (
                <ListView events={visible} selectedId={selected?.id ?? null} onSelect={setSelected} />
              )}
            </div>
            <DetailPanel
              event={selected}
              index={index}
              total={visible.length}
              onNav={nav}
              onSource={(chunkId) => setSource({ chunkId })}
              bookName={(n) => books.find((b) => b.id === n)?.name ?? `Book ${n}`}
            />
          </div>
        )}
      </div>
      {source && <HighlightedSourceViewer chunkId={source.chunkId} onClose={() => setSource(null)} />}
    </div>
  );
}

// ── chart view (horizontal SVG axis, cards alternating above/below) ─────────

function ChartView({
  events,
  selectedId,
  onSelect,
}: {
  events: TimelineEvent[];
  selectedId: number | null;
  onSelect: (e: TimelineEvent) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const totalW = Math.max(events.length * (CARD_W + CARD_GAP) + CARD_GAP, 800);

  useEffect(() => {
    if (selectedId == null || !containerRef.current) return;
    const idx = events.findIndex((e) => e.id === selectedId);
    if (idx < 0) return;
    const x = CARD_GAP + idx * (CARD_W + CARD_GAP);
    containerRef.current.scrollTo({ left: Math.max(0, x - 24), behavior: "smooth" });
  }, [selectedId]);

  if (events.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
        <Zap className="h-8 w-8 text-ink-muted" strokeWidth={1} />
        <p className="text-xs text-ink-muted">No events match these filters.</p>
      </div>
    );
  }

  return (
    <div ref={containerRef} className="overflow-x-auto overflow-y-hidden" style={{ height: `${CHART_H}px` }}>
      <svg width={totalW} height={CHART_H} className="select-none">
        <line x1={0} y1={AXIS_Y} x2={totalW} y2={AXIS_Y} stroke="#2a2d3a" strokeWidth={1.5} />
        {events.map((ev, idx) => {
          const cx = CARD_GAP + idx * (CARD_W + CARD_GAP) + CARD_W / 2;
          const above = idx % 2 === 0;
          const cardY = above ? AXIS_Y - 160 : AXIS_Y + 32;
          const stemY1 = above ? AXIS_Y - 8 : AXIS_Y + 8;
          const stemY2 = above ? cardY + 100 : cardY;
          const isSelected = selectedId === ev.id;
          return (
            <g key={ev.id}>
              <line x1={cx} y1={stemY1} x2={cx} y2={stemY2} stroke="#2a2d3a" strokeWidth={1} />
              <circle cx={cx} cy={AXIS_Y} r={4} fill={EVENT_DOT_HEX[ev.type] ?? "#94a3b8"} stroke="#1a1d27" strokeWidth={1.5} />
              <foreignObject
                x={cx - CARD_W / 2}
                y={cardY}
                width={CARD_W}
                height={100}
                style={{ cursor: "pointer" }}
                onClick={() => onSelect(ev)}
              >
                <div
                  className={clsx(
                    "flex h-[100px] flex-col gap-2 overflow-hidden rounded-md border p-2.5 shadow-sm transition-colors",
                    isSelected
                      ? "border-accent/40 bg-accent/10"
                      : "border-surface-border bg-surface-card hover:border-accent/30 hover:bg-surface-hover",
                  )}
                >
                  <span className={clsx("self-start rounded border px-1 py-px text-[9px] font-semibold leading-tight", EVENT_TYPE_COLORS[ev.type] ?? EVENT_TYPE_COLORS.other)}>
                    {ev.type}
                  </span>
                  <p className="line-clamp-2 text-[11px] font-medium leading-snug text-ink-primary">{ev.title}</p>
                  {ev.date && <p className="truncate text-[10px] text-ink-muted">{ev.date}</p>}
                </div>
              </foreignObject>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

// ── list view ────────────────────────────────────────────────────────────────

function ListView({
  events,
  selectedId,
  onSelect,
}: {
  events: TimelineEvent[];
  selectedId: number | null;
  onSelect: (e: TimelineEvent) => void;
}) {
  return (
    <div className="max-h-[45vh] overflow-y-auto px-4 py-3">
      <div className="flex flex-col gap-3">
        {events.map((ev) => (
          <button
            key={ev.id}
            onClick={() => onSelect(ev)}
            className={clsx(
              "flex items-center gap-3 rounded-lg border px-4 py-3 text-sm transition-colors",
              selectedId === ev.id
                ? "border-accent/40 bg-accent/10"
                : "border-surface-border bg-surface hover:border-accent/30 hover:bg-surface-hover",
            )}
          >
            <span className={clsx("flex-shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-semibold", EVENT_TYPE_COLORS[ev.type] ?? EVENT_TYPE_COLORS.other)}>
              {ev.type}
            </span>
            <div className="min-w-0 flex-1 text-left">
              <p className="truncate font-medium text-ink-primary">{ev.title}</p>
              {ev.participants.length > 0 && (
                <p className="truncate text-[11px] text-ink-muted">{ev.participants.join(", ")}</p>
              )}
            </div>
            <div className="flex-shrink-0 space-y-0.5 text-right text-[11px] text-ink-muted">
              <p>Book {ev.book_number} · Ch. {ev.chapter_number}</p>
              {ev.date && <p>{ev.date}</p>}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

// ── detail panel below the chart ─────────────────────────────────────────────

function DetailPanel({
  event,
  index,
  total,
  onNav,
  onSource,
  bookName,
}: {
  event: TimelineEvent | null;
  index: number;
  total: number;
  onNav: (dir: 1 | -1) => void;
  onSource: (chunkId: string) => void;
  bookName: (n: number) => string;
}) {
  if (!event) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-1 border-t border-surface-border text-center">
        <Calendar className="mb-1 h-8 w-8 text-ink-muted/40" strokeWidth={1.5} />
        <p className="text-sm font-medium text-ink-secondary">Select an event to view insights</p>
        <p className="text-xs text-ink-muted">
          Click any event card on the timeline above to explore its details,
          <br />
          character impacts, and cross-book connections.
        </p>
      </div>
    );
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden border-t border-surface-border">
      <div className="flex-shrink-0 border-b border-surface-border px-6 py-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <span className={clsx("rounded border px-1.5 py-0.5 text-[10px] font-semibold", EVENT_TYPE_COLORS[event.type] ?? EVENT_TYPE_COLORS.other)}>
              {event.type}
            </span>
            <h2 className="mt-2 text-base font-bold text-ink-primary">{event.title}</h2>
            <span className="mt-2 flex items-center gap-3 text-[11px] text-ink-muted">
              <span className={clsx("rounded-full px-2 py-px text-[10px] font-medium", bookColor(event.book_number))}>
                {bookName(event.book_number)} · Ch. {event.chapter_number}
              </span>
              {event.date && (
                <span className="flex items-center gap-1">
                  <Calendar className="h-3 w-3 flex-shrink-0" strokeWidth={1.5} /> {event.date}
                </span>
              )}
            </span>
          </div>
          <div className="mt-0.5 flex flex-shrink-0 items-center gap-1 self-start">
            <button
              onClick={() => onNav(-1)}
              disabled={index <= 0}
              className="pointer-events-auto rounded p-1 text-ink-muted transition-colors hover:bg-surface-hover hover:text-ink-primary disabled:pointer-events-none disabled:opacity-30"
            >
              <ChevronLeft className="h-4 w-4" strokeWidth={1.5} />
            </button>
            <span className="min-w-[3rem] text-center text-[11px] tabular-nums text-ink-muted">
              {index + 1} / {total}
            </span>
            <button
              onClick={() => onNav(1)}
              disabled={index >= total - 1}
              className="rounded p-1 text-ink-muted transition-colors hover:bg-surface-hover hover:text-ink-primary disabled:pointer-events-none disabled:opacity-30"
            >
              <ChevronRight className="h-4 w-4" strokeWidth={1.5} />
            </button>
          </div>
        </div>
      </div>
      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-6 py-5">
        {event.summary && <p className="text-sm leading-relaxed text-ink-secondary">{event.summary}</p>}

        {event.participants.length > 0 && (
          <div>
            <p className="text-[10px] font-bold uppercase tracking-wider text-ink-primary">
              Characters ({event.participants.length})
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              {event.participants.map((p) => {
                const pc = povColor(p);
                return (
                  <span key={p} className="flex items-center gap-2 rounded-md border border-surface-border bg-surface px-2.5 py-1.5">
                    <span className={clsx("flex h-6 w-6 items-center justify-center rounded-full text-[9px] font-semibold ring-1", pc.text, pc.ring, pc.bg)}>
                      {initials(p) || "?"}
                    </span>
                    <span className="text-[12px] font-medium text-ink-primary">{p}</span>
                  </span>
                );
              })}
            </div>
          </div>
        )}

        {event.location && (
          <div>
            <p className="text-[10px] font-bold uppercase tracking-wider text-ink-primary">Location</p>
            <div className="mt-1.5 flex items-center gap-1.5 text-[11px] text-ink-secondary">
              <MapPin className="h-3 w-3 flex-shrink-0 text-ink-muted" strokeWidth={1.5} />
              {event.location}
            </div>
          </div>
        )}

        {event.knowledge_impact.length > 0 && (
          <div>
            <p className="text-[10px] font-bold uppercase tracking-wider text-ink-primary">Knowledge impact</p>
            <div className="mt-1.5 space-y-1">
              {event.knowledge_impact.slice(0, 6).map((ki, i) => (
                <div key={i} className="text-[11px] text-ink-secondary">
                  <span className="font-medium text-ink-primary">{ki.character}</span> learns: {ki.learns}
                </div>
              ))}
            </div>
          </div>
        )}

        {event.setups.length > 0 && (
          <div>
            <p className="text-[10px] font-bold uppercase tracking-wider text-ink-primary">Cross-book connections</p>
            <div className="mt-1.5 space-y-2">
              {event.setups.map((s, i) => (
                <div key={i} className="rounded-md border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-300">
                  <span className="font-semibold">Sets up: </span>
                  {s}
                </div>
              ))}
            </div>
          </div>
        )}

        {event.source_chunk_ids.length > 0 && (
          <div>
            <p className="text-[10px] font-bold uppercase tracking-wider text-ink-primary">
              Sources ({event.source_chunk_ids.length})
            </p>
            <div className="mt-1.5 flex flex-wrap gap-2">
              {event.source_chunk_ids.map((cid, i) => (
                <button
                  key={cid}
                  onClick={() => onSource(cid)}
                  className="flex items-center gap-1.5 rounded-md border border-surface-border bg-surface px-2.5 py-1 text-[11px] text-ink-secondary transition-colors hover:border-accent hover:text-accent"
                >
                  Passage {i + 1} — Chapter {event.chapter_number}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── source viewer: full chapter with the cited passage highlighted ──────────

function HighlightedSourceViewer({ chunkId, onClose }: { chunkId: string; onClose: () => void }) {
  const [data, setData] = useState<{ title: string; before: string; quote: string; after: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const markRef = useRef<HTMLElement>(null);

  useEffect(() => {
    setData(null);
    (async () => {
      try {
        const chunk = await api<{ text: string; book_number: number; book_title: string; chapter_number: number }>(
          `/api/chunks/${chunkId}`,
        );
        const chapter = await api<{ text: string }>(
          `/api/books/${chunk.book_number}/chapters/${chunk.chapter_number}/text`,
        );
        const idx = chapter.text.indexOf(chunk.text);
        const title = `${chunk.book_title} — Chapter ${chunk.chapter_number}`;
        if (idx < 0) {
          setData({ title, before: "", quote: chunk.text, after: "" });
        } else {
          setData({
            title,
            before: chapter.text.slice(0, idx),
            quote: chunk.text,
            after: chapter.text.slice(idx + chunk.text.length),
          });
        }
      } catch (e) {
        setError(String(e));
      }
    })();
  }, [chunkId]);

  useEffect(() => {
    if (data) setTimeout(() => markRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
  }, [data]);

  return (
    <div className="flex h-full w-[40%] shrink-0 flex-col border-l border-surface-border bg-surface-card">
      <div className="flex items-center justify-between border-b border-surface-border px-4 py-3">
        <span className="text-xs font-medium text-ink-primary">{data?.title ?? "Loading source…"}</span>
        <button onClick={onClose} className="rounded-md p-1 text-ink-secondary hover:text-ink-primary">
          <X className="h-4 w-4" strokeWidth={1.5} />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {error && <div className="text-xs text-rose-300">{error}</div>}
        {!data && !error && (
          <div className="flex justify-center py-10">
            <Spinner />
          </div>
        )}
        {data && (
          <div className="whitespace-pre-wrap font-serif text-[13px] leading-relaxed text-ink-secondary">
            {data.before}
            <mark ref={markRef} className="rounded-sm bg-amber-300/90 px-0.5 text-black">
              {data.quote}
            </mark>
            {data.after}
          </div>
        )}
      </div>
    </div>
  );
}
