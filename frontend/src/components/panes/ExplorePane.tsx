import { useState } from "react";
import clsx from "clsx";
import { Compass } from "lucide-react";
import { useApp } from "../../store";
import type { Citation, QueryMode } from "../../types";
import { ChatInput, ChunkViewer, MessageThread, useStream } from "../chat";
import { EmptyState } from "../ui";
import { bookColor, povColor } from "../../lib/palette";

const MODES: { id: QueryMode; label: string; color: string }[] = [
  { id: "general", label: "General", color: "border-surface-border text-ink-secondary" },
  { id: "plot_hole", label: "Plot Holes", color: "border-mode-plot/50 text-mode-plot" },
  { id: "timeline", label: "Timeline", color: "border-mode-timeline/50 text-mode-timeline" },
  { id: "character", label: "Characters", color: "border-mode-character/50 text-mode-character" },
  { id: "alternate", label: "Alternate", color: "border-mode-alternate/50 text-mode-alternate" },
];

const SUGGESTIONS = [
  "What does Noah know about That Night by the end of book 2?",
  "Are there unresolved plot threads in book 1?",
  "How does the relationship between the brothers evolve?",
];

export function ExplorePane() {
  const { books } = useApp();
  const [mode, setMode] = useState<QueryMode>("general");
  const [bookFilter, setBookFilter] = useState<Set<number>>(new Set());
  const [povFilter, setPovFilter] = useState<Set<string>>(new Set());
  const [viewChunk, setViewChunk] = useState<string | null>(null);
  const { messages, streaming, send } = useStream("/api/chat/stream");

  const povs = Array.from(new Set(books.flatMap((b) => b.povs))).sort();

  const ask = (text: string) =>
    send(text, {
      message: text,
      mode,
      book_filter: Array.from(bookFilter),
      pov_filter: Array.from(povFilter),
    });

  const toggle = <T,>(set: Set<T>, v: T, update: (s: Set<T>) => void) => {
    const next = new Set(set);
    next.has(v) ? next.delete(v) : next.add(v);
    update(next);
  };

  return (
    <div className="flex h-full">
      <div className="flex min-w-0 flex-1 flex-col">
        {/* filter bar */}
        <div className="flex flex-wrap items-center gap-2 border-b border-surface-border px-6 py-3">
          {books.map((b) => (
            <button
              key={b.id}
              onClick={() => toggle(bookFilter, b.id, setBookFilter)}
              className={clsx(
                "rounded-full px-2 py-0.5 text-[10px] font-medium transition-opacity",
                bookColor(b.id),
                bookFilter.size && !bookFilter.has(b.id) && "opacity-30",
              )}
            >
              {b.name}
            </button>
          ))}
          <span className="mx-1 h-4 w-px bg-surface-border" />
          {povs.map((p) => {
            const pc = povColor(p);
            return (
              <button
                key={p}
                onClick={() => toggle(povFilter, p, setPovFilter)}
                className={clsx(
                  "rounded-full px-1.5 py-px text-[9px] font-medium ring-1 transition-opacity",
                  pc.text,
                  pc.ring,
                  pc.bg,
                  povFilter.size && !povFilter.has(p) && "opacity-30",
                )}
              >
                {p}
              </button>
            );
          })}
          <span className="flex-1" />
          <div className="flex gap-1.5">
            {MODES.map((m) => (
              <button
                key={m.id}
                onClick={() => setMode(m.id)}
                className={clsx(
                  "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                  m.color,
                  mode === m.id ? "bg-surface-hover" : "opacity-60 hover:opacity-100",
                )}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>

        {/* thread */}
        <div className="min-h-0 flex-1 overflow-y-auto">
          {messages.length === 0 ? (
            <EmptyState
              icon={<Compass className="h-10 w-10" strokeWidth={1} />}
              title="Ask anything about your series"
              hint="Answers are grounded in your manuscripts, with citations you can open."
              action={
                <div className="mt-2 flex flex-col gap-1.5">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      onClick={() => ask(s)}
                      className="rounded-full border border-surface-border px-3 py-1.5 text-xs text-ink-secondary hover:border-accent hover:text-ink-primary"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              }
            />
          ) : (
            <MessageThread
              messages={messages}
              activeCitation={viewChunk}
              onCitation={(c: Citation) => setViewChunk(c.chunk_id)}
            />
          )}
        </div>

        <ChatInput onSend={ask} disabled={streaming} placeholder="Ask about plot, characters, timeline…" />
      </div>
      {viewChunk && <ChunkViewer chunkId={viewChunk} onClose={() => setViewChunk(null)} />}
    </div>
  );
}
