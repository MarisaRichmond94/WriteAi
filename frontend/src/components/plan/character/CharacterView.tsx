import { useState, useEffect, useRef } from "react";
import { Loader2, Users, Search, X, Plus } from "lucide-react";
import { clsx } from "clsx";
import { usePlanStore } from "../../../store/usePlanStore";
import { useAppStore } from "../../../store/useAppStore";
import {
  fetchWriterCharacters,
  replaceAllWriterCharacters,
  upsertWriterCharacter,
  deleteWriterCharacter,
} from "../../../api/plan";
import { fetchCharacters } from "../../../api/characters";
import type { WriterCharacter, CharacterCategory } from "../../../types";
import ConfirmModal from "../../ui/ConfirmModal";

const firstName = (name: string) => name.trim().split(/\s+/)[0].toLowerCase();
const nameParts = (name: string) => name.trim().split(/\s+/).length;

/**
 * One-time seed: only called when the writer has zero characters.
 * Pulls name + avatar from ALL AI-extracted characters (across all books),
 * deduplicates by first name (keeping the most detailed version), and saves
 * each as a new WriterCharacter. Never runs again once characters exist.
 */
async function seedFromExtracted(): Promise<WriterCharacter[]> {
  const extracted = await fetchCharacters(); // no book filter → full series

  // Deduplicate by first name — keep the most detailed name found
  const byFirst = new Map<string, typeof extracted[number]>();
  for (const ec of extracted) {
    const fn = firstName(ec.name);
    const current = byFirst.get(fn);
    if (!current || nameParts(ec.name) > nameParts(current.name)) {
      byFirst.set(fn, ec);
    }
  }

  const toCreate: WriterCharacter[] = [...byFirst.values()].map((ec) => ({
    id: ec.id,
    name: ec.name,
    category: null,
    role: null,
    traits: [],
    arc_notes: null,
    goals: null,
    relationships: [],
    books: ec.books ?? [],
    photo_url: ec.photo_url,
  }));

  // Single atomic write — avoids the race condition from parallel individual upserts
  return replaceAllWriterCharacters(toCreate);
}
import WriterCharacterCard from "./WriterCharacterCard";
import CharacterComparePanel from "./CharacterComparePanel";
import CharacterReviewPanel from "./CharacterReviewPanel";

type PanelMode = "compare" | "review" | null;

interface CharacterViewProps {
  addTrigger?: number;
  selectedBook: string;
}

export default function CharacterView({ addTrigger, selectedBook }: CharacterViewProps) {
  const { showToast, books } = useAppStore();
  const { writerCharacters, setWriterCharacters } = usePlanStore();

  // Resolve selected book ID → name for filtering (WriterCharacter.books stores names)
  const selectedBookName = books.find((b) => b.id === selectedBook)?.name ?? null;

  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [newCharacterId, setNewCharacterId] = useState<string | null>(null);
  const [activeCharacterId, setActiveCharacterId] = useState<string | null>(null);
  const [panelMode, setPanelMode] = useState<PanelMode>(null);

  useEffect(() => {
    setLoading(true);
    fetchWriterCharacters()
      .then((existing) =>
        // Seed from AI only on first ever load (zero writer characters).
        // After that, the writer owns their characters and we never auto-merge again.
        existing.length === 0 ? seedFromExtracted() : existing
      )
      .then(setWriterCharacters)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [setWriterCharacters]); // runs once on mount; writer characters are series-wide

  const handleAddCharacter = async () => {
    const newChar: WriterCharacter = {
      id: `draft-${Date.now()}`,
      name: "",
      category: null,
      role: null,
      aliases: null,
      traits: [],
      arc_notes: null,
      goals: null,
      relationships: [],
      books: selectedBookName ? [selectedBookName] : [],
      photo_url: null,
    };
    try {
      const saved = await upsertWriterCharacter(newChar);
      setWriterCharacters([...writerCharacters, saved]);
      setStableOrderIds((prev) => [...prev, saved.id]);
      setSearch("");
      setNewCharacterId(saved.id);
    } catch {
      showToast("Failed to create character.");
    }
  };

  // Trigger from PlanPane toolbar button
  useEffect(() => {
    if (!addTrigger) return;
    handleAddCharacter();
  }, [addTrigger]); // eslint-disable-line react-hooks/exhaustive-deps

  // Scroll to newly added card and focus its name input
  useEffect(() => {
    if (!newCharacterId) return;
    const raf = requestAnimationFrame(() => {
      const el = document.querySelector(`[data-character-id="${newCharacterId}"]`);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "nearest" });
        el.querySelector<HTMLInputElement>('input[type="text"]')?.focus();
      }
      setNewCharacterId(null);
    });
    return () => cancelAnimationFrame(raf);
  }, [newCharacterId]);

  const activeCharacter = writerCharacters.find((c) => c.id === activeCharacterId) ?? null;
  const panelOpen = panelMode !== null && activeCharacter !== null;

  // Keep the last active character/mode alive during the slide-out so the
  // panel content doesn't vanish before the transition finishes.
  const displayedCharacterRef = useRef(activeCharacter);
  const displayedModeRef = useRef(panelMode);
  if (panelOpen) {
    displayedCharacterRef.current = activeCharacter;
    displayedModeRef.current = panelMode;
  }

  const handleDelete = async (characterId: string) => {
    try {
      await deleteWriterCharacter(characterId);
      setWriterCharacters(writerCharacters.filter((c) => c.id !== characterId));
      setStableOrderIds((prev) => prev.filter((id) => id !== characterId));
      if (activeCharacterId === characterId) {
        setActiveCharacterId(null);
        setPanelMode(null);
      }
    } catch {
      showToast("Failed to delete character.");
    }
  };

  const [focusedCharacterId, setFocusedCharacterId] = useState<string | null>(null);

  // Stable order: only recomputed on initial load or book switch
  const [stableOrderIds, setStableOrderIds] = useState<string[]>([]);
  const prevBookRef = useRef(selectedBook);

  const CATEGORY_ORDER: Record<string, number> = { main: 0, secondary: 1, tertiary: 2 };

  const computeStableOrder = (chars: WriterCharacter[], bookName: string | null) => {
    const forBook = chars.filter(
      (c) => !bookName || c.books.some((b) => b.toLowerCase() === bookName.toLowerCase())
    );
    forBook.sort((a, b) => {
      const aRank = a.category != null ? CATEGORY_ORDER[a.category] : 3;
      const bRank = b.category != null ? CATEGORY_ORDER[b.category] : 3;
      if (aRank !== bRank) return aRank - bRank;
      if (!a.name && b.name) return 1;
      if (a.name && !b.name) return -1;
      return a.name.localeCompare(b.name);
    });
    setStableOrderIds(forBook.map((c) => c.id));
  };

  // Re-sort on initial load
  useEffect(() => {
    if (!loading) computeStableOrder(writerCharacters, selectedBookName);
  }, [loading]); // eslint-disable-line react-hooks/exhaustive-deps

  // Re-sort when the selected book changes
  useEffect(() => {
    if (selectedBook === prevBookRef.current) return;
    prevBookRef.current = selectedBook;
    computeStableOrder(writerCharacters, selectedBookName);
  }, [selectedBook]); // eslint-disable-line react-hooks/exhaustive-deps

  const sortedCharacters = stableOrderIds
    .map((id) => writerCharacters.find((c) => c.id === id))
    .filter((c): c is WriterCharacter => !!c)
    .filter((c) => !search.trim() || c.name.toLowerCase().includes(search.toLowerCase()) || c.id === focusedCharacterId);

  const handleCardFocus = (id: string) => setFocusedCharacterId(id);
  const handleCardBlur = () => setFocusedCharacterId(null);

  const optimisticUpdate = async (updated: WriterCharacter, errorMsg: string) => {
    const snapshot = writerCharacters;
    setWriterCharacters(snapshot.map((c) => (c.id === updated.id ? updated : c)));
    try {
      await upsertWriterCharacter(updated);
    } catch {
      setWriterCharacters(snapshot);
      showToast(errorMsg);
    }
  };

  const handleCategoryChange = (character: WriterCharacter, category: CharacterCategory | null) =>
    optimisticUpdate({ ...character, category }, "Failed to update category.");

  const handleGoalsChange = (character: WriterCharacter, goals: string | null) =>
    optimisticUpdate({ ...character, goals }, "Failed to save goals.");

  const handleArcNotesChange = (character: WriterCharacter, arc_notes: string | null) =>
    optimisticUpdate({ ...character, arc_notes }, "Failed to save arc notes.");

  const handleTraitsChange = (character: WriterCharacter, traits: string[]) =>
    optimisticUpdate({ ...character, traits }, "Failed to update traits.");

  const handleBooksChange = (character: WriterCharacter, books: string[]) =>
    optimisticUpdate({ ...character, books }, "Failed to update books.");

  const handleNameChange = (character: WriterCharacter, name: string) =>
    optimisticUpdate({ ...character, name }, "Failed to update name.");

  const handleRelationshipsChange = (character: WriterCharacter, relationships: WriterCharacter["relationships"]) =>
    optimisticUpdate({ ...character, relationships }, "Failed to update relationships.");

  const handlePhotoChange = (character: WriterCharacter, photo_url: string) =>
    optimisticUpdate({ ...character, photo_url }, "Failed to update photo.");

  const handleAliasesChange = (character: WriterCharacter, aliases: string | null) =>
    optimisticUpdate({ ...character, aliases }, "Failed to save aliases.");

  const openPanel = (characterId: string, mode: PanelMode) => {
    if (activeCharacterId === characterId && panelMode === mode) {
      setActiveCharacterId(null);
      setPanelMode(null);
    } else {
      setActiveCharacterId(characterId);
      setPanelMode(mode);
    }
  };

  return (
    <div className="flex flex-1 overflow-hidden">
      {/* Left column — character grid */}
      <div className={clsx(
        "flex flex-col overflow-hidden transition-all duration-500 ease-in-out",
        panelOpen ? "w-[55%]" : "w-full"
      )}>
        {/* Search */}
        <div className="flex-shrink-0 px-6 pb-3">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-muted" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search characters..."
              disabled={loading}
              className="w-full rounded-md border border-surface-border bg-surface py-1.5 pl-8 pr-8 text-xs text-ink-primary placeholder:text-ink-muted focus:border-accent focus:outline-none transition-colors disabled:cursor-not-allowed disabled:opacity-40"
            />
            {search && (
              <button
                onClick={() => setSearch("")}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-ink-muted hover:text-ink-secondary transition-colors"
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>
        </div>

        {/* Grid */}
        <div className="flex flex-1 flex-col overflow-y-auto px-6 pb-6">
          {loading && (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-5 w-5 animate-spin text-ink-muted" />
            </div>
          )}
          {!loading && writerCharacters.length === 0 && (
            <div className="flex flex-1 flex-col items-center justify-center h-full py-12">
              <div className="flex flex-col items-center gap-3">
                <div className="rounded-full bg-surface-hover p-4">
                  <Users className="h-7 w-7 text-ink-muted/50" />
                </div>
                <div className="flex flex-col items-center gap-1 text-center">
                  <p className="text-sm font-medium text-ink-secondary">No Characters Found</p>
                  <p className="text-[11px] text-ink-muted">Add a new character to get started</p>
                </div>
              </div>
            </div>
          )}
          {!loading && writerCharacters.length > 0 && sortedCharacters.length === 0 && (
            <div className="flex flex-1 items-center justify-center">
              {search.trim() ? (
                <div className="flex flex-col items-center gap-3 text-center">
                  <div className="flex h-12 w-12 items-center justify-center rounded-full bg-surface border border-surface-border">
                    <Users className="h-5 w-5 text-ink-muted" />
                  </div>
                  <div>
                    <p className="text-sm font-medium text-ink-primary">No results found for "{search}"</p>
                    <p className="mt-1 text-[11px] text-ink-muted">Try modifying your search or create a new character</p>
                  </div>
                  <button
                    onClick={handleAddCharacter}
                    className="flex items-center gap-1.5 rounded-md border border-surface-border px-3 py-1.5 text-xs text-ink-secondary hover:border-accent hover:text-accent transition-colors"
                  >
                    <Plus className="h-3 w-3" />
                    New Character
                  </button>
                </div>
              ) : (
                <p className="text-[11px] text-ink-muted">
                  No characters found for {selectedBookName ?? "this book"}
                </p>
              )}
            </div>
          )}
          {!loading && sortedCharacters.length > 0 && (
            <div className={clsx("grid gap-4 items-start transition-all duration-500 ease-in-out", panelOpen ? "grid-cols-2" : "grid-cols-4")}>
              {sortedCharacters.map((c) => (
                <WriterCharacterCard
                  key={c.id}
                  character={c}
                  isFocused={focusedCharacterId === c.id}
                  onCardFocus={() => handleCardFocus(c.id)}
                  onCardBlur={handleCardBlur}
                  onDelete={() => setPendingDeleteId(c.id)}
                  onReview={() => openPanel(c.id, "review")}
                  onCompare={() => openPanel(c.id, "compare")}
                  onCategoryChange={(cat) => handleCategoryChange(c, cat)}
                  onGoalsChange={(goals) => handleGoalsChange(c, goals)}
                  onArcNotesChange={(arcNotes) => handleArcNotesChange(c, arcNotes)}
                  onTraitsChange={(traits) => handleTraitsChange(c, traits)}
                  onBooksChange={(books) => handleBooksChange(c, books)}
                  onNameChange={(name) => handleNameChange(c, name)}
                  onRelationshipsChange={(rels) => handleRelationshipsChange(c, rels)}
                  onPhotoChange={(url) => handlePhotoChange(c, url)}
                  onAliasesChange={(aliases) => handleAliasesChange(c, aliases)}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Panel */}
      <div className={clsx(
        "flex-shrink-0 overflow-hidden rounded-tl-lg transition-all duration-500 ease-in-out",
        panelOpen ? "w-[45%]" : "w-0"
      )}>
        {displayedCharacterRef.current && displayedModeRef.current === "compare" && (
          <CharacterComparePanel
            character={displayedCharacterRef.current}
            onClose={() => { setActiveCharacterId(null); setPanelMode(null); }}
          />
        )}
        {displayedCharacterRef.current && displayedModeRef.current === "review" && (
          <CharacterReviewPanel
            character={displayedCharacterRef.current}
            onClose={() => { setActiveCharacterId(null); setPanelMode(null); }}
          />
        )}
      </div>

      <ConfirmModal
        open={pendingDeleteId !== null}
        title="Delete character?"
        message={(() => {
          const name = writerCharacters.find((c) => c.id === pendingDeleteId)?.name;
          return name
            ? `${name} will be permanently removed from your planning workspace. This cannot be undone.`
            : "This character will be permanently removed. This cannot be undone.";
        })()}
        confirmLabel="Delete"
        cancelLabel="Keep"
        onConfirm={() => { handleDelete(pendingDeleteId!); setPendingDeleteId(null); }}
        onCancel={() => setPendingDeleteId(null)}
      />
    </div>
  );
}
