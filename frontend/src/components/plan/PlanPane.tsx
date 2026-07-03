import { useEffect, useState } from "react";
import { Info, Kanban, RefreshCw, Loader2, Plus, Download, MessageSquare } from "lucide-react";
import { clsx } from "clsx";
import { useAppStore } from "../../store/useAppStore";
import { usePlanStore } from "../../store/usePlanStore";
import { fetchOutline, fetchResyncPreview, importWriterCharacters } from "../../api/plan";
import { fetchPipelineStatus } from "../../api/pipeline";
import OutlineView from "./outline/OutlineView";
import CharacterView from "./character/CharacterView";
import ChapterSelectModal from "./outline/ChapterSelectModal";
import ImportCharactersModal from "./character/ImportCharactersModal";

export default function PlanPane() {
  const { books, showToast } = useAppStore();
  const {
    planView, setPlanView,
    selectedBook, setSelectedBook,
    setOutlineForBook,
    outlineByBook,
    setPendingResync,
    setResyncModalOpen,
    syncing, setSyncing,
    setSelectedChapterIds,
    setReviewOpen,
    writerCharacters, setWriterCharacters,
  } = usePlanStore();

  const [addCharacterTrigger, setAddCharacterTrigger] = useState(0);
  const [importOpen, setImportOpen] = useState(false);
  const [importing, setImporting] = useState(false);

  const handleImport = async (names: string[]) => {
    setImporting(true);
    try {
      const imported = await importWriterCharacters(names);
      setWriterCharacters([...writerCharacters, ...imported]);
      setImportOpen(false);
      showToast(`Imported ${imported.length} character${imported.length === 1 ? "" : "s"}.`);
    } catch {
      showToast("Import failed.");
    } finally {
      setImporting(false);
    }
  };
  const [reviewModalOpen, setReviewModalOpen] = useState(false);
  const [pipelineRunning, setPipelineRunning] = useState(false);

  // Read URL params on mount and clear them on unmount (navigate away)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const urlView = params.get("view");
    const urlBook = params.get("book");
    if (urlView === "outline" || urlView === "character") setPlanView(urlView);
    if (urlBook) setSelectedBook(urlBook);
    return () => {
      const p = new URLSearchParams(window.location.search);
      p.delete("view");
      p.delete("book");
      const qs = p.toString();
      history.replaceState(null, "", qs ? `?${qs}` : window.location.pathname);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Sync planView to URL
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    params.set("view", planView);
    history.replaceState(null, "", `?${params}`);
  }, [planView]);

  // Sync selectedBook to URL
  useEffect(() => {
    if (!selectedBook) return;
    const params = new URLSearchParams(window.location.search);
    params.set("book", selectedBook);
    history.replaceState(null, "", `?${params}`);
  }, [selectedBook]);

  const handleResync = async () => {
    if (!selectedBook) return;
    setSyncing(true);
    try {
      const preview = await fetchResyncPreview(selectedBook);
      setPendingResync(preview);
      setResyncModalOpen(true);
    } catch {
      showToast("Failed to fetch sync preview.");
    } finally {
      setSyncing(false);
    }
  };

  // Default to first book
  useEffect(() => {
    if (!selectedBook && books.length > 0) {
      setSelectedBook(books[0].id);
    }
  }, [books, selectedBook, setSelectedBook]);

  // Check whether the extraction pipeline is currently running
  useEffect(() => {
    fetchPipelineStatus()
      .then((s) => setPipelineRunning(s.running))
      .catch(() => {});
  }, []);

  // Load outline whenever selected book changes. On failure, store an empty
  // outline so the view leaves its loading skeleton (undefined = not loaded).
  useEffect(() => {
    if (!selectedBook) return;
    fetchOutline(selectedBook)
      .then((data) => setOutlineForBook(selectedBook, data.chapters))
      .catch(() => setOutlineForBook(selectedBook, []));
  }, [selectedBook, setOutlineForBook]);

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Header */}
      <div className="flex-shrink-0 px-6 pt-4 pb-3">
        <div className="flex items-center gap-2">
          <Kanban className="h-6 w-6 flex-shrink-0 text-accent" />
          <div>
            <div className="flex items-center gap-1">
              <p className="text-xs font-semibold uppercase tracking-widest text-ink-primary">
                Plan
              </p>
              <div className="group relative">
                <Info className="h-3.5 w-3.5 cursor-default text-ink-muted transition-colors hover:text-ink-secondary" />
                <div className="pointer-events-none absolute left-0 top-5 z-50 w-80 rounded-md border border-surface-border bg-surface-card px-3 py-2 text-[11px] leading-relaxed text-ink-muted shadow-lg opacity-0 transition-opacity duration-150 group-hover:opacity-100">
                  Your living planning workspace. The Outline view shows your chapter cards and syncs
                  with your extracted chapter data — letting the AI fill in what actually happened once
                  you write it. The Characters view is where you record your authorial intent for each
                  character, and compare it against what the AI picked up from reading your books.
                  AI feedback is available on both outlines and individual characters.
                </div>
              </div>
            </div>
            <p className="mt-0.5 text-[11px] text-ink-muted">
              Outline your story and design your characters — AI keeps it in sync with what you actually wrote.
            </p>
          </div>
        </div>
        <div className="mt-3 border-t border-surface-border" />
      </div>

      {/* Row 1 — view toggle */}
      <div className="flex-shrink-0 flex items-center gap-4 px-6 pb-2">
        <div className="flex items-center rounded border border-surface-border overflow-hidden flex-shrink-0">
          {(["outline", "character"] as const).map((v) => (
            <button
              key={v}
              onClick={() => setPlanView(v)}
              className={clsx(
                "px-3 py-1 text-[11px] font-medium capitalize transition-colors",
                planView === v
                  ? "bg-accent/20 text-accent"
                  : "bg-surface text-ink-muted hover:bg-surface-hover hover:text-ink-secondary"
              )}
            >
              {v === "outline" ? "Outline" : "Characters"}
            </button>
          ))}
        </div>
      </div>

      {/* Row 2 — book filter pills + review / sync / add button */}
      <div className="flex-shrink-0 flex items-center gap-2 px-6 pb-3 pt-px">
        <div className="flex flex-1 items-center gap-1 overflow-x-auto scrollbar-hide py-0.5 px-0.5">
          {books.map((b) => (
            <button
              key={b.id}
              onClick={() => setSelectedBook(b.id)}
              className={clsx(
                "flex-shrink-0 rounded-full px-3 py-1 text-xs transition-colors",
                selectedBook === b.id
                  ? "bg-accent/20 text-accent ring-1 ring-accent/40"
                  : "text-ink-secondary hover:bg-surface-hover"
              )}
            >
              {b.name}
            </button>
          ))}
        </div>

        {planView === "outline" && (
          <div className="flex items-center flex-shrink-0" style={{ gap: "8px" }}>
            <button
              onClick={() => setReviewModalOpen(true)}
              className="flex items-center gap-1.5 rounded-md border border-surface-border px-3 py-1.5 text-xs text-ink-secondary hover:border-accent hover:text-accent transition-colors"
            >
              <MessageSquare className="h-3 w-3" />
              Review
            </button>
            <div className="relative group/sync">
              <button
                onClick={handleResync}
                disabled={syncing || pipelineRunning}
                className="flex items-center gap-1.5 rounded-md border border-surface-border px-3 py-1.5 text-xs text-ink-secondary hover:border-accent hover:text-accent disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                {syncing
                  ? <Loader2 className="h-3 w-3 animate-spin" />
                  : <RefreshCw className="h-3 w-3" />}
                {syncing ? "Checking..." : "Sync"}
              </button>
              {pipelineRunning && !syncing && (
                <div className="pointer-events-none absolute right-0 top-full mt-1 z-50 w-52 rounded-md border border-surface-border bg-surface-card px-2.5 py-1.5 text-[10px] leading-relaxed text-ink-muted shadow-lg opacity-0 group-hover/sync:opacity-100 transition-opacity">
                  Sync is unavailable while the extraction pipeline is running.
                </div>
              )}
            </div>
          </div>
        )}

        {planView === "character" && (
          <>
            <button
              onClick={() => setImportOpen(true)}
              title="Import AI-extracted characters"
              className="flex flex-shrink-0 items-center gap-1.5 rounded-md border border-surface-border px-3 py-1.5 text-xs text-ink-secondary hover:border-accent hover:text-accent transition-colors"
            >
              <Download className="h-3 w-3" />
              Import
            </button>
            <button
              onClick={() => setAddCharacterTrigger((n) => n + 1)}
              className="flex flex-shrink-0 items-center gap-1.5 rounded-md border border-surface-border px-3 py-1.5 text-xs text-ink-secondary hover:border-accent hover:text-accent transition-colors"
            >
              <Plus className="h-3 w-3" />
              New Character
            </button>
          </>
        )}
      </div>

      {importOpen && (
        <ImportCharactersModal
          existingNames={new Set(writerCharacters.map((c) => c.name))}
          importing={importing}
          onImport={handleImport}
          onClose={() => setImportOpen(false)}
        />
      )}

      {planView === "outline" && <OutlineView bookId={selectedBook} bookName={books.find(b => b.id === selectedBook)?.name ?? ""} />}
      {planView === "character" && <CharacterView addTrigger={addCharacterTrigger} selectedBook={selectedBook} />}

      <ChapterSelectModal
        open={reviewModalOpen}
        chapters={outlineByBook[selectedBook] ?? []}
        onReview={(ids) => {
          setSelectedChapterIds(ids);
          setReviewOpen(true);
          setReviewModalOpen(false);
        }}
        onCancel={() => setReviewModalOpen(false)}
      />
    </div>
  );
}
