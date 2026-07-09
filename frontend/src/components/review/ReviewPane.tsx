import { useEffect, useRef, useState, useCallback, KeyboardEvent } from "react";
import { ChevronDown, ChevronRight, Eye, Info, Loader2, RefreshCw, RotateCcw, Send, ScanText, ClipboardCheck, Settings2, Sparkles, X } from "lucide-react";
import { clsx } from "clsx";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useAppStore } from "../../store/useAppStore";
import type { ChapterSummary, Citation, PipelineCostEstimate, ReviewFocus, ReviewMessage, ReviewSession } from "../../types";
import { streamReview, fetchChapterText, bookNameToId } from "../../api/review";
import { chapterLabel } from "../../lib/format";
import { runPipeline, fetchCostEstimate, fetchIngestStatus, fetchEnrichStatus, runEnrichment } from "../../api/pipeline";
import { fetchBooks, fetchChapterDraft, type ChapterDraft } from "../../api/books";
import { createNotification, logAudit } from "../../api/notifications";
import CitationCard from "../chat/CitationCard";
import StreamingIndicator from "../chat/StreamingIndicator";
import ChapterViewer from "../chat/ChapterViewer";

// ── Constants ─────────────────────────────────────────────────────────────────

const MODELS = [
  { id: "claude-sonnet-4-6", label: "Sonnet 4.6" },
  { id: "claude-opus-4-6", label: "Opus 4.6" },
  { id: "claude-haiku-4-5-20251001", label: "Haiku 4.5" },
];

const FOCUS_OPTIONS: { value: ReviewFocus; description: string }[] = [
  { value: "Literary Agent", description: "Commercial instincts — the hook, the voice, would they request pages" },
  { value: "Casual Reader", description: "Honest gut reactions — hooked, bored, confused, would they keep reading" },
  { value: "Hard-Core Reader", description: "Superfan who knows every book — callbacks, canon slips, theories" },
  { value: "Philosopher", description: "Themes, moral stakes, and what the chapter is really about" },
  { value: "What-If Explorer", description: "The roads not taken — pivotal choices and how alternates would play out" },
];

const SUGGESTIONS = [
  "Would you keep reading past this chapter? Where did you almost stop?",
  "What is the pivotal choice in this chapter, and what if it had gone the other way?",
  "Does anything here contradict what an attentive reader of the series would know?",
];

function uuid(): string {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

// ── Dropdown ──────────────────────────────────────────────────────────────────

function Dropdown<T extends string | number>({
  value,
  options,
  placeholder,
  onChange,
  renderOption,
  renderValue,
  maxHeight,
}: {
  value: T | "";
  options: T[];
  placeholder: string;
  onChange: (v: T) => void;
  renderOption?: (v: T) => React.ReactNode;
  renderValue?: (v: T) => React.ReactNode;
  maxHeight?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  // explicit emptiness check — chapter 0 (the prologue) is a valid value
  const hasValue = value !== "";

  useEffect(() => {
    if (!open) return;
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className={clsx(
          "flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors",
          hasValue
            ? "border-accent bg-accent/10 text-accent"
            : "border-surface-border bg-surface text-ink-secondary hover:border-accent/50 hover:text-ink-primary"
        )}
      >
        <span>{hasValue ? (renderValue ? renderValue(value as T) : value) : placeholder}</span>
        <ChevronDown className={clsx("h-3 w-3 flex-shrink-0 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="absolute left-0 top-full z-50 mt-1 min-w-[200px] rounded-md border border-surface-border bg-surface-card shadow-lg overflow-y-auto" style={maxHeight ? { maxHeight } : undefined}>
          {options.map((opt) => (
            <button
              key={opt}
              onClick={() => { onChange(opt); setOpen(false); }}
              className={clsx(
                "w-full px-3 py-2 text-left text-[11px] transition-colors hover:bg-surface-hover",
                value === opt ? "text-accent" : "text-ink-secondary"
              )}
            >
              {renderOption ? renderOption(opt) : opt}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Resync confirm modal ───────────────────────────────────────────────────────

function ResyncConfirmModal({
  book,
  initialEstimate,
  onConfirm,
  onCancel,
}: {
  book: string;
  // Skips the in-modal estimate fetch when the opener already ran one
  // (the Loom deep-link diffs the book before deciding to show the modal).
  initialEstimate?: PipelineCostEstimate | null;
  onConfirm: (runEnrich: boolean) => void;
  onCancel: () => void;
}) {
  const [runEnrich, setRunEnrich] = useState(false);
  const [estimate, setEstimate] = useState<PipelineCostEstimate | null>(initialEstimate ?? null);
  const [estimating, setEstimating] = useState(false);

  useEffect(() => {
    if (initialEstimate) return;
    setEstimating(true);
    fetchCostEstimate(book)
      .then(setEstimate)
      .catch(() => setEstimate(null))
      .finally(() => setEstimating(false));
  }, [book, initialEstimate]);

  const total = estimate?.total_cost_usd_est ?? null;
  const formatCost = (n: number | null) => {
    if (n === null) return "—";
    if (n < 0.01) return "<$0.01";
    return `$${n.toFixed(2)}`;
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="relative w-full max-w-md rounded-xl border border-surface-border bg-surface-card shadow-2xl">

        {/* Header */}
        <div className="flex items-start justify-between border-b border-surface-border px-5 py-4">
          <div>
            <p className="text-sm font-semibold text-ink-primary">Re-index "{book}"</p>
            <p className="mt-0.5 text-[11px] text-ink-muted">Incremental re-ingest of this book</p>
          </div>
          <button
            onClick={onCancel}
            className="rounded-md p-1 text-ink-muted hover:bg-surface-hover hover:text-ink-primary transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 space-y-4">

          {/* What will happen */}
          <div className="rounded-lg border border-surface-border bg-surface px-4 py-3 space-y-2 text-[11px] text-ink-muted leading-relaxed">
            <p><span className="font-semibold text-ink-secondary">Stage &amp; diff</span><br />Copies the latest manuscript from your Writing folder (read-only) and re-chunks it, comparing content hashes against the index. Unchanged chapters are skipped.</p>
            <p><span className="font-semibold text-ink-secondary">Extract &amp; embed</span><br />Only new or changed chunks are sent to the extraction model for metadata, then re-embedded locally (free). Deleted chunks are removed.</p>
            <p><span className="font-semibold text-ink-secondary">Rebuild</span><br />The canonical character view — including your merges, hides, and renames — rebuilds automatically when the run finishes. No LLM cost.</p>
          </div>

          {/* Optional enrichment */}
          <label className="flex items-start gap-2.5 rounded-lg border border-surface-border bg-surface px-4 py-3 cursor-pointer hover:border-accent/40 transition-colors">
            <input
              type="checkbox"
              checked={runEnrich}
              onChange={(e) => setRunEnrich(e.target.checked)}
              className="mt-0.5 accent-[#7c6af7]"
            />
            <span className="text-[11px] text-ink-muted leading-relaxed">
              <span className="font-semibold text-ink-secondary">Run enrichment afterward</span><br />
              Updates Timeline events and character profiles from the changed chapters. Incremental — only re-processes what changed — with its own small LLM cost.
            </span>
          </label>

          {/* Cost estimate */}
          <div className="flex items-center justify-between rounded-lg border border-surface-border bg-surface px-4 py-3">
            <div>
              <p className="text-[11px] text-ink-muted">Estimated extraction cost</p>
              <p className="mt-0.5 text-[10px] text-ink-muted/70">
                {estimate?.changed_chunks != null
                  ? `${estimate.changed_chunks} changed chunk${estimate.changed_chunks === 1 ? "" : "s"} · ${estimate.model ?? "model from Settings"}`
                  : "model from Settings"}
              </p>
            </div>
            <div className="flex items-center gap-1.5">
              {estimating && <Loader2 className="h-3 w-3 animate-spin text-ink-muted" />}
              <p className={clsx("text-sm font-semibold", estimating ? "text-ink-muted" : "text-ink-primary")}>
                {estimating ? "Calculating…" : formatCost(total)}
              </p>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-surface-border px-5 py-3">
          <button
            onClick={onCancel}
            className="rounded-lg border border-surface-border bg-surface px-4 py-1.5 text-[11px] text-ink-secondary transition-colors hover:border-accent/40 hover:text-ink-primary"
          >
            Cancel
          </button>
          <button
            onClick={() => onConfirm(runEnrich)}
            className="flex items-center gap-1.5 rounded-lg border border-accent/40 bg-accent/10 px-4 py-1.5 text-[11px] font-medium text-accent transition-colors hover:bg-accent/20"
          >
            <RefreshCw className="h-3 w-3" />
            Re-Index
          </button>
        </div>

      </div>
    </div>
  );
}

// ── Message bubble ─────────────────────────────────────────────────────────────

function ReviewBubble({
  message,
  onCitationClick,
  activeCitation,
}: {
  message: ReviewMessage;
  onCitationClick: (c: Citation) => void;
  activeCitation: Citation | null;
}) {
  const isUser = message.role === "user";
  const [sourcesOpen, setSourcesOpen] = useState(false);

  if (isUser) {
    const timestamp = message.timestamp
      ? new Date(message.timestamp).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
      : null;
    return (
      <div className="flex justify-end">
        <div className="max-w-[75%]">
          <div className="rounded-2xl rounded-tr-sm bg-accent-subtle px-4 py-2.5">
            <p className="text-sm leading-relaxed text-ink-primary whitespace-pre-wrap">
              {message.content}
            </p>
          </div>
          {timestamp && <p className="mt-1 pl-4 text-[10px] text-ink-muted">{timestamp}</p>}
        </div>
      </div>
    );
  }

  function citationKey(c: Citation) {
    return `${c.book}__${c.chapter}__${c.chunk_index}`;
  }

  return (
    // Mirrors the Explore page's assistant bubble: the pane's message list
    // is the scroll container, so the response grows to the full remaining
    // height instead of scrolling inside a capped box.
    <div className="flex justify-start">
      <div className="flex w-[90%] flex-col gap-4">
        <div className="relative">
          <div className="rounded-2xl rounded-tl-sm bg-surface-card px-4 py-3 border border-surface-border">
            {message.isStreaming && !message.content ? (
              <StreamingIndicator />
            ) : (
              <div className="prose-dark text-sm">
                {/* Tracked-changes markup from the review prompt's Ideal
                    Version: the model reserves bold for additions and uses
                    strikethrough for deletions, so style them as a diff. */}
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    strong: ({ node: _node, ...props }) => (
                      <strong className="font-semibold text-emerald-400" {...props} />
                    ),
                    del: ({ node: _node, ...props }) => (
                      <del className="text-red-400/90 [text-decoration-color:rgba(248,113,113,0.8)]" {...props} />
                    ),
                  }}
                >
                  {message.content}
                </ReactMarkdown>
              </div>
            )}
          </div>
          {message.isStreaming && message.content && (
            <div className="absolute bottom-2 right-2 rounded-full bg-surface-card p-0.5">
              <Loader2 className="h-3.5 w-3.5 animate-spin text-accent/70" />
            </div>
          )}
        </div>
        {!message.isStreaming && message.citations && message.citations.length > 0 && (
          <div className="flex flex-col">
            <div className="flex-shrink-0 flex items-center justify-between px-1 mb-1.5">
              <button
                onClick={() => setSourcesOpen((o) => !o)}
                className="flex items-center gap-1 text-[10px] font-bold uppercase tracking-widest text-ink-primary hover:text-accent transition-colors"
              >
                {sourcesOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                Sources ({message.citations.length})
              </button>
              {sourcesOpen && (
                <p className="text-[10px] text-ink-muted">Click a row to view the sourced text in context</p>
              )}
            </div>
            {sourcesOpen && (
            <div className="flex-1 min-h-0 overflow-y-auto space-y-1.5">
              {[...message.citations]
                .sort((a, b) => a.distance - b.distance)
                .map((citation, i) => (
                  <CitationCard
                    key={i}
                    citation={citation}
                    index={i + 1}
                    isSelected={!!activeCitation && citationKey(activeCitation) === citationKey(citation)}
                    onClick={() => onCitationClick(citation)}
                  />
                ))}
            </div>
            )}
            {message.timestamp && (
              <p className="flex-shrink-0 mt-1.5 pl-1 text-[10px] text-ink-muted">
                {new Date(message.timestamp).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main pane ─────────────────────────────────────────────────────────────────

export default function ReviewPane() {
  const { books, appSettings, reviewSessions, viewingReviewSessionId, upsertReview, setViewingReviewSessionId, clearReviewSignal, refreshBell, setBooks } = useAppStore();

  // Persisted filters
  const [filterBook, setFilterBook] = useState<string>(
    () => localStorage.getItem("review_filter_book") ?? ""
  );
  const [filterFocus, setFilterFocus] = useState<ReviewFocus>(() => {
    const stored = localStorage.getItem("review_filter_focus") as ReviewFocus | null;
    // discard pre-persona values ("Rough Draft", "Line Edit", …)
    return stored && FOCUS_OPTIONS.some((f) => f.value === stored) ? stored : "Casual Reader";
  });

  useEffect(() => { localStorage.setItem("review_filter_book", filterBook); }, [filterBook]);
  useEffect(() => { localStorage.setItem("review_filter_focus", filterFocus); }, [filterFocus]);

  // Chapter state
  const [chapters, setChapters] = useState<ChapterSummary[]>([]);
  const [selectedChapter, setSelectedChapter] = useState<number | "new" | null>(null);
  const [chapterText, setChapterText] = useState("");
  const [chapterFetching, setChapterFetching] = useState(false);

  // Draft mode: chapter text read straight from the manuscript file (no
  // ingest, no LLM cost) so the writer can iterate review→revise→re-review
  // and only reindex once the revision lands.
  const [draft, setDraft] = useState<ChapterDraft | null>(null);
  const [draftLoading, setDraftLoading] = useState(false);

  // Cost controls: the Ideal Version rewrite is the dominant output cost, so
  // it defaults ON for the first review of a conversation and auto-switches
  // OFF (with a drop to the cheapest model) for follow-up iterations.
  const [includeIdeal, setIncludeIdeal] = useState(true);
  const autoTunedRef = useRef(false);
  // one resync nudge per book when the canon-dependent persona is picked
  const hardcoreNudgedRef = useRef<Set<string>>(new Set());

  // Resync state
  const [resyncing, setResyncing] = useState(false);
  const [resyncModalOpen, setResyncModalOpen] = useState(false);
  // Estimate pre-fetched by the deep-link sync check, handed to the modal
  // so it doesn't stage-and-diff the book a second time.
  const [resyncEstimate, setResyncEstimate] = useState<PipelineCostEstimate | null>(null);
  // Bumped when a resync lands so open chapter viewers refetch their text.
  const [syncVersion, setSyncVersion] = useState(0);


  // Conversation state
  const [messages, setMessages] = useState<ReviewMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [inputValue, setInputValue] = useState("");

  // Citation viewer
  const [activeCitation, setActiveCitation] = useState<Citation | null>(null);
  const [lightMode, setLightMode] = useState(() => useAppStore.getState().appSettings?.viewer_light_mode ?? true);

  // Chapter preview
  const [previewOpen, setPreviewOpen] = useState(false);

  // Model selector
  const defaultModel = appSettings?.query_model ?? "claude-sonnet-4-6";
  const [model, setModel] = useState<string>(defaultModel);
  const [modelDropdownOpen, setModelDropdownOpen] = useState(false);
  const modelDropdownRef = useRef<HTMLDivElement>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const settingsRef = useRef<HTMLDivElement>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesScrollRef = useRef<HTMLDivElement>(null);
  // Follow the stream only while the reader is at the bottom — scrolling up
  // mid-stream stops the auto-scroll; returning to the bottom resumes it.
  const stickToBottomRef = useRef(true);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const activeSessionIdRef = useRef<string | null>(null);
  const messagesRef = useRef<ReviewMessage[]>(messages);
  messagesRef.current = messages;
  const prevStreamingRef = useRef(false);

  const bookOptions = books.map((b) => b.name);
  const selectedBookObj = books.find((b) => b.name === filterBook) ?? null;

  // A fresh conversation gets the Ideal Version again; the auto-downshift to
  // the cheap model is undone only if it was ours (a manual pick sticks).
  const resetCostControls = () => {
    setIncludeIdeal(true);
    if (autoTunedRef.current) setModel(defaultModel);
    autoTunedRef.current = false;
  };

  // Load chapters when book changes
  useEffect(() => {
    if (!selectedBookObj) {
      setChapters([]);
      setSelectedChapter(null);
      setChapterText("");
      return;
    }
    setChapters(selectedBookObj.chapters);
  }, [selectedBookObj]);

  // Fetch chapter text when a synced chapter is selected. Draft mode owns
  // the text instead — the index copy would stomp the fresh manuscript read.
  useEffect(() => {
    if (draft || draftLoading) return;   // a manuscript read owns (or is about to own) the text
    if (selectedChapter === "new") return;  // the paste box owns the text (cleared on manual switch)
    if (selectedChapter === null || !selectedBookObj) {
      setChapterText("");
      return;
    }
    setChapterFetching(true);
    setChapterText("");
    fetchChapterText(selectedBookObj.id, selectedChapter)
      .then(setChapterText)
      .catch(() => setChapterText(""))
      .finally(() => setChapterFetching(false));
  }, [selectedChapter, selectedBookObj, syncVersion, draft, draftLoading]);

  // Read the chapter's current text from the manuscript file on disk.
  // Content-hash cached server-side: only the first read after a fresh
  // Loom export pays the Pages round-trip.
  const loadDraft = async (bookId: string, chapterNum: number): Promise<ChapterDraft | null> => {
    setDraftLoading(true);
    try {
      const d = await fetchChapterDraft(bookId, chapterNum);
      setDraft(d);
      setChapterText(d.text);
      return d;
    } catch (e) {
      await createNotification({
        type: "error",
        title: "Couldn't read the draft",
        body: `Falling back to the indexed text. ${e instanceof Error ? e.message : ""}`,
      });
      refreshBell();
      return null;
    } finally {
      setDraftLoading(false);
    }
  };

  // Deep link from Loom's Review button:
  //   ?pane=review&book=<title>&chapter=<n>&focus=<persona>&preview=1&draft=1
  // Applied once the book list is loaded, then stripped from the URL so a
  // refresh doesn't re-trigger it. `draft=1` means "Loom just exported the
  // manuscript" — read the chapter text straight from the file (no ingest,
  // no LLM cost) and let the writer reindex when the revision lands.
  const deepLinkAppliedRef = useRef(false);
  useEffect(() => {
    if (deepLinkAppliedRef.current || books.length === 0) return;
    const params = new URLSearchParams(window.location.search);
    const bookParam = params.get("book");
    if (!bookParam) return;
    deepLinkAppliedRef.current = true;

    const looseKey = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, "");
    const match = books.find((b) => looseKey(b.name) === looseKey(bookParam));
    if (match) {
      setFilterBook(match.name);
      setViewingReviewSessionId(null);
      activeSessionIdRef.current = null;
      const chapterRaw = params.get("chapter");
      const chapterNum = chapterRaw && /^\d+$/.test(chapterRaw) ? Number(chapterRaw) : null;
      if (chapterNum !== null) setSelectedChapter(chapterNum);
      const focus = params.get("focus") as ReviewFocus | null;
      if (focus && FOCUS_OPTIONS.some((f) => f.value === focus)) setFilterFocus(focus);
      // preview is deliberately NOT auto-opened — it's a modal now, opened
      // from the eye button on demand (the param is still stripped below)
      if (params.get("draft") === "1" && chapterNum !== null) {
        loadDraft(String(match.id), chapterNum);
      }
    } else {
      createNotification({
        type: "error",
        title: "Book not found",
        body: `No synced book matches "${bookParam}".`,
      }).then(refreshBell);
    }

    for (const k of ["book", "chapter", "focus", "preview", "draft", "sync"]) params.delete(k);
    const qs = params.toString();
    history.replaceState(null, "", qs ? `?${qs}` : window.location.pathname);
  }, [books]); // eslint-disable-line react-hooks/exhaustive-deps

  // The Hard-Core Reader persona's canon-checking leans on the index for
  // EARLIER chapters, so when it's picked while the manuscript has unsynced
  // changes, offer the (cost-gated) resync once per book.
  useEffect(() => {
    if (filterFocus !== "Hard-Core Reader" || !filterBook) return;
    if (hardcoreNudgedRef.current.has(filterBook)) return;
    hardcoreNudgedRef.current.add(filterBook);
    fetchCostEstimate(filterBook)
      .then((est) => {
        if ((est.changed_chunks ?? 0) > 0) {
          logAudit("hardcore_resync_nudge",
            `offered resync of "${filterBook}" for Hard-Core Reader`,
            { changed_chunks: est.changed_chunks });
          setResyncEstimate(est);
          setResyncModalOpen(true);
        }
      })
      .catch(() => {});
  }, [filterFocus, filterBook]); // eslint-disable-line react-hooks/exhaustive-deps

  // Clear session tracking when navigating away
  useEffect(() => {
    return () => {
      setViewingReviewSessionId(null);
    };
  }, []);

  // Clear view when the active review session is deleted from history
  useEffect(() => {
    if (!clearReviewSignal) return;
    setMessages([]);
    setPreviewOpen(false);
    setActiveCitation(null);
    activeSessionIdRef.current = null;
  }, [clearReviewSignal]); // eslint-disable-line react-hooks/exhaustive-deps

  // Restore state when a review session is loaded from history
  useEffect(() => {
    if (!viewingReviewSessionId) return;
    const session = reviewSessions.find((s) => s.id === viewingReviewSessionId);
    if (!session) return;
    activeSessionIdRef.current = viewingReviewSessionId;
    setFilterBook(session.book);
    setFilterFocus(session.focus);
    setSelectedChapter(session.chapter);
    setMessages(session.messages);
    setPreviewOpen(false);
    setActiveCitation(null);
    setDraft(null);
    // Re-acquire the reviewed text so follow-ups work after a refresh:
    // pasted chapters restore their saved text; draft reviews re-read the
    // manuscript file (fresh — "re-pulls the latest version"); synced
    // chapters are handled by the index-fetch effect.
    if (session.chapter === "new") {
      setChapterText(session.chapterText ?? "");
    } else if (session.draft) {
      const b = books.find((x) => x.name === session.book);
      if (b) loadDraft(String(b.id), session.chapter);
    }
    resetCostControls();
  }, [viewingReviewSessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-save session whenever streaming completes
  useEffect(() => {
    const was = prevStreamingRef.current;
    prevStreamingRef.current = isStreaming;
    if (!was || isStreaming) return;
    const msgs = messagesRef.current;
    if (msgs.length === 0) return;
    // After the FIRST review of a conversation, downshift for the iteration
    // rounds: skip the Ideal Version rewrite and drop to the cheapest model.
    // One-time and fully manual afterwards — the toggle and model selector
    // stay in the writer's hands.
    if (!autoTunedRef.current && msgs.filter((m) => m.role === "assistant").length === 1) {
      autoTunedRef.current = true;
      setIncludeIdeal(false);
      setModel("claude-haiku-4-5-20251001");
    }
    if (!activeSessionIdRef.current) activeSessionIdRef.current = uuid();
    const sessionId = activeSessionIdRef.current;
    const chapterPart = typeof selectedChapter === "number"
      ? ` (Chapter ${selectedChapter})`
      : selectedChapter === "new" ? " (New Chapter)" : "";
    const label = filterBook ? `${filterBook}${chapterPart} - ${filterFocus}` : filterFocus;
    const session: ReviewSession = {
      id: sessionId,
      label,
      book: filterBook,
      chapter: selectedChapter ?? "new",
      focus: filterFocus,
      messages: msgs.map((m) => ({ ...m, isStreaming: false })),
      timestamp: new Date(),
      draft: !!draft,
      ...(selectedChapter === "new" && chapterText ? { chapterText } : {}),
    };
    upsertReview(session);
  }, [isStreaming]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-scroll to bottom (only while the reader hasn't scrolled away)
  useEffect(() => {
    if (stickToBottomRef.current) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  const handleMessagesScroll = () => {
    const el = messagesScrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    stickToBottomRef.current = atBottom;
    setIsAtBottom(atBottom);
  };

  // Close model dropdown on outside click
  useEffect(() => {
    if (!modelDropdownOpen) return;
    function handler(e: MouseEvent) {
      if (modelDropdownRef.current && !modelDropdownRef.current.contains(e.target as Node)) {
        setModelDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [modelDropdownOpen]);

  // Close settings popover on outside click
  useEffect(() => {
    if (!settingsOpen) return;
    function handler(e: MouseEvent) {
      if (settingsRef.current && !settingsRef.current.contains(e.target as Node)) {
        setSettingsOpen(false);
      }
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [settingsOpen]);

  // Reviewing mid-resync would submit stale text — wait for the index.
  const canSend = !!chapterText.trim() && !!filterBook && !isStreaming && !resyncing;

  // textOverride carries a just-loaded updated draft — state hasn't
  // re-rendered yet when the send fires (same for modelOverride, which the
  // updated-draft flow sets alongside a setModel call). previousText rides
  // to the backend so a re-review diffs the drafts instead of asking the
  // model to reconstruct what changed.
  const sendMessage = useCallback(async (
    text: string,
    opts?: { textOverride?: string; previousText?: string; modelOverride?: string },
  ) => {
    const reviewText = opts?.textOverride ?? chapterText;
    if (!reviewText.trim() || !filterBook || isStreaming || resyncing || !text.trim()) return;

    const userMsg: ReviewMessage = {
      id: uuid(),
      role: "user",
      content: text,
      focus: filterFocus,
      timestamp: new Date(),
    };
    const assistantId = uuid();
    const assistantMsg: ReviewMessage = {
      id: assistantId,
      role: "assistant",
      content: "",
      focus: filterFocus,
      citations: [],
      timestamp: new Date(),
      isStreaming: true,
    };

    const newMessages = [...messages, userMsg, assistantMsg];
    setMessages(newMessages);
    messagesRef.current = newMessages;
    setInputValue("");
    setIsStreaming(true);
    stickToBottomRef.current = true; // a fresh send always jumps to the reply
    setIsAtBottom(true);
    if (textareaRef.current) textareaRef.current.style.height = "auto";

    // Immediately create/update the history entry so it appears in the sidebar right away
    if (!activeSessionIdRef.current) activeSessionIdRef.current = uuid();
    const chapterPart = typeof selectedChapter === "number"
      ? ` (Chapter ${selectedChapter})`
      : selectedChapter === "new" ? " (New Chapter)" : "";
    const sessionLabel = filterBook ? `${filterBook}${chapterPart} - ${filterFocus}` : filterFocus;
    upsertReview({
      id: activeSessionIdRef.current,
      label: sessionLabel,
      book: filterBook,
      chapter: selectedChapter ?? "new",
      focus: filterFocus,
      messages: newMessages.map((m) => ({ ...m, isStreaming: false })),
      timestamp: new Date(),
      draft: !!draft,
      ...(selectedChapter === "new" && reviewText ? { chapterText: reviewText } : {}),
    });

    const history = messages.slice(-6).map((m) => ({ role: m.role, content: m.content }));

    try {
      const gen = streamReview({
        chapter_text: reviewText,
        previous_text: opts?.previousText,
        chapter: typeof selectedChapter === "number" ? selectedChapter : undefined,
        book: filterBook,
        focus: filterFocus,
        message: text,
        conversation_history: history,
        model: opts?.modelOverride ?? model,
        include_ideal: includeIdeal,
      });

      for await (const event of gen) {
        if (event.type === "chunk") {
          setMessages((prev) =>
            prev.map((m) => m.id === assistantId ? { ...m, content: m.content + event.content } : m)
          );
        } else if (event.type === "citations") {
          setMessages((prev) =>
            prev.map((m) => m.id === assistantId ? { ...m, citations: event.sources } : m)
          );
        } else if (event.type === "done" || event.type === "error") {
          setMessages((prev) =>
            prev.map((m) => m.id === assistantId ? { ...m, isStreaming: false } : m)
          );
          setIsStreaming(false);
        }
      }
    } catch {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? { ...m, content: "Something went wrong. Please try again.", isStreaming: false }
            : m
        )
      );
      setIsStreaming(false);
    }
  }, [chapterText, filterBook, filterFocus, includeIdeal, isStreaming, messages, model, resyncing, selectedChapter, upsertReview]);

  const handleReviewClick = () => {
    sendMessage(`Please give me a ${filterFocus} review of this chapter.`);
  };

  // Draft-mode iteration: Loom re-exported the manuscript, so re-read it and
  // send the fresh text into the SAME conversation — the reviewer reacts to
  // what changed instead of starting over.
  const handleSendUpdatedDraft = async () => {
    if (!selectedBookObj || typeof selectedChapter !== "number" || isStreaming) return;
    const prevText = chapterText;
    const d = await loadDraft(selectedBookObj.id, selectedChapter);
    if (!d) return;
    if (d.text === prevText) {
      await createNotification({
        type: "sync_complete",
        title: "No changes found",
        body: "The manuscript on disk matches the draft already under review — save and export from Loom first.",
        book: filterBook,
      });
      refreshBell();
      return;
    }
    // Diffing drafts is the hardest turn of the conversation — undo the
    // automatic cheap-model downshift for it (visibly, via the dropdown).
    // A model the writer picked by hand sticks.
    const reviewModel = autoTunedRef.current ? defaultModel : model;
    if (autoTunedRef.current) setModel(defaultModel);
    sendMessage(
      "I've revised the chapter — here is my updated draft. Assess the changes against your earlier feedback: what improved, and what still needs work?",
      { textOverride: d.text, previousText: prevText, modelOverride: reviewModel },
    );
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(inputValue);
    }
  };

  const handleInput = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  };

  // Poll a background enrichment to completion, then refresh the book data,
  // open chapter viewers, and the bell (enrichment posts its own completion
  // notification). Reviewing is NOT blocked while it runs — enrichment
  // updates Timeline/profile data, not chapter text.
  const watchEnrichment = async () => {
    const started = Date.now();
    while (Date.now() - started < 30 * 60_000) {
      await new Promise((r) => setTimeout(r, 5000));
      const st = await fetchEnrichStatus();
      if (st.running) continue;
      fetchBooks().then(setBooks).catch(() => {});
      setSyncVersion((v) => v + 1);
      refreshBell();
      break;
    }
  };

  // Start enrichment for a just-finished sync. An earlier enrichment may
  // still be running (both progress bars show in the sidebar during the
  // overlap) — starting now would 409, so wait it out and run afterward:
  // the in-flight run predates this sync's chunks, so a fresh pass is
  // needed either way.
  const queueEnrichment = async () => {
    if ((await fetchEnrichStatus()).running) {
      logAudit("enrich_queued", "Enrichment already running — waiting to re-run for the latest sync");
      await watchEnrichment();
    }
    await runEnrichment();
    await watchEnrichment();
  };

  // Poll a running ingest to completion. Success/failure notifications come
  // from the ingest process itself (it posts to the bell); this side only
  // tracks the syncing state, refreshes stale data, and nudges the bell.
  const watchIngest = async (runEnrich: boolean) => {
    setResyncing(true);
    try {
      const started = Date.now();
      while (Date.now() - started < 15 * 60_000) {
        await new Promise((r) => setTimeout(r, 3000));
        const st = await fetchIngestStatus();
        if (st.running) continue;
        if (st.finished && st.exit_code === 0) {
          fetchBooks().then(setBooks).catch(() => {});
          setSyncVersion((v) => v + 1);
          setDraft(null); // index now matches the file — leave draft mode
          if (runEnrich) {
            // not awaited — reviewing can resume as soon as the sync lands
            queueEnrichment().catch(async (e: Error) => {
              await createNotification({
                type: "error",
                title: "Enrichment failed to start",
                body: `The resync finished, but enrichment could not be started. ${e.message}`,
              });
              refreshBell();
            });
          }
        }
        break;
      }
    } finally {
      setResyncing(false);
      refreshBell();
    }
  };

  // Adopt an ingest that is already running (started from another pane or a
  // previous visit) so the Review button and preview reflect it.
  useEffect(() => {
    fetchIngestStatus()
      .then((st) => { if (st.running) watchIngest(false); })
      .catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleResyncConfirm = async (runEnrich: boolean) => {
    setResyncModalOpen(false);
    setResyncEstimate(null);
    if (!filterBook) return;
    try {
      await runPipeline({ book: filterBook });
    } catch (e) {
      await createNotification({
        type: "error",
        title: "Resync failed to start",
        body: `Could not start the re-ingest of "${filterBook}". ${e instanceof Error ? e.message : ""}`,
        book: filterBook,
      });
      refreshBell();
      return;
    }
    await watchIngest(runEnrich);
  };

  const chapterDropdownOptions: (number | "new")[] = [
    "new",
    ...chapters.map((c) => c.chapter as number),
  ];

  const selectedModel = MODELS.find((m) => m.id === model)?.label ?? model;

  const sideOpen = activeCitation !== null;
  const canPreview = selectedChapter !== null && selectedChapter !== "new" && !!chapterText && !chapterFetching;

  return (
    <div className="flex flex-1 flex-col overflow-hidden">

      {resyncModalOpen && filterBook && (
        <ResyncConfirmModal
          book={filterBook}
          initialEstimate={resyncEstimate}
          onConfirm={handleResyncConfirm}
          onCancel={() => { setResyncModalOpen(false); setResyncEstimate(null); }}
        />
      )}

      {/* Title block */}
      <div className="flex-shrink-0 px-6 pt-4 pb-3">
        <div className="flex items-center gap-2">
          <ScanText className="h-6 w-6 flex-shrink-0 text-accent" />
          <div>
            <div className="flex items-center gap-2">
              <p className="text-xs font-semibold uppercase tracking-widest text-ink-primary">Review</p>
              <div className="group relative">
                <Info className="h-3.5 w-3.5 cursor-default text-ink-muted transition-colors hover:text-ink-secondary" />
                <div className="pointer-events-none absolute left-0 top-5 z-50 w-72 rounded-md border border-surface-border bg-surface-card px-3 py-2 text-[11px] leading-relaxed text-ink-muted shadow-lg opacity-0 transition-opacity duration-150 group-hover:opacity-100">
                  Get AI feedback on a chapter you're writing. Select the book for context, choose a Focus
                  to set the analytical lens, then pick a synced chapter or paste new text to review.
                  The AI draws on extracted knowledge from all prior books in the series.
                </div>
              </div>
            </div>
            <p className="mt-0.5 text-[11px] text-ink-muted">
              AI feedback on your writing, grounded in your series canon
            </p>
          </div>
        </div>
        <div className="mt-3 border-t border-surface-border" />
      </div>

      {/* Main content: left column + right panel */}
      <div className="flex flex-1 min-h-0 overflow-hidden">

        {/* Left column — filter row + textarea + messages + footer */}
        <div className={clsx(
          "relative flex flex-col overflow-hidden transition-all duration-300",
          sideOpen ? "w-[60%]" : "w-full"
        )}>

          {/* Filter row */}
          <div className="flex-shrink-0 flex items-center gap-2 px-6">
            {/* Book dropdown */}
            <Dropdown
              value={filterBook}
              options={bookOptions}
              placeholder="Select book…"
              onChange={(v) => { setFilterBook(v); setSelectedChapter(null); setChapterText(""); setDraft(null); setMessages([]); setPreviewOpen(false); setActiveCitation(null); setViewingReviewSessionId(null); activeSessionIdRef.current = null; resetCostControls(); }}
            />

            {/* Chapter dropdown */}
            <Dropdown
              value={selectedChapter === null ? "" : (selectedChapter as number | "new")}
              options={chapterDropdownOptions}
              placeholder={filterBook ? "Select chapter…" : "Select a book first"}
              onChange={(v) => { setSelectedChapter(v); setChapterText(""); setDraft(null); setMessages([]); setPreviewOpen(false); setActiveCitation(null); setViewingReviewSessionId(null); activeSessionIdRef.current = null; resetCostControls(); }}
              renderOption={(v) => (
                <span className={v === "new" ? "text-accent" : undefined}>
                  {v === "new" ? "+ New Chapter (paste)" : chapterLabel(v)}
                </span>
              )}
              renderValue={(v) => v === "new" ? "New Chapter" : chapterLabel(v)}
              maxHeight="198px"
            />

            {/* Reviewer persona dropdown */}
            <Dropdown
              value={filterFocus}
              options={FOCUS_OPTIONS.map((f) => f.value)}
              placeholder="Select reviewer…"
              onChange={(v) => { setFilterFocus(v); setMessages([]); setPreviewOpen(false); setActiveCitation(null); setViewingReviewSessionId(null); activeSessionIdRef.current = null; resetCostControls(); }}
              renderOption={(v) => (
                <div>
                  <p className="font-medium text-ink-primary">{v}</p>
                  <p className="text-[10px] text-ink-muted mt-0.5">
                    {FOCUS_OPTIONS.find((f) => f.value === v)?.description}
                  </p>
                </div>
              )}
            />

            {chapterFetching && (
              <span className="text-[10px] text-ink-muted animate-pulse">Loading chapter…</span>
            )}


            {/* Chapter preview toggle */}
            {selectedChapter !== null && selectedChapter !== "new" && (
              <button
                onClick={() => {
                  setActiveCitation(null);
                  setPreviewOpen((v) => !v);
                }}
                disabled={!canPreview}
                title={previewOpen ? "Close preview" : "Preview chapter text"}
                className={clsx(
                  "flex items-center justify-center rounded p-1 transition-colors",
                  previewOpen
                    ? "text-accent"
                    : canPreview
                    ? "text-ink-muted hover:text-ink-primary"
                    : "text-ink-muted/30 cursor-not-allowed"
                )}
              >
                <Eye className="h-4 w-4" />
              </button>
            )}

            {/* Settings · Resync · Review · Re-Index (or loading skeletons) */}
            {filterBook && draftLoading && (
              <div className="ml-auto flex items-center gap-2">
                <div className="h-[26px] w-[26px] animate-pulse rounded border border-surface-border bg-surface-border/40" />
                <div className="h-[26px] w-16 animate-pulse rounded border border-surface-border bg-surface-border/40" />
                <div className="h-[26px] w-[72px] animate-pulse rounded border border-surface-border bg-surface-border/40" />
              </div>
            )}
            {filterBook && !draftLoading && (
              <div className="ml-auto flex items-center gap-2">

                {/* Settings cog — Ideal Version and other per-session options */}
                <div ref={settingsRef} className="relative">
                  <button
                    onClick={() => setSettingsOpen((v) => !v)}
                    title="Review settings"
                    className={clsx(
                      "flex items-center justify-center rounded border p-1.5 transition-colors",
                      settingsOpen || includeIdeal
                        ? "border-accent/40 bg-accent/10 text-accent"
                        : "border-surface-border bg-surface text-ink-muted hover:border-accent/50 hover:text-ink-secondary"
                    )}
                  >
                    <Settings2 className="h-3.5 w-3.5" />
                  </button>
                  {settingsOpen && (
                    <div className="absolute right-0 top-full z-50 mt-1 w-60 rounded-md border border-surface-border bg-surface-card shadow-lg overflow-hidden">
                      <button
                        onClick={() => setIncludeIdeal((v) => !v)}
                        className="flex w-full items-start gap-2.5 px-3 py-2.5 text-left transition-colors hover:bg-surface-hover"
                      >
                        <Sparkles className={clsx("mt-0.5 h-3.5 w-3.5 flex-shrink-0", includeIdeal ? "text-accent" : "text-ink-muted")} />
                        <div className="flex-1 min-w-0">
                          <p className={clsx("text-[11px] font-medium", includeIdeal ? "text-accent" : "text-ink-secondary")}>Ideal Version</p>
                          <p className="mt-0.5 text-[10px] text-ink-muted leading-relaxed">
                            {includeIdeal
                              ? "Full tracked-changes rewrite on next review. Auto-disables after round 1."
                              : "Only marks passages needing work. Toggle on for a full rewrite."}
                          </p>
                        </div>
                        <div className={clsx(
                          "mt-0.5 h-4 w-7 flex-shrink-0 rounded-full transition-colors",
                          includeIdeal ? "bg-accent" : "bg-surface-border"
                        )}>
                          <div className={clsx(
                            "mt-0.5 ml-0.5 h-3 w-3 rounded-full bg-white shadow transition-transform",
                            includeIdeal ? "translate-x-3" : "translate-x-0"
                          )} />
                        </div>
                      </button>
                    </div>
                  )}
                </div>

                {/* Draft iteration: re-reads the latest export from Loom and
                    continues the same conversation — no reindex needed. */}
                {draft && messages.length > 0 && (
                  <div className="relative group/resyncdraft">
                    <button
                      onClick={handleSendUpdatedDraft}
                      disabled={isStreaming || draftLoading || resyncing}
                      className={clsx(
                        "flex items-center gap-1.5 rounded border px-2.5 py-1 text-[11px] font-medium transition-colors",
                        isStreaming || draftLoading || resyncing
                          ? "border-surface-border text-ink-muted/30 cursor-not-allowed"
                          : "border-accent/40 bg-accent/10 text-accent hover:bg-accent/20"
                      )}
                    >
                      <RotateCcw className="h-3 w-3" />
                      Resync
                    </button>
                    <div className="pointer-events-none absolute right-0 top-full mt-1 z-50 w-64 rounded-md border border-surface-border bg-surface-card px-2.5 py-1.5 text-[10px] leading-relaxed text-ink-muted shadow-lg opacity-0 transition-opacity group-hover/resyncdraft:opacity-100">
                      Re-reads your latest export from Loom and continues the conversation with the updated text — picks up any edits you made since the last review without starting over.
                    </div>
                  </div>
                )}

                {/* Review button — hidden once a draft has a review underway;
                    Resync (above) is the follow-up action in that state. */}
                {!(draft && messages.length > 0) && (
                  <div className="relative group/revbtn">
                    <button
                      onClick={handleReviewClick}
                      disabled={!canSend}
                      className={clsx(
                        "flex items-center gap-1.5 rounded border px-2.5 py-1 text-[11px] font-medium transition-colors",
                        canSend
                          ? "border-accent/40 bg-accent/10 text-accent hover:bg-accent/20"
                          : "border-surface-border text-ink-muted/30 cursor-not-allowed"
                      )}
                    >
                      <ScanText className="h-3 w-3" />
                      Review
                    </button>
                    <div className="pointer-events-none absolute right-0 top-full mt-1 z-50 w-60 rounded-md border border-surface-border bg-surface-card px-2.5 py-1.5 text-[10px] leading-relaxed text-ink-muted shadow-lg opacity-0 transition-opacity group-hover/revbtn:opacity-100">
                      {`Send this chapter to your selected reviewer (${filterFocus}). The review streams into the chat below, grounded in earlier books for continuity.`}
                    </div>
                  </div>
                )}

                {/* Re-Index: amber warning when draft is out of sync,
                    disabled when already in sync, neutral when no draft. */}
                <div className="relative group/reindexbtn">
                  <button
                    onClick={() => {
                      if (!resyncing && !(draft?.in_sync)) setResyncModalOpen(true);
                    }}
                    disabled={resyncing || (draft != null && draft.in_sync)}
                    className={clsx(
                      "flex items-center gap-1.5 rounded border px-2.5 py-1 text-[11px] transition-colors",
                      resyncing
                        ? "border-surface-border text-ink-muted cursor-not-allowed"
                        : draft != null && !draft.in_sync
                        ? "border-amber-400/40 bg-amber-400/10 text-amber-300 hover:bg-amber-400/20"
                        : draft != null && draft.in_sync
                        ? "border-surface-border text-ink-muted/40 cursor-not-allowed"
                        : "border-surface-border bg-surface text-ink-secondary hover:border-accent/50 hover:text-ink-primary"
                    )}
                  >
                    <RefreshCw className={clsx("h-3 w-3", resyncing && "animate-spin")} />
                    {resyncing ? "Indexing…" : "Re-Index"}
                  </button>
                  <div className="pointer-events-none absolute right-0 top-full mt-1 z-50 w-64 rounded-md border border-surface-border bg-surface-card px-2.5 py-1.5 text-[10px] leading-relaxed text-ink-muted shadow-lg opacity-0 transition-opacity group-hover/reindexbtn:opacity-100">
                    {resyncing
                      ? "Re-indexing in progress…"
                      : draft?.in_sync
                      ? "The index is up to date — no re-index needed."
                      : draft != null
                      ? "Chapter isn't indexed yet — click to re-ingest and make it searchable."
                      : "Pull your latest manuscript edits into the app: re-ingests this book (only changed chapters processed) so the review sees your current text. Shows a cost estimate before running."}
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Chapter textarea (new chapter mode) */}
          {selectedChapter === "new" && (
            <div className="flex-shrink-0 border-b border-surface-border px-4 py-3">
              <textarea
                value={chapterText}
                onChange={(e) => setChapterText(e.target.value)}
                placeholder="Paste your chapter text here…"
                rows={6}
                className="w-full resize-none rounded-lg border border-surface-border bg-surface px-3 py-2.5 text-xs leading-relaxed text-ink-primary placeholder:text-ink-muted focus:border-accent focus:outline-none transition-colors"
              />
            </div>
          )}

          {/* Message list — 16px margins keep a fixed gap to the filter row
              above and the input footer below even mid-scroll. */}
          <div className="relative flex-1 min-h-0">
            <div ref={messagesScrollRef} onScroll={handleMessagesScroll} className="absolute inset-0 overflow-y-auto px-6 my-4">
              {messages.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full gap-4 text-center">
                  <ClipboardCheck className="h-8 w-8 text-ink-muted/40" strokeWidth={1} />
                  <div>
                    <p className="text-sm font-medium text-ink-secondary">
                      {chapterText ? "Ready to review" : "Select a chapter to begin"}
                    </p>
                    <p className="mt-1 text-xs text-ink-muted">
                      {chapterText
                        ? `Click Review or ask a specific question below`
                        : "Choose a book, focus, and chapter above, then ask for feedback."}
                    </p>
                  </div>
                  {chapterText && (
                    <div className="flex flex-wrap justify-center gap-2 max-w-sm">
                      {SUGGESTIONS.map((s) => (
                        <button
                          key={s}
                          onClick={() => setInputValue(s)}
                          disabled={isStreaming}
                          className="rounded-full border border-surface-border bg-surface px-3 py-1 text-[11px] text-ink-secondary transition-colors hover:border-accent/50 hover:text-ink-primary"
                        >
                          "{s}"
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              ) : (
                <div className="space-y-4">
                  {messages.map((m) => (
                    <ReviewBubble
                      key={m.id}
                      message={m}
                      onCitationClick={(c) => { setPreviewOpen(false); setActiveCitation(c); }}
                      activeCitation={activeCitation}
                    />
                  ))}
                  <div ref={messagesEndRef} />
                </div>
              )}
            </div>
            {isStreaming && !isAtBottom && (
              <div className="absolute bottom-4 right-6 z-10 rounded-full bg-surface-card/90 p-1.5 shadow-lg border border-surface-border">
                <Loader2 className="h-4 w-4 animate-spin text-accent" />
              </div>
            )}
          </div>

          {/* Footer input */}
          <div className="border-t border-surface-border bg-surface-card px-4 py-3">
        <div className="flex items-end gap-3">
          {/* Textarea */}
          <div className="flex flex-1 items-center rounded-xl border border-surface-border bg-surface focus-within:border-accent transition-colors">
            <textarea
              ref={textareaRef}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              onInput={handleInput}
              placeholder={
                !filterBook
                  ? "Select a book and chapter above to begin…"
                  : !chapterText
                  ? "Select or paste a chapter to review…"
                  : "Ask a specific question about this chapter or click Review..."
              }
              rows={1}
              disabled={isStreaming || !chapterText}
              className={clsx(
                "w-full resize-none bg-transparent px-4 py-3 text-sm leading-tight text-ink-primary placeholder-ink-muted outline-none",
                (isStreaming || !chapterText) && "opacity-50 cursor-not-allowed"
              )}
            />
          </div>

          {/* Send button */}
          <button
            onClick={() => sendMessage(inputValue)}
            disabled={isStreaming || !inputValue.trim() || !chapterText}
            className={clsx(
              "flex-shrink-0 mb-0.5 flex h-9 w-9 items-center justify-center rounded-xl transition-all",
              isStreaming || !inputValue.trim() || !chapterText
                ? "text-ink-muted/30 cursor-not-allowed"
                : "hover:text-accent transition-colors"
            )}
          >
            <Send className="h-6 w-6" strokeWidth={2} style={{ color: (!isStreaming && inputValue.trim() && chapterText) ? "#ffffff" : undefined }} />
          </button>
        </div>

        <div className="mt-1.5 flex items-center justify-between pl-4 pr-12">
          <p className="text-[10px] text-ink-muted">
            {isStreaming ? "Claude is thinking…" : "Press Enter to send"}
          </p>

          {/* Model selector */}
          <div ref={modelDropdownRef} className="relative">
            <button
              onClick={() => setModelDropdownOpen((v) => !v)}
              className="flex items-center gap-1 rounded px-2 py-0.5 text-[10px] text-ink-muted transition-colors hover:bg-surface-hover hover:text-ink-secondary"
            >
              {selectedModel}
              <ChevronDown className="h-2.5 w-2.5" />
            </button>
            {modelDropdownOpen && (
              <div className="absolute bottom-full right-0 mb-1 min-w-[120px] rounded-md border border-surface-border bg-surface-card shadow-lg">
                {MODELS.map((m) => (
                  <button
                    key={m.id}
                    onClick={() => { setModel(m.id); setModelDropdownOpen(false); }}
                    className={clsx(
                      "w-full px-3 py-1.5 text-left text-[11px] transition-colors hover:bg-surface-hover",
                      model === m.id ? "text-accent" : "text-ink-secondary"
                    )}
                  >
                    {m.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
          </div>{/* end footer */}

          {/* Chapter preview — absolute overlay clipped to this column so
              the citation panel on the right stays unaffected. */}
          {previewOpen && selectedChapter !== null && selectedChapter !== "new" && filterBook && (
            <div
              className="absolute inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
              onClick={() => setPreviewOpen(false)}
            >
              <div
                className="h-[85vh] w-[min(860px,92vw)] overflow-hidden rounded-xl shadow-2xl"
                onClick={(e) => e.stopPropagation()}
              >
                <ChapterViewer
                  citation={{
                    book: filterBook,
                    chapter: selectedChapter as number,
                    chapter_heading: String(selectedChapter),
                    pov: "",
                    date: null,
                    chunk_index: 0,
                    snippet: "",
                    distance: 0,
                  }}
                  bookId={bookNameToId(filterBook)}
                  lightMode={lightMode}
                  onToggleLightMode={() => setLightMode((v) => !v)}
                  onClose={() => setPreviewOpen(false)}
                  syncing={resyncing}
                  refreshToken={syncVersion}
                  contentOverride={draft ? { text: draft.text, rich: draft.rich } : undefined}
                />
              </div>
            </div>
          )}

        </div>{/* end left column */}

        {/* Citation viewer panel */}
        <div className={clsx(
          "flex flex-col overflow-hidden border-l border-surface-border rounded-tl-lg transition-all duration-300 ease-in-out",
          activeCitation !== null ? "w-[40%]" : "w-0 border-l-0"
        )}>
          {activeCitation && (
            <ChapterViewer
              citation={activeCitation}
              bookId={bookNameToId(activeCitation.book)}
              lightMode={lightMode}
              onToggleLightMode={() => setLightMode((v) => !v)}
              onClose={() => setActiveCitation(null)}
              syncing={resyncing}
              refreshToken={syncVersion}
            />
          )}
        </div>

      </div>{/* end main content row */}


    </div>
  );
}
