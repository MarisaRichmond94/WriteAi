import { useState, useRef } from "react";
import { clsx } from "clsx";
import { AlertTriangle, X } from "lucide-react";
import type { ResyncPreviewResponse } from "../../../types";
import DiffChapterRow from "./DiffChapterRow";

interface ResyncModalProps {
  open: boolean;
  preview: ResyncPreviewResponse | null;
  onApprove: (approvedDiffIds: string[]) => void;
  onCancel: () => void;
}

export default function ResyncModal({ open, preview, onApprove, onCancel }: ResyncModalProps) {
  const [approvedIds, setApprovedIds] = useState<Set<string>>(new Set());
  const fieldChangesRef = useRef<HTMLDivElement>(null);
  const lastToggledIndex = useRef<number>(-1);
  const lastToggledAction = useRef<boolean>(true);

  if (!open || !preview) return null;

  const isConflict = preview.status === "conflict";
  const isPartial = preview.status === "partial";
  const matchCount = preview.numbering.length;
  const totalOutline = matchCount + preview.unmatched_outline_count;

  const toggleApproved = (index: number, shiftKey: boolean) => {
    setApprovedIds((prev) => {
      const next = new Set(prev);
      const diffs = preview!.field_diffs;
      const id = diffs[index].chapter_id;

      if (shiftKey && lastToggledIndex.current >= 0) {
        const start = Math.min(lastToggledIndex.current, index);
        const end = Math.max(lastToggledIndex.current, index);
        for (let i = start; i <= end; i++) {
          const rangeId = diffs[i].chapter_id;
          if (lastToggledAction.current) next.add(rangeId);
          else next.delete(rangeId);
        }
        lastToggledIndex.current = index;
      } else {
        const isNowChecked = !next.has(id);
        if (isNowChecked) next.add(id);
        else next.delete(id);
        lastToggledAction.current = isNowChecked;
        lastToggledIndex.current = index;
      }

      return next;
    });
  };

  const approveAll = () => {
    setApprovedIds(new Set(preview.field_diffs.map((d) => d.chapter_id)));
  };

  const handleApply = () => {
    onApprove([...approvedIds]);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="flex flex-col w-full max-w-2xl max-h-[85vh] rounded-xl border border-surface-border bg-surface-card shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-surface-border px-5 py-4 flex-shrink-0">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-ink-primary">
            Sync Outline
          </h2>
          <button
            onClick={onCancel}
            className="rounded p-1 text-ink-muted hover:text-ink-secondary transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-6">
          {/* Conflict state */}
          {isConflict && (
            <div className="flex items-start gap-3 rounded-lg border border-red-500/30 bg-red-500/5 px-4 py-3">
              <AlertTriangle className="h-4 w-4 flex-shrink-0 text-red-400 mt-0.5" />
              <div>
                <p className="text-xs font-medium text-red-400 mb-1">Cannot sync</p>
                <p className="text-[11px] text-ink-muted leading-relaxed">{preview.conflict_reason}</p>
              </div>
            </div>
          )}

          {/* Partial banner */}
          {isPartial && (
            <div className="flex items-start gap-3 rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3">
              <AlertTriangle className="h-4 w-4 flex-shrink-0 text-amber-400 mt-0.5" />
              <p className="text-[11px] text-ink-muted leading-relaxed">
                Your outline has <strong className="text-ink-secondary">{totalOutline}</strong> chapters
                but only <strong className="text-ink-secondary">{matchCount}</strong> have been extracted.
                The first {matchCount} chapters will be synced. The remaining{" "}
                <strong className="text-ink-secondary">{preview.unmatched_outline_count}</strong> planned
                chapter{preview.unmatched_outline_count !== 1 ? "s" : ""} will not be touched.
              </p>
            </div>
          )}

          {/* Section 1: Numbering plan */}
          {!isConflict && preview.numbering.length > 0 && (
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-widest text-ink-muted mb-3">
                Chapter Numbering
              </p>
              <div className="rounded-lg border border-surface-border overflow-hidden">
                <table className="w-full text-[11px] table-fixed">
                  <colgroup>
                    <col className="w-1/2" />
                    <col className="w-1/4" />
                    <col className="w-1/4" />
                  </colgroup>
                  <thead>
                    <tr className="border-b border-surface-border bg-surface">
                      <th className="text-left px-4 py-2 text-ink-muted font-medium">Heading</th>
                      <th className="text-right px-4 py-2 text-ink-muted font-medium">Old #</th>
                      <th className="text-right px-4 py-2 text-ink-muted font-medium">New #</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-surface-border">
                    {preview.numbering.map((n) => (
                      <tr
                        key={n.outline_id}
                        className={clsx(
                          n.is_renumbered ? "bg-amber-500/5" : "",
                          n.old_chapter === null ? "bg-emerald-500/5" : ""
                        )}
                      >
                        <td className="px-4 py-2 text-ink-secondary truncate">
                          {n.outline_heading || "(untitled)"}
                        </td>
                        <td className="px-4 py-2 text-right text-ink-muted">
                          {n.old_chapter !== null ? `Chapter ${n.old_chapter}` : (
                            <span className="text-amber-400 font-medium">Planned</span>
                          )}
                        </td>
                        <td className={clsx(
                          "px-4 py-2 text-right font-medium",
                          n.is_renumbered ? "text-amber-400" : n.old_chapter === null ? "text-emerald-400" : "text-ink-secondary"
                        )}>
                          Chapter {n.new_chapter}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-2 text-[10px] text-ink-muted">
                Numbering is applied in full — individual chapters cannot be excluded.
              </p>
            </div>
          )}

          {/* Section 2: Field diffs */}
          {!isConflict && preview.field_diffs.length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-3">
                <p className="text-[11px] font-semibold uppercase tracking-widest text-ink-muted">
                  Field Changes <span className="text-red-400">*</span>
                </p>
                <button
                  onClick={approveAll}
                  className="text-[11px] text-accent hover:text-accent/80 transition-colors"
                >
                  Approve All Changes
                </button>
              </div>
              <div ref={fieldChangesRef} className="space-y-3">
                {preview.field_diffs.map((d, i) => (
                  <DiffChapterRow
                    key={d.chapter_id}
                    diff={d}
                    approved={approvedIds.has(d.chapter_id)}
                    onToggle={(shiftKey) => toggleApproved(i, shiftKey)}
                  />
                ))}
                <button
                  onClick={() => fieldChangesRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })}
                  className="w-full text-center text-[10px] text-ink-muted/60 hover:text-ink-muted transition-colors pt-1"
                >
                  scroll to top
                </button>
              </div>
            </div>
          )}

          {/* No changes message */}
          {!isConflict && preview.field_diffs.length === 0 && preview.numbering.length === 0 && (
            <p className="text-center text-[11px] text-ink-muted py-4">
              Your outline is already in sync with the extracted data.
            </p>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-surface-border px-5 py-3 flex-shrink-0">
          <button
            onClick={onCancel}
            className="rounded-md px-3 py-1.5 text-xs text-ink-muted hover:text-ink-secondary transition-colors"
          >
            {isConflict ? "Close" : "Cancel"}
          </button>
          {!isConflict && (() => {
            const allApproved = preview.field_diffs.length === 0 || approvedIds.size === preview.field_diffs.length;
            return (
              <div className="relative group/sync-btn">
                <button
                  onClick={handleApply}
                  disabled={!allApproved}
                  className="rounded-md bg-accent px-4 py-1.5 text-xs font-medium text-white hover:bg-accent/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  {isPartial
                    ? `Sync ${matchCount} of ${totalOutline}`
                    : "Sync"}
                </button>
                {!allApproved && (
                  <div className="pointer-events-none absolute bottom-full right-0 mb-1.5 z-50 w-64 rounded-md border border-surface-border bg-surface-card px-2.5 py-1.5 text-[10px] leading-relaxed text-ink-muted shadow-lg opacity-0 group-hover/sync-btn:opacity-100 transition-opacity">
                    You must approve all field changes in order to sync
                  </div>
                )}
              </div>
            );
          })()}
        </div>
      </div>
    </div>
  );
}
