import { useEffect, useRef } from "react";
import { useAppStore } from "../../store/useAppStore";
import MessageBubble from "./MessageBubble";
import { MessageSquare } from "lucide-react";
import type { Citation } from "../../types";

interface Props {
  onCitationClick: (citation: Citation) => void;
  activeCitation: Citation | null;
}

export default function MessageList({ onCitationClick, activeCitation }: Props) {
  const { messages } = useAppStore();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
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
    <div className="flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-4">
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
  );
}
