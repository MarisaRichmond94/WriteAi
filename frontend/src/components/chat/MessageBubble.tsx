import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Loader2 } from "lucide-react";
import type { Citation, Message } from "../../types";
import CitationCard from "./CitationCard";
import StreamingIndicator from "./StreamingIndicator";

interface Props {
  message: Message;
  onCitationClick: (citation: Citation) => void;
  activeCitation: Citation | null;
}

function citationKey(c: Citation) {
  return `${c.book}__${c.chapter}__${c.chunk_index}`;
}

export default function MessageBubble({ message, onCitationClick, activeCitation }: Props) {
  const isUser = message.role === "user";

  if (isUser) {
    const timestamp = message.timestamp
      ? new Date(message.timestamp).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
      : null;

    return (
      <div className="flex justify-end items-start h-full">
        <div className="max-w-[75%]">
          <div className="rounded-2xl rounded-tr-sm bg-accent-subtle px-4 py-2.5">
            <p className="text-sm leading-relaxed text-ink-primary whitespace-pre-wrap">
              {message.content}
            </p>
          </div>
          {timestamp && (
            <p className="mt-1 pl-4 text-[10px] text-ink-muted">{timestamp}</p>
          )}
        </div>
      </div>
    );
  }

  // Assistant message
  const hasCitations = !message.isStreaming && !!message.citations && message.citations.length > 0;

  return (
    <div className="flex justify-start h-full">
      <div className="flex w-[90%] flex-col h-full gap-4">
        {/* Response box — flex-[55] of available height */}
        <div className="relative min-h-0" style={{ flex: "55 55 0%" }}>
          <div className="rounded-2xl rounded-tl-sm bg-surface-card px-4 py-3 border border-surface-border h-full overflow-y-auto">
            {message.isStreaming && !message.content ? (
              <StreamingIndicator />
            ) : (
              <div className="prose-dark text-sm">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
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

        {/* Citations — flex-[35] of available height, always reserves space */}
        <div className="min-h-0 flex flex-col" style={{ flex: "35 35 0%" }}>
          {hasCitations && (<>
            <div className="flex-shrink-0 flex items-center justify-between px-1 mb-1.5">
              <p className="text-[10px] font-bold uppercase tracking-widest text-white">
                Sources ({message.citations!.length})
              </p>
              <p className="text-[10px] text-white">
                Click a row to view the sourced text in context
              </p>
            </div>

            <div className="flex-1 min-h-0 overflow-y-auto space-y-1.5">
              {[...message.citations!]
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
          </>)}
        </div>
      </div>
    </div>
  );
}
