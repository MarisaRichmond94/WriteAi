import type { ChatMessage, Citation, QueryMode } from "../types";
import { isMockMode } from "../mocks/mockData";
import { MOCK_RESPONSE, MOCK_CITATIONS } from "../mocks/chatMocks";

export interface ChatRequest {
  message: string;
  mode: QueryMode;
  book_filter: string[];
  pov_filter: string[];
  conversation_history: ChatMessage[];
  n_results?: number;
  model?: string;
  thorough?: boolean;   // true -> full-quality (slower) reranker; default fast
}

export type SSEEvent =
  | { type: "chunk"; content: string }
  | { type: "citations"; sources: Citation[] }
  | { type: "done" }
  | { type: "error"; message: string };

export async function* streamChat(req: ChatRequest): AsyncGenerator<SSEEvent> {
  if (isMockMode()) {
    for (const word of MOCK_RESPONSE.split(" ")) {
      await new Promise((r) => setTimeout(r, 28));
      yield { type: "chunk", content: word + " " };
    }
    yield { type: "citations", sources: MOCK_CITATIONS };
    yield { type: "done" };
    return;
  }

  const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Chat request failed: ${response.status} ${text}`);
  }

  if (!response.body) throw new Error("No response body");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed.startsWith("data: ")) continue;
      const raw = trimmed.slice(6);
      try {
        const event = JSON.parse(raw) as SSEEvent;
        yield event;
      } catch {
        // malformed line — skip
      }
    }
  }

  // Flush remaining buffer
  if (buffer.trim().startsWith("data: ")) {
    try {
      const event = JSON.parse(buffer.trim().slice(6)) as SSEEvent;
      yield event;
    } catch {
      // ignore
    }
  }
}
