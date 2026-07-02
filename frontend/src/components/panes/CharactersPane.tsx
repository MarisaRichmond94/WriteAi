import { useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import { ArrowDownUp, EyeOff, GitMerge, Pencil, Search, Users, X } from "lucide-react";
import { useApp } from "../../store";
import type { CharacterDetail, CharacterSummary, QuarantinedName } from "../../types";
import { api } from "../../lib/api";
import { bookColor, initials, povColor } from "../../lib/palette";
import { Button, EmptyState, Modal, SectionLabel, Spinner } from "../ui";
import { ChunkViewer } from "../chat";

type SortKey = "shared_scenes" | "name";

export function CharactersPane() {
  const { toast } = useApp();
  const [characters, setCharacters] = useState<CharacterSummary[] | null>(null);
  const [quarantined, setQuarantined] = useState<QuarantinedName[]>([]);
  const [hidden, setHidden] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const [bookFilter, setBookFilter] = useState<number | null>(null);
  const [detailName, setDetailName] = useState<string | null>(null);
  const [detail, setDetail] = useState<CharacterDetail | null>(null);
  const [editTarget, setEditTarget] = useState<CharacterSummary | null>(null);
  const [showQuarantine, setShowQuarantine] = useState(false);
  const [relSort, setRelSort] = useState<SortKey>("shared_scenes");
  const [viewChunk, setViewChunk] = useState<string | null>(null);

  const load = () =>
    api<{ characters: CharacterSummary[]; quarantined: QuarantinedName[]; hidden: string[] }>("/api/characters")
      .then((d) => {
        setCharacters(d.characters);
        setQuarantined(d.quarantined);
        setHidden(d.hidden);
      })
      .catch((e) => toast(String(e), "error"));

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    setDetail(null);
    if (detailName) {
      api<CharacterDetail>(`/api/characters/${encodeURIComponent(detailName)}`)
        .then(setDetail)
        .catch((e) => toast(String(e), "error"));
    }
  }, [detailName]);

  const filtered = useMemo(() => {
    if (!characters) return [];
    return characters.filter(
      (c) =>
        (!search ||
          c.name.toLowerCase().includes(search.toLowerCase()) ||
          c.aliases.some((a) => a.toLowerCase().includes(search.toLowerCase()))) &&
        (bookFilter == null || c.books.includes(bookFilter)),
    );
  }, [characters, search, bookFilter]);

  const books = useMemo(
    () => Array.from(new Set((characters ?? []).flatMap((c) => c.books))).sort((a, b) => a - b),
    [characters],
  );

  if (characters === null) {
    return (
      <div className="flex h-full items-center justify-center text-ink-muted">
        <Spinner className="h-5 w-5" />
      </div>
    );
  }

  return (
    <div className="flex h-full">
      <div className="flex min-w-0 flex-1 flex-col">
        {/* toolbar */}
        <div className="flex flex-wrap items-center gap-2 border-b border-surface-border px-6 py-3">
          <div className="flex items-center gap-2 rounded-md border border-surface-border bg-surface px-2.5 py-1.5 focus-within:border-accent">
            <Search className="h-3.5 w-3.5 text-ink-muted" strokeWidth={1.5} />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search characters…"
              className="w-44 bg-transparent text-xs text-ink-primary outline-none placeholder:text-ink-muted"
            />
          </div>
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
              key={b}
              onClick={() => setBookFilter(bookFilter === b ? null : b)}
              className={clsx(
                "rounded-full px-2 py-0.5 text-[10px] font-medium",
                bookColor(b),
                bookFilter != null && bookFilter !== b && "opacity-30",
              )}
            >
              Book {b}
            </button>
          ))}
          <span className="flex-1" />
          {quarantined.length > 0 && (
            <button
              onClick={() => setShowQuarantine(true)}
              className="text-[11px] text-ink-muted underline-offset-2 hover:text-ink-secondary hover:underline"
            >
              {quarantined.length} quarantined name(s)
            </button>
          )}
        </div>

        {/* grid */}
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
          {filtered.length === 0 ? (
            <EmptyState
              icon={<Users className="h-10 w-10" strokeWidth={1} />}
              title="No characters matched"
              hint={search ? "Try a different search." : "Run ingestion first."}
            />
          ) : (
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-3">
              {filtered.map((c) => {
                const pc = povColor(c.name);
                return (
                  <button
                    key={c.id}
                    onClick={() => setDetailName(detailName === c.name ? null : c.name)}
                    className={clsx(
                      "flex flex-col gap-2 rounded-lg border p-4 text-left transition-colors",
                      detailName === c.name
                        ? "border-accent bg-accent/10"
                        : "border-surface-border bg-surface-card hover:bg-surface-hover",
                    )}
                  >
                    <div className="flex items-center gap-3">
                      <span
                        className={clsx(
                          "flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold ring-1",
                          pc.text,
                          pc.ring,
                          pc.bg,
                        )}
                      >
                        {initials(c.name) || "?"}
                      </span>
                      <span className="min-w-0">
                        <span className="flex items-center gap-2">
                          <span className="truncate text-sm font-medium text-ink-primary">{c.name}</span>
                          {c.is_pov && (
                            <span className="rounded-full bg-accent-subtle px-1.5 py-px text-[9px] font-medium text-accent">
                              POV
                            </span>
                          )}
                        </span>
                        <span className="text-[10px] text-ink-muted">
                          {c.chapter_count} chapters · books {c.books.join(", ")}
                        </span>
                      </span>
                    </div>
                    {c.aliases.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {c.aliases.map((a) => (
                          <span key={a} className="rounded-full border border-surface-border px-1.5 py-px text-[9px] text-ink-secondary">
                            {a}
                          </span>
                        ))}
                      </div>
                    )}
                    {c.traits.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {c.traits.slice(0, 4).map((t) => (
                          <span key={t} className="rounded-full bg-surface px-1.5 py-px text-[9px] text-ink-secondary">
                            {t}
                          </span>
                        ))}
                      </div>
                    )}
                    {c.relationships.length > 0 && (
                      <div className="text-[10px] text-ink-muted">
                        {c.relationships
                          .slice(0, 3)
                          .map((r) => `${r.name}${r.nature ? ` (${r.nature})` : ""}`)
                          .join(" · ")}
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* detail panel */}
      {detailName && !viewChunk && (
        <div className="flex h-full w-[36%] shrink-0 flex-col border-l border-surface-border bg-surface-card">
          <div className="flex items-center justify-between border-b border-surface-border px-4 py-3">
            <div className="text-sm font-semibold">{detailName}</div>
            <div className="flex items-center gap-1">
              <button
                onClick={() => detail && setEditTarget(detail)}
                className="rounded-md p-1 text-ink-secondary hover:text-ink-primary"
                title="Edit / merge / hide"
              >
                <Pencil className="h-3.5 w-3.5" strokeWidth={1.5} />
              </button>
              <button onClick={() => setDetailName(null)} className="rounded-md p-1 text-ink-secondary hover:text-ink-primary">
                <X className="h-4 w-4" strokeWidth={1.5} />
              </button>
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
            {!detail ? (
              <div className="flex justify-center py-10">
                <Spinner />
              </div>
            ) : (
              <div className="flex flex-col gap-4 text-xs">
                {detail.traits.length > 0 && (
                  <div>
                    <SectionLabel>Traits</SectionLabel>
                    <div className="flex flex-wrap gap-1">
                      {detail.traits.map((t) => (
                        <span key={t} className="rounded-full bg-surface px-2 py-0.5 text-[10px] text-ink-secondary">
                          {t}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                <div>
                  <div className="flex items-center justify-between">
                    <SectionLabel>Relationships</SectionLabel>
                    <button
                      onClick={() => setRelSort(relSort === "shared_scenes" ? "name" : "shared_scenes")}
                      className="flex items-center gap-1 text-[9px] text-ink-muted hover:text-ink-secondary"
                    >
                      <ArrowDownUp className="h-3 w-3" strokeWidth={1.5} />
                      {relSort === "shared_scenes" ? "by scenes" : "by name"}
                    </button>
                  </div>
                  <div className="flex flex-col gap-1">
                    {[...detail.relationships]
                      .sort((a, b) =>
                        relSort === "shared_scenes" ? b.shared_scenes - a.shared_scenes : a.name.localeCompare(b.name),
                      )
                      .slice(0, 14)
                      .map((r) => (
                        <button
                          key={r.name}
                          onClick={() => setDetailName(r.name)}
                          className="flex items-center justify-between rounded-md px-2 py-1 text-left hover:bg-surface-hover"
                        >
                          <span>
                            <span className="text-ink-primary">{r.name}</span>
                            {r.nature && <span className="text-ink-muted"> — {r.nature}</span>}
                          </span>
                          <span className="text-[10px] text-ink-muted">{r.shared_scenes}</span>
                        </button>
                      ))}
                  </div>
                </div>
                {Object.keys(detail.arcs).length > 0 && (
                  <div>
                    <SectionLabel>Arc by book</SectionLabel>
                    <div className="flex flex-col gap-2">
                      {Object.entries(detail.arcs)
                        .sort(([a], [b]) => Number(a) - Number(b))
                        .map(([book, arc]) => (
                          <div key={book}>
                            <span className={clsx("mr-1.5 rounded-full px-1.5 py-px text-[9px]", bookColor(Number(book)))}>
                              Book {book}
                            </span>
                            <span className="leading-relaxed text-ink-secondary">{arc}</span>
                          </div>
                        ))}
                    </div>
                  </div>
                )}
                <div>
                  <SectionLabel>Knowledge</SectionLabel>
                  <div className="flex flex-col gap-2">
                    {Object.entries(detail.knowledge_by_book)
                      .sort(([a], [b]) => Number(a) - Number(b))
                      .map(([book, facts]) => (
                        <details key={book} className="group">
                          <summary className="cursor-pointer text-[11px] text-ink-secondary hover:text-ink-primary">
                            Book {book} — {facts.length} facts learned
                          </summary>
                          <ul className="mt-1 flex flex-col gap-0.5 pl-3">
                            {facts.slice(0, 40).map((f, i) => (
                              <li key={i} className="text-[10px] leading-relaxed text-ink-muted">
                                <span className="text-ink-secondary">Ch {f.chapter}:</span> {f.learns}
                              </li>
                            ))}
                          </ul>
                        </details>
                      ))}
                  </div>
                </div>
                <div>
                  <SectionLabel>Appearances</SectionLabel>
                  {Object.entries(detail.appearances_by_book)
                    .sort(([a], [b]) => Number(a) - Number(b))
                    .map(([book, chapters]) => (
                      <div key={book} className="mb-1.5 flex flex-wrap items-center gap-1">
                        <span className={clsx("rounded-full px-1.5 py-px text-[9px]", bookColor(Number(book)))}>
                          B{book}
                        </span>
                        {chapters.map((ch) => (
                          <span key={ch} className="rounded border border-surface-border px-1 py-px text-[9px] text-ink-muted">
                            {ch}
                          </span>
                        ))}
                      </div>
                    ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
      {viewChunk && <ChunkViewer chunkId={viewChunk} onClose={() => setViewChunk(null)} />}

      {editTarget && (
        <EditCharacterModal
          character={editTarget}
          allNames={(characters ?? []).map((c) => c.name)}
          onClose={() => setEditTarget(null)}
          onChanged={() => {
            setEditTarget(null);
            setDetailName(null);
            load();
          }}
        />
      )}
      {showQuarantine && (
        <Modal title="Quarantined names" onClose={() => setShowQuarantine(false)} wide>
          <p className="mb-3 text-xs text-ink-secondary">
            These extraction tags don't appear anywhere in your prose and had no unambiguous match, so they're
            excluded from every page. Assign one to a character to rescue it.
          </p>
          <div className="flex flex-col gap-1.5">
            {quarantined.map((q) => (
              <QuarantineRow
                key={q.name}
                item={q}
                allNames={(characters ?? []).map((c) => c.name)}
                onAssigned={() => {
                  setShowQuarantine(false);
                  load();
                }}
              />
            ))}
          </div>
        </Modal>
      )}
    </div>
  );
}

function QuarantineRow({
  item,
  allNames,
  onAssigned,
}: {
  item: QuarantinedName;
  allNames: string[];
  onAssigned: () => void;
}) {
  const { toast } = useApp();
  const [target, setTarget] = useState("");
  return (
    <div className="flex items-center gap-2 rounded-md border border-surface-border px-3 py-2 text-xs">
      <span className="min-w-0 flex-1 truncate text-ink-primary">{item.name}</span>
      <span className="text-[10px] text-ink-muted">{item.chunk_count} scene(s)</span>
      <select
        value={target}
        onChange={(e) => setTarget(e.target.value)}
        className="rounded border border-surface-border bg-surface px-1.5 py-1 text-[10px] outline-none"
      >
        <option value="">assign to…</option>
        {allNames.map((n) => (
          <option key={n} value={n}>
            {n}
          </option>
        ))}
      </select>
      <Button
        variant="secondary"
        className="!px-2 !py-1 !text-[10px]"
        disabled={!target}
        onClick={async () => {
          try {
            await api("/api/characters/merge", {
              method: "POST",
              body: JSON.stringify({ source: item.name, target }),
            });
            toast(`"${item.name}" assigned to ${target}`, "success");
            onAssigned();
          } catch (e) {
            toast(String(e), "error");
          }
        }}
      >
        Assign
      </Button>
    </div>
  );
}

function EditCharacterModal({
  character,
  allNames,
  onClose,
  onChanged,
}: {
  character: CharacterSummary;
  allNames: string[];
  onClose: () => void;
  onChanged: () => void;
}) {
  const { toast } = useApp();
  const [mergeTarget, setMergeTarget] = useState("");
  const [newName, setNewName] = useState(character.name);
  const [busy, setBusy] = useState(false);

  const act = async (fn: () => Promise<unknown>, message: string) => {
    setBusy(true);
    try {
      await fn();
      toast(message, "success");
      onChanged();
    } catch (e) {
      toast(String(e), "error");
      setBusy(false);
    }
  };

  return (
    <Modal title={`Edit "${character.name}"`} onClose={onClose}>
      <div className="flex flex-col gap-5 text-xs">
        <div>
          <SectionLabel>Rename</SectionLabel>
          <div className="flex gap-2">
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              className="flex-1 rounded-md border border-surface-border bg-surface px-2.5 py-1.5 text-xs outline-none focus:border-accent"
            />
            <Button
              variant="secondary"
              disabled={busy || !newName.trim() || newName === character.name}
              onClick={() =>
                act(
                  () =>
                    api("/api/characters/rename", {
                      method: "POST",
                      body: JSON.stringify({ old: character.name, new: newName.trim() }),
                    }),
                  "Renamed",
                )
              }
            >
              Rename
            </Button>
          </div>
        </div>
        <div>
          <SectionLabel>Merge into another character</SectionLabel>
          <div className="flex gap-2">
            <select
              value={mergeTarget}
              onChange={(e) => setMergeTarget(e.target.value)}
              className="flex-1 rounded-md border border-surface-border bg-surface px-2.5 py-1.5 text-xs outline-none focus:border-accent"
            >
              <option value="">Choose target…</option>
              {allNames
                .filter((n) => n !== character.name)
                .map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
            </select>
            <Button
              variant="secondary"
              disabled={busy || !mergeTarget}
              onClick={() =>
                act(
                  () =>
                    api("/api/characters/merge", {
                      method: "POST",
                      body: JSON.stringify({ source: character.name, target: mergeTarget }),
                    }),
                  `Merged into ${mergeTarget}`,
                )
              }
            >
              <GitMerge className="h-3.5 w-3.5" strokeWidth={1.5} /> Merge
            </Button>
          </div>
          <p className="mt-1.5 text-[10px] text-ink-muted">
            Merges are saved to writer_data and survive re-indexing — you decide once.
          </p>
        </div>
        <div>
          <SectionLabel>Hide</SectionLabel>
          <Button
            variant="danger"
            disabled={busy}
            onClick={() =>
              act(
                () =>
                  api("/api/characters/hide", {
                    method: "POST",
                    body: JSON.stringify({ name: character.name }),
                  }),
                "Hidden from all pages",
              )
            }
          >
            <EyeOff className="h-3.5 w-3.5" strokeWidth={1.5} /> Hide "{character.name}"
          </Button>
        </div>
      </div>
    </Modal>
  );
}
