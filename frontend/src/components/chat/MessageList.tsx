import { useEffect, useRef, useState } from "react";
import { useAppStore } from "../../store/useAppStore";
import MessageBubble from "./MessageBubble";
import { MessageSquare, Loader2 } from "lucide-react";
import type { Citation } from "../../types";

interface Props {
  onCitationClick: (citation: Citation) => void;
  activeCitation: Citation | null;
}

export default function MessageList({ onCitationClick, activeCitation }: Props) {
  const { messages, isStreaming } = useAppStore();
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const isAtBottomRef = useRef(true);
  const [isAtBottom, setIsAtBottom] = useState(true);

  const handleScroll = () => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    isAtBottomRef.current = atBottom;
    setIsAtBottom(atBottom);
  };

  useEffect(() => {
    if (isAtBottomRef.current) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-4 text-center px-8">
        <MessageSquare className="h-10 w-10 text-accent" strokeWidth={1.5} />
        <div>
          <h2 className="text-base font-semibold text-ink-primary mb-1">
            Ask anything about your series
          </h2>
          <p className="text-sm text-ink-muted max-w-sm">
            Ask about plot continuity, character arcs, timeline events, or
            explore alternate scenarios — answers are grounded in your books
            and cite their sources.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative flex-1 min-h-0">
      <div ref={scrollContainerRef} onScroll={handleScroll} className="absolute inset-0 overflow-y-auto px-4 py-4 flex flex-col gap-4">
        {messages.map((message) => (
          <MessageBubble
            key={message.id}
            message={message}
            onCitationClick={onCitationClick}
            activeCitation={activeCitation}
          />
        ))}
        <div ref={bottomRef} />
      </div>
      {isStreaming && !isAtBottom && (
        <div className="absolute bottom-4 right-4 z-10 rounded-full bg-surface-card/90 p-1.5 shadow-lg border border-surface-border">
          <Loader2 className="h-4 w-4 animate-spin text-accent" />
        </div>
      )}
    </div>
  );
}
