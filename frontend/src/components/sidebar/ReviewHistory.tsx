import { useState } from "react";
import { ClipboardCheck, Trash2 } from "lucide-react";
import { clsx } from "clsx";
import { useAppStore } from "../../store/useAppStore";
import type { ReviewSession } from "../../types";

function DeleteDialog({
  session,
  onCancel,
  onConfirm,
}: {
  session: ReviewSession;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60" onClick={onCancel} />
      <div className="relative w-80 rounded-xl border border-surface-border bg-surface-card px-6 py-5 shadow-2xl">
        <h3 className="text-sm font-semibold text-ink-primary">Delete Review</h3>
        <p className="mt-2 text-xs leading-relaxed text-ink-muted">
          This review session will be permanently deleted and cannot be recovered.
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <button
            onClick={onCancel}
            className="rounded-md px-3 py-1.5 text-xs text-ink-secondary hover:bg-surface-hover transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="rounded-md bg-red-500/20 px-3 py-1.5 text-xs font-medium text-red-400 ring-1 ring-red-500/40 hover:bg-red-500/30 transition-colors"
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}

export default function ReviewHistory() {
  const { reviewSessions, viewingReviewSessionId, loadReview, deleteReview } = useAppStore();
  const [pendingDelete, setPendingDelete] = useState<ReviewSession | null>(null);

  if (reviewSessions.length === 0) return null;

  return (
    <>
      <div className="flex flex-col h-64 mb-[100px]">
        <p className="flex-shrink-0 px-4 pt-3 pb-1.5 text-[10px] font-semibold uppercase tracking-widest text-ink-muted">
          Review History
        </p>
        <div className="flex-1 min-h-0 overflow-y-auto pb-3">
          {[...reviewSessions].reverse().map((session) => {
            const isActive = session.id === viewingReviewSessionId;
            return (
              <div
                key={session.id}
                className={clsx(
                  "group relative flex items-center gap-2 px-3 py-2 cursor-pointer transition-colors",
                  isActive
                    ? "border-l-2 border-accent bg-accent/10"
                    : "border-l-2 border-transparent hover:bg-surface"
                )}
                onClick={() => loadReview(session.id)}
              >
                <ClipboardCheck
                  className="h-3 w-3 flex-shrink-0 text-ink-muted"
                  strokeWidth={1.5}
                />
                <span
                  className="flex-1 min-w-0 truncate text-xs text-ink-secondary group-hover:pr-5 transition-all"
                  title={session.label}
                >
                  {session.label}
                </span>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setPendingDelete(session);
                  }}
                  className="absolute right-2 opacity-0 group-hover:opacity-100 transition-opacity text-white hover:text-white/70 rounded p-0.5"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            );
          })}
        </div>
      </div>

      {pendingDelete && (
        <DeleteDialog
          session={pendingDelete}
          onCancel={() => setPendingDelete(null)}
          onConfirm={() => {
            deleteReview(pendingDelete.id);
            setPendingDelete(null);
          }}
        />
      )}
    </>
  );
}
