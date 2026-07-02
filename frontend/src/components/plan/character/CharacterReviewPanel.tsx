import { useState, useCallback, useRef, useEffect } from "react";
import { X, Send, ChevronDown } from "lucide-react";
import { clsx } from "clsx";
import { streamCharacterReview } from "../../../api/plan";
import { isMockMode } from "../../../mocks/mockData";
import type { Citation, WriterCharacter } from "../../../types";
import MessageBubble from "../../chat/MessageBubble";
import StreamingIndicator from "../../chat/StreamingIndicator";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  isStreaming?: boolean;
}

interface CharacterReviewPanelProps {
  character: WriterCharacter;
  onClose: () => void;
}

const MODELS = [
  { id: "claude-sonnet-4-6",        label: "Sonnet 4.6" },
  { id: "claude-opus-4-6",          label: "Opus 4.6"   },
  { id: "claude-haiku-4-5-20251001", label: "Haiku 4.5"  },
];

export default function CharacterReviewPanel({ character, onClose }: CharacterReviewPanelProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [model, setModel] = useState("claude-sonnet-4-6");
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Auto-grow textarea
  const handleInput = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  };

  // Close dropdown on outside click
  useEffect(() => {
    if (!dropdownOpen) return;
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node))
        setDropdownOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [dropdownOpen]);

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || streaming) return;

    const userMsg: Message = { id: crypto.randomUUID(), role: "user", content: text.trim() };
    const assistantId = crypto.randomUUID();
    const assistantMsg: Message = { id: assistantId, role: "assistant", content: "", isStreaming: true };

    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setInput("");
    setStreaming(true);

    const history = messages.map((m) => ({ role: m.role, content: m.content }));

    try {
      const gen = streamCharacterReview({
        character_id: character.id,
        message: text.trim(),
        conversation_history: history,
        model,
      });

      let accumulated = "";
      let citations: Citation[] = [];

      for await (const event of gen) {
        if (event.type === "chunk") {
          accumulated += event.content;
          setMessages((prev) => prev.map((m) => m.id === assistantId ? { ...m, content: accumulated } : m));
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
        prev.map((m) => m.id === assistantId
          ? { ...m, content: accumulated, citations, isStreaming: false }
          : m)
      );
    } catch {
      setMessages((prev) =>
        prev.map((m) => m.id === assistantId
          ? { ...m, content: "Failed to get a response.", isStreaming: false }
          : m)
      );
    } finally {
      setStreaming(false);
    }
  }, [messages, streaming, character.id, model]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (textareaRef.current) textareaRef.current.style.height = "auto";
      sendMessage(input);
    }
  };

  const isMock = isMockMode();
  const selectedLabel = MODELS.find((m) => m.id === model)?.label ?? model;

  const isEmpty = messages.length === 0;

  return (
    <div className="flex flex-col h-full border-l border-surface-border bg-surface">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-surface-border bg-surface-card px-4 py-3 flex-shrink-0">
        <p className="text-xs font-semibold uppercase tracking-widest text-ink-primary">
          Character Review: {character.name}
        </p>
        <button onClick={onClose} className="rounded p-1 text-ink-muted hover:text-ink-secondary transition-colors">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {isEmpty && (
          <div className="flex flex-col items-center justify-center h-full gap-4 py-8">
            <p className="text-[11px] text-ink-muted text-center">
              Get AI feedback on {character.name}'s characterization.
            </p>
            <div className="flex flex-col gap-2 w-full">
              {[
                `Is ${character.name} a well-rounded character based on what I've described?`,
                `What gaps do you see in ${character.name}'s development?`,
                `How does what I planned for ${character.name} compare to what the books actually show?`,
              ].map((s, i) => (
                <button
                  key={i}
                  onClick={() => sendMessage(s)}
                  className="text-left text-[11px] text-ink-muted hover:text-ink-secondary border border-surface-border rounded-lg px-3 py-2 hover:border-accent/30 transition-colors"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m) =>
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
        )}
      </div>

      {/* Input */}
      <div className="flex-shrink-0 border-t border-surface-border bg-surface-card px-4 py-3">
        <div className="flex items-end gap-3">
          <div className="flex flex-1 items-center rounded-xl border border-surface-border bg-surface focus-within:border-accent transition-colors">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              onInput={handleInput}
              placeholder={`Ask about ${character.name}…`}
              rows={1}
              disabled={streaming}
              className={clsx(
                "w-full resize-none bg-transparent px-4 py-3 text-sm leading-tight text-ink-primary placeholder-ink-muted outline-none",
                streaming && "opacity-50 cursor-not-allowed"
              )}
            />
          </div>
          <button
            onClick={() => { if (textareaRef.current) textareaRef.current.style.height = "auto"; sendMessage(input); }}
            disabled={!input.trim() || streaming}
            className={clsx(
              "flex-shrink-0 mb-0.5 flex h-9 w-9 items-center justify-center rounded-xl transition-all",
              !input.trim() || streaming ? "text-ink-muted/30 cursor-not-allowed" : "hover:text-accent transition-colors"
            )}
          >
            <Send className="h-6 w-6" strokeWidth={2} style={{ color: !input.trim() || streaming ? undefined : "#ffffff" }} />
          </button>
        </div>
        <div className="mt-1.5 flex items-center justify-between pl-4 pr-12">
          <p className="text-[10px] text-ink-muted">
            {streaming ? "Claude is thinking…" : "Press Enter to send"}
          </p>
          <div ref={dropdownRef} className="relative">
            {isMock ? (
              <span className="rounded px-2 py-0.5 text-[10px] text-amber-400 font-medium">mock mode</span>
            ) : (
            <button
              onClick={() => setDropdownOpen((v) => !v)}
              className="flex items-center gap-1 rounded px-2 py-0.5 text-[10px] text-ink-muted transition-colors hover:bg-surface-hover hover:text-ink-secondary"
            >
              {selectedLabel}
              <ChevronDown className="h-2.5 w-2.5" />
            </button>
            )}
            {!isMock && dropdownOpen && (
              <div className="absolute bottom-full right-0 mb-1 min-w-[120px] rounded-md border border-surface-border bg-surface-card shadow-lg">
                {MODELS.map((m) => (
                  <button
                    key={m.id}
                    onClick={() => { setModel(m.id); setDropdownOpen(false); }}
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
      </div>
    </div>
  );
}
