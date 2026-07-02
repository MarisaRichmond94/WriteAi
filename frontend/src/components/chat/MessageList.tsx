import { useEffect } from "react";
import { useAppStore } from "../../store/useAppStore";
import MessageBubble from "./MessageBubble";
import { MessageSquare } from "lucide-react";
import type { Citation } from "../../types";

interface Props {
  onCitationClick: (citation: Citation) => void;
  activeCitation: Citation | null;
  onSuggestionClick: (text: string) => void;
}

export default function MessageList({ onCitationClick, activeCitation, onSuggestionClick }: Props) {
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
            Select a query mode above, then ask about plot continuity, character arcs,
            timeline events, or explore alternate scenarios.
          </p>
        </div>
        <div className="flex flex-wrap justify-center gap-2 text-xs text-ink-muted max-w-md">
          {[
            "When did Noah first learn about the existence of The Black Hand?",
            "What would've happened if Emma hadn't lost the baby?",
            "Are there any timeline contradictions in Split?",
          ].map((suggestion) => (
            <button
              key={suggestion}
              onClick={() => onSuggestionClick(suggestion)}
              className="rounded-full border border-surface-border px-3 py-1 hover:border-accent hover:text-accent transition-colors"
            >
              "{suggestion}"
            </button>
          ))}
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
