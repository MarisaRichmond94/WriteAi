import { useEffect, useState } from "react";
import clsx from "clsx";
import { Eye, FileScan, ScanText, X } from "lucide-react";
import { useApp } from "../../store";
import type { Citation, ReviewFocus } from "../../types";
import { api } from "../../lib/api";
import { ChatInput, ChunkViewer, MessageThread, useStream } from "../chat";
import { ConfirmModal, Spinner } from "../ui";
import { Dropdown, PaneHeader } from "../shared";

const FOCUSES: { value: ReviewFocus; accent: string }[] = [
  { value: "Rough Draft", accent: "border-mode-plot/50 text-mode-plot" },
  { value: "Continuity", accent: "border-mode-timeline/50 text-mode-timeline" },
  { value: "Character Voice", accent: "border-mode-character/50 text-mode-character" },
  { value: "Line Edit", accent: "border-mode-alternate/50 text-mode-alternate" },
  { value: "Pacing", accent: "border-fuchsia-400/50 text-fuchsia-300" },
];

export function ReviewPane() {
  const { books, toast } = useApp();
  const [book, setBook] = useState<string>("");
  const [chapter, setChapter] = useState<string>("");
  const [focus, setFocus] = useState<ReviewFocus>("Rough Draft");
  const [draftText, setDraftText] = useState("");
  const [preview, setPreview] = useState<{ text: string } | null>(null);
  const [showPreview, setShowPreview] = useState(false);
  const [viewChunk, setViewChunk] = useState<string | null>(null);
  const [resync, setResync] = useState<{ estimated_cost_usd: number; changed_chunks: number } | null>(null);
  const [resyncBusy, setResyncBusy] = useState(false);
  const { messages, setMessages, streaming, send } = useStream("/api/review/stream");

  const bookId = book ? Number(book) : null;
  const selectedBook = books.find((b) => b.id === bookId);
  const focusOpt = FOCUSES.find((f) => f.value === focus)!;

  useEffect(() => {
    setPreview(null);
    setShowPreview(false);
    if (bookId != null && chapter && chapter !== "new") {
      api<{ text: string }>(`/api/books/${bookId}/chapters/${chapter}/text`)
        .then(setPreview)
        .catch(() => toast("Could not load chapter text", "error"));
    }
  }, [book, chapter]);

  const runReview = (message: string) => {
    if (bookId == null) return toast("Select a book first", "error");
    const body: Record<string, unknown> = { book: bookId, focus, message };
    if (chapter === "new") {
      if (!draftText.trim()) return toast("Paste your draft chapter first", "error");
      body.chapter_text = draftText;
    } else if (chapter) {
      body.chapter = Number(chapter);
    } else {
      return toast("Select a chapter (or paste a new draft)", "error");
    }
    send(message || `Review this chapter (${focus}).`, body);
  };

  const startResync = async () => {
    if (bookId == null) return toast("Select a book first", "error");
    setResyncBusy(true);
    try {
      setResync(await api(`/api/ingest/preview?book=${bookId}`));
    } catch (e) {
      toast(String(e), "error");
    } finally {
      setResyncBusy(false);
    }
  };

  return (
    <div className="flex h-full">
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <PaneHeader
          icon={FileScan}
          title="Review"
          info="Pick a synced chapter (or paste a fresh draft) and get feedback through a chosen lens, grounded in your series canon with citations."
          subtitle="AI feedback on your writing, grounded in your series canon"
        />

        {/* controls row */}
        <div className="flex flex-shrink-0 flex-wrap items-center gap-2 px-6 pb-3">
          <Dropdown
            label="Select book…"
            value={book}
            onChange={(v) => {
              setBook(v);
              setChapter("");
              setMessages([]);
            }}
            options={[
              { value: "", label: "Select book…" },
              ...books.map((b) => ({ value: String(b.id), label: b.name })),
            ]}
            accentClass={book ? "border-accent/60 text-accent" : undefined}
          />
          <Dropdown
            label="Focus"
            value={focus}
            onChange={(v) => setFocus(v as ReviewFocus)}
            options={FOCUSES.map((f) => ({ value: f.value, label: f.value }))}
            accentClass={focusOpt.accent}
          />
          <Dropdown
            label="Select chapter…"
            value={chapter}
            onChange={(v) => {
              setChapter(v);
              setMessages([]);
            }}
            options={[
              { value: "", label: "Select chapter…" },
              { value: "new", label: "✏️ New draft (paste text)" },
              ...(selectedBook?.chapters ?? []).map((c) => ({
                value: String(c.chapter),
                label: `${c.kind === "prologue" ? "Prologue" : `Chapter ${c.chapter}`}${c.pov ? ` — ${c.pov}` : ""}`,
              })),
            ]}
          />
          {preview && (
            <button
              onClick={() => setShowPreview((v) => !v)}
              className={clsx(
                "flex items-center gap-1 rounded px-2 py-1 text-[11px] transition-colors",
                showPreview ? "text-accent" : "text-ink-secondary hover:text-ink-primary",
              )}
            >
              <Eye className="h-3.5 w-3.5" strokeWidth={1.5} /> Preview
            </button>
          )}
          <span className="flex-1" />
          <button
            onClick={() => runReview("")}
            disabled={streaming || !book || !chapter}
            className="rounded border border-surface-border px-3 py-1 text-[11px] text-ink-secondary transition-colors hover:border-accent hover:text-ink-primary disabled:pointer-events-none disabled:opacity-40"
          >
            Review
          </button>
          <button
            onClick={startResync}
            disabled={resyncBusy}
            className="flex items-center gap-1.5 rounded border border-surface-border px-3 py-1 text-[11px] text-ink-secondary transition-colors hover:border-accent hover:text-ink-primary disabled:opacity-40"
          >
            {resyncBusy && <Spinner className="h-3 w-3" />} Resync
          </button>
        </div>

        {chapter === "new" && (
          <div className="flex-shrink-0 px-6 pb-3">
            <textarea
              value={draftText}
              onChange={(e) => setDraftText(e.target.value)}
              placeholder="Paste your unpublished draft chapter here…"
              rows={6}
              className="w-full resize-y rounded-xl border border-surface-border bg-surface px-4 py-3 text-[13px] text-ink-primary outline-none placeholder:text-ink-muted focus:border-accent"
            />
          </div>
        )}

        {/* content card */}
        <div className="mx-6 mb-4 flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-surface-border">
          <div className="min-h-0 flex-1 overflow-y-auto">
            {messages.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center gap-3 p-10 text-center">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-accent-subtle">
                  <ScanText className="h-5 w-5 text-accent" strokeWidth={1.5} />
                </div>
                <div className="text-sm font-semibold text-ink-primary">
                  {!book || !chapter ? "Select a chapter to begin" : "Ready to review"}
                </div>
                <div className="max-w-xs text-xs leading-relaxed text-ink-secondary">
                  Choose a book, focus, and chapter above, then ask for feedback.
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
            onSend={runReview}
            disabled={streaming}
            placeholder="Select or paste a chapter to review…"
            hintRight="Sonnet 4.6"
          />
        </div>
      </div>

      {showPreview && preview && !viewChunk && (
        <div className="flex h-full w-[40%] shrink-0 flex-col border-l border-surface-border bg-surface-card">
          <div className="flex items-center justify-between border-b border-surface-border px-4 py-3">
            <span className="text-xs font-medium text-ink-primary">
              {selectedBook?.name} — {chapter === "new" ? "Draft" : `Chapter ${chapter}`}
            </span>
            <button onClick={() => setShowPreview(false)} className="rounded-md p-1 text-ink-secondary hover:text-ink-primary">
              <X className="h-4 w-4" strokeWidth={1.5} />
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto whitespace-pre-wrap px-5 py-4 font-serif text-[13px] leading-relaxed">
            {preview.text}
          </div>
        </div>
      )}
      {viewChunk && <ChunkViewer chunkId={viewChunk} onClose={() => setViewChunk(null)} />}

      {resync && (
        <ConfirmModal
          title="Re-ingest this book?"
          body={
            <p>
              {resync.changed_chunks} chunk(s) changed since the last sync. Estimated extraction cost:{" "}
              <span className="font-semibold text-ink-primary">${resync.estimated_cost_usd}</span>. Runs in
              the background; your manuscript files stay read-only.
            </p>
          }
          confirmLabel={`Spend ~$${resync.estimated_cost_usd}`}
          onConfirm={async () => {
            await api(`/api/ingest/run?book=${bookId}`, { method: "POST" }).catch((e) => toast(String(e), "error"));
            toast("Re-ingestion started — see Books for progress", "success");
            setResync(null);
          }}
          onClose={() => setResync(null)}
        />
      )}
    </div>
  );
}
