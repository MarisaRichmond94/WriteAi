import { useState } from "react";
import { Compass, MessageSquare } from "lucide-react";
import { useApp } from "../../store";
import type { Citation, QueryMode } from "../../types";
import { ChatInput, ChunkViewer, MessageThread, useStream } from "../chat";
import { Dropdown, PaneHeader } from "../shared";

const MODE_OPTIONS: { value: QueryMode; label: string; accent: string }[] = [
  { value: "general", label: "General", accent: "border-surface-border text-ink-secondary" },
  { value: "plot_hole", label: "Plot Holes", accent: "border-mode-plot/50 text-mode-plot" },
  { value: "timeline", label: "Timeline", accent: "border-mode-timeline/50 text-mode-timeline" },
  { value: "character", label: "Character", accent: "border-mode-character/50 text-mode-character" },
  { value: "alternate", label: "Alternate", accent: "border-mode-alternate/50 text-mode-alternate" },
];

const SUGGESTIONS = [
  "“When did Noah first learn about what happened That Night?”",
  "“What would've happened if Emma hadn't found the first note?”",
  "“Are there any timeline contradictions in Split?”",
];

export function ExplorePane() {
  const { books } = useApp();
  const [mode, setMode] = useState<QueryMode>("general");
  const [povFilter, setPovFilter] = useState("all");
  const [bookFilter, setBookFilter] = useState("all");
  const [viewChunk, setViewChunk] = useState<string | null>(null);
  const { messages, streaming, send } = useStream("/api/chat/stream");

  const povs = Array.from(new Set(books.flatMap((b) => b.povs))).sort();
  const modeOpt = MODE_OPTIONS.find((m) => m.value === mode)!;

  const ask = (text: string) =>
    send(text.replace(/^“|”$/g, ""), {
      message: text.replace(/^“|”$/g, ""),
      mode,
      book_filter: bookFilter === "all" ? [] : [Number(bookFilter)],
      pov_filter: povFilter === "all" ? [] : [povFilter],
    });

  return (
    <div className="flex h-full">
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <PaneHeader
          icon={Compass}
          title="Explore"
          info="Semantic search over every chunk of every book, answered by the query model with citations."
          subtitle="Ask AI anything about your series, grounded in extracted knowledge"
        />

        {/* filter row */}
        <div className="flex flex-shrink-0 items-center gap-2 px-6 pb-3">
          <Dropdown
            label="All POVs"
            value={povFilter}
            onChange={setPovFilter}
            options={[{ value: "all", label: "All POVs" }, ...povs.map((p) => ({ value: p, label: p }))]}
          />
          <Dropdown
            label="All Books"
            value={bookFilter}
            onChange={setBookFilter}
            options={[
              { value: "all", label: "All Books" },
              ...books.map((b) => ({ value: String(b.id), label: b.name })),
            ]}
          />
          <Dropdown
            label="Mode"
            value={mode}
            onChange={(v) => setMode(v as QueryMode)}
            options={MODE_OPTIONS.map((m) => ({ value: m.value, label: m.label }))}
            accentClass={modeOpt.accent}
          />
        </div>

        {/* content card */}
        <div className="mx-6 mb-4 flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-surface-border">
          <div className="min-h-0 flex-1 overflow-y-auto">
            {messages.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center gap-3 p-10 text-center">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-accent-subtle">
                  <MessageSquare className="h-5 w-5 text-accent" strokeWidth={1.5} />
                </div>
                <div className="text-sm font-semibold text-ink-primary">Ask anything about your series</div>
                <div className="max-w-xs text-xs leading-relaxed text-ink-secondary">
                  Select a query mode above, then ask about plot continuity, character arcs, timeline events,
                  or explore alternate scenarios.
                </div>
                <div className="mt-1 flex flex-col gap-1.5">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      onClick={() => ask(s)}
                      className="rounded-full border border-surface-border px-3.5 py-1.5 text-[11px] text-ink-secondary transition-colors hover:border-accent hover:text-ink-primary"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <MessageThread
                messages={messages}
                activeCitation={viewChunk}
                onCitation={(c: Citation) => setViewChunk(c.chunk_id)}
              />
            )}
          </div>
          <ChatInput
            onSend={ask}
            disabled={streaming}
            placeholder="Ask AI a question about your book series…"
            hintRight="Sonnet 4.6"
          />
        </div>
      </div>
      {viewChunk && <ChunkViewer chunkId={viewChunk} onClose={() => setViewChunk(null)} />}
    </div>
  );
}
