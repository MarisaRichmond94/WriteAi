import { useState } from "react";
import { MessageSquare, SquarePen, Trash2 } from "lucide-react";
import { clsx } from "clsx";
import { useAppStore } from "../../store/useAppStore";
import type { ChatSession } from "../../types";

function DeleteDialog({
  session,
  onCancel,
  onConfirm,
}: {
  session: ChatSession;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60" onClick={onCancel} />
      {/* Modal */}
      <div className="relative w-80 rounded-xl border border-surface-border bg-surface-card px-6 py-5 shadow-2xl">
        <h3 className="text-sm font-semibold text-ink-primary">Delete Chat</h3>
        <p className="mt-2 text-xs leading-relaxed text-ink-muted">
          This chat will be permanently deleted and cannot be recovered.
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

export default function ChatHistory() {
  const { chatSessions, viewingSessionId, loadChat, deleteChat, saveChatAndClear, setLiveChatSessionId, closeExploreViewer } = useAppStore();
  const [pendingDelete, setPendingDelete] = useState<ChatSession | null>(null);

  if (chatSessions.length === 0) return null;

  const startNewChat = () => {
    saveChatAndClear();
    setLiveChatSessionId(null);
    closeExploreViewer();
  };

  return (
    <>
      <div className="flex flex-col h-64 mb-[100px]">
        <div className="flex-shrink-0 flex items-center justify-between px-4 pt-3 pb-1.5">
          <p className="text-[10px] font-semibold uppercase tracking-widest text-ink-muted">
            Chat History
          </p>
          <button
            onClick={startNewChat}
            title="Start a new chat"
            className="rounded p-0.5 text-ink-muted hover:text-accent hover:bg-surface-hover transition-colors"
          >
            <SquarePen className="h-3.5 w-3.5" />
          </button>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto pb-3">
          {[...chatSessions].reverse().map((session) => {
            const isActive = session.id === viewingSessionId;
            return (
              <div
                key={session.id}
                className={clsx(
                  "group relative flex items-center gap-2 px-3 py-2 cursor-pointer transition-colors",
                  isActive
                    ? "border-l-2 border-accent bg-accent/10"
                    : "border-l-2 border-transparent hover:bg-surface"
                )}
                onClick={() => loadChat(session.id)}
              >
                <MessageSquare
                  className="h-3 w-3 flex-shrink-0 text-ink-muted"
                  strokeWidth={1.5}
                />
                <span
                  className="flex-1 min-w-0 truncate text-xs text-ink-secondary group-hover:pr-5 transition-all"
                  title={session.question}
                >
                  {session.question}
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
            deleteChat(pendingDelete.id);
            setPendingDelete(null);
          }}
        />
      )}
    </>
  );
}
