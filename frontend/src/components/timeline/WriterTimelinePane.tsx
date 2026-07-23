import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { clsx } from "clsx";
import { CalendarClock, Info, MapPin, Plus, Search, X } from "lucide-react";
import { FaTimeline } from "react-icons/fa6";
import type { BookResponse, WriterCharacter } from "../../types";
import { formatTime12h } from "../../lib/format";
import { fetchBooks } from "../../api/books";
import { fetchWriterCharacters } from "../../api/plan";
import {
  fetchWriterEvents,
  createWriterEvent,
  updateWriterEvent,
  deleteWriterEvent,
  type WriterEvent,
  type WriterEventInput,
} from "../../api/writerEvents";
import { useAppStore } from "../../store/useAppStore";
import WriterEventDrawer from "./WriterEventForm";

// ── Chart constants ──────────────────────────────────────────────────────────

const CARD_W = 160;
const CARD_GAP = 48;
const AXIS_Y = 176;
const CHART_H = 340;

function smoothScrollX(el: HTMLElement, targetLeft: number, duration = 600) {
  const startLeft = el.scrollLeft;
  const start = performance.now();
  function easeInOut(t: number) { return t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t; }
  function step(now: number) {
    const p = Math.min((now - start) / duration, 1);
    el.scrollLeft = startLeft + (targetLeft - startLeft) * easeInOut(p);
    if (p < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

// ── Writer chart view ────────────────────────────────────────────────────────

function WriterChartView({
  events,
  selectedId,
  onSelect,
}: {
  events: WriterEvent[];
  selectedId: string | null;
  onSelect: (event: WriterEvent) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cardRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  useEffect(() => {
    if (!selectedId) return;
    const container = containerRef.current;
    const card = cardRefs.current.get(selectedId);
    if (!container || !card) return;
    const cardLeft =
      card.getBoundingClientRect().left -
      container.getBoundingClientRect().left +
      container.scrollLeft;
    smoothScrollX(container, Math.max(0, cardLeft - 16));
  }, [selectedId]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          (entry.target as HTMLDivElement).style.opacity = entry.isIntersecting
            ? "1"
            : "0";
        });
      },
      { root: container, threshold: 0, rootMargin: "0px -160px 0px -160px" },
    );
    cardRefs.current.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, [events]);

  if (events.length === 0) {
    return (
      <div
        className="flex flex-col items-center justify-center gap-3 text-center"
        style={{ height: CHART_H }}
      >
        <div className="rounded-full bg-surface-hover p-4">
          <CalendarClock className="h-7 w-7 text-ink-muted/50" />
        </div>
        <p className="text-sm font-medium text-ink-secondary">No events yet</p>
        <p className="text-[11px] text-ink-muted">
          Add your first event to start your timeline.
        </p>
      </div>
    );
  }

  const totalW = Math.max(events.length * (CARD_W + CARD_GAP) + CARD_GAP, 800);

  return (
    <div
      ref={containerRef}
      className="overflow-x-auto overflow-y-hidden"
      style={{ height: CHART_H }}
    >
      <svg width={totalW} height={CHART_H} className="select-none">
        <line
          x1={0}
          y1={AXIS_Y}
          x2={totalW}
          y2={AXIS_Y}
          stroke="var(--color-surface-border, #334155)"
          strokeWidth={1.5}
        />

        {events.map((ev, idx) => {
          const cx = CARD_GAP + idx * (CARD_W + CARD_GAP) + CARD_W / 2;
          const above = idx % 2 === 0;
          const cardY = above ? AXIS_Y - 160 : AXIS_Y + 32;
          const stemY1 = above ? AXIS_Y - 8 : AXIS_Y + 8;
          const stemY2 = above ? cardY + 100 : cardY;
          const isSelected = selectedId === ev.id;

          return (
            <g key={ev.id}>
              <line
                x1={cx}
                y1={stemY1}
                x2={cx}
                y2={stemY2}
                stroke="var(--color-surface-border, #334155)"
                strokeWidth={1}
              />
              <circle
                cx={cx}
                cy={AXIS_Y}
                r={4}
                fill="var(--color-accent, #6366f1)"
                stroke="var(--color-surface-card, #1e293b)"
                strokeWidth={1.5}
              />
              <foreignObject
                x={cx - CARD_W / 2}
                y={cardY}
                width={CARD_W}
                height={100}
                style={{ cursor: "pointer" }}
                onClick={() => onSelect(ev)}
              >
                <div
                  ref={(el) => {
                    if (el) cardRefs.current.set(ev.id, el);
                    else cardRefs.current.delete(ev.id);
                  }}
                  className={clsx(
                    "flex flex-col gap-1.5 rounded-md border p-2.5 shadow-sm",
                    isSelected
                      ? "border-accent/40 bg-accent/10"
                      : "border-surface-border bg-surface-card hover:border-accent/30 hover:bg-surface-hover",
                  )}
                  style={{
                    height: "100px",
                    overflow: "hidden",
                    opacity: 0,
                    transition:
                      "opacity 0.7s ease, background-color 150ms, border-color 150ms",
                  }}
                >
                  <p className="line-clamp-2 text-[11px] font-medium leading-snug text-ink-primary">
                    {ev.title || (
                      <span className="italic text-ink-muted">Untitled</span>
                    )}
                  </p>
                  {ev.date && (
                    <p className="truncate text-[10px] text-ink-muted">
                      {ev.date}
                      {ev.time && ` · ${formatTime12h(ev.time)}`}
                    </p>
                  )}
                  {ev.location && (
                    <p className="flex items-center gap-0.5 truncate text-[10px] text-ink-muted">
                      <MapPin className="h-2.5 w-2.5 flex-shrink-0" />
                      {ev.location}
                    </p>
                  )}
                </div>
              </foreignObject>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function ChartSkeleton() {
  const count = 6;
  const totalW = count * (CARD_W + CARD_GAP) + CARD_GAP;
  return (
    <div className="overflow-x-auto" style={{ height: CHART_H }}>
      <svg width={totalW} height={CHART_H} className="select-none">
        <line
          x1={0}
          y1={AXIS_Y}
          x2={totalW}
          y2={AXIS_Y}
          stroke="var(--color-surface-border, #334155)"
          strokeWidth={1.5}
        />
        {[...Array(count)].map((_, idx) => {
          const cx = CARD_GAP + idx * (CARD_W + CARD_GAP) + CARD_W / 2;
          const above = idx % 2 === 0;
          const cardY = above ? AXIS_Y - 160 : AXIS_Y + 32;
          const stemY1 = above ? AXIS_Y - 8 : AXIS_Y + 8;
          const stemY2 = above ? cardY + 100 : cardY;
          return (
            <g key={idx}>
              <line
                x1={cx}
                y1={stemY1}
                x2={cx}
                y2={stemY2}
                stroke="var(--color-surface-border, #334155)"
                strokeWidth={1}
              />
              <circle
                cx={cx}
                cy={AXIS_Y}
                r={4}
                fill="var(--color-surface-border, #334155)"
                stroke="var(--color-surface-card, #1e293b)"
                strokeWidth={1.5}
              />
              <foreignObject x={cx - CARD_W / 2} y={cardY} width={CARD_W} height={100}>
                <div className="flex h-full animate-pulse flex-col gap-2 rounded-md border border-surface-border bg-surface-card p-2.5">
                  <div className="h-2.5 w-full rounded bg-surface-border" />
                  <div className="h-2.5 w-3/4 rounded bg-surface-border" />
                </div>
              </foreignObject>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

// ── List card ────────────────────────────────────────────────────────────────

function EventListCard({
  event,
  selected,
  onSelect,
}: {
  event: WriterEvent;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      onClick={onSelect}
      className={clsx(
        "flex w-full items-center gap-3 rounded-lg border px-4 py-3 text-sm transition-colors",
        selected
          ? "border-accent/40 bg-surface-hover"
          : "border-surface-border bg-surface hover:bg-surface-hover",
      )}
    >
      <div className="flex-1 min-w-0 text-left">
        <p className="truncate font-medium text-ink-primary">
          {event.title || (
            <span className="italic text-ink-muted">Untitled event</span>
          )}
        </p>
        {event.characters.length > 0 && (
          <p className="truncate text-[11px] text-ink-muted">
            {event.characters.join(", ")}
          </p>
        )}
      </div>

      <div className="flex-shrink-0 space-y-0.5 text-right text-[11px] text-ink-muted">
        {event.location && (
          <p className="flex items-center justify-end gap-1">
            <MapPin className="h-3 w-3" /> {event.location}
          </p>
        )}
        {event.date && (
          <p>
            {event.date}
            {event.time && ` · ${formatTime12h(event.time)}`}
          </p>
        )}
        {event.book_chapters.length > 0 && (
          <p>
            {event.book_chapters.length} tag
            {event.book_chapters.length === 1 ? "" : "s"}
          </p>
        )}
      </div>
    </button>
  );
}

// ── Main pane ────────────────────────────────────────────────────────────────

export default function WriterTimelinePane() {
  const { showToast } = useAppStore();

  const [events, setEvents] = useState<WriterEvent[]>([]);
  const [locations, setLocations] = useState<string[]>([]);
  const [characters, setCharacters] = useState<WriterCharacter[]>([]);
  const [books, setBooks] = useState<BookResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [view, setView] = useState<"list" | "chart">(() => {
    const v = new URLSearchParams(window.location.search).get("wtlview");
    return v === "list" || v === "chart" ? v : "chart";
  });

  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<WriterEvent | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    Promise.all([fetchWriterEvents(), fetchWriterCharacters(), fetchBooks()])
      .then(([we, chars, bks]) => {
        setEvents(we.events);
        setLocations(we.locations);
        setCharacters(chars);
        setBooks(bks);
      })
      .catch(() => showToast("Failed to load timeline."))
      .finally(() => setLoading(false));
  }, [showToast]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    params.set("wtlview", view);
    history.replaceState(null, "", `?${params}`);
  }, [view]);

  // Single source of truth: all events sorted oldest-first.
  // Story dates look like "Saturday, October 31st, 2009" — strip ordinal suffixes to parse.
  const parseStoryDate = (d: string, time?: string | null) => {
    const cleaned = d.replace(/(\d+)(st|nd|rd|th)/g, "$1");
    return new Date(time ? `${cleaned} ${time}` : cleaned).getTime();
  };

  const sortedEvents = useMemo(
    () =>
      [...events].sort((a, b) => {
        if (!a.date && !b.date) return 0;
        if (!a.date) return 1;
        if (!b.date) return -1;

        const dayA = parseStoryDate(a.date);
        const dayB = parseStoryDate(b.date);
        if (dayA !== dayB) return dayA - dayB;

        // Same calendar day: order by time of day when both have one.
        if (a.time && b.time) {
          return parseStoryDate(a.date, a.time) - parseStoryDate(b.date, b.time);
        }
        if (a.time) return -1;
        if (b.time) return 1;
        // Neither has a time — fall back to creation order (oldest first),
        // so the newest card reads as having happened later that day.
        return a.created_at.localeCompare(b.created_at);
      }),
    [events],
  );

  // New events default to the latest dated event's date/location, not
  // today's real-world date — undated events sort last, so walk backward
  // to find the last one that actually has a date.
  const lastDatedEvent = useMemo(() => {
    for (let i = sortedEvents.length - 1; i >= 0; i--) {
      if (sortedEvents[i].date) return sortedEvents[i];
    }
    return null;
  }, [sortedEvents]);
  const lastEventDate = lastDatedEvent?.date ?? null;
  const lastEventLocation = lastDatedEvent?.location ?? null;

  // List view applies the search filter on top of the sorted base.
  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return sortedEvents;
    return sortedEvents.filter((e) => e.title.toLowerCase().includes(q));
  }, [sortedEvents, search]);

  // Chart view uses the full sorted list (search is hidden in chart mode).
  const chartEvents = sortedEvents;

  const openCreate = () => { setEditing(null); setOpen(true); };
  const openEdit = (e: WriterEvent) => { setEditing(e); setOpen(true); };
  const closeDrawer = useCallback(() => { setOpen(false); setEditing(null); }, []);

  // ⌥⇧N opens a new event (title autofocuses via EditMode's own effect).
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.altKey && e.shiftKey && e.code === "KeyN") {
        e.preventDefault();
        openCreate();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  function handleViewChange(v: "list" | "chart") {
    if (v !== view) { setView(v); closeDrawer(); }
  }

  const handleSave = async (input: WriterEventInput) => {
    setSaving(true);
    try {
      if (editing) {
        const updated = await updateWriterEvent(editing.id, input);
        setEvents((prev) => prev.map((e) => (e.id === updated.id ? updated : e)));
      } else {
        const created = await createWriterEvent(input);
        setEvents((prev) => [created, ...prev]);
      }
      if (input.location && !locations.includes(input.location)) {
        setLocations((prev) => [...prev, input.location!]);
      }
      closeDrawer();
    } catch {
      showToast("Failed to save event.");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!editing) return;
    const id = editing.id;
    try {
      await deleteWriterEvent(id);
      setEvents((prev) => prev.filter((e) => e.id !== id));
      closeDrawer();
    } catch {
      showToast("Failed to delete event.");
    }
  };

  const selectedIndex = editing ? visible.findIndex((e) => e.id === editing.id) : -1;
  const handlePrev = () => { if (selectedIndex > 0) openEdit(visible[selectedIndex - 1]); };
  const handleNext = () => { if (selectedIndex < visible.length - 1) openEdit(visible[selectedIndex + 1]); };

  const drawerProps = {
    defaultDate: lastEventDate,
    defaultLocation: lastEventLocation,
    characters,
    books,
    locations,
    saving,
    eventIndex: selectedIndex,
    totalEvents: visible.length,
    onPrev: handlePrev,
    onNext: handleNext,
    onSave: handleSave,
    onDelete: handleDelete,
    onClose: closeDrawer,
  };

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Header */}
      <div className="flex-shrink-0 px-6 pt-4 pb-3">
        <div className="flex items-center gap-2">
          <FaTimeline className="h-6 w-6 flex-shrink-0 text-accent" />
          <div>
            <div className="flex items-center gap-2">
              <p className="text-xs font-semibold uppercase tracking-widest text-ink-primary">
                Timeline
              </p>
              <div className="group relative">
                <Info className="h-3.5 w-3.5 cursor-default text-ink-muted transition-colors hover:text-ink-secondary" />
                <div className="pointer-events-none absolute left-0 top-5 z-50 w-72 rounded-md border border-surface-border bg-surface-card px-3 py-2 text-[11px] leading-relaxed text-ink-muted shadow-lg opacity-0 transition-opacity duration-150 group-hover:opacity-100">
                  Your own timeline — events you author as part of the writing
                  process, separate from the AI-extracted Events page. Use the
                  List view for a scannable overview, or the Chart view for a
                  visual timeline you can pan.
                </div>
              </div>
            </div>
            <p className="mt-0.5 text-[11px] text-ink-muted">
              Events you author as you plan and write. Add or select an event to
              edit its details.
            </p>
          </div>
        </div>
        <div className="mt-3 border-t border-surface-border" />
      </div>

      {/* Controls row */}
      <div className="flex-shrink-0 flex items-center justify-between gap-3 px-6 pt-0 pb-4">
        <div className="flex items-center gap-2">
          {/* View toggle */}
          <div className="flex items-center overflow-hidden rounded border border-surface-border">
            {(["chart", "list"] as const).map((v) => (
              <button
                key={v}
                onClick={() => handleViewChange(v)}
                className={clsx(
                  "px-3 py-1 text-[11px] font-medium capitalize transition-colors",
                  view === v
                    ? "bg-accent/20 text-accent"
                    : "bg-surface text-ink-muted hover:bg-surface-hover hover:text-ink-secondary",
                )}
              >
                {v === "chart" ? "Chart" : "List"}
              </button>
            ))}
          </div>

          {/* Search — list only */}
          <div
            className={clsx(
              "relative transition-all duration-200",
              view === "list"
                ? "opacity-100"
                : "pointer-events-none opacity-0",
            )}
          >
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3 w-3 -translate-y-1/2 text-ink-muted" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search events…"
              disabled={events.length === 0}
              className="w-52 rounded border border-surface-border bg-surface py-1 pl-7 pr-6 text-[11px] text-ink-primary placeholder:text-ink-muted focus:border-accent/50 focus:outline-none disabled:cursor-not-allowed disabled:opacity-40"
            />
            {search && (
              <button
                onClick={() => setSearch("")}
                className="absolute right-1.5 top-1/2 -translate-y-1/2 text-ink-muted hover:text-ink-primary"
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>
        </div>

        <button
          onClick={openCreate}
          className="flex items-center gap-1.5 rounded-md border border-surface-border px-3 py-1.5 text-xs text-ink-secondary transition-colors hover:border-accent hover:text-accent"
        >
          <Plus className="h-3 w-3" /> Add Event
        </button>
      </div>

      {/* Body */}
      {loading ? (
        <div className="flex flex-1 flex-col overflow-hidden">
          {view === "chart" ? (
            <ChartSkeleton />
          ) : (
            <div className="flex flex-1 flex-col gap-3 px-6 py-3">
              {[...Array(6)].map((_, i) => (
                <div
                  key={i}
                  className="h-14 animate-pulse rounded-lg bg-surface-card"
                />
              ))}
            </div>
          )}
        </div>
      ) : view === "chart" ? (
        /* ── Chart layout ─────────────────────────────────────────────────── */
        <div className="flex flex-1 flex-col overflow-hidden">
          <div className="flex-shrink-0">
            <WriterChartView
              events={chartEvents}
              selectedId={open ? (editing?.id ?? null) : null}
              onSelect={openEdit}
            />
          </div>

          {/* Persistent bottom panel — mirrors EventDrawer in chart view */}
          <div className="relative flex flex-1 flex-col overflow-hidden border-t border-surface-border">
            {/* Empty state */}
            <div
              className={clsx(
                "absolute inset-0 flex flex-col items-center justify-center gap-2 text-center transition-all duration-300",
                open
                  ? "pointer-events-none opacity-0 translate-y-1"
                  : "opacity-100 translate-y-0",
              )}
            >
              <FaTimeline className="mb-1 h-8 w-8 text-ink-muted/40" />
              <p className="text-sm font-medium text-ink-secondary">
                Select an event to view details
              </p>
              <p className="text-xs text-ink-muted">
                Click an event card on the timeline above to view/edit its details
              </p>
            </div>

            {/* Form panel */}
            <div
              className={clsx(
                "h-full transition-all duration-300",
                open
                  ? "opacity-100 translate-y-0"
                  : "pointer-events-none opacity-0 translate-y-1",
              )}
            >
              {open && <WriterEventDrawer event={editing} {...drawerProps} />}
            </div>
          </div>
        </div>
      ) : (
        /* ── List layout ──────────────────────────────────────────────────── */
        <div className="flex flex-1 flex-col overflow-hidden">
          {visible.length === 0 ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
              <div className="rounded-full bg-surface-hover p-4">
                <CalendarClock className="h-7 w-7 text-ink-muted/50" />
              </div>
              <div className="flex flex-col items-center gap-1">
                <p className="text-sm font-medium text-ink-secondary">
                  {search ? "No events matched" : "No events yet"}
                </p>
                <p className="text-[11px] text-ink-muted">
                  {search
                    ? `Nothing titled "${search}".`
                    : "Add your first event to start your timeline."}
                </p>
              </div>
              {!search && (
                <button
                  onClick={openCreate}
                  className="flex items-center gap-1.5 rounded-md border border-surface-border px-3 py-1.5 text-xs text-ink-secondary transition-colors hover:border-accent hover:text-accent"
                >
                  <Plus className="h-3 w-3" /> Add Event
                </button>
              )}
            </div>
          ) : (
            <div className="flex-1 overflow-y-auto px-4 py-3">
              <div className="flex flex-col gap-3">
                {visible.map((ev) => (
                  <EventListCard
                    key={ev.id}
                    event={ev}
                    selected={open && editing?.id === ev.id}
                    onSelect={() => openEdit(ev)}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Slide-up bottom drawer */}
          <div
            className={clsx(
              "flex-shrink-0 overflow-hidden border-t border-surface-border transition-all duration-300 ease-in-out",
              open ? "h-[60%]" : "h-0 border-t-0",
            )}
          >
            {open && <WriterEventDrawer event={editing} {...drawerProps} />}
          </div>
        </div>
      )}
    </div>
  );
}
