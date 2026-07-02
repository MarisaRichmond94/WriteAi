import { useState, useCallback } from "react";
import { X, Send, Loader2, MessageSquare } from "lucide-react";
import { streamOutlineReview } from "../../../api/plan";
import type { Citation } from "../../../types";
import MessageBubble from "../../chat/MessageBubble";
import StreamingIndicator from "../../chat/StreamingIndicator";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  isStreaming?: boolean;
}

interface OutlineReviewPanelProps {
  book: string;
  bookId: string;
  selectedChapterIds: string[];
  onClose: () => void;
}

export default function OutlineReviewPanel({
  book,
  bookId: _bookId,
  selectedChapterIds,
  onClose,
}: OutlineReviewPanelProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || streaming) return;

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: text.trim(),
    };

    const assistantId = crypto.randomUUID();
    const assistantMsg: Message = {
      id: assistantId,
      role: "assistant",
      content: "",
      isStreaming: true,
    };

    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setInput("");
    setStreaming(true);

    const history = messages.map((m) => ({ role: m.role, content: m.content }));

    try {
      const gen = streamOutlineReview({
        book,
        chapter_ids: selectedChapterIds,
        message: text.trim(),
        conversation_history: history,
      });

      let accumulated = "";
      let citations: Citation[] = [];

      for await (const event of gen) {
        if (event.type === "chunk") {
          accumulated += event.content;
          setMessages((prev) =>
            prev.map((m) => (m.id === assistantId ? { ...m, content: accumulated } : m))
          );
        } else if (event.type === "citations") {
          citations = event.sources;
        } else if (event.type === "done") {
          break;
        } else if (event.type === "error") {
          accumulated += `\n\n*Error: ${event.message}*`;
          break;
        }
      }

      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? { ...m, content: accumulated, citations, isStreaming: false }
            : m
        )
      );
    } catch (err) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? { ...m, content: "Failed to get a response.", isStreaming: false }
            : m
        )
      );
    } finally {
      setStreaming(false);
    }
  }, [messages, streaming, book, selectedChapterIds]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  };

  const isEmpty = messages.length === 0;

  return (
    <div className="flex flex-col h-full border-l border-surface-border bg-surface-card rounded-tl-[8px]">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-surface-border px-4 py-3 flex-shrink-0">
        <div className="flex items-center">
          <p className="text-xs font-semibold uppercase tracking-widest text-ink-primary">
            AI Review
          </p>
          <span className="text-[10px] text-ink-muted pl-2">
            {selectedChapterIds.length} chapter(s) selected
          </span>
        </div>
        <button
          onClick={onClose}
          className="rounded p-1 text-ink-muted hover:text-ink-secondary transition-colors"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {isEmpty && (
          <div className="flex h-full items-center justify-center">
            <div className="flex flex-col items-center gap-4 w-1/2">
              <MessageSquare className="h-5 w-5 text-ink-muted/50" strokeWidth={1.5} />
              <p className="text-[11px] text-ink-muted text-center leading-relaxed">
                Ask about your selected chapter(s) or click one of the prepopulated questions below for a quick review
              </p>
              <div className="flex flex-col gap-2 w-full">
                {[
                  "Is the chapter purpose clear and does it earn its place?",
                  "Are there any continuity issues with earlier books?",
                  "Does the pacing feel right for this point in the story?",
                ].map((s, i) => (
                  <button
                    key={i}
                    onClick={() => setInput(s)}
                    className="flex items-center justify-center text-center text-[11px] text-ink-muted hover:text-ink-secondary border border-surface-border rounded-full px-3 py-2 hover:border-accent/30 transition-colors"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}
        {messages.map((m) => (
          m.isStreaming && m.content === ""
            ? <StreamingIndicator key={m.id} />
            : <MessageBubble key={m.id} message={{
                id: m.id,
                role: m.role,
                content: m.content,
                citations: m.citations,
                timestamp: new Date(),
                isStreaming: m.isStreaming,
              }} onCitationClick={() => {}} activeCitation={null} />
        ))}
      </div>

      {/* Input */}
      <div className="flex-shrink-0 border-t border-surface-border px-3 py-3">
        <div className="flex items-center gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about these chapters…"
            rows={1}
            className="flex-1 resize-none rounded-xl border border-surface-border bg-surface px-3 py-2 text-xs text-ink-primary placeholder-ink-muted/50 focus:border-accent focus:outline-none leading-relaxed"
          />
          <button
            onClick={() => sendMessage(input)}
            disabled={!input.trim() || streaming}
            className="flex h-7 w-8 items-center justify-center rounded-xl bg-accent text-white hover:bg-accent/90 disabled:opacity-40 transition-colors"
          >
            {streaming ? <Loader2 className="h-3 w-3 animate-spin" /> : <Send className="h-3 w-3" />}
          </button>
        </div>
      </div>
    </div>
  );
}
