import { create } from "zustand";
import type {
  OutlineChapter,
  PlanView,
  ResyncPreviewResponse,
  WriterCharacter,
} from "../types";

interface PlanState {
  planView: PlanView;
  setPlanView: (v: PlanView) => void;

  selectedBook: string;
  setSelectedBook: (b: string) => void;

  outlineByBook: Record<string, OutlineChapter[]>;
  setOutlineForBook: (book: string, chapters: OutlineChapter[]) => void;

  selectedChapterIds: Set<string>;
  toggleChapterSelection: (id: string) => void;
  clearChapterSelection: () => void;
  setSelectedChapterIds: (ids: string[]) => void;

  reviewOpen: boolean;
  setReviewOpen: (open: boolean) => void;

  pendingResync: ResyncPreviewResponse | null;
  setPendingResync: (d: ResyncPreviewResponse | null) => void;

  resyncModalOpen: boolean;
  setResyncModalOpen: (open: boolean) => void;

  syncing: boolean;
  setSyncing: (v: boolean) => void;

  writerCharacters: WriterCharacter[];
  setWriterCharacters: (c: WriterCharacter[]) => void;
}

export const usePlanStore = create<PlanState>((set) => ({
  planView: "outline",
  setPlanView: (v) => set({ planView: v }),

  selectedBook: "",
  setSelectedBook: (b) => set({ selectedBook: b, selectedChapterIds: new Set() }),

  outlineByBook: {},
  setOutlineForBook: (book, chapters) =>
    set((state) => ({ outlineByBook: { ...state.outlineByBook, [book]: chapters } })),

  selectedChapterIds: new Set(),
  toggleChapterSelection: (id) =>
    set((state) => {
      const next = new Set(state.selectedChapterIds);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return { selectedChapterIds: next };
    }),
  clearChapterSelection: () => set({ selectedChapterIds: new Set() }),
  setSelectedChapterIds: (ids) => set({ selectedChapterIds: new Set(ids) }),

  reviewOpen: false,
  setReviewOpen: (open) => set({ reviewOpen: open }),

  pendingResync: null,
  setPendingResync: (d) => set({ pendingResync: d }),

  resyncModalOpen: false,
  setResyncModalOpen: (open) => set({ resyncModalOpen: open }),

  syncing: false,
  setSyncing: (v) => set({ syncing: v }),

  writerCharacters: [],
  setWriterCharacters: (c) => set({ writerCharacters: c }),
}));
