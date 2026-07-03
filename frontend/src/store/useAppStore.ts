import { create } from "zustand";
import type { BookResponse, ChatSession, Citation, IndexStatus, Message, QueryMode, ReviewSession } from "../types";
import type { AppSettings } from "../types";
import { persistSession, removeSession } from "../api/sessions";

// server writes are best-effort: a failed save must never break the live UI
const quiet = (p: Promise<void>) => { p.catch(() => {}); };

function uuid(): string {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

interface AppState {
  // Books
  books: BookResponse[];
  booksLoading: boolean;
  setBooksLoading: (v: boolean) => void;
  setBooks: (books: BookResponse[]) => void;

  // Index status
  indexStatus: IndexStatus | null;
  setIndexStatus: (s: IndexStatus) => void;

  // Filters
  selectedBooks: Set<string>;
  toggleBook: (id: string) => void;
  selectedPovs: Set<string>;
  togglePov: (name: string) => void;
  setPovFilter: (names: string[]) => void;
  clearPovFilter: () => void;
  setBookFilter: (ids: string[]) => void;
  clearBookFilter: () => void;
  clearFilters: () => void;

  // Query mode
  queryMode: QueryMode;
  setQueryMode: (mode: QueryMode) => void;

  // Conversation
  messages: Message[];
  isStreaming: boolean;
  addUserMessage: (content: string, mode: QueryMode) => string;
  startAssistantMessage: (mode: QueryMode) => string;
  appendChunk: (id: string, chunk: string) => void;
  finalizeMessage: (id: string, citations: Citation[]) => void;
  clearConversation: () => void;

  // Chat history
  chatSessions: ChatSession[];
  viewingSessionId: string | null;
  liveChatSessionId: string | null;
  saveChatAndClear: () => void;
  upsertChatSession: (session: ChatSession) => void;
  setChatSessions: (sessions: ChatSession[]) => void;
  setLiveChatSessionId: (id: string | null) => void;
  deleteChat: (id: string) => void;
  loadChat: (id: string) => void;

  // Review history
  reviewSessions: ReviewSession[];
  viewingReviewSessionId: string | null;
  upsertReview: (session: ReviewSession) => void;
  setReviewSessions: (sessions: ReviewSession[]) => void;
  deleteReview: (id: string) => void;
  loadReview: (id: string) => void;
  setViewingReviewSessionId: (id: string | null) => void;
  clearReviewSignal: number;

  // Explore viewer close signal
  exploreViewerCloseSignal: number;
  closeExploreViewer: () => void;

  // Toast
  toastMessage: string | null;
  showToast: (msg: string) => void;
  clearToast: () => void;

  // Pane navigation
  activePane: "explore" | "timeline" | "writer-timeline" | "locations" | "plan" | "review" | "status" | "characters" | "import" | "pipeline" | "quality-review" | "odv-lab" | "settings";
  setActivePane: (pane: "explore" | "timeline" | "writer-timeline" | "locations" | "plan" | "review" | "status" | "characters" | "import" | "pipeline" | "quality-review" | "odv-lab" | "settings") => void;
  pendingPipelineBook: string | null;
  setPendingPipelineBook: (book: string | null) => void;

  // Site settings
  siteName: string;
  setSiteName: (name: string) => void;
  appSettings: AppSettings | null;
  setAppSettings: (s: AppSettings) => void;
}

export const useAppStore = create<AppState>((set) => ({
  books: [],
  booksLoading: false,
  setBooksLoading: (v) => set({ booksLoading: v }),
  setBooks: (books) => set({ books }),

  indexStatus: null,
  setIndexStatus: (s) => set({ indexStatus: s }),

  selectedBooks: (() => {
    const b = new URLSearchParams(window.location.search).get("books");
    return b ? new Set(b.split(",").filter(Boolean)) : new Set<string>();
  })(),
  toggleBook: (id) =>
    set((state) => {
      const next = new Set(state.selectedBooks);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return { selectedBooks: next };
    }),
  selectedPovs: (() => {
    const p = new URLSearchParams(window.location.search).get("povs");
    return p ? new Set(p.split(",").filter(Boolean)) : new Set<string>();
  })(),
  togglePov: (name) =>
    set((state) => {
      const next = new Set(state.selectedPovs);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return { selectedPovs: next };
    }),
  setPovFilter: (names) => set({ selectedPovs: new Set(names) }),
  clearPovFilter: () => set({ selectedPovs: new Set() }),
  setBookFilter: (ids) => set({ selectedBooks: new Set(ids) }),
  clearBookFilter: () => set({ selectedBooks: new Set() }),
  clearFilters: () => set({ selectedBooks: new Set(), selectedPovs: new Set() }),

  queryMode: "general" as QueryMode,
  setQueryMode: (mode) => set({ queryMode: mode }),

  messages: [],
  isStreaming: false,

  addUserMessage: (content, mode) => {
    const id = uuid();
    set((state) => ({
      messages: [
        ...state.messages,
        { id, role: "user", content, mode, timestamp: new Date() },
      ],
    }));
    return id;
  },

  startAssistantMessage: (mode) => {
    const id = uuid();
    set((state) => ({
      isStreaming: true,
      messages: [
        ...state.messages,
        {
          id,
          role: "assistant",
          content: "",
          mode,
          citations: [],
          timestamp: new Date(),
          isStreaming: true,
        },
      ],
    }));
    return id;
  },

  appendChunk: (id, chunk) =>
    set((state) => ({
      messages: state.messages.map((m) =>
        m.id === id ? { ...m, content: m.content + chunk } : m
      ),
    })),

  finalizeMessage: (id, citations) =>
    set((state) => ({
      isStreaming: false,
      messages: state.messages.map((m) =>
        m.id === id ? { ...m, citations, isStreaming: false } : m
      ),
    })),

  clearConversation: () => set({ messages: [], isStreaming: false }),

  chatSessions: [],
  viewingSessionId: null,
  liveChatSessionId: null,

  saveChatAndClear: () =>
    set((_state) => ({
      messages: [],
      isStreaming: false,
      viewingSessionId: null,
      liveChatSessionId: null,
    })),

  upsertChatSession: (session: ChatSession) => {
    quiet(persistSession("chat", session));
    set((state) => ({
      chatSessions: state.chatSessions.some((s) => s.id === session.id)
        ? state.chatSessions.map((s) => (s.id === session.id ? session : s))
        : [...state.chatSessions, session],
    }));
  },

  setChatSessions: (sessions: ChatSession[]) => set({ chatSessions: sessions }),

  setLiveChatSessionId: (id) => set({ liveChatSessionId: id }),

  deleteChat: (id) => {
    quiet(removeSession("chat", id));
    set((state) => ({
      chatSessions: state.chatSessions.filter((s) => s.id !== id),
      ...(state.viewingSessionId === id || state.liveChatSessionId === id
        ? { messages: [], viewingSessionId: null, liveChatSessionId: null }
        : {}),
    }));
  },

  loadChat: (id) =>
    set((state) => {
      const session = state.chatSessions.find((s) => s.id === id);
      if (!session) return {};
      return {
        messages: session.messages,
        viewingSessionId: id,
        ...(session.mode ? { queryMode: session.mode } : {}),
        ...(session.selectedBooks ? { selectedBooks: new Set(session.selectedBooks) } : {}),
        ...(session.selectedPovs ? { selectedPovs: new Set(session.selectedPovs) } : {}),
      };
    }),

  reviewSessions: [],
  viewingReviewSessionId: null,
  upsertReview: (session: ReviewSession) => {
    quiet(persistSession("review", session));
    set((state) => ({
      reviewSessions: state.reviewSessions.some((s) => s.id === session.id)
        ? state.reviewSessions.map((s) => (s.id === session.id ? session : s))
        : [...state.reviewSessions, session],
    }));
  },
  setReviewSessions: (sessions: ReviewSession[]) => set({ reviewSessions: sessions }),
  deleteReview: (id) => {
    quiet(removeSession("review", id));
    set((state) => ({
      reviewSessions: state.reviewSessions.filter((s) => s.id !== id),
      ...(state.viewingReviewSessionId === id ? { viewingReviewSessionId: null, clearReviewSignal: state.clearReviewSignal + 1 } : {}),
    }));
  },
  loadReview: (id) => set({ viewingReviewSessionId: id }),
  setViewingReviewSessionId: (id) => set({ viewingReviewSessionId: id }),
  clearReviewSignal: 0,

  exploreViewerCloseSignal: 0,
  closeExploreViewer: () => set((state) => ({ exploreViewerCloseSignal: state.exploreViewerCloseSignal + 1 })),

  toastMessage: null,
  showToast: (msg) => set({ toastMessage: msg }),
  clearToast: () => set({ toastMessage: null }),

  activePane: ((): AppState["activePane"] => {
    const p = new URLSearchParams(window.location.search).get("pane");
    const valid = ["explore", "timeline", "writer-timeline", "locations", "plan", "review", "status", "characters", "import", "pipeline", "quality-review", "odv-lab", "settings"];
    return (valid.includes(p ?? "") ? p : "explore") as AppState["activePane"];
  })(),
  setActivePane: (pane) => set({ activePane: pane }),

  pendingPipelineBook: null,
  setPendingPipelineBook: (book) => set({ pendingPipelineBook: book }),

  siteName: "The Archive",
  setSiteName: (name) => set({ siteName: name }),
  appSettings: null,
  setAppSettings: (s) => set({ appSettings: s, siteName: s.site_name }),
}));
