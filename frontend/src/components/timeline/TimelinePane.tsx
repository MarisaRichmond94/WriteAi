import { useEffect, useRef, useState, useCallback } from "react";
import { ArrowLeft, BookOpen, Calendar, ChevronDown, ChevronLeft, ChevronRight, Clock, Info, MapPin, Search, Users, X, Zap } from "lucide-react";
import { clsx } from "clsx";
import { useAppStore } from "../../store/useAppStore";
import type { Citation, TimelineEvent, EventSourceQuote } from "../../types";
import { fetchEvents } from "../../api/events";
import { fetchCharacters } from "../../api/characters";
import ChapterViewer from "../chat/ChapterViewer";
import { generateMockCharacterProfile } from "../../mocks/timelineMocks";
import { chapterLabel } from "../../lib/format";

// ── Helpers ───────────────────────────────────────────────────────────────────

function bookIdFromName(name: string): string {
  return name.toLowerCase().replace(/'/g, "").replace(/ /g, "-");
}

// ── Event type color palette (same as BookDrawer) ─────────────────────────────

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

const EVENT_TYPE_DOT_COLORS = [
  "#fb7185", // rose-400
  "#a78bfa", // violet-400
  "#60a5fa", // blue-400
  "#34d399", // emerald-400
  "#fbbf24", // amber-400
  "#f472b6", // pink-400
  "#fb923c", // orange-400
  "#22d3ee", // cyan-400
  "#818cf8", // indigo-400
  "#2dd4bf", // teal-400
];

function eventTypeHash(type: string): number {
  return type.toLowerCase().split("").reduce((acc, ch) => acc + ch.charCodeAt(0), 0);
}

function eventTypeColor(type: string): string {
  return EVENT_TYPE_PALETTE[eventTypeHash(type) % EVENT_TYPE_PALETTE.length];
}

function eventTypeDotColor(type: string): string {
  return EVENT_TYPE_DOT_COLORS[eventTypeHash(type) % EVENT_TYPE_DOT_COLORS.length];
}

// ── Book color palette ─────────────────────────────────────────────────────────

const BOOK_PILL_PALETTE = [
  "border-violet-500/40 bg-violet-500/10 text-violet-300 hover:bg-violet-500/20",
  "border-amber-500/40 bg-amber-500/10 text-amber-300 hover:bg-amber-500/20",
  "border-blue-500/40 bg-blue-500/10 text-blue-300 hover:bg-blue-500/20",
  "border-emerald-500/40 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20",
  "border-rose-500/40 bg-rose-500/10 text-rose-300 hover:bg-rose-500/20",
  "border-pink-500/40 bg-pink-500/10 text-pink-300 hover:bg-pink-500/20",
  "border-cyan-500/40 bg-cyan-500/10 text-cyan-300 hover:bg-cyan-500/20",
  "border-orange-500/40 bg-orange-500/10 text-orange-300 hover:bg-orange-500/20",
];
function bookPillColor(book: string) {
  const hash = book.split("").reduce((acc, ch) => acc + ch.charCodeAt(0), 0);
  return BOOK_PILL_PALETTE[hash % BOOK_PILL_PALETTE.length];
}

// ── Smooth scroll helper ───────────────────────────────────────────────────────

function smoothScroll(el: HTMLElement, target: { top?: number; left?: number }, duration = 600) {
  const startTop = el.scrollTop;
  const startLeft = el.scrollLeft;
  const endTop = target.top ?? startTop;
  const endLeft = target.left ?? startLeft;
  const start = performance.now();
  function easeInOut(t: number) { return t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t; }
  function step(now: number) {
    const p = Math.min((now - start) / duration, 1);
    const e = easeInOut(p);
    el.scrollTop = startTop + (endTop - startTop) * e;
    el.scrollLeft = startLeft + (endLeft - startLeft) * e;
    if (p < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

// ── Section header helper ──────────────────────────────────────────────────────

function SectionHeader({ label, count }: { label: string; count?: number }) {
  return (
    <div className="text-[10px] font-bold uppercase tracking-wider text-ink-primary">
      {count !== undefined ? `${label} (${count})` : label}
    </div>
  );
}

const AVATAR_COLORS = [
  "bg-rose-500/30 text-rose-300",
  "bg-violet-500/30 text-violet-300",
  "bg-blue-500/30 text-blue-300",
  "bg-emerald-500/30 text-emerald-300",
  "bg-amber-500/30 text-amber-300",
  "bg-pink-500/30 text-pink-300",
  "bg-teal-500/30 text-teal-300",
  "bg-indigo-500/30 text-indigo-300",
];

function avatarColor(name: string): string {
  const hash = name.split("").reduce((acc, ch) => acc + ch.charCodeAt(0), 0);
  return AVATAR_COLORS[hash % AVATAR_COLORS.length];
}

function nameInitials(name: string): string {
  const parts = name.trim().split(" ");
  return parts.length >= 2
    ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
    : name.slice(0, 2).toUpperCase();
}

function resolvePhoto(name: string, photos: Record<string, string>): string | undefined {
  return photos[name] ?? photos[name.trim().split(/\s+/)[0]];
}

function AvatarCircle({
  name,
  photoUrl,
  className,
}: {
  name: string;
  photoUrl?: string | null;
  className?: string;
}) {
  if (photoUrl) {
    return (
      <img
        src={photoUrl}
        alt={name}
        className={clsx("rounded-full object-cover flex-shrink-0", className)}
      />
    );
  }
  return (
    <div className={clsx(
      "flex flex-shrink-0 items-center justify-center rounded-full font-bold",
      avatarColor(name),
      className
    )}>
      {nameInitials(name)}
    </div>
  );
}

// ── Character profile panel ────────────────────────────────────────────────────

function CharacterProfilePanel({
  name,
  filterBook,
  characterPhotos,
}: {
  name: string;
  filterBook: string;
  characterPhotos: Record<string, string>;
}) {
  const stub = generateMockCharacterProfile(name, filterBook || undefined);
  const [real, setReal] = useState<Record<string, any> | null>(null);
  useEffect(() => {
    setReal(null);
    fetch(`/api/characters/${encodeURIComponent(name)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then(setReal)
      .catch(() => setReal(null));
  }, [name]);
  const profile = real
    ? {
        ...stub,
        role: real.is_pov ? "POV Character" : "Character",
        aliases: (real.aliases ?? []).map((a: any) => a.alias ?? a),
        traits: real.traits ?? [],
        relationships: (real.relationships ?? []).slice(0, 8).map((r: any) => ({
          name: r.target,
          nature: r.status,
        })),
        books: real.books ?? [],
        description: Object.values(real.arc ?? {})
          .flat()
          .map((a: any) => a?.insight)
          .filter(Boolean)
          .join(" ")
          .slice(0, 400),
      }
    : stub;

  return (
    <div className="flex h-full flex-col bg-surface-card">
      {/* Header — avatar circle fills the padded height on the left */}
      <div className="flex-shrink-0 flex border-b border-surface-border">
        {/* Avatar column: py matches text column so circle is same height as text content */}
        <div className="flex-shrink-0 flex items-center py-4 pl-4 pr-3">
          <AvatarCircle
            name={name}
            photoUrl={resolvePhoto(name, characterPhotos)}
            className="h-10 w-10 text-base"
          />
        </div>
        {/* Text column */}
        <div className="flex-1 min-w-0 py-4 pr-4">
          <p className="text-[10px] font-bold uppercase tracking-wider text-ink-muted mb-1">{profile.role}</p>
          <h3 className="text-base font-bold text-ink-primary">{profile.name}</h3>
          {profile.aliases.length > 0 && (
            <p className="mt-0.5 text-[11px] text-ink-muted">Also known as: {profile.aliases.join(", ")}</p>
          )}
        </div>
      </div>
      {/* Body */}
      <div className="flex-1 min-h-0 overflow-y-auto px-5 py-4 space-y-4">
        <p className="text-sm leading-relaxed text-ink-secondary">{profile.description}</p>

        {profile.traits.length > 0 && (
          <div>
            <SectionHeader label="Traits" />
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {profile.traits.map((t: string) => (
                <span key={t} className="rounded border border-surface-border bg-surface px-2 py-0.5 text-[11px] text-ink-secondary">{t}</span>
              ))}
            </div>
          </div>
        )}

        {profile.relationships.length > 0 && (
          <div>
            <SectionHeader label="Relationships" count={profile.relationships.length} />
            <div className="mt-1.5 space-y-2">
              {profile.relationships.map((r: { name: string; nature: string }) => (
                <div key={r.name} className="flex items-center gap-2.5 rounded-md border border-surface-border bg-surface px-3 py-2">
                  <AvatarCircle
                    name={r.name}
                    photoUrl={resolvePhoto(r.name, characterPhotos)}
                    className="h-8 w-8 text-[10px]"
                  />
                  <div className="min-w-0 flex-1">
                    <p className="text-[11px] font-semibold text-ink-primary">{r.name}</p>
                    <p title={r.nature} className="mt-0.5 text-[11px] text-ink-muted truncate">{r.nature}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {profile.booksAppearing.length > 0 && (
          <div>
            <SectionHeader label="Appears In" count={profile.booksAppearing.length} />
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {profile.booksAppearing.map((b: string) => (
                <span key={b} className={clsx("rounded border px-2 py-0.5 text-[11px]", bookPillColor(b))}>{b}</span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── EventDrawer ───────────────────────────────────────────────────────────────

function EventDrawer({
  event,
  eventIndex,
  totalEvents,
  onPrev,
  onNext,
  filterBook,
  characterPhotos,
  onClose,
}: {
  event: TimelineEvent | null;
  eventIndex: number;
  totalEvents: number;
  onPrev: () => void;
  onNext: () => void;
  filterBook: string;
  characterPhotos: Record<string, string>;
  onClose: () => void;
}) {
  const [activePill, setActivePill] = useState<EventSourceQuote | null>(null);
  const [selectedCharacter, setSelectedCharacter] = useState<string | null>(null);
  const [lightMode, setLightMode] = useState(() => useAppStore.getState().appSettings?.viewer_light_mode ?? true);

  // Reset side panels when event changes
  useEffect(() => {
    setActivePill(null);
    setSelectedCharacter(null);
  }, [event?.id]);

  function openSource(quote: EventSourceQuote) {
    setActivePill(prev => prev === quote ? null : quote);
    setSelectedCharacter(null);
  }

  function openCharacter(name: string) {
    setSelectedCharacter(prev => prev === name ? null : name);
    setActivePill(null);
  }

  const citation: Citation | null = activePill
    ? {
        book: activePill.book,
        chapter: activePill.chapter,
        chapter_heading: String(activePill.chapter),
        pov: "",
        date: null,
        chunk_index: 0,
        snippet: activePill.quote,
        distance: 0,
      }
    : null;

  const sideOpen = citation !== null || selectedCharacter !== null;

  return (
    <div className={clsx("flex h-full flex-1 flex-col overflow-hidden relative", event && "border-t border-surface-border")}>
      {/* Empty state */}
      <div className={clsx(
        "absolute inset-0 flex flex-col items-center justify-center gap-2 text-center transition-all duration-300",
        event ? "opacity-0 pointer-events-none translate-y-1" : "opacity-100 translate-y-0"
      )}>
        <Calendar className="h-8 w-8 text-ink-muted/40 mb-1" />
        <p className="text-sm font-medium text-ink-secondary">Select an event to view insights</p>
        <p className="text-xs text-ink-muted">Click any event card on the timeline above to explore its details,<br />character impacts, and cross-book connections.</p>
      </div>

      {/* Drawer content — horizontal split */}
      <div className={clsx(
        "flex flex-1 overflow-hidden transition-all duration-300",
        event ? "opacity-100 translate-y-0" : "opacity-0 pointer-events-none translate-y-1"
      )}>

        {/* Detail panel */}
        <div className={clsx(
          "flex h-full flex-col overflow-hidden transition-all duration-300 ease-in-out",
          sideOpen ? "w-[60%]" : "w-full"
        )}>
          {event && (
            <>
              {/* Header */}
              <div className="flex-shrink-0 border-b border-surface-border px-6 py-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                  <span className={clsx("rounded border px-1.5 py-0.5 text-[10px] font-semibold", eventTypeColor(event.type))}>
                    {event.type}
                  </span>
                  <h2 className="mt-2 text-base font-bold text-ink-primary">{event.title}</h2>
                  {event.date && (
                    <span className="mt-2 flex items-center gap-1 text-[11px] text-ink-muted">
                      <Calendar className="h-3 w-3 flex-shrink-0" />
                      {event.date}
                    </span>
                  )}
                  </div>

                  {/* Navigator */}
                  {totalEvents > 1 && (
                    <div className="flex-shrink-0 flex items-center gap-1 self-start mt-0.5">
                      <button
                        onClick={onPrev}
                        disabled={eventIndex <= 0}
                        title="Previous event (⌥←)"
                        className="rounded p-1 text-ink-muted transition-colors hover:bg-surface-hover hover:text-ink-primary disabled:opacity-30 disabled:pointer-events-none"
                      >
                        <ChevronLeft className="h-4 w-4" />
                      </button>
                      <span className="min-w-[3rem] text-center text-[11px] tabular-nums text-ink-muted">
                        {eventIndex + 1} / {totalEvents}
                      </span>
                      <button
                        onClick={onNext}
                        disabled={eventIndex >= totalEvents - 1}
                        title="Next event (⌥→)"
                        className="rounded p-1 text-ink-muted transition-colors hover:bg-surface-hover hover:text-ink-primary disabled:opacity-30 disabled:pointer-events-none"
                      >
                        <ChevronRight className="h-4 w-4" />
                      </button>
                    </div>
                  )}
                </div>
              </div>

              {/* Body */}
              <div className="flex-1 min-h-0 overflow-y-auto px-6 py-5 space-y-5">
                <p className="text-sm leading-relaxed text-ink-secondary">{event.summary}</p>

                {/* Characters */}
                {event.participants.length > 0 && (
                  <div>
                    <SectionHeader label="Character(s)" count={event.participants.length} />
                    <div className="mt-2 flex flex-wrap gap-2">
                      {event.participants.map((p) => {
                        const profile = generateMockCharacterProfile(p);
                        const aliases = profile.aliases.slice(0, 3);
                        const active = selectedCharacter === p;
                        return (
                          <button
                            key={p}
                            onClick={() => openCharacter(p)}
                            className={clsx(
                              "flex items-center gap-2.5 rounded-lg border px-3 py-2 text-left transition-colors",
                              active
                                ? "border-accent/50 bg-accent/10"
                                : "border-surface-border bg-surface hover:border-accent/30 hover:bg-surface-hover"
                            )}
                          >
                            <AvatarCircle
                              name={p}
                              photoUrl={resolvePhoto(p, characterPhotos)}
                              className="h-9 w-9 text-[11px]"
                            />
                            <div className="min-w-0">
                              <div className={clsx("text-[12px] font-semibold", active ? "text-accent" : "text-ink-primary")}>
                                {p}
                              </div>
                              {aliases.length > 0 && (
                                <div className="mt-0.5 text-[10px] text-ink-muted truncate">
                                  {aliases.join(" · ")}
                                </div>
                              )}
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* Location */}
                {event.location && (
                  <div>
                    <SectionHeader label="Location" />
                    <div className="mt-1.5 flex items-center gap-1.5 text-[11px] text-ink-secondary">
                      <MapPin className="h-3 w-3 flex-shrink-0 text-ink-muted" />
                      {event.location}
                    </div>
                  </div>
                )}

                {/* Knowledge impact */}
                {event.knowledge_impact.length > 0 && (
                  <div>
                    <SectionHeader label="Knowledge Impact" />
                    <div className="mt-1.5 space-y-1">
                      {event.knowledge_impact.map((ki, i) => (
                        <div key={i} className="text-[11px] text-ink-secondary">
                          <span className="font-medium text-ink-primary">{ki.character}</span>
                          {" "}learns: {ki.learns}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Cross-book connections */}
                {(event.cross_book_setup || event.cross_book_payoff) && (
                  <div className="space-y-2">
                    <SectionHeader label="Cross-Book Connections" />
                    {event.cross_book_setup && (
                      <div className="rounded-md border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-300">
                        <span className="font-semibold">Sets up: </span>{event.cross_book_setup}
                      </div>
                    )}
                    {event.cross_book_payoff && (
                      <div className="rounded-md border border-emerald-500/20 bg-emerald-500/5 px-3 py-2 text-[11px] text-emerald-300">
                        <span className="font-semibold">Pays off: </span>{event.cross_book_payoff}
                      </div>
                    )}
                  </div>
                )}

                {/* Sources */}
                {event.source_quotes.length > 0 && (
                  <div>
                    <SectionHeader label="Sources" count={event.source_quotes.length} />
                    <div className="mt-1.5 flex flex-wrap gap-2">
                      {event.source_quotes.map((sq, i) => (
                        <button
                          key={i}
                          onClick={() => openSource(sq)}
                          className={clsx(
                            "flex items-center gap-1.5 rounded-full border px-3 py-1 text-[11px] font-medium transition-colors",
                            activePill === sq
                              ? "border-accent bg-accent/20 text-accent"
                              : bookPillColor(sq.book)
                          )}
                        >
                          <BookOpen className="h-3 w-3 flex-shrink-0" />
                          {sq.book} — {chapterLabel(sq.chapter)}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        {/* Side panel — ChapterViewer or CharacterProfile, slides in at 40% */}
        <div className={clsx(
          "flex flex-col overflow-hidden border-l border-surface-border transition-all duration-300 ease-in-out",
          sideOpen ? "w-[40%]" : "w-0 border-l-0"
        )}>
          {citation && (
            <ChapterViewer
              citation={citation}
              bookId={bookIdFromName(citation.book)}
              lightMode={lightMode}
              onToggleLightMode={() => setLightMode((v) => !v)}
            />
          )}
          {selectedCharacter && !citation && (
            <CharacterProfilePanel
              name={selectedCharacter}
              filterBook={filterBook}
              characterPhotos={characterPhotos}
            />
          )}
        </div>

      </div>
    </div>
  );
}

// ── List view ─────────────────────────────────────────────────────────────────

function ListView({
  events,
  selectedId,
  onSelect,
  compressed,
}: {
  events: TimelineEvent[];
  selectedId: string | null;
  onSelect: (event: TimelineEvent) => void;
  compressed: boolean;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const buttonRefs = useRef<Map<string, HTMLButtonElement>>(new Map());

  useEffect(() => {
    if (!selectedId) return;
    const container = scrollRef.current;
    const button = buttonRefs.current.get(selectedId);
    if (!container || !button) return;
    const top = button.offsetTop - container.offsetTop;
    smoothScroll(container, { top: Math.max(0, top - 12) });
  }, [selectedId]);

  if (events.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
        <Zap className="h-8 w-8 text-ink-muted" strokeWidth={1} />
        <p className="text-xs text-ink-muted">No events found.</p>
        <p className="text-[10px] text-ink-muted">Run extraction to populate events data.</p>
      </div>
    );
  }

  return (
    <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3">
      <div className="flex flex-col gap-3">
        {events.map((ev) => (
          <button
            key={ev.id}
            ref={(el) => { if (el) buttonRefs.current.set(ev.id, el); else buttonRefs.current.delete(ev.id); }}
            onClick={() => onSelect(ev)}
            className={clsx(
              "flex w-full items-center gap-3 rounded-lg border px-4 py-3 text-sm transition-colors",
              selectedId === ev.id
                ? "border-accent/40 bg-surface-hover"
                : "border-surface-border bg-surface hover:bg-surface-hover"
            )}
          >
            {/* Type badge */}
            <span className={clsx("flex-shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-semibold", eventTypeColor(ev.type))}>
              {ev.type}
            </span>

            {/* Title + participants */}
            <div className="flex-1 min-w-0 text-left">
              <p className="truncate font-medium text-ink-primary">{ev.title}</p>
              {ev.participants.length > 0 && (
                <p className="truncate text-[11px] text-ink-muted">
                  {ev.participants.join(", ")}
                </p>
              )}
            </div>

            {/* Book + chapter + date */}
            {!compressed && (
              <div className="flex-shrink-0 text-right text-[11px] text-ink-muted space-y-0.5">
                <p>{ev.book} · Ch. {ev.chapter}</p>
                {ev.date && <p>{ev.date}</p>}
              </div>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Chart view ────────────────────────────────────────────────────────────────

const ZOOM_LABELS = ["Overview", "Mid", "Detailed"] as const;
const CARD_W = 160;
const CARD_GAP = 48;
const AXIS_Y = 176;
const CHART_H = 340;

function ChartView({
  events,
  onSelect,
  selectedId,
}: {
  events: TimelineEvent[];
  onSelect: (event: TimelineEvent) => void;
  selectedId: string | null;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgWrapRef = useRef<SVGSVGElement>(null);
  const cardRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const [zoom, setZoom] = useState(1); // 0=major, 1=mid, 2=all
  const wheelAccum = useRef(0);
  const lastTouchDist = useRef<number | null>(null);
  const zoomDirRef = useRef<"in" | "out">("in");
  const prevVisibleIds = useRef(new Set<string>());

  const visibleEvents = events.filter((ev) => {
    if (zoom === 0) return ev.granularity === "major";
    if (zoom === 1) return ev.granularity === "major" || ev.granularity === "moderate";
    return true;
  });

  // Inject keyframes once
  useEffect(() => {
    if (document.getElementById("tl-zoom-keyframes")) return;
    const style = document.createElement("style");
    style.id = "tl-zoom-keyframes";
    style.textContent = `
      @keyframes tl-enter-up   { from { opacity:0; transform:translateY(8px) } to { opacity:1; transform:translateY(0) } }
      @keyframes tl-enter-down { from { opacity:0; transform:translateY(-8px) } to { opacity:1; transform:translateY(0) } }
    `;
    document.head.appendChild(style);
  }, []);

  // Animate SVG wrapper and track direction on zoom change
  useEffect(() => {
    if (!svgWrapRef.current) return;
    const dir = zoomDirRef.current;
    svgWrapRef.current.animate(
      [
        { transform: dir === "in" ? "scale(0.97)" : "scale(1.02)", opacity: "0.85" },
        { transform: "scale(1)",                                     opacity: "1"    },
      ],
      { duration: 900, easing: "cubic-bezier(0.25, 0.46, 0.45, 0.94)" }
    );
  }, [zoom]);

  // Scroll selected card to the left edge of the chart container
  useEffect(() => {
    if (!selectedId) return;
    const container = containerRef.current;
    const card = cardRefs.current.get(selectedId);
    if (!container || !card) return;
    const cardLeft = card.getBoundingClientRect().left - container.getBoundingClientRect().left + container.scrollLeft;
    smoothScroll(container, { left: Math.max(0, cardLeft - 16) });
  }, [selectedId]);

  // Update which IDs were visible after each render
  useEffect(() => {
    prevVisibleIds.current = new Set(visibleEvents.map(e => e.id));
  });

  // Fade cards in/out as they scroll into/out of view
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          const el = entry.target as HTMLDivElement;
          el.style.opacity = entry.isIntersecting ? "1" : "0";
        });
      },
      { root: container, threshold: 0, rootMargin: "0px -160px 0px -160px" }
    );

    cardRefs.current.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, [visibleEvents]);

  // Trackpad pinch: fires as ctrlKey+wheel on macOS
  const handleWheel = useCallback((e: WheelEvent) => {
    if (!e.ctrlKey) return;
    e.preventDefault();
    wheelAccum.current += e.deltaY;
    if (Math.abs(wheelAccum.current) > 40) {
      const step = wheelAccum.current > 0 ? -1 : 1;
      zoomDirRef.current = step > 0 ? "in" : "out";
      setZoom(z => Math.max(0, Math.min(2, z + step)));
      wheelAccum.current = 0;
    }
  }, []);

  // Touch pinch: two-finger gesture on touch screens
  const handleTouchStart = useCallback((e: TouchEvent) => {
    if (e.touches.length !== 2) return;
    const dx = e.touches[0].clientX - e.touches[1].clientX;
    const dy = e.touches[0].clientY - e.touches[1].clientY;
    lastTouchDist.current = Math.hypot(dx, dy);
  }, []);

  const handleTouchMove = useCallback((e: TouchEvent) => {
    if (e.touches.length !== 2 || lastTouchDist.current === null) return;
    e.preventDefault();
    const dx = e.touches[0].clientX - e.touches[1].clientX;
    const dy = e.touches[0].clientY - e.touches[1].clientY;
    const dist = Math.hypot(dx, dy);
    const delta = dist - lastTouchDist.current;
    if (Math.abs(delta) > 24) {
      const step = delta > 0 ? 1 : -1;
      zoomDirRef.current = step > 0 ? "in" : "out";
      setZoom(z => Math.max(0, Math.min(2, z + step)));
      lastTouchDist.current = dist;
    }
  }, []);

  const handleTouchEnd = useCallback(() => {
    lastTouchDist.current = null;
  }, []);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    el.addEventListener("wheel", handleWheel, { passive: false });
    el.addEventListener("touchstart", handleTouchStart, { passive: false });
    el.addEventListener("touchmove", handleTouchMove, { passive: false });
    el.addEventListener("touchend", handleTouchEnd);
    return () => {
      el.removeEventListener("wheel", handleWheel);
      el.removeEventListener("touchstart", handleTouchStart);
      el.removeEventListener("touchmove", handleTouchMove);
      el.removeEventListener("touchend", handleTouchEnd);
    };
  }, [handleWheel, handleTouchStart, handleTouchMove, handleTouchEnd]);

  if (events.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
        <Zap className="h-8 w-8 text-ink-muted" strokeWidth={1} />
        <p className="text-xs text-ink-muted">No events found.</p>
        <p className="text-[10px] text-ink-muted">Run extraction to populate events data.</p>
      </div>
    );
  }

  const totalW = Math.max(visibleEvents.length * (CARD_W + CARD_GAP) + CARD_GAP, 800);

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Scrollable chart area */}
      <div
        ref={containerRef}
        className="flex-1 overflow-x-auto overflow-y-hidden"
        style={{ height: `${CHART_H}px`, touchAction: "pan-x" }}
      >
        <svg
          ref={svgWrapRef}
          width={totalW}
          height={CHART_H}
          className="select-none"
        >
          {/* Axis line */}
          <line
            x1={0}
            y1={AXIS_Y}
            x2={totalW}
            y2={AXIS_Y}
            stroke="var(--color-surface-border, #334155)"
            strokeWidth={1.5}
          />

          {visibleEvents.map((ev, idx) => {
            const cx = CARD_GAP + idx * (CARD_W + CARD_GAP) + CARD_W / 2;
            const above = idx % 2 === 0;
            const cardY = above ? AXIS_Y - 160 : AXIS_Y + 32;
            const stemY1 = above ? AXIS_Y - 8 : AXIS_Y + 8;
            const stemY2 = above ? cardY + 100 : cardY;
            const isSelected = selectedId === ev.id;

            return (
              <g key={ev.id}>
                {/* Stem */}
                <line
                  x1={cx}
                  y1={stemY1}
                  x2={cx}
                  y2={stemY2}
                  stroke="var(--color-surface-border, #334155)"
                  strokeWidth={1}
                />
                {/* Dot on axis */}
                <circle
                  cx={cx}
                  cy={AXIS_Y}
                  r={4}
                  fill={eventTypeDotColor(ev.type)}
                  stroke="var(--color-surface-card, #1e293b)"
                  strokeWidth={1.5}
                />

                {/* Card (foreignObject for rich HTML) */}
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
                      "flex flex-col gap-2 rounded-md border p-2.5 shadow-sm",
                      isSelected
                        ? "border-accent/40 bg-accent/10"
                        : "border-surface-border bg-surface-card hover:border-accent/30 hover:bg-surface-hover"
                    )}
                    style={{
                      height: "100px",
                      overflow: "hidden",
                      opacity: 0,
                      transition: "opacity 0.7s ease, background-color 150ms, border-color 150ms",
                    }}
                  >
                    <span className={clsx("self-start rounded border px-1 py-px text-[9px] font-semibold leading-tight", eventTypeColor(ev.type))}>
                      {ev.type}
                    </span>
                    <p className="text-[11px] font-medium leading-snug text-ink-primary line-clamp-2">
                      {ev.title}
                    </p>
                    {ev.date && (
                      <p className="text-[10px] text-ink-muted truncate">{ev.date}</p>
                    )}
                  </div>
                </foreignObject>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

// ── Loading skeletons ─────────────────────────────────────────────────────────

function SkeletonBox({ className }: { className?: string }) {
  return <div className={clsx("animate-pulse rounded bg-surface-border", className)} />;
}

function ChartSkeleton() {
  const count = 8;
  const totalW = count * (CARD_W + CARD_GAP) + CARD_GAP;

  return (
    <div className="flex-shrink-0 overflow-x-auto" style={{ height: `${CHART_H}px` }}>
      <svg width={totalW} height={CHART_H} className="select-none">
        {/* Axis */}
        <line x1={0} y1={AXIS_Y} x2={totalW} y2={AXIS_Y} stroke="var(--color-surface-border, #334155)" strokeWidth={1.5} />

        {[...Array(count)].map((_, idx) => {
          const cx = CARD_GAP + idx * (CARD_W + CARD_GAP) + CARD_W / 2;
          const above = idx % 2 === 0;
          const cardY = above ? AXIS_Y - 160 : AXIS_Y + 32;
          const stemY1 = above ? AXIS_Y - 8 : AXIS_Y + 8;
          const stemY2 = above ? cardY + 100 : cardY;

          return (
            <g key={idx}>
              <line x1={cx} y1={stemY1} x2={cx} y2={stemY2} stroke="var(--color-surface-border, #334155)" strokeWidth={1} />
              <circle cx={cx} cy={AXIS_Y} r={4} fill="var(--color-surface-border, #334155)" stroke="var(--color-surface-card, #1e293b)" strokeWidth={1.5} />
              <foreignObject x={cx - CARD_W / 2} y={cardY} width={CARD_W} height={100}>
                <div className="flex h-full animate-pulse flex-col gap-2 rounded-md border border-surface-border bg-surface-card p-2.5">
                  <div className="h-3 w-12 rounded bg-surface-border" />
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

function ListSkeleton() {
  const widths = ["w-3/4", "w-2/3", "w-4/5", "w-1/2", "w-3/5", "w-4/5", "w-2/3", "w-3/4"];
  // enough rows to overflow any viewport; overflow-hidden clips the rest
  const rows = Array.from({ length: 20 }, (_, i) => widths[i % widths.length]);
  return (
    <div className="flex-1 overflow-hidden px-4 py-3">
      <div className="flex flex-col gap-3">
        {rows.map((w, i) => (
          <div key={i} className="flex animate-pulse items-center gap-3 rounded-lg border border-surface-border bg-surface px-4 py-3">
            <div className="h-4 w-16 flex-shrink-0 rounded bg-surface-border" />
            <div className="min-w-0 flex-1 space-y-1.5">
              <div className={clsx("h-3 rounded bg-surface-border", w)} />
              <div className="h-2.5 w-1/3 rounded bg-surface-border" />
            </div>
            <div className="flex-shrink-0">
              <div className="h-2.5 w-28 rounded bg-surface-border" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Dropdown ──────────────────────────────────────────────────────────────────

function Dropdown({
  value,
  options,
  allLabel,
  onChange,
}: {
  value: string;
  options: string[];
  allLabel: string;
  onChange: (v: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded border border-surface-border bg-surface px-2.5 py-1 text-[11px] text-ink-secondary transition-colors hover:border-accent hover:text-ink-primary"
      >
        {value || allLabel}
        <ChevronDown className="h-3 w-3 flex-shrink-0" />
      </button>
      {open && (
        <div className="absolute right-0 top-full z-50 mt-1 min-w-[160px] rounded-md border border-surface-border bg-surface-card shadow-lg">
          <button
            onClick={() => { onChange(""); setOpen(false); }}
            className={clsx(
              "w-full px-3 py-1.5 text-left text-[11px] hover:bg-surface-hover transition-colors",
              !value ? "text-accent" : "text-ink-secondary"
            )}
          >
            {allLabel}
          </button>
          {options.map((opt) => (
            <button
              key={opt}
              onClick={() => { onChange(opt); setOpen(false); }}
              className={clsx(
                "w-full px-3 py-1.5 text-left text-[11px] hover:bg-surface-hover transition-colors",
                value === opt ? "text-accent" : "text-ink-secondary"
              )}
            >
              {opt}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main pane ─────────────────────────────────────────────────────────────────

export default function TimelinePane() {
  const books = useAppStore((s) => s.books);

  const [view, setView] = useState<"list" | "chart">(() => {
    const v = new URLSearchParams(window.location.search).get("tlview");
    return v === "list" || v === "chart" ? v : "chart";
  });
  const [search, setSearch] = useState("");
  const [filterType, setFilterType] = useState("");
  const [filterBook, setFilterBook] = useState("");
  const [filterPov, setFilterPov] = useState("");
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedEvent, setSelectedEvent] = useState<TimelineEvent | null>(null);
  const [characterPhotos, setCharacterPhotos] = useState<Record<string, string>>({});

  // Derive POV options from books store
  const povOptions = Array.from(new Set(books.flatMap((b) => b.povs))).sort();
  const bookOptions = books.map((b) => b.name);

  useEffect(() => {
    fetchCharacters()
      .then((chars) => {
        const map: Record<string, string> = {};
        for (const c of chars) {
          if (c.photo_url) {
            map[c.name] = c.photo_url;
            const firstName = c.name.trim().split(/\s+/)[0];
            if (firstName) map[firstName] = c.photo_url;
          }
        }
        setCharacterPhotos(map);
      })
      .catch(() => {/* photos are best-effort */});
  }, []);

  useEffect(() => {
    setLoading(true);
    setError(null);
    const filters: Record<string, string> = {};
    if (filterBook) filters.book = filterBook;
    if (filterPov) filters.pov = filterPov;
    fetchEvents(Object.keys(filters).length ? filters : undefined)
      .then(setEvents)
      .catch(() => setError("Failed to load events. Run extraction to generate events data."))
      .finally(() => setLoading(false));
  }, [filterBook, filterPov]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    params.set("tlview", view);
    history.replaceState(null, "", `?${params}`);
  }, [view]);

  const query = search.trim().toLowerCase();
  const typeOptions = [...new Set(events.map((e) => e.type))].sort();
  const visibleEvents = view === "list"
    ? events.filter((e) =>
        (!filterType || e.type === filterType) &&
        (!query || e.title.toLowerCase().includes(query)))
    : events;

  const selectedIndex = selectedEvent ? visibleEvents.findIndex((e) => e.id === selectedEvent.id) : -1;

  function handleSelect(event: TimelineEvent) {
    setSelectedEvent((prev) => (prev?.id === event.id ? null : event));
  }

  function handlePrev() {
    if (selectedIndex > 0) setSelectedEvent(visibleEvents[selectedIndex - 1]);
  }

  function handleNext() {
    if (selectedIndex < visibleEvents.length - 1) setSelectedEvent(visibleEvents[selectedIndex + 1]);
  }

  function handleViewChange(v: "list" | "chart") {
    if (v !== view) {
      setView(v);
      setSelectedEvent(null);
    }
  }

  // Keyboard navigation: Option+← (prev) and Option+→ (next)
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (!selectedEvent) return;
      if (e.altKey && e.key === "ArrowLeft")  { e.preventDefault(); handlePrev(); }
      if (e.altKey && e.key === "ArrowRight") { e.preventDefault(); handleNext(); }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selectedEvent, selectedIndex, visibleEvents]);

  const drawerOpen = selectedEvent !== null;

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Header */}
      <div className="flex-shrink-0 px-6 pt-4 pb-3">
        <div className="flex items-center gap-2">
          <Clock className="h-6 w-6 flex-shrink-0 text-accent" />
          <div>
            <div className="flex items-center gap-2">
              <p className="text-xs font-semibold uppercase tracking-widest text-ink-primary">
                Timeline
              </p>
              <div className="group relative">
                <Info className="h-3.5 w-3.5 cursor-default text-ink-muted transition-colors hover:text-ink-secondary" />
                <div className="pointer-events-none absolute left-0 top-5 z-50 w-72 rounded-md border border-surface-border bg-surface-card px-3 py-2 text-[11px] leading-relaxed text-ink-muted shadow-lg opacity-0 transition-opacity duration-150 group-hover:opacity-100">
                  The Timeline page visualises significant events extracted from your books. Use the List view
                  for a scannable overview, or the Chart view for a visual timeline you can pan and zoom.
                  Click any event to see full details including character knowledge impact, cross-book connections,
                  and direct source passages from the text.
                </div>
              </div>
            </div>
            <p className="mt-0.5 text-[11px] text-ink-muted">
              Significant events extracted from the series. Select an event to view expanded details.
            </p>
          </div>
        </div>
        <div className="mt-3 border-t border-surface-border" />
      </div>

      {/* Controls row */}
      <div className="flex-shrink-0 flex items-center justify-between gap-3 px-6 pt-0 pb-4">
        {/* View toggle + sort */}
        <div className="flex items-center gap-2">
          <div className="flex items-center rounded border border-surface-border overflow-hidden">
            {(["chart", "list"] as const).map((v) => (
              <button
                key={v}
                onClick={() => handleViewChange(v)}
                className={clsx(
                  "px-3 py-1 text-[11px] font-medium capitalize transition-colors",
                  view === v
                    ? "bg-accent/20 text-accent"
                    : "bg-surface text-ink-muted hover:bg-surface-hover hover:text-ink-secondary"
                )}
              >
                {v === "chart" ? "Chart" : "List"}
              </button>
            ))}
          </div>
          {/* Search — list only */}
          <div className={clsx(
            "relative transition-all duration-200",
            view === "list" ? "opacity-100" : "pointer-events-none opacity-0"
          )}>
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3 w-3 -translate-y-1/2 text-ink-muted" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search events…"
              className="w-52 rounded border border-surface-border bg-surface py-1 pl-7 pr-6 text-[11px] text-ink-primary placeholder:text-ink-muted focus:border-accent/50 focus:outline-none"
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
          {/* Event type filter — list only */}
          <div className={clsx(
            "transition-all duration-200",
            view === "list" ? "opacity-100" : "pointer-events-none opacity-0"
          )}>
            <Dropdown
              value={filterType}
              options={typeOptions}
              allLabel="All Types"
              onChange={setFilterType}
            />
          </div>
        </div>

        {/* Filters */}
        <div className="flex items-center gap-2">
          <Dropdown
            value={filterPov}
            options={povOptions}
            allLabel="All POVs"
            onChange={setFilterPov}
          />
          <Dropdown
            value={filterBook}
            options={bookOptions}
            allLabel="All Books"
            onChange={setFilterBook}
          />
        </div>
      </div>

      {/* Body */}
      {loading ? (
        <div className="flex flex-1 flex-col overflow-hidden">
          {view === "chart" ? <ChartSkeleton /> : <ListSkeleton />}
        </div>
      ) : error ? (
        <div className="px-6 py-4 text-xs text-ink-muted">{error}</div>
      ) : (
        <div className="flex flex-1 flex-col overflow-hidden">
          {/* Chart / list */}
          {view === "list" ? (
            visibleEvents.length === 0 && (query || filterType) ? (
              <div className="flex flex-1 items-center justify-center text-xs text-ink-muted">
                No events matched{query ? ` "${search}"` : ""}{filterType ? ` (type: ${filterType})` : ""}
              </div>
            ) : (
            <ListView
              events={visibleEvents}
              selectedId={selectedEvent?.id ?? null}
              onSelect={handleSelect}
              compressed={false}
            />
            )
          ) : (
            <div className="flex-shrink-0">
              <ChartView
                events={events}
                selectedId={selectedEvent?.id ?? null}
                onSelect={handleSelect}
              />
            </div>
          )}

          {/* Bottom drawer / empty state */}
          {view === "list" ? (
            <div className={clsx(
              "flex-shrink-0 transition-all duration-300 ease-in-out overflow-hidden",
              selectedEvent ? "h-[60%]" : "h-0"
            )}>
              <EventDrawer
                event={selectedEvent}
                eventIndex={selectedIndex}
                totalEvents={visibleEvents.length}
                onPrev={handlePrev}
                onNext={handleNext}
                filterBook={filterBook}
                characterPhotos={characterPhotos}
                onClose={() => setSelectedEvent(null)}
              />
            </div>
          ) : (
            <EventDrawer
              event={selectedEvent}
              eventIndex={selectedIndex}
              totalEvents={visibleEvents.length}
              onPrev={handlePrev}
              onNext={handleNext}
              filterBook={filterBook}
              characterPhotos={characterPhotos}
              onClose={() => setSelectedEvent(null)}
            />
          )}
        </div>
      )}
    </div>
  );
}
