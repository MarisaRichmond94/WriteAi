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
import type { BookResponse, WriterCharacter } from "../../types";
import type { WriterEvent, WriterEventInput, WriterEventTag } from "../../api/writerEvents";
import { formatTime12h } from "../../lib/format";
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
  characters: WriterCharacter[];
  books: BookResponse[];
  locations: string[];
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
  eventIndex,
  totalEvents,
  onPrev,
  onNext,
  onEdit,
  onClose,
}: {
  event: WriterEvent;
  characters: WriterCharacter[];
  eventIndex: number;
  totalEvents: number;
  onPrev: () => void;
  onNext: () => void;
  onEdit: () => void;
  onClose: () => void;
}) {
  const charMap = useMemo(() => {
    const map: Record<string, string | null> = {};
    for (const c of characters) map[c.name] = c.photo_url;
    return map;
  }, [characters]);

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
              {event.characters.map((name) => (
                <div
                  key={name}
                  className="flex items-center gap-2.5 rounded-lg border border-surface-border bg-surface px-3 py-2"
                >
                  <AvatarCircle
                    name={name}
                    photoUrl={charMap[name]}
                    className="h-9 w-9 text-[11px]"
                  />
                  <div className="min-w-0">
                    <div className="text-[12px] font-semibold text-ink-primary">
                      {name}
                    </div>
                  </div>
                </div>
              ))}
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

        {/* Book & Chapter tags */}
        {event.book_chapters.length > 0 && (
          <div>
            <SectionHeader
              label="Book & Chapter"
              count={event.book_chapters.length}
            />
            <div className="mt-1.5 flex flex-wrap gap-2">
              {event.book_chapters.map((tag, i) => (
                <span
                  key={i}
                  className="flex items-center gap-1.5 rounded-full border border-surface-border px-3 py-1 text-[11px] text-ink-secondary"
                >
                  <BookOpen className="h-3 w-3 flex-shrink-0" />
                  {tag.book} — Ch. {tag.chapter}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Empty body */}
        {!event.description &&
          event.characters.length === 0 &&
          !event.location &&
          event.book_chapters.length === 0 && (
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
  characters,
  books,
  locations,
  saving,
  onSave,
  onDelete,
  onCancel,
}: {
  event: WriterEvent | null;
  defaultDate: string | null;
  characters: WriterCharacter[];
  books: BookResponse[];
  locations: string[];
  saving: boolean;
  onSave: (input: WriterEventInput) => void;
  onDelete: () => void;
  onCancel: () => void;
}) {
  // New events default to the last event's date rather than starting blank
  // (today's date isn't relevant to where the writer is in the story).
  const [title, setTitle] = useState(event?.title ?? "");
  const [date, setDate] = useState(event ? event.date ?? "" : defaultDate ?? "");
  const [time, setTime] = useState(event?.time ?? "");
  const [description, setDescription] = useState(event?.description ?? "");
  const [selectedChars, setSelectedChars] = useState<string[]>(
    event?.characters ?? [],
  );
  const [location, setLocation] = useState(event?.location ?? "");
  const [tags, setTags] = useState<WriterEventTag[]>(
    event?.book_chapters ?? [],
  );

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
    setLocation(event?.location ?? "");
    setTags(event?.book_chapters ?? []);
    setDatePickerOpen(false);
    setLocOpen(false);
    setCharOpen(false);
    setCharSearch("");
  }, [event, defaultDate]);

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

  const toggleChar = (name: string) =>
    setSelectedChars((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name],
    );

  const addTag = () => {
    const firstBook = books[0];
    if (!firstBook) return;
    setTags((prev) => [
      ...prev,
      { book: firstBook.name, chapter: firstBook.chapters[0]?.chapter ?? 0 },
    ]);
  };

  const updateTag = (i: number, patch: Partial<WriterEventTag>) =>
    setTags((prev) =>
      prev.map((t, idx) => (idx === i ? { ...t, ...patch } : t)),
    );

  const removeTag = (i: number) =>
    setTags((prev) => prev.filter((_, idx) => idx !== i));

  const handleSave = () =>
    onSave({
      title: title.trim(),
      date: date.trim() || null,
      time: date.trim() ? time.trim() || null : null,
      description,
      characters: selectedChars,
      location: location.trim() || null,
      book_chapters: tags,
    });

  const canSave = title.trim().length > 0 && !saving;

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
              autoFocus
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
                {selectedChars.map((name) => (
                  <span
                    key={name}
                    className="flex items-center gap-1 rounded-full border border-accent/30 bg-accent/10 px-2.5 py-1 text-[11px] text-accent"
                  >
                    {name}
                    <button
                      onClick={() => toggleChar(name)}
                      className="transition-colors hover:text-red-400"
                      title={`Remove ${name}`}
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
                              toggleChar(filteredChars[0].name);
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
                          const isSelected = selectedChars.includes(c.name);
                          return (
                            <button
                              key={c.id}
                              onClick={() => { toggleChar(c.name); setCharSearch(""); }}
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

          {/* Book + chapter tags */}
          <div>
            <SectionHeader label="Chapter(s)" />
            <div className="mt-1.5 flex flex-col gap-2">
              {tags.map((tag, i) => {
                const book = books.find((b) => b.name === tag.book);
                return (
                  <div key={i} className="flex items-center gap-2">
                    <select
                      value={tag.book}
                      onChange={(e) => {
                        const nb = books.find((b) => b.name === e.target.value);
                        updateTag(i, {
                          book: e.target.value,
                          chapter: nb?.chapters[0]?.chapter ?? 0,
                        });
                      }}
                      className="flex-1 rounded-md border border-surface-border bg-surface px-2 py-1.5 text-xs text-ink-primary focus:border-accent/50 focus:outline-none"
                    >
                      {books.map((b) => (
                        <option key={b.id} value={b.name}>
                          {b.name}
                        </option>
                      ))}
                    </select>
                    <select
                      value={tag.chapter}
                      onChange={(e) =>
                        updateTag(i, { chapter: Number(e.target.value) })
                      }
                      className="w-40 rounded-md border border-surface-border bg-surface px-2 py-1.5 text-xs text-ink-primary focus:border-accent/50 focus:outline-none"
                    >
                      {(book?.chapters ?? []).map((c) => (
                        <option key={c.chapter} value={c.chapter}>
                          {c.chapter_heading}
                        </option>
                      ))}
                    </select>
                    <button
                      onClick={() => removeTag(i)}
                      className="rounded p-1.5 text-ink-muted transition-colors hover:bg-surface-hover hover:text-red-400"
                      title="Remove"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                );
              })}
              <button
                onClick={addTag}
                disabled={books.length === 0}
                className="flex items-center gap-1.5 self-start rounded-md border border-dashed border-surface-border px-2.5 py-1.5 text-[11px] text-ink-secondary transition-colors hover:border-accent hover:text-accent disabled:opacity-40"
              >
                <Plus className="h-3 w-3" /> Tag a book &amp; chapter
              </button>
            </div>
          </div>
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
  characters,
  books,
  locations,
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
          characters={characters}
          books={books}
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
