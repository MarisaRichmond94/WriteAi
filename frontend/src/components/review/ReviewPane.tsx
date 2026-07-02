import { useEffect, useRef, useState, useCallback, KeyboardEvent } from "react";
import { BookOpen, ChevronDown, Eye, Info, Loader2, Moon, RefreshCw, Send, ScanText, ClipboardCheck, Sun, X } from "lucide-react";
import { clsx } from "clsx";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useAppStore } from "../../store/useAppStore";
import type { ChapterSummary, Citation, PipelineCostEstimate, ReviewFocus, ReviewMessage, ReviewSession } from "../../types";
import { streamReview, fetchChapterText, bookNameToId } from "../../api/review";
import { runPipeline, fetchCostEstimate } from "../../api/pipeline";
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
  "What is this chapter really about, beneath the plot?",
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
          value
            ? "border-accent bg-accent/10 text-accent"
            : "border-surface-border bg-surface text-ink-secondary hover:border-accent/50 hover:text-ink-primary"
        )}
      >
        <span>{value ? (renderValue ? renderValue(value as T) : value) : placeholder}</span>
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

// ── Review confirm modal ───────────────────────────────────────────────────────

function ReviewConfirmModal({
  book,
  chapter,
  chapterText,
  focus,
  onConfirm,
  onCancel,
}: {
  book: string;
  chapter: number;
  chapterText: string;
  focus: ReviewFocus;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const [lightMode, setLightMode] = useState(() => useAppStore.getState().appSettings?.viewer_light_mode ?? true);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="relative flex w-full max-w-2xl flex-col rounded-xl border border-surface-border bg-surface-card shadow-2xl" style={{ maxHeight: "80vh" }}>

        {/* Header */}
        <div className="flex-shrink-0 flex items-start justify-between border-b border-surface-border px-5 py-4">
          <div>
            <p className="text-sm font-semibold text-ink-primary">Confirm chapter text</p>
            <p className="mt-0.5 text-[11px] text-ink-muted">
              This is the text that will be sent for a <span className="text-ink-secondary font-medium">{focus}</span> review. Make sure it's up to date before proceeding.
            </p>
          </div>
          <div className="flex items-center gap-1 ml-4 flex-shrink-0">
            <button
              onClick={() => setLightMode((v) => !v)}
              title={lightMode ? "Switch to dark mode" : "Switch to light mode"}
              className="rounded-md p-1.5 text-ink-muted hover:bg-surface-hover hover:text-ink-primary transition-colors"
            >
              {lightMode ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}
            </button>
            <button
              onClick={onCancel}
              className="rounded-md p-1.5 text-ink-muted hover:bg-surface-hover hover:text-ink-primary transition-colors"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Chapter metadata bar */}
        <div className="flex-shrink-0 flex items-center gap-3 border-b border-surface-border bg-surface px-5 py-2.5">
          <BookOpen className="h-4 w-4 flex-shrink-0 text-accent" />
          <div>
            <p className="text-[11px] font-semibold text-ink-primary">{book}</p>
            <p className="text-[10px] text-ink-muted">{chapter === 0 ? "Prologue" : `Chapter ${chapter}`}</p>
          </div>
        </div>

        {/* Chapter text */}
        <div className={clsx("flex-1 min-h-0 overflow-y-auto px-6 py-5 select-text cursor-default", lightMode ? "bg-white" : "bg-surface-card")}>
          <p className={clsx("text-sm leading-relaxed whitespace-pre-wrap", lightMode ? "text-gray-700" : "text-ink-secondary")}>
            {chapterText}
          </p>
        </div>

        {/* Footer */}
        <div className="flex-shrink-0 flex items-center justify-between border-t border-surface-border px-5 py-3">
          <p className="text-[10px] text-ink-muted">
            If this text is outdated, close and use Resync to update it first.
          </p>
          <div className="flex items-center gap-2">
            <button
              onClick={onCancel}
              className="rounded-lg border border-surface-border bg-surface px-4 py-1.5 text-[11px] text-ink-secondary transition-colors hover:border-accent/40 hover:text-ink-primary"
            >
              Cancel
            </button>
            <button
              onClick={onConfirm}
              className="flex items-center gap-1.5 rounded-lg border border-accent/40 bg-accent/10 px-4 py-1.5 text-[11px] font-medium text-accent transition-colors hover:bg-accent/20"
            >
              <ScanText className="h-3 w-3" />
              Send for Review
            </button>
          </div>
        </div>

      </div>
    </div>
  );
}

// ── Resync confirm modal ───────────────────────────────────────────────────────

const EXTRACTION_MODELS = [
  { id: "claude-haiku-4-5-20251001", label: "Haiku 4.5" },
  { id: "claude-sonnet-4-6", label: "Sonnet 4.6" },
  { id: "claude-opus-4-6", label: "Opus 4.6" },
];

function ResyncConfirmModal({
  book,
  onConfirm,
  onCancel,
}: {
  book: string;
  onConfirm: (modelA: string) => void;
  onCancel: () => void;
}) {
  const [modelA, setModelA] = useState("claude-haiku-4-5-20251001");
  const [estimate, setEstimate] = useState<PipelineCostEstimate | null>(null);
  const [estimating, setEstimating] = useState(false);

  useEffect(() => {
    setEstimating(true);
    fetchCostEstimate(["a", "b", "c"], { a: modelA })
      .then(setEstimate)
      .catch(() => setEstimate(null))
      .finally(() => setEstimating(false));
  }, [modelA]);

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
            <p className="text-sm font-semibold text-ink-primary">Resync "{book}"</p>
            <p className="mt-0.5 text-[11px] text-ink-muted">Phases A → B → C scoped to this book</p>
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
            <p><span className="font-semibold text-ink-secondary">Phase A — Chapter Extraction</span><br />Re-reads every chapter in this book and extracts characters, events, facts, and locations using the selected model.</p>
            <p><span className="font-semibold text-ink-secondary">Phase B — Book Consolidation</span><br />Merges per-chapter extractions into a deduplicated knowledge set for this book. No LLM cost.</p>
            <p><span className="font-semibold text-ink-secondary">Phase C — Series Synthesis</span><br />Rebuilds series-wide profiles, events, and facts. No LLM cost.</p>
          </div>

          {/* Model selector */}
          <div>
            <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-widest text-ink-muted">
              Phase A Model
            </p>
            <div className="flex gap-2">
              {EXTRACTION_MODELS.map((m) => (
                <button
                  key={m.id}
                  onClick={() => setModelA(m.id)}
                  className={clsx(
                    "flex-1 rounded-lg border px-3 py-2 text-[11px] font-medium transition-colors",
                    modelA === m.id
                      ? "border-accent/60 bg-accent/10 text-accent"
                      : "border-surface-border bg-surface text-ink-secondary hover:border-accent/40 hover:text-ink-primary"
                  )}
                >
                  {m.label}
                </button>
              ))}
            </div>
            <p className="mt-1.5 text-[10px] text-ink-muted">
              Haiku recommended — structured extraction works well on smaller models.
            </p>
          </div>

          {/* Cost estimate */}
          <div className="flex items-center justify-between rounded-lg border border-surface-border bg-surface px-4 py-3">
            <p className="text-[11px] text-ink-muted">Estimated cost</p>
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
            onClick={() => onConfirm(modelA)}
            className="flex items-center gap-1.5 rounded-lg border border-accent/40 bg-accent/10 px-4 py-1.5 text-[11px] font-medium text-accent transition-colors hover:bg-accent/20"
          >
            <RefreshCw className="h-3 w-3" />
            Start Resync
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
    <div className="flex justify-start">
      <div className="flex max-w-[85%] w-full flex-col max-h-[calc(100vh-360px)]">
        <div className="relative flex-shrink-0">
          <div className="rounded-2xl rounded-tl-sm bg-surface-card px-4 py-3 border border-surface-border max-h-[30vh] overflow-y-auto">
            {message.isStreaming && !message.content ? (
              <StreamingIndicator />
            ) : (
              <div className="prose-dark text-sm">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
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
          <div className="mt-2 flex flex-col min-h-0 flex-1">
            <div className="flex-shrink-0 flex items-center justify-between px-1 mb-1.5">
              <p className="text-[10px] font-bold uppercase tracking-widest text-white">
                Sources ({message.citations.length})
              </p>
              <p className="text-[10px] text-white">Click a row to view the sourced text in context</p>
            </div>
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
  const { books, appSettings, reviewSessions, viewingReviewSessionId, upsertReview, setViewingReviewSessionId, clearReviewSignal } = useAppStore();

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

  // Resync state
  const [resyncing, setResyncing] = useState(false);
  const [resyncModalOpen, setResyncModalOpen] = useState(false);

  // Review confirm state
  const [reviewConfirmOpen, setReviewConfirmOpen] = useState(false);

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

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const activeSessionIdRef = useRef<string | null>(null);
  const messagesRef = useRef<ReviewMessage[]>(messages);
  messagesRef.current = messages;
  const prevStreamingRef = useRef(false);

  const bookOptions = books.map((b) => b.name);
  const selectedBookObj = books.find((b) => b.name === filterBook) ?? null;

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

  // Fetch chapter text when a synced chapter is selected
  useEffect(() => {
    if (selectedChapter === null || selectedChapter === "new" || !selectedBookObj) {
      setChapterText("");
      return;
    }
    setChapterFetching(true);
    setChapterText("");
    fetchChapterText(selectedBookObj.id, selectedChapter)
      .then(setChapterText)
      .catch(() => setChapterText(""))
      .finally(() => setChapterFetching(false));
  }, [selectedChapter, selectedBookObj]);

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
  }, [viewingReviewSessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-save session whenever streaming completes
  useEffect(() => {
    const was = prevStreamingRef.current;
    prevStreamingRef.current = isStreaming;
    if (!was || isStreaming) return;
    const msgs = messagesRef.current;
    if (msgs.length === 0) return;
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
    };
    upsertReview(session);
  }, [isStreaming]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

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

  const canSend = !!chapterText.trim() && !!filterBook && !isStreaming;

  const sendMessage = useCallback(async (text: string) => {
    if (!canSend || !text.trim()) return;

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
    });

    const history = messages.slice(-6).map((m) => ({ role: m.role, content: m.content }));

    try {
      const gen = streamReview({
        chapter_text: chapterText,
        chapter: typeof selectedChapter === "number" ? selectedChapter : undefined,
        book: filterBook,
        focus: filterFocus,
        message: text,
        conversation_history: history,
        model,
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
  }, [canSend, chapterText, filterBook, filterFocus, messages, model, selectedChapter, upsertReview]);

  const handleReviewClick = () => {
    // For synced chapters, show confirmation modal first; for pasted text, send directly
    if (selectedChapter !== "new" && selectedChapter !== null) {
      setReviewConfirmOpen(true);
    } else {
      sendMessage(`Please give me a ${filterFocus} review of this chapter.`);
    }
  };

  const handleReviewConfirm = () => {
    setReviewConfirmOpen(false);
    sendMessage(`Please give me a ${filterFocus} review of this chapter.`);
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

  const handleResyncConfirm = async (modelA: string) => {
    setResyncModalOpen(false);
    if (!filterBook) return;
    setResyncing(true);
    try {
      await runPipeline({ phases: ["a", "b", "c"], force: false, book: filterBook, model_a: modelA });
      setTimeout(() => {
        if (selectedBookObj) setChapters(selectedBookObj.chapters);
        setResyncing(false);
      }, 2000);
    } catch {
      setResyncing(false);
    }
  };

  const chapterDropdownOptions: (number | "new")[] = [
    "new",
    ...chapters.map((c) => c.chapter as number),
  ];

  const chapterLabel = (v: number | "new") =>
    v === "new" ? "+ New Chapter" : v === 0 ? "Prologue" : `Chapter ${v}`;

  const selectedModel = MODELS.find((m) => m.id === model)?.label ?? model;

  const sideOpen = activeCitation !== null || previewOpen;
  const canPreview = selectedChapter !== null && selectedChapter !== "new" && !!chapterText && !chapterFetching;

  return (
    <div className="flex flex-1 flex-col overflow-hidden">

      {resyncModalOpen && filterBook && (
        <ResyncConfirmModal
          book={filterBook}
          onConfirm={handleResyncConfirm}
          onCancel={() => setResyncModalOpen(false)}
        />
      )}

      {reviewConfirmOpen && filterBook && typeof selectedChapter === "number" && (
        <ReviewConfirmModal
          book={filterBook}
          chapter={selectedChapter}
          chapterText={chapterText}
          focus={filterFocus}
          onConfirm={handleReviewConfirm}
          onCancel={() => setReviewConfirmOpen(false)}
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
          "flex flex-col overflow-hidden transition-all duration-300",
          sideOpen ? "w-[60%]" : "w-full"
        )}>

          {/* Filter row */}
          <div className="flex-shrink-0 flex items-center gap-2 px-6">
            {/* Book dropdown */}
            <Dropdown
              value={filterBook}
              options={bookOptions}
              placeholder="Select book…"
              onChange={(v) => { setFilterBook(v); setSelectedChapter(null); setChapterText(""); setMessages([]); setPreviewOpen(false); setActiveCitation(null); setViewingReviewSessionId(null); activeSessionIdRef.current = null; }}
            />

            {/* Reviewer persona dropdown */}
            <Dropdown
              value={filterFocus}
              options={FOCUS_OPTIONS.map((f) => f.value)}
              placeholder="Select reviewer…"
              onChange={(v) => { setFilterFocus(v); setMessages([]); setPreviewOpen(false); setActiveCitation(null); setViewingReviewSessionId(null); activeSessionIdRef.current = null; }}
              renderOption={(v) => (
                <div>
                  <p className="font-medium text-ink-primary">{v}</p>
                  <p className="text-[10px] text-ink-muted mt-0.5">
                    {FOCUS_OPTIONS.find((f) => f.value === v)?.description}
                  </p>
                </div>
              )}
            />

            {/* Chapter dropdown */}
            <Dropdown
              value={selectedChapter === null ? "" : (selectedChapter as number | "new")}
              options={chapterDropdownOptions}
              placeholder={filterBook ? "Select chapter…" : "Select a book first"}
              onChange={(v) => { setSelectedChapter(v); setMessages([]); setPreviewOpen(false); setActiveCitation(null); setViewingReviewSessionId(null); activeSessionIdRef.current = null; }}
              renderOption={(v) => (
                <span className={v === "new" ? "text-accent" : undefined}>
                  {v === "new" ? "+ New Chapter (paste)" : `Chapter ${v}`}
                </span>
              )}
              renderValue={(v) => v === "new" ? "New Chapter" : `Chapter ${v}`}
              maxHeight="198px"
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

            {/* Review + Resync buttons */}
            {filterBook && (
              <div className="ml-auto flex items-center gap-2">
                <button
                  onClick={handleReviewClick}
                  disabled={!canSend}
                  title={`Start a ${filterFocus} review`}
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
                <button
                  onClick={() => { if (!resyncing) setResyncModalOpen(true); }}
                  disabled={resyncing}
                  title="Re-run extraction for this book (phases A → B → C)"
                  className={clsx(
                    "flex items-center gap-1.5 rounded border px-2.5 py-1 text-[11px] transition-colors",
                    resyncing
                      ? "border-surface-border text-ink-muted cursor-not-allowed"
                      : "border-surface-border bg-surface text-ink-secondary hover:border-accent/50 hover:text-ink-primary"
                  )}
                >
                  <RefreshCw className={clsx("h-3 w-3", resyncing && "animate-spin")} />
                  {resyncing ? "Syncing…" : "Resync"}
                </button>
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

          {/* Message list */}
          <div className="flex-1 overflow-y-auto px-6 py-4">
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
            />
          )}
        </div>

        {/* Chapter preview panel */}
        <div className={clsx(
          "flex flex-col overflow-hidden border-l border-surface-border rounded-tl-lg transition-all duration-300 ease-in-out",
          previewOpen ? "w-[40%]" : "w-0 border-l-0"
        )}>
          {previewOpen && selectedChapter !== null && selectedChapter !== "new" && filterBook && (
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
            />
          )}
        </div>

      </div>{/* end main content row */}

    </div>
  );
}
