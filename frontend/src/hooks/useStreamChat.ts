import { useCallback, useRef } from "react";
import { streamChat } from "../api/chat";
import { useAppStore } from "../store/useAppStore";
import { notifyAnswerReady } from "../lib/attention";
import type { QueryMode } from "../types";

function uuid(): string {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export function useStreamChat() {
  const {
    selectedBooks,
    selectedPovs,
    books,
    messages,
    addUserMessage,
    startAssistantMessage,
    appendChunk,
    finalizeMessage,
    showToast,
    saveChatAndClear,
    upsertChatSession,
    liveChatSessionId,
    setLiveChatSessionId,
    closeExploreViewer,
  } = useAppStore();

  const liveChatSessionIdRef = useRef<string | null>(liveChatSessionId);
  liveChatSessionIdRef.current = liveChatSessionId;

  const sendMessage = useCallback(
    async (text: string, mode: QueryMode, model?: string) => {
      if (!text.trim()) return;

      const bookFilter = selectedBooks.size > 0
        ? books.filter((b) => selectedBooks.has(b.id)).map((b) => b.name)
        : [];
      const povFilter = selectedPovs.size > 0 ? [...selectedPovs] : [];
      const history = messages.slice(-6).map((m) => ({ role: m.role, content: m.content }));

      // Clear previous conversation from the live view and close any open viewer
      saveChatAndClear();
      closeExploreViewer();
      liveChatSessionIdRef.current = null;

      // Create a new session ID for this conversation
      const sessionId = uuid();
      liveChatSessionIdRef.current = sessionId;
      setLiveChatSessionId(sessionId);

      addUserMessage(text, mode);
      const assistantId = startAssistantMessage(mode);

      // Immediately create the history entry so it appears in the sidebar right away
      upsertChatSession({
        id: sessionId,
        question: text,
        messages: useAppStore.getState().messages.map((m) => ({ ...m, isStreaming: false })),
        timestamp: new Date(),
        mode,
        selectedBooks: bookFilter.length > 0 ? books.filter((b) => selectedBooks.has(b.id)).map((b) => b.id) : [],
        selectedPovs: povFilter,
      });

      let pendingCitations: import("../types").Citation[] = [];
      let finalized = false;

      const finish = (citations: import("../types").Citation[]) => {
        if (!finalized) {
          finalized = true;
          finalizeMessage(assistantId, citations);
          // Answer's done — chime + flash the tab title if the user tabbed away.
          notifyAnswerReady();
          // Update the history entry with the completed response
          upsertChatSession({
            id: sessionId,
            question: text,
            messages: useAppStore.getState().messages.map((m) => ({ ...m, isStreaming: false })),
            timestamp: new Date(),
            mode,
            selectedBooks: bookFilter.length > 0 ? books.filter((b) => selectedBooks.has(b.id)).map((b) => b.id) : [],
            selectedPovs: povFilter,
          });
        }
      };

      try {
        for await (const event of streamChat({
          message: text,
          mode,
          book_filter: bookFilter,
          pov_filter: povFilter,
          conversation_history: history,
          ...(model ? { model } : {}),
        })) {
          if (event.type === "chunk") {
            appendChunk(assistantId, event.content);
          } else if (event.type === "citations") {
            pendingCitations = event.sources;
          } else if (event.type === "done") {
            finish(pendingCitations);
          } else if (event.type === "error") {
            showToast(`Claude error: ${event.message}`);
            finish([]);
          }
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Unknown error";
        showToast(`Error: ${msg}`);
      } finally {
        finish(pendingCitations);
      }
    },
    [selectedBooks, selectedPovs, books, messages, addUserMessage, startAssistantMessage, appendChunk, finalizeMessage, showToast, saveChatAndClear, upsertChatSession, setLiveChatSessionId, closeExploreViewer]
  );

  return { sendMessage };
}
