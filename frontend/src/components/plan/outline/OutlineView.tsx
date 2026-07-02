import { useState } from "react";
import { clsx } from "clsx";
import { Plus, Kanban } from "lucide-react";
import { usePlanStore } from "../../../store/usePlanStore";
import { useAppStore } from "../../../store/useAppStore";
import {
  saveOutline,
  approveResync,
} from "../../../api/plan";
import type { OutlineChapter } from "../../../types";
import ChapterCard from "./ChapterCard";
import ChapterEditModal from "./ChapterEditModal";
import ResyncModal from "./ResyncModal";
import OutlineReviewPanel from "./OutlineReviewPanel";
import ConfirmModal from "../../ui/ConfirmModal";

function ChapterCardSkeleton() {
  return (
    <div className="rounded-lg h-[250px] border border-surface-border bg-surface-card flex flex-col px-4 py-3 gap-2">
      {/* Status badge + X placeholder */}
      <div className="flex items-center justify-between">
        <div className="h-4 w-16 rounded-full bg-surface-border animate-pulse" />
        <div className="h-3.5 w-3.5 rounded bg-surface-border animate-pulse" />
      </div>
      {/* Chapter title + POV pill */}
      <div className="flex items-center gap-2 mt-1">
        <div className="h-4 w-20 rounded bg-surface-border animate-pulse" />
        <div className="h-5 w-16 rounded-full bg-surface-border animate-pulse" />
      </div>
      {/* Date row */}
      <div className="h-3.5 w-32 rounded bg-surface-border animate-pulse" />
      {/* Summary block */}
      <div className="flex flex-col flex-1 gap-1.5 mt-1">
        <div className="h-3 w-full rounded bg-surface-border animate-pulse" />
        <div className="h-3 w-[90%] rounded bg-surface-border animate-pulse" />
        <div className="h-3 w-[75%] rounded bg-surface-border animate-pulse" />
        <div className="h-3 w-[85%] rounded bg-surface-border animate-pulse" />
        <div className="h-3 w-[60%] rounded bg-surface-border animate-pulse" />
      </div>
    </div>
  );
}

function todayAsStoryDate(): string {
  const d = new Date();
  const MONTHS = ["January","February","March","April","May","June","July","August","September","October","November","December"];
  const DAYS = ["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"];
  const n = d.getDate();
  const v = n % 100;
  const ord = (["th","st","nd","rd"] as const)[(v - 20) % 10] ?? (["th","st","nd","rd"] as const)[v] ?? "th";
  return `${DAYS[d.getDay()]}, ${MONTHS[d.getMonth()]} ${n}${ord}, ${d.getFullYear()}`;
}

interface OutlineViewProps {
  bookId: string;
  bookName: string;
}

export default function OutlineView({ bookId, bookName }: OutlineViewProps) {
  const isMock = new URLSearchParams(window.location.search).get("mock") === "true";
  const { showToast } = useAppStore();
  const {
    outlineByBook,
    setOutlineForBook,
    selectedChapterIds,
    clearChapterSelection,
    pendingResync,
    setPendingResync,
    resyncModalOpen,
    setResyncModalOpen,
    reviewOpen,
    setReviewOpen,
    syncing,
    setSyncing,
  } = usePlanStore();

  const chapters = outlineByBook[bookId] ?? [];


  const [editModal, setEditModal] = useState<{
    open: boolean;
    chapter: Partial<OutlineChapter> | null;
  }>({ open: false, chapter: null });
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);

  // Count field diffs per chapter id
  const diffCountById: Record<string, number> = {};
  if (pendingResync) {
    for (const d of pendingResync.field_diffs) {
      diffCountById[d.chapter_id] = d.diffs.length;
    }
  }

  const handleSave = async (partial: Omit<OutlineChapter, "id"> & { id?: string }) => {
    if (isMock) {
      if (partial.id) {
        const updated = chapters.map((c) => (c.id === partial.id ? { ...c, ...partial, id: c.id } : c));
        setOutlineForBook(bookId, updated);
      }
      setEditModal({ open: false, chapter: null });
      return;
    }
    if (!partial.id) return;
    try {
      const updated = chapters.map((c) =>
        c.id === partial.id ? { ...c, ...partial, id: c.id } : c
      );
      const result = await saveOutline(bookId, updated);
      setOutlineForBook(bookId, result.chapters);
    } catch {
      showToast("Failed to save chapter.");
    }
    setEditModal({ open: false, chapter: null });
  };

  // Assign sequential chapter numbers (1, 2, 3…) based on sorted position
  const renumberChapters = (chs: OutlineChapter[]): OutlineChapter[] =>
    [...chs]
      .sort((a, b) => a.position - b.position)
      .map((ch, i) => ({ ...ch, chapter: i + 1 }));

  const handleInsertChapter = async (position: number, date: string) => {
    const newCh: OutlineChapter = {
      id: crypto.randomUUID(),
      book: bookName,
      chapter: null,
      position,
      status: "planned",
      heading: "",
      pov: "",
      date,
      writer_summary: "",
      extracted_bullets: [],
      notes: null,
    };
    const renumbered = renumberChapters([...chapters, newCh]);
    if (isMock) {
      setOutlineForBook(bookId, renumbered);
      return;
    }
    try {
      const result = await saveOutline(bookId, renumbered);
      setOutlineForBook(bookId, result.chapters);
    } catch {
      showToast("Failed to add chapter.");
    }
  };

  const handleDelete = async (chapterId: string) => {
    const remaining = chapters.filter((c) => c.id !== chapterId);
    const renumbered = renumberChapters(remaining);
    if (isMock) {
      setOutlineForBook(bookId, renumbered);
      return;
    }
    try {
      const result = await saveOutline(bookId, renumbered);
      setOutlineForBook(bookId, result.chapters);
    } catch {
      showToast("Failed to delete chapter.");
    }
  };

  const handleAddFirst = () => {
    handleInsertChapter(1, todayAsStoryDate());
  };

  const handleInsert = (prev: OutlineChapter, next: OutlineChapter | undefined) => {
    const position = next
      ? (prev.position + next.position) / 2
      : prev.position + 1;
    handleInsertChapter(position, prev.date || todayAsStoryDate());
  };

  const handleApproveResync = async (approvedDiffIds: string[]) => {
    setResyncModalOpen(false);
    setSyncing(true);
    try {
      const result = await approveResync(bookId, {
        book: bookName,
        approved_diff_ids: approvedDiffIds,
      });
      setOutlineForBook(bookId, result.chapters);
      setPendingResync(null);
      showToast("Outline synced successfully.");
    } catch {
      showToast("Failed to apply sync.");
    } finally {
      setSyncing(false);
    }
  };

  const sorted = [...chapters].sort((a, b) => a.position - b.position);
  const povSuggestions = [...new Set(chapters.map((c) => c.pov).filter(Boolean))] as string[];

  return (
    <div className="flex flex-1 overflow-hidden">
      {/* Left column */}
      <div className={clsx(
        "flex flex-col flex-1 overflow-hidden transition-all duration-300",
        reviewOpen ? "w-[55%]" : "w-full"
      )}>

        {/* Chapter grid */}
        <div className="flex flex-1 flex-col overflow-y-auto px-6 pb-6">
          {syncing ? (
            <div className={`grid gap-3 ${reviewOpen ? "grid-cols-2" : "grid-cols-4"}`}>
              {Array.from({ length: chapters.length || 8 }).map((_, i) => (
                <ChapterCardSkeleton key={i} />
              ))}
            </div>
          ) : (
          <>
          {sorted.length === 0 && (
            <div className="flex flex-1 items-center justify-center">
              <div className="flex flex-col items-center gap-4 text-center">
                <div className="rounded-full bg-surface-hover p-4">
                  <Kanban className="h-7 w-7 text-ink-muted/50" />
                </div>
                <div className="flex flex-col items-center gap-1">
                  <p className="text-sm font-medium text-ink-secondary">No Chapters Outlined</p>
                  <p className="text-[11px] text-ink-muted">Click Add Chapter to get started</p>
                </div>
                <button
                  onClick={handleAddFirst}
                  className="flex items-center gap-1.5 rounded-md border border-surface-border px-3 py-1.5 text-xs text-ink-secondary hover:border-accent hover:text-accent transition-colors"
                >
                  <Plus className="h-3 w-3" />
                  Add Chapter
                </button>
              </div>
            </div>
          )}

          <div className={`grid gap-3 ${reviewOpen ? "grid-cols-2" : "grid-cols-4"}`}>
            {sorted.map((ch, i) => (
              <div key={ch.id} className="relative group/insert">
                <ChapterCard
                  chapter={ch}
                  sortedIndex={i}
                  hasDiff={ch.id in diffCountById}
                  diffCount={diffCountById[ch.id] ?? 0}
                  onDiffClick={() => setResyncModalOpen(true)}
                  onDelete={() => setPendingDeleteId(ch.id)}
                  onSave={handleSave}
                  povSuggestions={povSuggestions}
                  disabled={syncing}
                />
                {i < sorted.length - 1 && !syncing && (
                  <button
                    onClick={() => handleInsert(ch, sorted[i + 1])}
                    className="absolute right-0 top-1/2 -translate-y-1/2 translate-x-1/2 z-20 h-5 w-5 rounded-full bg-accent flex items-center justify-center opacity-0 group-hover/insert:opacity-100 transition-opacity shadow-md hover:bg-accent/80"
                    title="Insert chapter here"
                  >
                    <Plus className="h-3 w-3 text-white" />
                  </button>
                )}
              </div>
            ))}
          </div>
          </>
          )}
        </div>
      </div>

      {/* Review panel */}
      {reviewOpen && (
        <div className="w-[45%] flex-shrink-0 overflow-hidden">
          <OutlineReviewPanel
            book={bookName}
            bookId={bookId}
            selectedChapterIds={[...selectedChapterIds]}
            onClose={() => { setReviewOpen(false); clearChapterSelection(); }}
          />
        </div>
      )}

      {/* Modals */}
      <ChapterEditModal
        open={editModal.open}
        chapter={editModal.chapter}
        onSave={handleSave}
        onCancel={() => setEditModal({ open: false, chapter: null })}
      />

      <ResyncModal
        open={resyncModalOpen}
        preview={pendingResync}
        onApprove={handleApproveResync}
        onCancel={() => setResyncModalOpen(false)}
      />

      <ConfirmModal
        open={pendingDeleteId !== null}
        title="Delete chapter?"
        message={(() => {
          const ch = chapters.find((c) => c.id === pendingDeleteId);
          return ch?.chapter != null
            ? `Chapter ${ch.chapter} will be permanently deleted and all subsequent chapters will be renumbered. This cannot be undone.`
            : "This chapter will be permanently deleted and all subsequent chapters will be renumbered. This cannot be undone.";
        })()}
        confirmLabel="Delete"
        cancelLabel="Keep"
        onConfirm={() => { handleDelete(pendingDeleteId!); setPendingDeleteId(null); }}
        onCancel={() => setPendingDeleteId(null)}
      />
    </div>
  );
}
