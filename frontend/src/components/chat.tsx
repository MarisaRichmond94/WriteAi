// Shared streaming-chat machinery: message thread, citation cards, the
// source (chunk) viewer panel, and the input box.

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import clsx from "clsx";
import { Send, X } from "lucide-react";
import type { Citation, Message } from "../types";
import { api, streamSSE } from "../lib/api";
import { bookColor, povColor } from "../lib/palette";
import { Spinner } from "./ui";

// ── streaming hook ──────────────────────────────────────────────────────────

export function useStream(endpoint: string) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [streaming, setStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  async function send(userText: string, body: Record<string, unknown>) {
    const history = messages.map((m) => ({ role: m.role, content: m.content }));
    setMessages((ms) => [
      ...ms,
      { role: "user", content: userText },
      { role: "assistant", content: "", streaming: true },
    ]);
    setStreaming(true);
    abortRef.current = new AbortController();
    try {
      for await (const ev of streamSSE(
        endpoint,
        { ...body, conversation_history: history },
        abortRef.current.signal,
      )) {
        if (ev.type === "chunk") {
          setMessages((ms) => {
            const out = [...ms];
            const last = out[out.length - 1];
            out[out.length - 1] = { ...last, content: last.content + (ev.content ?? "") };
            return out;
          });
        } else if (ev.type === "citations") {
          setMessages((ms) => {
            const out = [...ms];
            out[out.length - 1] = { ...out[out.length - 1], citations: ev.sources as Citation[] };
            return out;
          });
        } else if (ev.type === "usage") {
          setMessages((ms) => {
            const out = [...ms];
            out[out.length - 1] = { ...out[out.length - 1], cost_usd: ev.cost_usd as number };
            return out;
          });
        } else if (ev.type === "error") {
          setMessages((ms) => {
            const out = [...ms];
            const last = out[out.length - 1];
            out[out.length - 1] = { ...last, content: last.content + `\n\n*Error: ${ev.message}*` };
            return out;
          });
        }
      }
    } finally {
      setMessages((ms) => {
        const out = [...ms];
        out[out.length - 1] = { ...out[out.length - 1], streaming: false };
        return out;
      });
      setStreaming(false);
    }
  }

  return { messages, setMessages, streaming, send, abort: () => abortRef.current?.abort() };
}

// ── citation card ───────────────────────────────────────────────────────────

export function CitationCard({
  citation,
  index,
  onClick,
  active,
}: {
  citation: Citation;
  index: number;
  onClick: () => void;
  active: boolean;
}) {
  const relevance = citation.distance == null ? null : Math.max(0, Math.min(1, 1 - citation.distance));
  const barColor =
    relevance == null ? "bg-ink-muted" : relevance > 0.6 ? "bg-emerald-400" : relevance > 0.45 ? "bg-amber-400" : "bg-rose-400";
  const pov = citation.pov_character;
  const pc = pov ? povColor(pov) : null;
  return (
    <button
      onClick={onClick}
      className={clsx(
        "flex w-full items-center gap-3 rounded-lg border px-3 py-2 text-left transition-colors duration-150",
        active ? "border-accent bg-accent/10" : "border-surface-border bg-surface-card hover:bg-surface-hover",
      )}
    >
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent-subtle text-[10px] font-semibold text-accent">
        {index + 1}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span className={clsx("rounded-full px-2 py-0.5 text-[10px] font-medium", bookColor(citation.book_number ?? 1))}>
            {citation.book_title ?? "?"}
          </span>
          <span className="text-[11px] text-ink-secondary">Ch {citation.chapter_number}</span>
          {pov && pc && (
            <span className={clsx("rounded-full px-1.5 py-px text-[9px] font-medium ring-1", pc.text, pc.ring, pc.bg)}>
              {pov}
            </span>
          )}
        </span>
        <span className="mt-1 block truncate text-[11px] text-ink-muted">{citation.preview}</span>
      </span>
      {relevance != null && (
        <span className="flex w-14 shrink-0 flex-col items-end gap-1">
          <span className="text-[9px] text-ink-muted">{Math.round(relevance * 100)}%</span>
          <span className="h-1 w-full overflow-hidden rounded-full bg-surface-border">
            <span className={clsx("block h-full rounded-full", barColor)} style={{ width: `${relevance * 100}%` }} />
          </span>
        </span>
      )}
    </button>
  );
}

// ── message thread ──────────────────────────────────────────────────────────

export function MessageThread({
  messages,
  onCitation,
  activeCitation,
}: {
  messages: Message[];
  onCitation: (c: Citation) => void;
  activeCitation: string | null;
}) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  return (
    <div className="flex flex-col gap-4 px-6 py-4">
      {messages.map((m, i) =>
        m.role === "user" ? (
          <div key={i} className="flex justify-end">
            <div className="max-w-[75%] rounded-2xl rounded-tr-sm bg-accent-subtle px-4 py-2.5 text-sm text-ink-primary">
              {m.content}
            </div>
          </div>
        ) : (
          <div key={i} className="flex flex-col gap-2">
            <div className="max-w-[85%] rounded-2xl rounded-tl-sm border border-surface-border bg-surface-card px-4 py-3">
              {m.content ? (
                <div className="prose-dark">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                </div>
              ) : (
                <div className="flex items-center gap-2 text-xs text-ink-secondary">
                  <Spinner className="h-3.5 w-3.5" /> Thinking…
                </div>
              )}
              {m.streaming && m.content && (
                <span className="mt-1 inline-block h-3 w-1.5 animate-pulse-slow rounded-sm bg-accent" />
              )}
              {m.cost_usd != null && (
                <div className="mt-2 text-right text-[9px] text-ink-muted">${m.cost_usd.toFixed(4)}</div>
              )}
            </div>
            {m.citations && m.citations.length > 0 && (
              <div className="flex max-w-[85%] flex-col gap-1.5">
                {m.citations.map((c, ci) => (
                  <CitationCard
                    key={c.chunk_id + ci}
                    citation={c}
                    index={ci}
                    active={activeCitation === c.chunk_id}
                    onClick={() => onCitation(c)}
                  />
                ))}
              </div>
            )}
          </div>
        ),
      )}
      <div ref={endRef} />
    </div>
  );
}

// ── chunk (source) viewer panel ─────────────────────────────────────────────

interface ChunkData {
  chunk_id: string;
  text: string;
  book_title: string;
  chapter_number: number;
  pov_character: string | null;
  date_line: string | null;
}

export function ChunkViewer({ chunkId, onClose }: { chunkId: string; onClose: () => void }) {
  const [chunk, setChunk] = useState<ChunkData | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setChunk(null);
    api<ChunkData>(`/api/chunks/${chunkId}`).then(setChunk).catch((e) => setError(String(e)));
  }, [chunkId]);
  return (
    <div className="flex h-full w-[40%] shrink-0 flex-col border-l border-surface-border bg-surface-card">
      <div className="flex items-center justify-between border-b border-surface-border px-4 py-3">
        <div className="text-xs">
          {chunk ? (
            <>
              <span className="font-medium text-ink-primary">{chunk.book_title}</span>
              <span className="text-ink-secondary"> — Chapter {chunk.chapter_number}</span>
              {chunk.pov_character && <span className="text-ink-muted"> · POV {chunk.pov_character}</span>}
            </>
          ) : (
            <span className="text-ink-muted">Loading source…</span>
          )}
        </div>
        <button onClick={onClose} className="rounded-md p-1 text-ink-secondary hover:text-ink-primary">
          <X className="h-4 w-4" strokeWidth={1.5} />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {error && <div className="text-xs text-rose-300">{error}</div>}
        {chunk && (
          <div className="whitespace-pre-wrap font-serif text-[13px] leading-relaxed text-ink-primary">
            {chunk.text}
          </div>
        )}
      </div>
    </div>
  );
}

// ── input ───────────────────────────────────────────────────────────────────

export function ChatInput({
  onSend,
  disabled,
  placeholder,
  hintRight,
}: {
  onSend: (text: string) => void;
  disabled: boolean;
  placeholder: string;
  hintRight?: string;
}) {
  const [text, setText] = useState("");
  const submit = () => {
    const t = text.trim();
    if (!t || disabled) return;
    setText("");
    onSend(t);
  };
  return (
    <div className="border-t border-surface-border px-4 pb-2.5 pt-3">
      <div className="flex items-end gap-2 rounded-xl border border-surface-border bg-surface px-4 py-2.5 focus-within:border-accent">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          rows={Math.min(5, Math.max(1, text.split("\n").length))}
          placeholder={placeholder}
          className="max-h-40 flex-1 resize-none bg-transparent text-sm text-ink-primary outline-none placeholder:text-ink-muted"
        />
        <button
          onClick={submit}
          disabled={disabled || !text.trim()}
          className={clsx(
            "rounded-md p-1.5 transition-colors",
            disabled || !text.trim() ? "text-ink-muted" : "text-accent hover:text-accent-hover",
          )}
        >
          <Send className="h-4 w-4" strokeWidth={1.5} />
        </button>
      </div>
      <div className="mt-1.5 flex items-center justify-between px-1">
        <span className="text-[10px] text-ink-muted">Press Enter to send</span>
        {hintRight && <span className="text-[10px] text-ink-muted">{hintRight}</span>}
      </div>
    </div>
  );
}
