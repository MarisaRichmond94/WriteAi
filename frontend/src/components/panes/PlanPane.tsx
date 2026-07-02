import { useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import {
  ArrowLeftRight,
  Kanban,
  Plus,
  RefreshCw,
  ScanText,
  Trash2,
  X,
} from "lucide-react";
import { useApp } from "../../store";
import type {
  Citation,
  OutlineChapter,
  ResyncDiff,
  WriterCharacter,
} from "../../types";
import { api } from "../../lib/api";
import { bookColor, initials, povColor } from "../../lib/palette";
import { Button, ConfirmModal, Modal, SectionLabel, Spinner } from "../ui";
import { ChunkViewer, MessageThread, useStream } from "../chat";

type View = "outline" | "characters";

export function PlanPane() {
  const [view, setView] = useState<View>("outline");
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-surface-border px-6 py-3">
        {(["outline", "characters"] as View[]).map((v) => (
          <button
            key={v}
            onClick={() => setView(v)}
            className={clsx(
              "rounded-full border px-3 py-1 text-xs font-medium capitalize",
              view === v
                ? "border-accent bg-accent/10 text-accent"
                : "border-surface-border text-ink-secondary hover:text-ink-primary",
            )}
          >
            {v}
          </button>
        ))}
        <span className="ml-2 text-[10px] text-ink-muted">
          {view === "outline"
            ? "Your plan for each chapter, alongside what the written text shows."
            : "Your intent for each character — compare against what the AI extracted from the books."}
        </span>
      </div>
      <div className="min-h-0 flex-1">{view === "outline" ? <OutlineView /> : <CharacterView />}</div>
    </div>
  );
}

// ═══════════════════════════════ OUTLINE ═══════════════════════════════════

function OutlineView() {
  const { books, toast } = useApp();
  const [book, setBook] = useState<number>(1);
  const [chapters, setChapters] = useState<OutlineChapter[] | null>(null);
  const [editing, setEditing] = useState<OutlineChapter | null>(null);
  const [resync, setResync] = useState<{ diffs: ResyncDiff[]; new_chapters: number[]; removed_chapters: number[] } | null>(null);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [viewChunk, setViewChunk] = useState<string | null>(null);
  const stream = useStream("/api/plan/outline/review/stream");

  const load = () =>
    api<{ chapters: OutlineChapter[] }>(`/api/plan/outline/${book}`)
      .then((d) => setChapters(d.chapters))
      .catch((e) => toast(String(e), "error"));

  useEffect(() => {
    setChapters(null);
    load();
  }, [book]);

  const save = async (updated: OutlineChapter[]) => {
    setChapters(updated);
    await api(`/api/plan/outline/${book}`, {
      method: "PUT",
      body: JSON.stringify({ chapters: updated }),
    }).catch((e) => toast(String(e), "error"));
  };

  const addAt = async (position: number) => {
    await api(`/api/plan/outline/${book}/chapter`, {
      method: "POST",
      body: JSON.stringify({ position }),
    });
    load();
  };

  const remove = async (id: string) => {
    await api(`/api/plan/outline/${book}/chapter/${id}`, { method: "DELETE" });
    load();
  };

  const checkResync = async () => {
    try {
      const r = await api<typeof resync & { status: string }>(`/api/plan/resync/${book}`);
      if (r!.status === "in_sync") toast("Outline is in sync with the written chapters", "success");
      else setResync(r);
    } catch (e) {
      toast(String(e), "error");
    }
  };

  const runReview = () => {
    setReviewOpen(true);
    stream.send("Review my outline", { book, chapter_ids: [], message: "" });
  };

  return (
    <div className="flex h-full">
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-2 border-b border-surface-border px-6 py-2.5">
          <select
            value={book}
            onChange={(e) => setBook(Number(e.target.value))}
            className="rounded-md border border-surface-border bg-surface px-2.5 py-1.5 text-xs outline-none focus:border-accent"
          >
            {books.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
          <span className="flex-1" />
          <Button variant="secondary" onClick={checkResync} className="!px-3 !py-1">
            <RefreshCw className="h-3.5 w-3.5" strokeWidth={1.5} /> Sync check
          </Button>
          <Button onClick={runReview} disabled={stream.streaming} className="!px-3 !py-1">
            <ScanText className="h-3.5 w-3.5" strokeWidth={1.5} /> AI Review
          </Button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
          {chapters === null ? (
            <div className="flex justify-center py-16">
              <Spinner />
            </div>
          ) : (
            <div className={clsx("grid gap-3", reviewOpen ? "grid-cols-1 xl:grid-cols-2" : "grid-cols-1 lg:grid-cols-2 xl:grid-cols-3")}>
              {chapters.map((c, i) => {
                const pc = c.pov ? povColor(c.pov) : null;
                return (
                  <div key={c.id} className="group relative">
                    <button
                      onClick={() => setEditing(c)}
                      className="flex h-full w-full flex-col gap-2 rounded-lg border border-surface-border bg-surface-card p-4 text-left transition-colors hover:bg-surface-hover"
                    >
                      <div className="flex items-center gap-2">
                        <span
                          className={clsx(
                            "rounded-full px-2 py-px text-[9px] font-semibold uppercase tracking-wide",
                            c.status === "synced" ? "bg-emerald-400/15 text-emerald-300" : "bg-amber-400/15 text-amber-300",
                          )}
                        >
                          {c.status}
                        </span>
                        <span className="text-sm font-medium text-ink-primary">{c.heading}</span>
                      </div>
                      <div className="flex items-center gap-2 text-[10px] text-ink-muted">
                        {c.pov && pc && (
                          <span className={clsx("rounded-full px-1.5 py-px text-[9px] ring-1", pc.text, pc.ring, pc.bg)}>
                            {c.pov}
                          </span>
                        )}
                        {c.date && <span>{c.date}</span>}
                      </div>
                      {c.writer_summary ? (
                        <p className="text-[11px] leading-relaxed text-ink-secondary">{c.writer_summary}</p>
                      ) : (
                        <p className="text-[11px] italic text-ink-muted">No plan written yet — click to add.</p>
                      )}
                      {c.extracted_bullets.length > 0 && (
                        <ul className="mt-1 flex flex-col gap-0.5 border-t border-surface-border/60 pt-2">
                          {c.extracted_bullets.map((b, bi) => (
                            <li key={bi} className="text-[10px] leading-snug text-ink-muted">
                              <span className="text-accent">·</span> {b}
                            </li>
                          ))}
                        </ul>
                      )}
                    </button>
                    {/* insert-between button */}
                    <button
                      onClick={() => {
                        const next = chapters[i + 1];
                        addAt(next ? (c.position + next.position) / 2 : c.position + 1);
                      }}
                      title="Insert planned chapter after"
                      className="absolute -right-2 top-1/2 z-10 hidden h-5 w-5 -translate-y-1/2 items-center justify-center rounded-full border border-surface-border bg-surface-card text-ink-muted hover:border-accent hover:text-accent group-hover:flex"
                    >
                      <Plus className="h-3 w-3" strokeWidth={2} />
                    </button>
                  </div>
                );
              })}
              {chapters.length === 0 && (
                <div className="col-span-full py-16 text-center text-xs text-ink-muted">
                  <Kanban className="mx-auto mb-3 h-8 w-8" strokeWidth={1} />
                  No chapters outlined.
                  <div className="mt-3">
                    <Button onClick={() => addAt(1)}>
                      <Plus className="h-3.5 w-3.5" /> Add chapter
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* AI review panel */}
      {reviewOpen && !viewChunk && (
        <div className="flex h-full w-[42%] shrink-0 flex-col border-l border-surface-border bg-surface-card">
          <div className="flex items-center justify-between border-b border-surface-border px-4 py-3">
            <span className="text-xs font-medium">Outline review</span>
            <button onClick={() => setReviewOpen(false)} className="rounded-md p-1 text-ink-secondary hover:text-ink-primary">
              <X className="h-4 w-4" strokeWidth={1.5} />
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            <MessageThread
              messages={stream.messages}
              activeCitation={viewChunk}
              onCitation={(c: Citation) => setViewChunk(c.chunk_id)}
            />
          </div>
        </div>
      )}
      {viewChunk && <ChunkViewer chunkId={viewChunk} onClose={() => setViewChunk(null)} />}

      {editing && (
        <ChapterEditModal
          chapter={editing}
          onClose={() => setEditing(null)}
          onDelete={() => {
            remove(editing.id);
            setEditing(null);
          }}
          onSave={(updated) => {
            save(chapters!.map((c) => (c.id === updated.id ? updated : c)));
            setEditing(null);
          }}
        />
      )}
      {resync && (
        <ResyncModal
          book={book}
          data={resync}
          onClose={() => setResync(null)}
          onApplied={() => {
            setResync(null);
            load();
          }}
        />
      )}
    </div>
  );
}

function ChapterEditModal({
  chapter,
  onClose,
  onSave,
  onDelete,
}: {
  chapter: OutlineChapter;
  onClose: () => void;
  onSave: (c: OutlineChapter) => void;
  onDelete: () => void;
}) {
  const [heading, setHeading] = useState(chapter.heading);
  const [pov, setPov] = useState(chapter.pov);
  const [date, setDate] = useState(chapter.date ?? "");
  const [summary, setSummary] = useState(chapter.writer_summary);
  const [notes, setNotes] = useState(chapter.notes ?? "");
  const [confirmDelete, setConfirmDelete] = useState(false);

  const field = "w-full rounded-md border border-surface-border bg-surface px-2.5 py-1.5 text-xs outline-none focus:border-accent";
  return (
    <Modal title={chapter.status === "planned" ? "Planned chapter" : chapter.heading} onClose={onClose} wide>
      <div className="flex flex-col gap-3 text-xs">
        <div className="grid grid-cols-3 gap-2">
          <div>
            <SectionLabel>Heading</SectionLabel>
            <input value={heading} onChange={(e) => setHeading(e.target.value)} className={field} />
          </div>
          <div>
            <SectionLabel>POV</SectionLabel>
            <input value={pov} onChange={(e) => setPov(e.target.value)} className={field} />
          </div>
          <div>
            <SectionLabel>In-story date</SectionLabel>
            <input value={date} onChange={(e) => setDate(e.target.value)} className={field} />
          </div>
        </div>
        <div>
          <SectionLabel>Your plan (writer summary)</SectionLabel>
          <textarea value={summary} onChange={(e) => setSummary(e.target.value)} rows={4} className={clsx(field, "resize-y")} />
        </div>
        <div>
          <SectionLabel>Private notes</SectionLabel>
          <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} className={clsx(field, "resize-y")} />
        </div>
        {chapter.extracted_bullets.length > 0 && (
          <div>
            <SectionLabel>Extracted from the written chapter (read-only)</SectionLabel>
            <ul className="rounded-md border border-surface-border/70 bg-surface px-3 py-2">
              {chapter.extracted_bullets.map((b, i) => (
                <li key={i} className="py-0.5 text-[11px] text-ink-muted">
                  · {b}
                </li>
              ))}
            </ul>
          </div>
        )}
        <div className="mt-2 flex items-center justify-between">
          <Button variant="danger" onClick={() => setConfirmDelete(true)}>
            <Trash2 className="h-3.5 w-3.5" strokeWidth={1.5} /> Delete
          </Button>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button
              onClick={() =>
                onSave({
                  ...chapter,
                  heading,
                  pov,
                  date: date || null,
                  writer_summary: summary,
                  notes: notes || null,
                })
              }
            >
              Save
            </Button>
          </div>
        </div>
      </div>
      {confirmDelete && (
        <ConfirmModal
          title="Delete this outline card?"
          body="Only the outline entry is removed — never the written chapter."
          confirmLabel="Delete"
          onConfirm={onDelete}
          onClose={() => setConfirmDelete(false)}
        />
      )}
    </Modal>
  );
}

function ResyncModal({
  book,
  data,
  onClose,
  onApplied,
}: {
  book: number;
  data: { diffs: ResyncDiff[]; new_chapters: number[]; removed_chapters: number[] };
  onClose: () => void;
  onApplied: () => void;
}) {
  const { toast } = useApp();
  const [approved, setApproved] = useState<Set<string>>(new Set(data.diffs.map((d) => d.id)));
  const [busy, setBusy] = useState(false);

  const apply = async () => {
    setBusy(true);
    try {
      await api(`/api/plan/resync/${book}/approve`, {
        method: "POST",
        body: JSON.stringify({ diff_ids: Array.from(approved), add_new_chapters: true }),
      });
      toast("Outline synced", "success");
      onApplied();
    } catch (e) {
      toast(String(e), "error");
      setBusy(false);
    }
  };

  const render = (v: unknown) =>
    Array.isArray(v) ? (v.length ? v.join("; ").slice(0, 140) : "(empty)") : String(v ?? "(empty)");

  return (
    <Modal title="Sync outline with written chapters" onClose={onClose} wide>
      <div className="flex flex-col gap-3 text-xs">
        {data.new_chapters.length > 0 && (
          <div className="rounded-md border border-emerald-400/30 bg-emerald-400/10 px-3 py-2 text-emerald-300">
            {data.new_chapters.length} newly written chapter(s) will be added to the outline:{" "}
            {data.new_chapters.join(", ")}
          </div>
        )}
        {data.removed_chapters.length > 0 && (
          <div className="rounded-md border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-amber-300">
            Chapters {data.removed_chapters.join(", ")} exist in the outline but not in the books (left untouched).
          </div>
        )}
        {data.diffs.length > 0 && (
          <div>
            <SectionLabel>Field changes — approve individually</SectionLabel>
            <div className="flex max-h-72 flex-col gap-1.5 overflow-y-auto">
              {data.diffs.map((d) => (
                <label
                  key={d.id}
                  className="flex cursor-pointer items-start gap-2.5 rounded-md border border-surface-border px-3 py-2 hover:bg-surface-hover"
                >
                  <input
                    type="checkbox"
                    checked={approved.has(d.id)}
                    onChange={(e) => {
                      const next = new Set(approved);
                      e.target.checked ? next.add(d.id) : next.delete(d.id);
                      setApproved(next);
                    }}
                    className="mt-0.5 accent-[#7c6af7]"
                  />
                  <span className="min-w-0">
                    <span className="font-medium text-ink-primary">
                      Ch {d.chapter} · {d.field.replace(/_/g, " ")}
                    </span>
                    <span className="mt-0.5 block text-[10px] text-ink-muted">
                      <span className="text-rose-300/80 line-through">{render(d.outline_value)}</span>
                      <span className="mx-1.5 text-ink-muted">→</span>
                      <span className="text-emerald-300/90">{render(d.extracted_value)}</span>
                    </span>
                  </span>
                </label>
              ))}
            </div>
          </div>
        )}
        <div className="mt-1 flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={apply} disabled={busy}>
            {busy && <Spinner className="h-3.5 w-3.5" />} Apply sync
          </Button>
        </div>
      </div>
    </Modal>
  );
}

// ═══════════════════════════ WRITER CHARACTERS ══════════════════════════════

interface ExtractedProfile {
  found: boolean;
  name: string;
  aliases?: string[];
  traits?: string[];
  relationships?: { name: string; shared_scenes: number; nature: string | null }[];
  arcs?: Record<string, string>;
}

function CharacterView() {
  const { toast } = useApp();
  const [characters, setCharacters] = useState<WriterCharacter[] | null>(null);
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<WriterCharacter | null>(null);
  const [compare, setCompare] = useState<{ wc: WriterCharacter; extracted: ExtractedProfile } | null>(null);
  const [reviewFor, setReviewFor] = useState<WriterCharacter | null>(null);
  const [viewChunk, setViewChunk] = useState<string | null>(null);
  const stream = useStream("/api/plan/character/review/stream");

  const load = () =>
    api<{ characters: WriterCharacter[]; seeded: boolean }>("/api/plan/characters")
      .then((d) => {
        setCharacters(d.characters);
        if (d.seeded) toast("Character intent cards seeded from your books — edit freely", "info");
      })
      .catch((e) => toast(String(e), "error"));

  useEffect(() => {
    load();
  }, []);

  const openCompare = async (wc: WriterCharacter) => {
    try {
      const extracted = await api<ExtractedProfile>(`/api/plan/characters/${wc.id}/extracted`);
      setCompare({ wc, extracted });
      setReviewFor(null);
    } catch (e) {
      toast(String(e), "error");
    }
  };

  const openReview = (wc: WriterCharacter) => {
    setReviewFor(wc);
    setCompare(null);
    stream.setMessages([]);
    stream.send(`Review ${wc.name}`, { character_id: wc.id, message: "" });
  };

  const ordered = useMemo(() => {
    const rank = { main: 0, secondary: 1, tertiary: 2 } as Record<string, number>;
    return (characters ?? [])
      .filter((c) => !search || c.name.toLowerCase().includes(search.toLowerCase()))
      .sort((a, b) => (rank[a.category ?? "tertiary"] ?? 3) - (rank[b.category ?? "tertiary"] ?? 3) || a.name.localeCompare(b.name));
  }, [characters, search]);

  const panelOpen = compare != null || reviewFor != null;

  return (
    <div className="flex h-full">
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-2 border-b border-surface-border px-6 py-2.5">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search…"
            className="w-48 rounded-md border border-surface-border bg-surface px-2.5 py-1.5 text-xs outline-none placeholder:text-ink-muted focus:border-accent"
          />
          <span className="flex-1" />
          <span className="text-[10px] text-ink-muted">
            These cards are YOUR intent — the AI never edits them.
          </span>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
          {characters === null ? (
            <div className="flex justify-center py-16">
              <Spinner />
            </div>
          ) : (
            <div className={clsx("grid gap-3", panelOpen ? "grid-cols-1 xl:grid-cols-2" : "grid-cols-2 xl:grid-cols-4")}>
              {ordered.map((c) => {
                const pc = povColor(c.name);
                return (
                  <div
                    key={c.id}
                    className="flex flex-col gap-2 rounded-lg border border-surface-border bg-surface-card p-4"
                  >
                    <div className="flex items-center gap-2.5">
                      <span
                        className={clsx(
                          "flex h-9 w-9 items-center justify-center rounded-full text-xs font-semibold ring-1",
                          pc.text,
                          pc.ring,
                          pc.bg,
                        )}
                      >
                        {initials(c.name) || "?"}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium text-ink-primary">{c.name}</span>
                        <span
                          className={clsx(
                            "rounded-full px-1.5 py-px text-[9px] font-medium uppercase tracking-wide",
                            c.category === "main"
                              ? "bg-accent-subtle text-accent"
                              : c.category === "secondary"
                                ? "bg-sky-400/15 text-sky-300"
                                : "bg-surface text-ink-muted",
                          )}
                        >
                          {c.category ?? "uncategorized"}
                        </span>
                      </span>
                    </div>
                    {c.goals && <p className="text-[11px] text-ink-secondary">🎯 {c.goals}</p>}
                    {c.traits.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {c.traits.slice(0, 5).map((t) => (
                          <span key={t} className="rounded-full bg-surface px-1.5 py-px text-[9px] text-ink-secondary">
                            {t}
                          </span>
                        ))}
                      </div>
                    )}
                    {c.relationships.length > 0 && (
                      <div className="text-[10px] text-ink-muted">
                        {c.relationships.slice(0, 3).map((r) => `${r.target}: ${r.nature}`).join(" · ")}
                      </div>
                    )}
                    <div className="mt-auto flex gap-1.5 border-t border-surface-border/60 pt-2">
                      <Button variant="text" onClick={() => setEditing(c)} className="!px-1.5">
                        Edit
                      </Button>
                      <Button variant="text" onClick={() => openCompare(c)} className="!px-1.5">
                        <ArrowLeftRight className="h-3 w-3" strokeWidth={1.5} /> Compare
                      </Button>
                      <Button variant="text" onClick={() => openReview(c)} className="!px-1.5" disabled={stream.streaming}>
                        <ScanText className="h-3 w-3" strokeWidth={1.5} /> Review
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* compare panel */}
      {compare && !viewChunk && (
        <div className="flex h-full w-[42%] shrink-0 flex-col border-l border-surface-border bg-surface-card">
          <div className="flex items-center justify-between border-b border-surface-border px-4 py-3">
            <span className="text-xs font-medium">Intent vs. extracted — {compare.wc.name}</span>
            <button onClick={() => setCompare(null)} className="rounded-md p-1 text-ink-secondary hover:text-ink-primary">
              <X className="h-4 w-4" strokeWidth={1.5} />
            </button>
          </div>
          <div className="grid min-h-0 flex-1 grid-cols-2 gap-px overflow-y-auto bg-surface-border">
            <div className="bg-surface-card px-4 py-3">
              <SectionLabel>Your intent</SectionLabel>
              <CompareColumn
                traits={compare.wc.traits}
                relationships={compare.wc.relationships.map((r) => `${r.target} — ${r.nature}`)}
                extra={[compare.wc.goals && `Goals: ${compare.wc.goals}`, compare.wc.arc_notes && `Arc: ${compare.wc.arc_notes}`].filter(Boolean) as string[]}
              />
            </div>
            <div className="bg-surface-card px-4 py-3">
              <SectionLabel>Extracted from the books</SectionLabel>
              {compare.extracted.found ? (
                <CompareColumn
                  traits={compare.extracted.traits ?? []}
                  relationships={(compare.extracted.relationships ?? [])
                    .slice(0, 8)
                    .map((r) => `${r.name}${r.nature ? ` — ${r.nature}` : ""} (${r.shared_scenes} scenes)`)}
                  extra={Object.entries(compare.extracted.arcs ?? {}).map(([b, a]) => `Book ${b}: ${a}`)}
                />
              ) : (
                <p className="text-[11px] text-ink-muted">
                  No extracted character matches "{compare.extracted.name}" — check the name spelling or the
                  Characters page.
                </p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* AI review panel */}
      {reviewFor && !viewChunk && (
        <div className="flex h-full w-[42%] shrink-0 flex-col border-l border-surface-border bg-surface-card">
          <div className="flex items-center justify-between border-b border-surface-border px-4 py-3">
            <span className="text-xs font-medium">Character review — {reviewFor.name}</span>
            <button onClick={() => setReviewFor(null)} className="rounded-md p-1 text-ink-secondary hover:text-ink-primary">
              <X className="h-4 w-4" strokeWidth={1.5} />
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            <MessageThread
              messages={stream.messages}
              activeCitation={viewChunk}
              onCitation={(c: Citation) => setViewChunk(c.chunk_id)}
            />
          </div>
        </div>
      )}
      {viewChunk && <ChunkViewer chunkId={viewChunk} onClose={() => setViewChunk(null)} />}

      {editing && (
        <WriterCharacterEditModal
          character={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            load();
          }}
        />
      )}
    </div>
  );
}

function CompareColumn({ traits, relationships, extra }: { traits: string[]; relationships: string[]; extra: string[] }) {
  return (
    <div className="flex flex-col gap-3 text-[11px]">
      <div className="flex flex-wrap gap-1">
        {traits.length ? (
          traits.map((t) => (
            <span key={t} className="rounded-full bg-surface px-1.5 py-px text-[9px] text-ink-secondary">
              {t}
            </span>
          ))
        ) : (
          <span className="italic text-ink-muted">no traits recorded</span>
        )}
      </div>
      <ul className="flex flex-col gap-1 text-ink-secondary">
        {relationships.map((r, i) => (
          <li key={i}>· {r}</li>
        ))}
      </ul>
      {extra.map((e, i) => (
        <p key={i} className="leading-relaxed text-ink-muted">
          {e}
        </p>
      ))}
    </div>
  );
}

function WriterCharacterEditModal({
  character,
  onClose,
  onSaved,
}: {
  character: WriterCharacter;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { toast } = useApp();
  const [form, setForm] = useState({ ...character });
  const [traitsText, setTraitsText] = useState(character.traits.join(", "));
  const [relsText, setRelsText] = useState(character.relationships.map((r) => `${r.target}: ${r.nature}`).join("\n"));
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const field = "w-full rounded-md border border-surface-border bg-surface px-2.5 py-1.5 text-xs outline-none focus:border-accent";

  const save = async () => {
    setBusy(true);
    const body: WriterCharacter = {
      ...form,
      traits: traitsText.split(",").map((t) => t.trim()).filter(Boolean),
      relationships: relsText
        .split("\n")
        .map((l) => l.trim())
        .filter((l) => l.includes(":"))
        .map((l) => {
          const [target, ...rest] = l.split(":");
          return { target: target.trim(), nature: rest.join(":").trim() };
        }),
    };
    try {
      await api(`/api/plan/characters/${character.id}`, { method: "PUT", body: JSON.stringify(body) });
      onSaved();
    } catch (e) {
      toast(String(e), "error");
      setBusy(false);
    }
  };

  return (
    <Modal title={`Edit intent — ${character.name}`} onClose={onClose} wide>
      <div className="flex flex-col gap-3 text-xs">
        <div className="grid grid-cols-3 gap-2">
          <div>
            <SectionLabel>Name</SectionLabel>
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className={field} />
          </div>
          <div>
            <SectionLabel>Category</SectionLabel>
            <select
              value={form.category ?? ""}
              onChange={(e) => setForm({ ...form, category: (e.target.value || null) as WriterCharacter["category"] })}
              className={field}
            >
              <option value="">—</option>
              <option value="main">main</option>
              <option value="secondary">secondary</option>
              <option value="tertiary">tertiary</option>
            </select>
          </div>
          <div>
            <SectionLabel>Role</SectionLabel>
            <input value={form.role ?? ""} onChange={(e) => setForm({ ...form, role: e.target.value || null })} className={field} />
          </div>
        </div>
        <div>
          <SectionLabel>Traits (comma-separated)</SectionLabel>
          <input value={traitsText} onChange={(e) => setTraitsText(e.target.value)} className={field} />
        </div>
        <div>
          <SectionLabel>Goals</SectionLabel>
          <textarea value={form.goals ?? ""} onChange={(e) => setForm({ ...form, goals: e.target.value || null })} rows={2} className={clsx(field, "resize-y")} />
        </div>
        <div>
          <SectionLabel>Arc notes</SectionLabel>
          <textarea
            value={form.arc_notes ?? ""}
            onChange={(e) => setForm({ ...form, arc_notes: e.target.value || null })}
            rows={3}
            className={clsx(field, "resize-y")}
          />
        </div>
        <div>
          <SectionLabel>Relationships (one per line, "Name: nature")</SectionLabel>
          <textarea value={relsText} onChange={(e) => setRelsText(e.target.value)} rows={3} className={clsx(field, "resize-y font-mono")} />
        </div>
        <div className="mt-1 flex items-center justify-between">
          <Button variant="danger" onClick={() => setConfirmDelete(true)}>
            <Trash2 className="h-3.5 w-3.5" strokeWidth={1.5} /> Delete
          </Button>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button onClick={save} disabled={busy}>
              {busy && <Spinner className="h-3.5 w-3.5" />} Save
            </Button>
          </div>
        </div>
      </div>
      {confirmDelete && (
        <ConfirmModal
          title="Delete this intent card?"
          body="Removes your plan-page record only — extracted data is untouched."
          confirmLabel="Delete"
          onConfirm={async () => {
            await api(`/api/plan/characters/${character.id}`, { method: "DELETE" });
            onSaved();
          }}
          onClose={() => setConfirmDelete(false)}
        />
      )}
    </Modal>
  );
}
