import { create } from "zustand";
import type { Book, Pane } from "./types";
import { api } from "./lib/api";

function paneFromURL(): Pane {
  const p = new URLSearchParams(window.location.search).get("pane");
  const valid: Pane[] = ["plan", "review", "explore", "timeline", "books", "characters", "settings"];
  return valid.includes(p as Pane) ? (p as Pane) : "explore";
}

interface Toast {
  id: number;
  message: string;
  kind: "info" | "error" | "success";
}

interface AppStore {
  pane: Pane;
  setPane: (p: Pane) => void;
  books: Book[];
  lastSynced: string | null;
  loadBooks: () => Promise<void>;
  writerName: string;
  siteName: string;
  loadProfile: () => Promise<void>;
  toasts: Toast[];
  toast: (message: string, kind?: Toast["kind"]) => void;
  dismissToast: (id: number) => void;
}

let toastId = 0;

export const useApp = create<AppStore>((set, get) => ({
  pane: paneFromURL(),
  setPane: (pane) => {
    const url = new URL(window.location.href);
    url.searchParams.set("pane", pane);
    window.history.pushState({}, "", url);
    set({ pane });
  },
  books: [],
  lastSynced: null,
  loadBooks: async () => {
    const data = await api<{ books: Book[]; last_synced: string | null }>("/api/books");
    set({ books: data.books, lastSynced: data.last_synced });
  },
  writerName: "Writer",
  siteName: "The Archive",
  loadProfile: async () => {
    try {
      const data = await api<{ profile: { writer_name: string; site_name: string } }>("/api/settings");
      set({
        writerName: data.profile.writer_name || "Writer",
        siteName: data.profile.site_name || "The Archive",
      });
    } catch {
      /* settings unavailable — keep defaults */
    }
  },
  toasts: [],
  toast: (message, kind = "info") => {
    const id = ++toastId;
    set({ toasts: [...get().toasts, { id, message, kind }] });
    setTimeout(() => get().dismissToast(id), 5000);
  },
  dismissToast: (id) => set({ toasts: get().toasts.filter((t) => t.id !== id) }),
}));

window.addEventListener("popstate", () => {
  useApp.setState({ pane: paneFromURL() });
});
