import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { Check, Download, Loader2, Search, X } from "lucide-react";
import { clsx } from "clsx";
import type { CharacterSummary } from "../../../types";
import { fetchCharacters } from "../../../api/characters";

/** Pick AI-extracted characters to import as writer characters.
 * Characters whose names already exist as writer characters are hidden —
 * import never merges or overwrites. */
export default function ImportCharactersModal({
  existingNames,
  importing,
  onImport,
  onClose,
}: {
  existingNames: Set<string>;
  importing: boolean;
  onImport: (names: string[]) => void;
  onClose: () => void;
}) {
  const [extracted, setExtracted] = useState<CharacterSummary[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  useEffect(() => {
    fetchCharacters()
      .then(setExtracted)
      .catch(() => setFailed(true));
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const candidates = useMemo(
    () => (extracted ?? []).filter((c) => !existingNames.has(c.name)),
    [extracted, existingNames],
  );
  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return candidates;
    return candidates.filter((c) =>
      [c.name, ...c.aliases.map((a) => a.alias)].join(" ").toLowerCase().includes(q));
  }, [candidates, search]);

  const toggle = (name: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name); else next.add(name);
      return next;
    });

  const allVisibleSelected = visible.length > 0 && visible.every((c) => selected.has(c.name));

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm py-10" onClick={onClose}>
      <div
        className="relative mx-4 flex max-h-full w-full max-w-md flex-col rounded-xl border border-surface-border bg-surface-card shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex flex-shrink-0 items-start justify-between border-b border-surface-border px-5 py-4">
          <div>
            <p className="text-sm font-semibold text-ink-primary">Import Extracted Characters</p>
            <p className="mt-0.5 text-[11px] text-ink-muted">
              Brings over name, aliases, relationships, and photo. Existing writer characters are never touched.
            </p>
          </div>
          <button onClick={onClose} className="rounded p-1 text-ink-muted hover:text-ink-primary transition-colors">
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Search + select all */}
        <div className="flex flex-shrink-0 items-center gap-2 border-b border-surface-border px-5 py-3">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3 w-3 -translate-y-1/2 text-ink-muted" />
            <input
              autoFocus
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search extracted characters…"
              className="w-full rounded border border-surface-border bg-surface py-1.5 pl-7 pr-2 text-xs text-ink-primary placeholder:text-ink-muted focus:border-accent focus:outline-none"
            />
          </div>
          <button
            onClick={() =>
              setSelected((prev) => {
                const next = new Set(prev);
                if (allVisibleSelected) visible.forEach((c) => next.delete(c.name));
                else visible.forEach((c) => next.add(c.name));
                return next;
              })
            }
            disabled={visible.length === 0}
            className="flex-shrink-0 text-[11px] text-ink-secondary hover:text-accent transition-colors disabled:opacity-40"
          >
            {allVisibleSelected ? "Clear visible" : "Select visible"}
          </button>
        </div>

        {/* List */}
        <div className="min-h-0 flex-1 overflow-y-auto">
          {extracted === null && !failed && (
            <div className="flex items-center justify-center gap-2 py-10 text-xs text-ink-muted">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading extracted characters…
            </div>
          )}
          {failed && <p className="px-5 py-8 text-center text-xs text-red-400">Failed to load extracted characters.</p>}
          {extracted !== null && visible.length === 0 && !failed && (
            <p className="px-5 py-8 text-center text-xs text-ink-muted">
              {candidates.length === 0
                ? "Every extracted character already exists as a writer character."
                : `No extracted characters matched "${search}"`}
            </p>
          )}
          <div className="divide-y divide-surface-border">
            {visible.map((c) => {
              const isSelected = selected.has(c.name);
              const initials = c.name.split(" ").map((w) => w[0]).slice(0, 2).join("").toUpperCase();
              return (
                <button
                  key={c.id}
                  onClick={() => toggle(c.name)}
                  className={clsx(
                    "flex w-full items-center gap-3 px-5 py-2.5 text-left transition-colors",
                    isSelected ? "bg-accent/10" : "hover:bg-surface-hover"
                  )}
                >
                  <span className={clsx(
                    "flex h-4 w-4 flex-shrink-0 items-center justify-center rounded border",
                    isSelected ? "border-accent bg-accent" : "border-surface-border"
                  )}>
                    {isSelected && <Check className="h-3 w-3 text-white" />}
                  </span>
                  <span className="h-7 w-7 flex-shrink-0 overflow-hidden rounded-full bg-surface-hover">
                    {c.photo_url ? (
                      <img src={c.photo_url} alt="" className="h-full w-full object-cover" />
                    ) : (
                      <span className="flex h-full w-full items-center justify-center text-[9px] font-semibold text-ink-muted">
                        {initials}
                      </span>
                    )}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-xs font-medium text-ink-primary">{c.name}</span>
                    {c.aliases.length > 0 && (
                      <span className="block truncate text-[10px] text-ink-muted">
                        aka {c.aliases.map((a) => a.alias).join(", ")}
                      </span>
                    )}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Footer */}
        <div className="flex flex-shrink-0 items-center justify-between border-t border-surface-border px-5 py-3">
          <p className="text-[11px] text-ink-muted">{selected.size} selected</p>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="rounded-md border border-surface-border px-3 py-1.5 text-xs text-ink-secondary hover:border-accent hover:text-ink-primary transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={() => onImport([...selected])}
              disabled={selected.size === 0 || importing}
              className="flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-hover transition-colors disabled:cursor-not-allowed disabled:opacity-40"
            >
              {importing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Download className="h-3 w-3" />}
              Import {selected.size > 0 ? selected.size : ""}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}
