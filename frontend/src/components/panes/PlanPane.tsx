import { useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import {
  ArrowLeftRight,
  Kanban,
  Plus,
  RefreshCw,
  ScanText,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { useApp } from "../../store";
import type { Citation, OutlineChapter, ResyncDiff, WriterCharacter } from "../../types";
import { api } from "../../lib/api";
import { initials, povColor } from "../../lib/palette";
import { Button, ConfirmModal, Modal, SectionLabel, Spinner } from "../ui";
import { ChunkViewer, MessageThread, useStream } from "../chat";
import { BookTabs, PaneHeader, Segmented } from "../shared";

type View = "outline" | "characters";

export function PlanPane() {
  const [view, setView] = useState<View>("outline");
  const { books } = useApp();
  const [book, setBook] = useState<number>(1);

  return (
    <div className="flex h-full flex-col">
      <PaneHeader
        icon={Kanban}
        title="Plan"
        info="Your authored plan lives here and is never edited by AI. Extracted data appears alongside it, read-only, for comparison."
        subtitle="Chapter outlines and character intent — your plan beside what the written books actually show"
      />
      <div className="flex flex-shrink-0 flex-wrap items-center gap-3 px-6 pb-3">
        <Segmented
          options={[
            { value: "outline", label: "Outline" },
            { value: "characters", label: "Characters" },
          ]}
          value={view}
          onChange={(v) => setView(v as View)}
        />
        <BookTabs books={books} value={book} onChange={setBook} />
      </div>
      <div className="min-h-0 flex-1">
        {view === "outline" ? <OutlineView book={book} /> : <CharacterView book={book} />}
      </div>
    </div>
  );
}

// ═══════════════════════════════ OUTLINE ═══════════════════════════════════

function OutlineView({ book }: { book: number }) {
  const { toast } = useApp();
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
    setReviewOpen(false);
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

  const checkResync = async () => {
    try {
      const r = await api<typeof resync & { status: string }>(`/api/plan/resync/${book}`);
      if (r!.status === "in_sync") toast("Outline is in sync with the written chapters", "success");
      else setResync(r);
    } catch (e) {
      toast(String(e), "error");
    }
  };

  return (
    <div className="flex h-full">
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex flex-shrink-0 items-center gap-2 px-6 pb-3">
          <span className="flex-1" />
          <button
            onClick={checkResync}
            className="flex items-center gap-1.5 rounded border border-surface-border px-3 py-1 text-[11px] text-ink-secondary transition-colors hover:border-accent hover:text-ink-primary"
          >
            <RefreshCw className="h-3 w-3" strokeWidth={1.5} /> Sync check
          </button>
          <button
            onClick={() => {
              setReviewOpen(true);
              stream.send("Review my outline", { book, chapter_ids: [], message: "" });
            }}
            disabled={stream.streaming}
            className="flex items-center gap-1.5 rounded border border-accent/50 px-3 py-1 text-[11px] text-accent transition-colors hover:bg-accent/10 disabled:opacity-40"
          >
            <ScanText className="h-3 w-3" strokeWidth={1.5} /> AI Review
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-4">
          {chapters === null ? (
            <div className="flex justify-center py-16">
              <Spinner />
            </div>
          ) : (
            <div className={clsx("grid gap-3", reviewOpen ? "grid-cols-1 xl:grid-cols-2" : "grid-cols-2 lg:grid-cols-3 xl:grid-cols-4")}>
              {chapters.map((c, i) => {
                const pc = c.pov ? povColor(c.pov) : null;
                return (
                  <div key={c.id} className="group relative">
                    <button
                      onClick={() => setEditing(c)}
                      className="flex h-full w-full flex-col gap-1.5 rounded-lg border border-surface-border bg-surface-card p-3 text-left transition-colors hover:border-accent/30 hover:bg-surface-hover"
                    >
                      <div className="flex w-full items-center gap-1.5">
                        <span className="text-[13px] font-semibold text-ink-primary">{c.heading}</span>
                        <span
                          className={clsx(
                            "rounded px-1.5 py-px text-[8px] font-semibold uppercase tracking-wide",
                            c.status === "synced" ? "bg-emerald-400/15 text-emerald-300" : "bg-amber-400/15 text-amber-300",
                          )}
                        >
                          {c.status}
                        </span>
                        <span className="flex-1" />
                        {c.pov && pc && (
                          <span className={clsx("rounded-full px-1.5 py-px text-[8px] font-medium ring-1", pc.text, pc.ring, pc.bg)}>
                            {c.pov.split(" ")[0]}
                          </span>
                        )}
                      </div>
                      {c.writer_summary && (
                        <p className="line-clamp-3 text-[10px] leading-relaxed text-ink-secondary">{c.writer_summary}</p>
                      )}
                      <ul className="flex flex-col gap-0.5">
                        {c.extracted_bullets.slice(0, 5).map((b, bi) => (
                          <li key={bi} className="text-[10px] leading-snug text-ink-muted">
                            <span className="text-accent">·</span> {b}
                          </li>
                        ))}
                        {c.extracted_bullets.length === 0 && !c.writer_summary && (
                          <li className="text-[10px] italic text-ink-muted">No plan yet — click to write one.</li>
                        )}
                      </ul>
                    </button>
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
          onDelete={async () => {
            await api(`/api/plan/outline/${book}/chapter/${editing.id}`, { method: "DELETE" });
            setEditing(null);
            load();
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

  const field =
    "w-full rounded-md border border-surface-border bg-surface px-2.5 py-1.5 text-xs outline-none focus:border-accent";
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
                onSave({ ...chapter, heading, pov, date: date || null, writer_summary: summary, notes: notes || null })
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

  const render = (v: unknown) =>
    Array.isArray(v) ? (v.length ? v.join("; ").slice(0, 140) : "(empty)") : String(v ?? "(empty)");

  return (
    <Modal title="Sync outline with written chapters" onClose={onClose} wide>
      <div className="flex flex-col gap-3 text-xs">
        {data.new_chapters.length > 0 && (
          <div className="rounded-md border border-emerald-400/30 bg-emerald-400/10 px-3 py-2 text-emerald-300">
            {data.new_chapters.length} newly written chapter(s) will be added: {data.new_chapters.join(", ")}
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
          <Button
            onClick={async () => {
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
            }}
            disabled={busy}
          >
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
  traits?: string[];
  relationships?: { name: string; shared_scenes: number; nature: string | null }[];
  arcs?: Record<string, string>;
}

function CharacterView({ book }: { book: number }) {
  const { toast } = useApp();
  const [characters, setCharacters] = useState<WriterCharacter[] | null>(null);
  const [search, setSearch] = useState("");
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

  const saveCharacter = async (updated: WriterCharacter) => {
    setCharacters((cs) => (cs ?? []).map((c) => (c.id === updated.id ? updated : c)));
    await api(`/api/plan/characters/${updated.id}`, {
      method: "PUT",
      body: JSON.stringify(updated),
    }).catch((e) => toast(String(e), "error"));
  };

  const addCharacter = async () => {
    const fresh: Omit<WriterCharacter, "id"> & { id?: string } = {
      name: "New Character",
      category: "tertiary",
      role: null,
      aliases: null,
      traits: [],
      arc_notes: null,
      goals: null,
      relationships: [],
      books: [book],
    };
    const all = [...(characters ?? []), { ...fresh, id: `wc-new-${Date.now()}` } as WriterCharacter];
    setCharacters(all);
    await api("/api/plan/characters", { method: "PUT", body: JSON.stringify({ characters: all }) }).catch((e) =>
      toast(String(e), "error"),
    );
    load();
  };

  const ordered = useMemo(() => {
    const rank = { main: 0, secondary: 1, tertiary: 2 } as Record<string, number>;
    return (characters ?? [])
      .filter((c) => !c.books.length || c.books.includes(book))
      .filter((c) => !search || c.name.toLowerCase().includes(search.toLowerCase()))
      .sort(
        (a, b) =>
          (rank[a.category ?? "tertiary"] ?? 3) - (rank[b.category ?? "tertiary"] ?? 3) ||
          a.name.localeCompare(b.name),
      );
  }, [characters, search, book]);

  const panelOpen = compare != null || reviewFor != null;

  return (
    <div className="flex h-full">
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex flex-shrink-0 items-center gap-2 px-6 pb-3">
          <div className="flex w-64 items-center gap-2 rounded-md border border-surface-border bg-surface px-2.5 py-1.5 focus-within:border-accent">
            <Search className="h-3.5 w-3.5 text-ink-muted" strokeWidth={1.5} />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search characters…"
              className="flex-1 bg-transparent text-xs text-ink-primary outline-none placeholder:text-ink-muted"
            />
          </div>
          <span className="flex-1" />
          <button
            onClick={addCharacter}
            className="flex items-center gap-1.5 rounded border border-accent/50 px-3 py-1 text-[11px] text-accent transition-colors hover:bg-accent/10"
          >
            <Plus className="h-3 w-3" strokeWidth={2} /> New Character
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-4">
          {characters === null ? (
            <div className="flex justify-center py-16">
              <Spinner />
            </div>
          ) : (
            <div className={clsx("grid items-start gap-3", panelOpen ? "grid-cols-1 xl:grid-cols-2" : "grid-cols-2 xl:grid-cols-4")}>
              {ordered.map((c) => (
                <WriterCharacterCard
                  key={c.id}
                  character={c}
                  onSave={saveCharacter}
                  onCompare={async () => {
                    try {
                      const extracted = await api<ExtractedProfile>(`/api/plan/characters/${c.id}/extracted`);
                      setCompare({ wc: c, extracted });
                      setReviewFor(null);
                    } catch (e) {
                      toast(String(e), "error");
                    }
                  }}
                  onReview={() => {
                    setReviewFor(c);
                    setCompare(null);
                    stream.setMessages([]);
                    stream.send(`Review ${c.name}`, { character_id: c.id, message: "" });
                  }}
                  onDelete={async () => {
                    await api(`/api/plan/characters/${c.id}`, { method: "DELETE" });
                    load();
                  }}
                  reviewDisabled={stream.streaming}
                />
              ))}
            </div>
          )}
        </div>
      </div>

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
                extra={
                  [compare.wc.goals && `Goals: ${compare.wc.goals}`, compare.wc.arc_notes && `Arc: ${compare.wc.arc_notes}`].filter(
                    Boolean,
                  ) as string[]
                }
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
                  No extracted character matches "{compare.extracted.name}" — check the spelling against the
                  Characters page.
                </p>
              )}
            </div>
          </div>
        </div>
      )}

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

// inline-editable writer character card (auto-saves on blur, like the reference)
function WriterCharacterCard({
  character,
  onSave,
  onCompare,
  onReview,
  onDelete,
  reviewDisabled,
}: {
  character: WriterCharacter;
  onSave: (c: WriterCharacter) => void;
  onCompare: () => void;
  onReview: () => void;
  onDelete: () => void;
  reviewDisabled: boolean;
}) {
  const [draft, setDraft] = useState(character);
  const [newTrait, setNewTrait] = useState("");
  const [newRel, setNewRel] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const pc = povColor(draft.name);

  useEffect(() => setDraft(character), [character.id]);

  const commit = (next: WriterCharacter) => {
    setDraft(next);
    onSave(next);
  };

  const inputCls =
    "w-full rounded-md border border-transparent bg-surface px-2 py-1 text-[11px] text-ink-primary outline-none transition-colors placeholder:text-ink-muted hover:border-surface-border focus:border-accent";

  return (
    <div className="flex flex-col gap-2.5 rounded-lg border border-surface-border bg-surface-card p-3.5">
      <div className="flex items-center gap-2.5">
        <span className={clsx("flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full text-xs font-semibold ring-1", pc.text, pc.ring, pc.bg)}>
          {initials(draft.name) || "?"}
        </span>
        <div className="min-w-0 flex-1">
          <input
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            onBlur={() => draft.name !== character.name && commit(draft)}
            className={clsx(inputCls, "!bg-transparent px-0 text-[13px] font-semibold")}
          />
          <select
            value={draft.category ?? ""}
            onChange={(e) => commit({ ...draft, category: (e.target.value || null) as WriterCharacter["category"] })}
            className="rounded bg-surface px-1 py-px text-[9px] uppercase tracking-wide text-ink-secondary outline-none"
          >
            <option value="main">main</option>
            <option value="secondary">secondary</option>
            <option value="tertiary">tertiary</option>
            <option value="">—</option>
          </select>
        </div>
        <button onClick={() => setConfirmDelete(true)} className="self-start rounded p-1 text-ink-muted hover:text-rose-300">
          <Trash2 className="h-3 w-3" strokeWidth={1.5} />
        </button>
      </div>

      <textarea
        value={draft.goals ?? ""}
        onChange={(e) => setDraft({ ...draft, goals: e.target.value || null })}
        onBlur={() => draft.goals !== character.goals && commit(draft)}
        placeholder="Goals — what do they want?"
        rows={2}
        className={clsx(inputCls, "resize-none")}
      />
      <textarea
        value={draft.arc_notes ?? ""}
        onChange={(e) => setDraft({ ...draft, arc_notes: e.target.value || null })}
        onBlur={() => draft.arc_notes !== character.arc_notes && commit(draft)}
        placeholder="Arc notes — where are they headed?"
        rows={2}
        className={clsx(inputCls, "resize-none")}
      />

      <div>
        <p className="mb-1 text-[9px] font-bold uppercase tracking-wider text-ink-muted">Relationships</p>
        <div className="flex flex-col gap-1">
          {draft.relationships.map((r, i) => (
            <div key={i} className="flex items-center gap-2">
              <span className={clsx("flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full text-[8px] font-semibold ring-1", povColor(r.target).text, povColor(r.target).ring, povColor(r.target).bg)}>
                {initials(r.target) || "?"}
              </span>
              <span className="min-w-0 flex-1 truncate text-[10px] text-ink-secondary">
                <span className="font-medium text-ink-primary">{r.target}</span> — {r.nature}
              </span>
              <button
                onClick={() => commit({ ...draft, relationships: draft.relationships.filter((_, ri) => ri !== i) })}
                className="rounded p-0.5 text-ink-muted hover:text-rose-300"
              >
                <X className="h-2.5 w-2.5" strokeWidth={2} />
              </button>
            </div>
          ))}
          <input
            value={newRel}
            onChange={(e) => setNewRel(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && newRel.includes(":")) {
                const [target, ...rest] = newRel.split(":");
                commit({
                  ...draft,
                  relationships: [...draft.relationships, { target: target.trim(), nature: rest.join(":").trim() }],
                });
                setNewRel("");
              }
            }}
            placeholder='+ Add ("Name: nature", Enter)'
            className={inputCls}
          />
        </div>
      </div>

      <div>
        <div className="flex flex-wrap items-center gap-1">
          {draft.traits.map((t, i) => (
            <span key={t + i} className="flex items-center gap-1 rounded-full bg-accent-subtle px-2 py-0.5 text-[9px] text-accent">
              {t}
              <button
                onClick={() => commit({ ...draft, traits: draft.traits.filter((_, ti) => ti !== i) })}
                className="hover:text-rose-300"
              >
                <X className="h-2 w-2" strokeWidth={2.5} />
              </button>
            </span>
          ))}
          <input
            value={newTrait}
            onChange={(e) => setNewTrait(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && newTrait.trim()) {
                commit({ ...draft, traits: [...draft.traits, newTrait.trim()] });
                setNewTrait("");
              }
            }}
            placeholder="+ trait"
            className="w-16 rounded-full border border-transparent bg-surface px-2 py-0.5 text-[9px] text-ink-secondary outline-none placeholder:text-ink-muted focus:border-accent"
          />
        </div>
      </div>

      <div className="mt-auto flex gap-1.5 border-t border-surface-border/60 pt-2">
        <button onClick={onCompare} className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-ink-secondary hover:text-ink-primary">
          <ArrowLeftRight className="h-3 w-3" strokeWidth={1.5} /> Compare
        </button>
        <button
          onClick={onReview}
          disabled={reviewDisabled}
          className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-ink-secondary hover:text-ink-primary disabled:opacity-40"
        >
          <ScanText className="h-3 w-3" strokeWidth={1.5} /> Review
        </button>
      </div>

      {confirmDelete && (
        <ConfirmModal
          title="Delete this intent card?"
          body="Removes your plan-page record only — extracted data is untouched."
          confirmLabel="Delete"
          onConfirm={onDelete}
          onClose={() => setConfirmDelete(false)}
        />
      )}
    </div>
  );
}
