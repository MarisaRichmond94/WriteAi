import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  BookOpen,
  Calendar,
  Check,
  ChevronLeft,
  ChevronRight,
  Clock,
  MapPin,
  Pencil,
  Plus,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { clsx } from "clsx";
import { ChapterLinkChips, ChapterLinksUnavailable } from "./ChapterLinks";
import type { WriterCharacter } from "../../types";
import type { ChapterLink, WriterEvent, WriterEventInput } from "../../api/writerEvents";
import { formatTime12h } from "../../lib/format";
import { characterLabel, indexCharacters, isUnknown, resolveCharacter } from "../../lib/characterNames";
import StoryDatePicker from "../plan/outline/StoryDatePicker";

// ── Avatar helpers (matches TimelinePane pattern) ────────────────────────────

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
    <div
      className={clsx(
        "flex flex-shrink-0 items-center justify-center rounded-full font-bold",
        avatarColor(name),
        className,
      )}
    >
      {nameInitials(name)}
    </div>
  );
}

// ── Section header (matches TimelinePane SectionHeader) ──────────────────────

function SectionHeader({ label, count }: { label: string; count?: number }) {
  return (
    <div className="text-[10px] font-bold uppercase tracking-wider text-ink-primary">
      {count !== undefined ? `${label} (${count})` : label}
    </div>
  );
}

// ── Props ────────────────────────────────────────────────────────────────────

interface WriterEventDrawerProps {
  event: WriterEvent | null;
  defaultDate: string | null;
  defaultLocation: string | null;
  characters: WriterCharacter[];
  locations: string[];
  /** Loom chapters referencing this event, and whether Loom could be asked
   *  at all — an empty list and an unanswerable question look identical
   *  otherwise, and only one means "referenced nowhere". */
  chapterLinks: ChapterLink[];
  loomUnreachable: boolean;
  saving: boolean;
  eventIndex: number;
  totalEvents: number;
  onPrev: () => void;
  onNext: () => void;
  onSave: (input: WriterEventInput) => void;
  onDelete: () => void;
  onClose: () => void;
}

// ── View mode ────────────────────────────────────────────────────────────────

function ViewMode({
  event,
  characters,
  chapterLinks,
  loomUnreachable,
  eventIndex,
  totalEvents,
  onPrev,
  onNext,
  onEdit,
  onClose,
}: {
  event: WriterEvent;
  characters: WriterCharacter[];
  chapterLinks: ChapterLink[];
  loomUnreachable: boolean;
  eventIndex: number;
  totalEvents: number;
  onPrev: () => void;
  onNext: () => void;
  onEdit: () => void;
  onClose: () => void;
}) {
  // `event.characters` holds `wc-` ids (LOOM-45). Name and portrait are derived
  // here, so renaming a character updates every event referencing it rather
  // than orphaning them all.
  const charIndex = useMemo(() => indexCharacters(characters), [characters]);

  return (
    <>
      {/* Header — matches EventDrawer header */}
      <div className="group/header flex-shrink-0 border-b border-surface-border px-6 py-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <h2 className="text-base font-bold text-ink-primary">
                {event.title || "Untitled event"}
              </h2>
              {/* Edit pencil — visible on header hover */}
              <button
                onClick={onEdit}
                title="Edit event"
                className="rounded p-0.5 text-ink-muted opacity-0 transition-opacity group-hover/header:opacity-100 hover:bg-surface-hover hover:text-ink-primary"
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
            </div>
            {event.date && (
              <span className="mt-2 flex items-center gap-1 text-[11px] text-ink-muted">
                <Calendar className="h-3 w-3 flex-shrink-0" />
                {event.date}
                {event.time && (
                  <>
                    <span className="text-ink-muted/50">·</span>
                    <Clock className="h-3 w-3 flex-shrink-0" />
                    {formatTime12h(event.time)}
                  </>
                )}
              </span>
            )}
          </div>

          <div className="flex-shrink-0 flex items-center gap-1 self-start mt-0.5">
            {/* Prev / next navigator */}
            {totalEvents > 1 && (
              <>
                <button
                  onClick={onPrev}
                  disabled={eventIndex <= 0}
                  title="Previous event"
                  className="rounded p-1 text-ink-muted transition-colors hover:bg-surface-hover hover:text-ink-primary disabled:pointer-events-none disabled:opacity-30"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <span className="min-w-[3rem] text-center text-[11px] tabular-nums text-ink-muted">
                  {eventIndex + 1} / {totalEvents}
                </span>
                <button
                  onClick={onNext}
                  disabled={eventIndex >= totalEvents - 1}
                  title="Next event"
                  className="rounded p-1 text-ink-muted transition-colors hover:bg-surface-hover hover:text-ink-primary disabled:pointer-events-none disabled:opacity-30"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </>
            )}

            {/* Close */}
            <button
              onClick={onClose}
              title="Close"
              className="rounded p-1 text-ink-muted transition-colors hover:bg-surface-hover hover:text-ink-primary"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Body — matches EventDrawer body layout */}
      <div className="flex-1 min-h-0 overflow-y-auto px-6 py-5 space-y-5">
        {/* Description */}
        {event.description && (
          <p className="text-sm leading-relaxed text-ink-secondary">
            {event.description}
          </p>
        )}

        {/* Characters */}
        {event.characters.length > 0 && (
          <div>
            <SectionHeader
              label="Character(s)"
              count={event.characters.length}
            />
            <div className="mt-2 flex flex-wrap gap-2">
              {event.characters.map((ref) => {
                const label = characterLabel(ref, charIndex);
                return (
                  <div
                    key={ref}
                    className="flex items-center gap-2.5 rounded-lg border border-surface-border bg-surface px-3 py-2"
                  >
                    <AvatarCircle
                      name={label}
                      photoUrl={resolveCharacter(ref, charIndex)?.photo_url ?? null}
                      className="h-9 w-9 text-[11px]"
                    />
                    <div className="min-w-0">
                      {/* An id that no longer resolves is shown, not dropped —
                          a silently vanishing cast member is the failure this
                          ticket exists to end. */}
                      <div
                        className={clsx(
                          "text-[12px] font-semibold",
                          isUnknown(ref, charIndex)
                            ? "italic text-ink-muted"
                            : "text-ink-primary",
                        )}
                      >
                        {label}
                      </div>
                    </div>
                  </div>
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

        {/* Chapters, from Loom (LOOM-32).
            Tagging happens in Loom's Events tab now, keyed by chapter cuid, so
            these follow their chapters through insertion and renumbering. The
            old book_chapters editor stored a title and a NUMBER and drifted
            silently the first time a chapter was inserted above one. */}
        {(loomUnreachable || chapterLinks.length > 0) && (
          <div>
            <SectionHeader
              label="Chapter(s)"
              count={loomUnreachable ? undefined : chapterLinks.length}
            />
            <div className="mt-1.5">
              {loomUnreachable ? (
                <ChapterLinksUnavailable />
              ) : (
                <ChapterLinkChips links={chapterLinks} />
              )}
            </div>
          </div>
        )}

        {/* Empty body */}
        {!event.description &&
          event.characters.length === 0 &&
          !event.location &&
          chapterLinks.length === 0 && (
            <p className="text-[11px] italic text-ink-muted">
              No details yet.{" "}
              <button
                onClick={onEdit}
                className="underline hover:text-ink-secondary"
              >
                Edit this event
              </button>{" "}
              to add them.
            </p>
          )}
      </div>
    </>
  );
}

// ── Edit / create form ───────────────────────────────────────────────────────

function EditMode({
  event,
  defaultDate,
  defaultLocation,
  characters,
  locations,
  saving,
  onSave,
  onDelete,
  onCancel,
}: {
  event: WriterEvent | null;
  defaultDate: string | null;
  defaultLocation: string | null;
  characters: WriterCharacter[];
  locations: string[];
  saving: boolean;
  onSave: (input: WriterEventInput) => void;
  onDelete: () => void;
  onCancel: () => void;
}) {
  // New events default to the last event's date/location rather than
  // starting blank (today's date isn't relevant to where the writer is in
  // the story, and consecutive events often share a location).
  const [title, setTitle] = useState(event?.title ?? "");
  const [date, setDate] = useState(event ? event.date ?? "" : defaultDate ?? "");
  const [time, setTime] = useState(event?.time ?? "");
  const [description, setDescription] = useState(event?.description ?? "");
  const [selectedChars, setSelectedChars] = useState<string[]>(
    event?.characters ?? [],
  );
  const [location, setLocation] = useState(
    event ? event.location ?? "" : defaultLocation ?? "",
  );
  const titleInputRef = useRef<HTMLInputElement>(null);

  const [datePickerOpen, setDatePickerOpen] = useState(false);
  const [datePos, setDatePos] = useState<{ top: number; left: number } | null>(
    null,
  );
  const dateBtnRef = useRef<HTMLButtonElement>(null);
  const datePopRef = useRef<HTMLDivElement>(null);

  const [locOpen, setLocOpen] = useState(false);
  const locRef = useRef<HTMLDivElement>(null);

  const [charOpen, setCharOpen] = useState(false);
  const [charSearch, setCharSearch] = useState("");
  const charRef = useRef<HTMLDivElement>(null);
  const charInputRef = useRef<HTMLInputElement>(null);

  // Sync form state when event prop changes (e.g. nav prev/next in edit mode).
  useEffect(() => {
    setTitle(event?.title ?? "");
    setDate(event ? event.date ?? "" : defaultDate ?? "");
    setTime(event?.time ?? "");
    setDescription(event?.description ?? "");
    setSelectedChars(event?.characters ?? []);
    setLocation(event ? event.location ?? "" : defaultLocation ?? "");
    setDatePickerOpen(false);
    setLocOpen(false);
    setCharOpen(false);
    setCharSearch("");
  }, [event, defaultDate, defaultLocation]);

  // Focus the title whenever a fresh edit session starts — covers both the
  // initial mount and switching straight from one event to another (e.g. via
  // the ⌥⇧N "new event" hotkey) without an intervening unmount.
  useEffect(() => {
    titleInputRef.current?.focus();
  }, [event]);

  useEffect(() => {
    if (!datePickerOpen) return;
    const handler = (e: MouseEvent) => {
      if (
        datePopRef.current?.contains(e.target as Node) ||
        dateBtnRef.current?.contains(e.target as Node)
      )
        return;
      setDatePickerOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [datePickerOpen]);

  useEffect(() => {
    if (!locOpen) return;
    const handler = (e: MouseEvent) => {
      if (locRef.current && !locRef.current.contains(e.target as Node))
        setLocOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [locOpen]);

  useEffect(() => {
    if (!charOpen) return;
    const handler = (e: MouseEvent) => {
      if (charRef.current && !charRef.current.contains(e.target as Node))
        setCharOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [charOpen]);

  useEffect(() => {
    if (charOpen) setTimeout(() => charInputRef.current?.focus(), 0);
  }, [charOpen]);

  // Selection is stored as `wc-` ids; this resolves them back to names for the
  // chips. Searching and sorting still work on names — that is what the writer
  // types and reads — only what gets STORED is an id.
  const editIndex = useMemo(() => indexCharacters(characters), [characters]);

  const sortedChars = useMemo(
    () => [...characters].sort((a, b) => a.name.localeCompare(b.name)),
    [characters],
  );

  const filteredChars = useMemo(() => {
    const q = charSearch.trim().toLowerCase();
    return sortedChars.filter((c) => !q || c.name.toLowerCase().includes(q));
  }, [sortedChars, charSearch]);

  const locMatches = useMemo(() => {
    const q = location.trim().toLowerCase();
    const all = [...locations].sort((a, b) => a.localeCompare(b));
    if (!q) return all;
    return all.filter((l) => l.toLowerCase().includes(q));
  }, [locations, location]);

  const exactLocExists = locations.some(
    (l) => l.toLowerCase() === location.trim().toLowerCase(),
  );

  // Selection is by `wc-` id (LOOM-45), never by name — a name is a display
  // value that can change under the reference.
  const toggleChar = (id: string) =>
    setSelectedChars((prev) =>
      prev.includes(id) ? prev.filter((n) => n !== id) : [...prev, id],
    );

  const handleSave = () =>
    onSave({
      title: title.trim(),
      date: date.trim() || null,
      time: date.trim() ? time.trim() || null : null,
      description,
      characters: selectedChars,
      location: location.trim() || null,
    });

  const canSave = title.trim().length > 0 && !saving;

  // ⌥⇧Enter saves the event, mirroring the Save button.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.altKey && e.shiftKey && e.code === "Enter") {
        e.preventDefault();
        if (canSave) handleSave();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [canSave, handleSave]);

  const inputCls =
    "w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-xs text-ink-primary placeholder:text-ink-muted focus:border-accent/50 focus:outline-none";

  return (
    <>
      {/* Header */}
      <div className="flex-shrink-0 border-b border-surface-border px-6 py-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h2 className="text-base font-bold text-ink-primary">
              {event ? (event.title || "Untitled event") : "New Event"}
            </h2>
            {event && (
              <p className="mt-0.5 text-[11px] text-ink-muted">
                Editing event details
              </p>
            )}
          </div>
          <button
            onClick={onCancel}
            title="Cancel"
            className="flex-shrink-0 rounded p-1 text-ink-muted transition-colors hover:bg-surface-hover hover:text-ink-primary"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 min-h-0 overflow-y-auto px-6 py-5">
        <div className="flex flex-col gap-5">

          {/* Title */}
          <div>
            <input
              ref={titleInputRef}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="What happens in this event?"
              className={inputCls}
            />
          </div>

          {/* Date + time */}
          <div className="flex items-center gap-2">
            <div>
              <button
                ref={dateBtnRef}
                onClick={() => {
                  if (datePickerOpen) { setDatePickerOpen(false); return; }
                  const rect = dateBtnRef.current?.getBoundingClientRect();
                  if (rect) setDatePos({ top: rect.bottom + 6, left: rect.left });
                  setDatePickerOpen(true);
                }}
                className={clsx(
                  "flex items-center gap-2 rounded-md border border-surface-border bg-surface px-3 py-2 text-xs transition-colors hover:border-accent/50",
                  datePickerOpen
                    ? "border-accent/50 text-accent"
                    : "text-ink-secondary",
                )}
              >
                <Calendar className="h-3.5 w-3.5 flex-shrink-0" />
                {date || <span className="text-ink-muted">Pick a date</span>}
                {date && (
                  <span
                    role="button"
                    tabIndex={-1}
                    onClick={(e) => { e.stopPropagation(); setDate(""); setTime(""); }}
                    className="ml-1 text-ink-muted hover:text-ink-primary"
                  >
                    <X className="h-3 w-3" />
                  </span>
                )}
              </button>
              {datePickerOpen &&
                datePos &&
                createPortal(
                  <div
                    ref={datePopRef}
                    className="fixed z-50 rounded-lg border border-surface-border bg-surface-card p-3 shadow-xl"
                    style={{ top: datePos.top, left: datePos.left }}
                  >
                    <StoryDatePicker value={date} onChange={setDate} />
                  </div>,
                  document.body,
                )}
            </div>

            {date.trim() && (
              <div className="relative">
                <Clock className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-muted" />
                <input
                  type="time"
                  value={time}
                  onChange={(e) => setTime(e.target.value)}
                  className="rounded-md border border-surface-border bg-surface py-2 pl-8 pr-2 text-xs text-ink-primary focus:border-accent/50 focus:outline-none"
                />
              </div>
            )}
          </div>

          {/* Description */}
          <div>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Describe the event…"
              rows={4}
              className={clsx(inputCls, "resize-y leading-relaxed")}
            />
          </div>

          {/* Characters */}
          <div>
            <SectionHeader
              label="Character(s)"
              count={selectedChars.length > 0 ? selectedChars.length : undefined}
            />

            {selectedChars.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {selectedChars.map((ref) => (
                  <span
                    key={ref}
                    className="flex items-center gap-1 rounded-full border border-accent/30 bg-accent/10 px-2.5 py-1 text-[11px] text-accent"
                  >
                    {characterLabel(ref, editIndex)}
                    <button
                      onClick={() => toggleChar(ref)}
                      className="transition-colors hover:text-red-400"
                      title={`Remove ${characterLabel(ref, editIndex)}`}
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </span>
                ))}
              </div>
            )}

            {characters.length === 0 ? (
              <p className="mt-1.5 text-[11px] italic text-ink-muted">
                No writer characters yet. Add them on the Plan page.
              </p>
            ) : (
              <div ref={charRef} className="relative mt-2">
                <button
                  onClick={() => { setCharSearch(""); setCharOpen((v) => !v); }}
                  className="flex items-center gap-1.5 rounded-md border border-dashed border-surface-border px-2.5 py-1.5 text-[11px] text-ink-secondary transition-colors hover:border-accent hover:text-accent"
                >
                  <Plus className="h-3 w-3" /> Add Character
                </button>

                {charOpen && (
                  <div className="absolute left-0 top-full z-40 mt-1 w-56 rounded-md border border-surface-border bg-surface-card shadow-lg">
                    <div className="p-2">
                      <div className="relative">
                        <Search className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-ink-muted" />
                        <input
                          ref={charInputRef}
                          value={charSearch}
                          onChange={(e) => setCharSearch(e.target.value)}
                          placeholder="Search…"
                          className="w-full rounded border border-surface-border bg-surface py-1 pl-6 pr-2 text-[11px] text-ink-primary placeholder:text-ink-muted focus:border-accent/50 focus:outline-none"
                          onKeyDown={(e) => {
                            if (e.key === "Enter" && filteredChars.length > 0) {
                              toggleChar(filteredChars[0].id);
                              setCharSearch("");
                              charInputRef.current?.focus();
                            }
                          }}
                        />
                      </div>
                    </div>
                    <div className="overflow-y-auto pb-1" style={{ maxHeight: "calc(3.5 * 2rem)" }}>
                      {filteredChars.length === 0 ? (
                        <p className="px-3 py-2 text-[11px] text-ink-muted">
                          No characters found
                        </p>
                      ) : (
                        filteredChars.map((c) => {
                          const isSelected = selectedChars.includes(c.id);
                          return (
                            <button
                              key={c.id}
                              onClick={() => { toggleChar(c.id); setCharSearch(""); }}
                              className={clsx(
                                "flex w-full items-center justify-between px-3 py-1.5 text-left text-[11px] transition-colors hover:bg-surface-hover",
                                isSelected ? "text-accent" : "text-ink-secondary",
                              )}
                            >
                              {c.name}
                              {isSelected && (
                                <Check className="h-3 w-3 flex-shrink-0 text-accent" />
                              )}
                            </button>
                          );
                        })
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Location */}
          <div>
            <div ref={locRef} className="relative mt-1.5">
              <div className="relative">
                <MapPin className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-muted" />
                <input
                  value={location}
                  onChange={(e) => { setLocation(e.target.value); setLocOpen(true); }}
                  onFocus={() => setLocOpen(true)}
                  placeholder="Select or create a location…"
                  className={clsx(inputCls, "pl-8")}
                />
                {location && (
                  <button
                    onClick={() => setLocation("")}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-ink-muted hover:text-ink-primary"
                  >
                    <X className="h-3 w-3" />
                  </button>
                )}
              </div>
              {locOpen &&
                (locMatches.length > 0 ||
                  (location.trim() && !exactLocExists)) && (
                  <div className="absolute left-0 right-0 top-full z-40 mt-1 max-h-48 overflow-y-auto rounded-md border border-surface-border bg-surface-card shadow-lg">
                    {location.trim() && !exactLocExists && (
                      <button
                        onClick={() => { setLocation(location.trim()); setLocOpen(false); }}
                        className="flex w-full items-center gap-1.5 px-3 py-1.5 text-left text-[11px] text-accent hover:bg-surface-hover"
                      >
                        <Plus className="h-3 w-3" /> Create "{location.trim()}"
                      </button>
                    )}
                    {locMatches.map((l) => (
                      <button
                        key={l}
                        onClick={() => { setLocation(l); setLocOpen(false); }}
                        className="block w-full px-3 py-1.5 text-left text-[11px] text-ink-secondary hover:bg-surface-hover"
                      >
                        {l}
                      </button>
                    ))}
                  </div>
                )}
            </div>
          </div>

          {/* Chapter tagging lives in Loom now (LOOM-32).

              It used to be two <select>s writing {book title, chapter number}
              into book_chapters. Both halves move — inserting a chapter in Loom
              renumbered every tag in that book, silently — which is why the
              feature went unused. Loom keys the join by chapter cuid instead,
              so a tag follows its chapter. The read view shows the result.

              Deliberately no read-only remnant here: there were 6 legacy tags
              in total and they are being re-made by hand (LOOM-40), so a
              disabled control would be scar tissue, not a fallback. */}
        </div>
      </div>

      {/* Footer */}
      <div className="flex flex-shrink-0 items-center justify-between border-t border-surface-border px-6 py-3">
        {event ? (
          <button
            onClick={onDelete}
            className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs text-red-400 transition-colors hover:bg-red-500/10"
          >
            <Trash2 className="h-3.5 w-3.5" /> Delete
          </button>
        ) : (
          <span />
        )}
        <div className="flex items-center gap-2">
          <button
            onClick={onCancel}
            className="rounded-md px-3 py-1.5 text-xs text-ink-secondary transition-colors hover:text-ink-primary"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={!canSave}
            className="flex items-center gap-1.5 rounded-md bg-accent px-4 py-1.5 text-xs font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            <Check className="h-3.5 w-3.5" /> {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </>
  );
}

// ── Main drawer ──────────────────────────────────────────────────────────────

export default function WriterEventDrawer({
  event,
  defaultDate,
  defaultLocation,
  characters,
  locations,
  chapterLinks,
  loomUnreachable,
  saving,
  eventIndex,
  totalEvents,
  onPrev,
  onNext,
  onSave,
  onDelete,
  onClose,
}: WriterEventDrawerProps) {
  // Creating a new event starts in edit mode; viewing an existing starts in view mode.
  const [mode, setMode] = useState<"view" | "edit">(event ? "view" : "edit");

  // When the selected event changes (including nav), reset to view mode.
  useEffect(() => {
    setMode(event ? "view" : "edit");
  }, [event?.id]);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {mode === "view" && event ? (
        <ViewMode
          event={event}
          characters={characters}
          chapterLinks={chapterLinks}
          loomUnreachable={loomUnreachable}
          eventIndex={eventIndex}
          totalEvents={totalEvents}
          onPrev={onPrev}
          onNext={onNext}
          onEdit={() => setMode("edit")}
          onClose={onClose}
        />
      ) : (
        <EditMode
          event={event}
          defaultDate={defaultDate}
          defaultLocation={defaultLocation}
          characters={characters}
          locations={locations}
          saving={saving}
          onSave={onSave}
          onDelete={onDelete}
          // When editing existing: Cancel goes back to view. When creating: Cancel closes.
          onCancel={event ? () => setMode("view") : onClose}
        />
      )}
    </div>
  );
}
