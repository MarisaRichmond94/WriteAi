import type { Citation, ReviewFocus } from "../types";
import { isMockMode, MOCK_REVIEW_RESPONSE } from "../mocks/mockData";
import { fetchChapterText as fetchChapterTextViaBooks } from "./books";
import { generateMockChapterText } from "../mocks/timelineMocks";

export interface ReviewRequest {
  chapter_text: string;
  chapter?: number;   // synced chapter number — backend scopes context strictly before it
  book: string;
  focus: ReviewFocus;
  message: string;
  conversation_history: { role: "user" | "assistant"; content: string }[];
  model?: string;
}

export type ReviewSSEEvent =
  | { type: "chunk"; content: string }
  | { type: "citations"; sources: Citation[] }
  | { type: "done" }
  | { type: "error"; message: string };

export async function* streamReview(req: ReviewRequest): AsyncGenerator<ReviewSSEEvent> {
  if (isMockMode()) {
    for (const word of MOCK_REVIEW_RESPONSE.split(" ")) {
      await new Promise((r) => setTimeout(r, 28));
      yield { type: "chunk", content: word + " " };
    }
    yield { type: "done" };
    return;
  }

  const response = await fetch("/api/review/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Review request failed: ${response.status} ${text}`);
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
        const event = JSON.parse(raw) as ReviewSSEEvent;
        yield event;
      } catch {
        // malformed line — skip
      }
    }
  }

  if (buffer.trim().startsWith("data: ")) {
    try {
      const event = JSON.parse(buffer.trim().slice(6)) as ReviewSSEEvent;
      yield event;
    } catch {
      // ignore
    }
  }
}

export async function fetchChapterText(bookId: string, chapterNum: number): Promise<string> {
  if (isMockMode()) return generateMockChapterText("", chapterNum);
  return fetchChapterTextViaBooks(bookId, chapterNum);
}

export function bookNameToId(name: string): string {
  return name.toLowerCase().replace(/'/g, "").replace(/ /g, "-");
}
