import { useState, useEffect } from "react";
import { X } from "lucide-react";
import type { OutlineChapter } from "../../../types";

interface ChapterEditModalProps {
  open: boolean;
  chapter: Partial<OutlineChapter> | null;
  onSave: (chapter: Omit<OutlineChapter, "id"> & { id?: string }) => void;
  onCancel: () => void;
}

export default function ChapterEditModal({ open, chapter, onSave, onCancel }: ChapterEditModalProps) {
  const [heading, setHeading] = useState("");
  const [pov, setPov] = useState("");
  const [date, setDate] = useState("");
  const [writerSummary, setWriterSummary] = useState("");
  const [notes, setNotes] = useState("");

  useEffect(() => {
    if (open && chapter) {
      setHeading(chapter.heading ?? "");
      setPov(chapter.pov ?? "");
      setDate(chapter.date ?? "");
      setWriterSummary(chapter.writer_summary ?? "");
      setNotes(chapter.notes ?? "");
    }
  }, [open, chapter]);

  if (!open) return null;

  const isNew = !chapter?.id;

  const handleSave = () => {
    if (!pov.trim()) return;
    onSave({
      ...(chapter?.id ? { id: chapter.id } : {}),
      book: chapter?.book ?? "",
      chapter: chapter?.chapter ?? null,
      position: chapter?.position ?? 1,
      status: chapter?.status ?? "planned",
      heading: heading.trim(),
      pov: pov.trim(),
      date: date.trim() || null,
      writer_summary: writerSummary.trim(),
      extracted_bullets: chapter?.extracted_bullets ?? [],
      notes: notes.trim() || null,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-lg rounded-xl border border-surface-border bg-surface-card shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-surface-border px-5 py-4">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-ink-primary">
            {isNew ? "New Chapter" : "Edit Chapter"}
          </h2>
          <button
            onClick={onCancel}
            className="rounded p-1 text-ink-muted hover:text-ink-secondary transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Form */}
        <div className="px-5 py-4 space-y-4">
          <div>
            <label className="block text-[11px] font-medium text-ink-muted mb-1">
              Working Title / Heading
            </label>
            <input
              type="text"
              value={heading}
              onChange={(e) => setHeading(e.target.value)}
              placeholder="e.g. The Confrontation"
              className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-xs text-ink-primary placeholder-ink-muted/50 focus:border-accent focus:outline-none"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[11px] font-medium text-ink-muted mb-1">
                POV <span className="text-red-400">*</span>
              </label>
              <input
                type="text"
                value={pov}
                onChange={(e) => setPov(e.target.value)}
                placeholder="POV character"
                className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-xs text-ink-primary placeholder-ink-muted/50 focus:border-accent focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-[11px] font-medium text-ink-muted mb-1">
                In-Universe Date
              </label>
              <input
                type="text"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                placeholder="e.g. Saturday, November 1st"
                className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-xs text-ink-primary placeholder-ink-muted/50 focus:border-accent focus:outline-none"
              />
            </div>
          </div>

          <div>
            <label className="block text-[11px] font-medium text-ink-muted mb-1">
              Plan / Summary
            </label>
            <textarea
              value={writerSummary}
              onChange={(e) => setWriterSummary(e.target.value)}
              rows={4}
              placeholder="What do you plan to happen in this chapter? What's the purpose?"
              className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-xs text-ink-primary placeholder-ink-muted/50 focus:border-accent focus:outline-none resize-none leading-relaxed"
            />
          </div>

          <div>
            <label className="block text-[11px] font-medium text-ink-muted mb-1">
              Private Notes
            </label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
              placeholder="Personal scratch notes — never shown in AI reviews"
              className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-xs text-ink-primary placeholder-ink-muted/50 focus:border-accent focus:outline-none resize-none"
            />
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-surface-border px-5 py-3">
          <button
            onClick={onCancel}
            className="rounded-md px-3 py-1.5 text-xs text-ink-muted hover:text-ink-secondary transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={!pov.trim()}
            className="rounded-md bg-accent px-4 py-1.5 text-xs font-medium text-white hover:bg-accent/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {isNew ? "Add Chapter" : "Save Changes"}
          </button>
        </div>
      </div>
    </div>
  );
}
