import { useRef, useState, useEffect, KeyboardEvent } from "react";
import { Send, ChevronDown } from "lucide-react";
import { clsx } from "clsx";
import { useAppStore } from "../../store/useAppStore";
import { useStreamChat } from "../../hooks/useStreamChat";

const MODELS = [
  { id: "claude-sonnet-4-6",       label: "Sonnet 4.6" },
  { id: "claude-opus-4-6",         label: "Opus 4.6"   },
  { id: "claude-haiku-4-5-20251001", label: "Haiku 4.5" },
];

interface Props {
  value: string;
  onChange: (value: string) => void;
}

export default function ChatInput({ value, onChange }: Props) {
  const { queryMode, isStreaming, appSettings } = useAppStore();
  const { sendMessage } = useStreamChat();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const [dropdownOpen, setDropdownOpen] = useState(false);

  const defaultModel = appSettings?.query_model ?? "claude-sonnet-4-6";
  const [model, setModel] = useState<string>(
    () => new URLSearchParams(window.location.search).get("model") ?? defaultModel
  );

  // Sync model to URL; clear on unmount (tab switch)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    params.set("model", model);
    history.replaceState(null, "", "?" + params.toString());
    return () => {
      const p = new URLSearchParams(window.location.search);
      p.delete("model");
      history.replaceState(null, "", "?" + p.toString());
    };
  }, [model]);

  // Close dropdown on outside click
  useEffect(() => {
    if (!dropdownOpen) return;
    function handler(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [dropdownOpen]);

  const handleSend = async () => {
    const text = value.trim();
    if (!text || isStreaming) return;
    onChange("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
    await sendMessage(text, queryMode, model);
  };

  const selectedLabel = MODELS.find((m) => m.id === model)?.label ?? model;

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleInput = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  };

  return (
    <div className="border-t border-surface-border bg-surface-card px-4 py-3">
      <div className="flex items-end gap-3">
        {/* Textarea */}
        <div className="flex flex-1 items-center rounded-xl border border-surface-border bg-surface focus-within:border-accent transition-colors">
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={handleKeyDown}
            onInput={handleInput}
            placeholder="Ask AI a question about your book series..."
            rows={1}
            disabled={isStreaming}
            className={clsx(
              "w-full resize-none bg-transparent px-4 py-3 text-sm leading-tight text-ink-primary placeholder-ink-muted outline-none",
              isStreaming && "opacity-50 cursor-not-allowed"
            )}
          />
        </div>

        {/* Send button */}
        <button
          onClick={handleSend}
          disabled={isStreaming || !value.trim()}
          className={clsx(
            "flex-shrink-0 mb-0.5 flex h-9 w-9 items-center justify-center rounded-xl transition-all",
            isStreaming || !value.trim()
              ? "text-ink-muted/30 cursor-not-allowed"
              : "hover:text-accent transition-colors"
          )}
        >
          <Send className="h-6 w-6" strokeWidth={2} style={{ color: isStreaming || !value.trim() ? undefined : '#ffffff' }} />
        </button>
      </div>

      <div className="mt-1.5 flex items-center justify-between pl-4 pr-12">
        <p className="text-[10px] text-ink-muted">
          {isStreaming ? "Claude is thinking…" : "Press Enter to send"}
        </p>

        {/* Model selector */}
        <div ref={dropdownRef} className="relative">
          <button
            onClick={() => setDropdownOpen((v) => !v)}
            className="flex items-center gap-1 rounded px-2 py-0.5 text-[10px] text-ink-muted transition-colors hover:bg-surface-hover hover:text-ink-secondary"
          >
            {selectedLabel}
            <ChevronDown className="h-2.5 w-2.5" />
          </button>
          {dropdownOpen && (
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
  );
}
