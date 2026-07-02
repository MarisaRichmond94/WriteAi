import { useEffect, useState } from "react";
import clsx from "clsx";
import { Eye, RefreshCw, ScanText, X } from "lucide-react";
import { useApp } from "../../store";
import type { Citation, ReviewFocus } from "../../types";
import { api } from "../../lib/api";
import { ChatInput, ChunkViewer, MessageThread, useStream } from "../chat";
import { Button, ConfirmModal, EmptyState, Spinner } from "../ui";

const FOCUSES: ReviewFocus[] = ["Rough Draft", "Continuity", "Character Voice", "Line Edit", "Pacing"];

export function ReviewPane() {
  const { books, toast } = useApp();
  const [book, setBook] = useState<number | null>(null);
  const [chapter, setChapter] = useState<number | "new" | null>(null);
  const [focus, setFocus] = useState<ReviewFocus>("Rough Draft");
  const [draftText, setDraftText] = useState("");
  const [preview, setPreview] = useState<{ text: string } | null>(null);
  const [showPreview, setShowPreview] = useState(false);
  const [viewChunk, setViewChunk] = useState<string | null>(null);
  const [resync, setResync] = useState<{ estimated_cost_usd: number; changed_chunks: number } | null>(null);
  const [resyncBusy, setResyncBusy] = useState(false);
  const { messages, setMessages, streaming, send } = useStream("/api/review/stream");

  const selectedBook = books.find((b) => b.id === book);

  useEffect(() => {
    setPreview(null);
    setShowPreview(false);
    if (book != null && typeof chapter === "number") {
      api<{ text: string }>(`/api/books/${book}/chapters/${chapter}/text`)
        .then(setPreview)
        .catch(() => toast("Could not load chapter text", "error"));
    }
  }, [book, chapter]);

  const runReview = (message: string) => {
    if (book == null) return toast("Select a book first", "error");
    const body: Record<string, unknown> = { book, focus, message };
    if (chapter === "new") {
      if (!draftText.trim()) return toast("Paste your draft chapter first", "error");
      body.chapter_text = draftText;
    } else if (typeof chapter === "number") {
      body.chapter = chapter;
    } else {
      return toast("Select a chapter (or paste a new draft)", "error");
    }
    send(message || `Review this chapter (${focus}).`, body);
  };

  const startResync = async () => {
    if (book == null) return;
    setResyncBusy(true);
    try {
      const p = await api<{ estimated_cost_usd: number; changed_chunks: number }>(
        `/api/ingest/preview?book=${book}`,
      );
      setResync(p);
    } catch (e) {
      toast(String(e), "error");
    } finally {
      setResyncBusy(false);
    }
  };

  const confirmResync = async () => {
    try {
      await api(`/api/ingest/run?book=${book}`, { method: "POST" });
      toast("Re-ingestion started — see the Books page for progress", "success");
    } catch (e) {
      toast(String(e), "error");
    }
    setResync(null);
  };

  const select = (
    <div className="flex flex-wrap items-center gap-2 border-b border-surface-border px-6 py-3">
      <select
        value={book ?? ""}
        onChange={(e) => {
          setBook(e.target.value ? Number(e.target.value) : null);
          setChapter(null);
          setMessages([]);
        }}
        className="rounded-md border border-surface-border bg-surface px-2.5 py-1.5 text-xs text-ink-primary outline-none focus:border-accent"
      >
        <option value="">Select book…</option>
        {books.map((b) => (
          <option key={b.id} value={b.id}>
            {b.name}
          </option>
        ))}
      </select>
      <select
        value={chapter === null ? "" : chapter}
        onChange={(e) => {
          const v = e.target.value;
          setChapter(v === "" ? null : v === "new" ? "new" : Number(v));
          setMessages([]);
        }}
        disabled={!selectedBook}
        className="rounded-md border border-surface-border bg-surface px-2.5 py-1.5 text-xs text-ink-primary outline-none focus:border-accent disabled:opacity-50"
      >
        <option value="">Select chapter…</option>
        <option value="new">✏️ New draft (paste text)</option>
        {selectedBook?.chapters.map((c) => (
          <option key={c.chapter} value={c.chapter}>
            {c.kind === "prologue" ? "Prologue" : `Chapter ${c.chapter}`}
            {c.pov ? ` — ${c.pov}` : ""}
          </option>
        ))}
      </select>
      <div className="flex gap-1">
        {FOCUSES.map((f) => (
          <button
            key={f}
            onClick={() => setFocus(f)}
            className={clsx(
              "rounded-full border px-2.5 py-1 text-[11px] transition-colors",
              focus === f
                ? "border-accent bg-accent/10 text-accent"
                : "border-surface-border text-ink-secondary hover:text-ink-primary",
            )}
          >
            {f}
          </button>
        ))}
      </div>
      <span className="flex-1" />
      {preview && (
        <button
          onClick={() => setShowPreview((v) => !v)}
          className={clsx(
            "flex items-center gap-1 rounded-md px-2 py-1 text-[11px]",
            showPreview ? "text-accent" : "text-ink-secondary hover:text-ink-primary",
          )}
        >
          <Eye className="h-3.5 w-3.5" strokeWidth={1.5} /> Preview
        </button>
      )}
      <Button variant="secondary" onClick={startResync} disabled={book == null || resyncBusy} className="!px-3 !py-1">
        {resyncBusy ? <Spinner className="h-3.5 w-3.5" /> : <RefreshCw className="h-3.5 w-3.5" strokeWidth={1.5} />}
        Resync
      </Button>
      <Button
        onClick={() => runReview("")}
        disabled={streaming || book == null || chapter == null}
        className="!px-3 !py-1"
      >
        <ScanText className="h-3.5 w-3.5" strokeWidth={1.5} /> Review
      </Button>
    </div>
  );

  return (
    <div className="flex h-full">
      <div className="flex min-w-0 flex-1 flex-col">
        {select}
        {chapter === "new" && (
          <div className="border-b border-surface-border px-6 py-3">
            <textarea
              value={draftText}
              onChange={(e) => setDraftText(e.target.value)}
              placeholder="Paste your unpublished draft chapter here…"
              rows={6}
              className="w-full resize-y rounded-xl border border-surface-border bg-surface px-4 py-3 text-[13px] text-ink-primary outline-none placeholder:text-ink-muted focus:border-accent"
            />
          </div>
        )}
        <div className="min-h-0 flex-1 overflow-y-auto">
          {messages.length === 0 ? (
            <EmptyState
              icon={<ScanText className="h-10 w-10" strokeWidth={1} />}
              title={book == null ? "Select a chapter to begin" : "Ready to review"}
              hint={`Focus lens: ${focus}. The review is grounded in the rest of the series, with citations.`}
            />
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
          placeholder={`Ask a ${focus.toLowerCase()} question about this chapter…`}
        />
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
            <>
              <p>
                {resync.changed_chunks} chunk(s) have changed since the last sync. Estimated extraction
                cost: <span className="font-semibold text-ink-primary">${resync.estimated_cost_usd}</span>.
              </p>
              <p className="mt-2">The run happens in the background; nothing under your writing folder is modified.</p>
            </>
          }
          confirmLabel={`Spend ~$${resync.estimated_cost_usd}`}
          onConfirm={confirmResync}
          onClose={() => setResync(null)}
        />
      )}
    </div>
  );
}
