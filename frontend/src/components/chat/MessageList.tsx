import { useEffect } from "react";
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
    <div className="flex flex-col h-full px-4">
      {messages.map((message) => (
        <div
          key={message.id}
          className={message.role === "user" ? "flex-shrink-0 h-[10%]" : "flex-1 min-h-0"}
        >
          <MessageBubble message={message} onCitationClick={onCitationClick} activeCitation={activeCitation} />
        </div>
      ))}
    </div>
  );
}
