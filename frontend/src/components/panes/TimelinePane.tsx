import { useEffect, useMemo, useRef, useState } from "react";
import clsx from "clsx";
import { ChevronLeft, ChevronRight, Clock, MapPin, Sparkles, Users } from "lucide-react";
import { useApp } from "../../store";
import type { TimelineEvent } from "../../types";
import { api } from "../../lib/api";
import { bookColor, EVENT_DOT_COLORS, EVENT_TYPE_COLORS } from "../../lib/palette";
import { Button, EmptyState, Spinner } from "../ui";
import { ChunkViewer } from "../chat";

export function TimelinePane() {
  const { books, toast, setPane } = useApp();
  const [events, setEvents] = useState<TimelineEvent[] | null>(null);
  const [bookFilter, setBookFilter] = useState<number | null>(null);
  const [granularity, setGranularity] = useState<string | null>(null);
  const [selected, setSelected] = useState<TimelineEvent | null>(null);
  const [viewChunk, setViewChunk] = useState<string | null>(null);
  const dotRefs = useRef<Record<number, HTMLButtonElement | null>>({});

  const load = () => {
    const params = new URLSearchParams();
    if (bookFilter != null) params.set("book", String(bookFilter));
    if (granularity) params.set("granularity", granularity);
    api<{ events: TimelineEvent[] }>(`/api/events?${params}`)
      .then((d) => setEvents(d.events))
      .catch((e) => toast(String(e), "error"));
  };

  useEffect(load, [bookFilter, granularity]);

  const filtered = events ?? [];
  const index = selected ? filtered.findIndex((e) => e.id === selected.id) : -1;

  const nav = (dir: 1 | -1) => {
    if (!filtered.length) return;
    const next = filtered[Math.min(filtered.length - 1, Math.max(0, index + dir))];
    setSelected(next);
    dotRefs.current[next.id]?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.altKey && e.key === "ArrowRight") nav(1);
      if (e.altKey && e.key === "ArrowLeft") nav(-1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const byBook = useMemo(() => {
    const groups: Record<number, TimelineEvent[]> = {};
    for (const e of filtered) (groups[e.book_number] ??= []).push(e);
    return groups;
  }, [filtered]);

  if (events === null) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner className="h-5 w-5" />
      </div>
    );
  }

  if (events.length === 0 && bookFilter == null && !granularity) {
    return (
      <EmptyState
        icon={<Clock className="h-10 w-10" strokeWidth={1} />}
        title="No timeline events yet"
        hint="Run the enrichment pass to distill events from your extracted metadata (it shows a cost estimate first)."
        action={
          <Button onClick={() => setPane("books")}>
            <Sparkles className="h-3.5 w-3.5" strokeWidth={1.5} /> Open Books → Enrich
          </Button>
        }
      />
    );
  }

  return (
    <div className="flex h-full">
      <div className="flex min-w-0 flex-1 flex-col">
        {/* filters */}
        <div className="flex flex-wrap items-center gap-2 border-b border-surface-border px-6 py-3">
          <button
            onClick={() => setBookFilter(null)}
            className={clsx(
              "rounded-full border px-2.5 py-0.5 text-[10px]",
              bookFilter == null ? "border-accent text-accent" : "border-surface-border text-ink-secondary",
            )}
          >
            All books
          </button>
          {books.map((b) => (
            <button
              key={b.id}
              onClick={() => setBookFilter(bookFilter === b.id ? null : b.id)}
              className={clsx(
                "rounded-full px-2 py-0.5 text-[10px] font-medium",
                bookColor(b.id),
                bookFilter != null && bookFilter !== b.id && "opacity-30",
              )}
            >
              {b.name}
            </button>
          ))}
          <span className="mx-1 h-4 w-px bg-surface-border" />
          {["major", "moderate", "minor"].map((g) => (
            <button
              key={g}
              onClick={() => setGranularity(granularity === g ? null : g)}
              className={clsx(
                "rounded-full border px-2.5 py-0.5 text-[10px] capitalize",
                granularity === g ? "border-accent text-accent" : "border-surface-border text-ink-secondary",
              )}
            >
              {g}
            </button>
          ))}
          <span className="flex-1" />
          <span className="text-[10px] text-ink-muted">{filtered.length} events</span>
        </div>

        {/* timeline scroller */}
        <div className="min-h-0 flex-1 overflow-y-auto px-8 py-6">
          {Object.entries(byBook).map(([book, evs]) => (
            <div key={book} className="mb-6">
              <div className="mb-3 flex items-center gap-2">
                <span className={clsx("rounded-full px-2.5 py-0.5 text-[11px] font-medium", bookColor(Number(book)))}>
                  {books.find((b) => b.id === Number(book))?.name ?? `Book ${book}`}
                </span>
                <span className="text-[10px] text-ink-muted">{evs.length} events</span>
              </div>
              <div className="relative ml-3 border-l border-surface-border pl-6">
                {evs.map((e) => (
                  <button
                    key={e.id}
                    ref={(el) => (dotRefs.current[e.id] = el)}
                    onClick={() => setSelected(selected?.id === e.id ? null : e)}
                    className={clsx(
                      "group relative mb-1.5 flex w-full items-start gap-3 rounded-lg px-3 py-2 text-left transition-colors",
                      selected?.id === e.id ? "bg-accent/10" : "hover:bg-surface-hover",
                    )}
                  >
                    <span
                      className={clsx(
                        "absolute -left-[31px] top-3 h-2.5 w-2.5 rounded-full ring-4 ring-surface",
                        EVENT_DOT_COLORS[e.type] ?? "bg-slate-400",
                        e.granularity === "major" && "scale-125",
                        e.granularity === "minor" && "scale-75 opacity-60",
                      )}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-2">
                        <span
                          className={clsx(
                            "text-[13px] text-ink-primary",
                            e.granularity === "major" ? "font-semibold" : "font-medium",
                            e.granularity === "minor" && "font-normal text-ink-secondary",
                          )}
                        >
                          {e.title}
                        </span>
                        <span
                          className={clsx(
                            "rounded-full border px-1.5 py-px text-[9px] font-medium",
                            EVENT_TYPE_COLORS[e.type] ?? EVENT_TYPE_COLORS.other,
                          )}
                        >
                          {e.type}
                        </span>
                      </span>
                      <span className="text-[10px] text-ink-muted">
                        Ch {e.chapter_number}
                        {e.date ? ` · ${e.date}` : ""}
                        {e.location ? ` · ${e.location}` : ""}
                      </span>
                    </span>
                  </button>
                ))}
              </div>
            </div>
          ))}
          {filtered.length === 0 && (
            <div className="py-16 text-center text-xs text-ink-muted">No events match these filters.</div>
          )}
        </div>

        {/* event drawer */}
        {selected && (
          <div className="max-h-[45%] shrink-0 overflow-y-auto border-t border-surface-border bg-surface-card px-6 py-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold text-ink-primary">{selected.title}</span>
                  <span
                    className={clsx(
                      "rounded-full border px-2 py-px text-[10px] font-medium",
                      EVENT_TYPE_COLORS[selected.type] ?? EVENT_TYPE_COLORS.other,
                    )}
                  >
                    {selected.type}
                  </span>
                  <span className="text-[10px] uppercase tracking-wider text-ink-muted">{selected.granularity}</span>
                </div>
                <div className="mt-1 flex items-center gap-3 text-[11px] text-ink-secondary">
                  <span>
                    {books.find((b) => b.id === selected.book_number)?.name}, Ch {selected.chapter_number}
                  </span>
                  {selected.date && <span>{selected.date}</span>}
                  {selected.location && (
                    <span className="flex items-center gap-1">
                      <MapPin className="h-3 w-3" strokeWidth={1.5} /> {selected.location}
                    </span>
                  )}
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-2 text-[11px] text-ink-secondary">
                <button onClick={() => nav(-1)} disabled={index <= 0} className="rounded p-1 hover:bg-surface disabled:opacity-30">
                  <ChevronLeft className="h-4 w-4" strokeWidth={1.5} />
                </button>
                {index + 1} / {filtered.length}
                <button
                  onClick={() => nav(1)}
                  disabled={index >= filtered.length - 1}
                  className="rounded p-1 hover:bg-surface disabled:opacity-30"
                >
                  <ChevronRight className="h-4 w-4" strokeWidth={1.5} />
                </button>
              </div>
            </div>
            {selected.summary && <p className="mt-3 text-xs leading-relaxed text-ink-secondary">{selected.summary}</p>}
            {selected.participants.length > 0 && (
              <div className="mt-3 flex flex-wrap items-center gap-1.5">
                <Users className="h-3.5 w-3.5 text-ink-muted" strokeWidth={1.5} />
                {selected.participants.map((p) => (
                  <span key={p} className="rounded-full border border-surface-border px-2 py-0.5 text-[10px] text-ink-secondary">
                    {p}
                  </span>
                ))}
              </div>
            )}
            {selected.knowledge_impact.length > 0 && (
              <div className="mt-3">
                <div className="mb-1 text-[10px] font-semibold uppercase tracking-widest text-ink-muted">
                  Knowledge impact
                </div>
                <ul className="flex flex-col gap-0.5">
                  {selected.knowledge_impact.slice(0, 6).map((k, i) => (
                    <li key={i} className="text-[11px] text-ink-secondary">
                      <span className="text-ink-primary">{k.character}</span> learns: {k.learns}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {selected.source_chunk_ids.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {selected.source_chunk_ids.map((cid) => (
                  <button
                    key={cid}
                    onClick={() => setViewChunk(cid)}
                    className="rounded-md border border-surface-border px-2 py-1 font-mono text-[9px] text-ink-secondary hover:border-accent hover:text-accent"
                  >
                    source: {cid}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
      {viewChunk && <ChunkViewer chunkId={viewChunk} onClose={() => setViewChunk(null)} />}
    </div>
  );
}
