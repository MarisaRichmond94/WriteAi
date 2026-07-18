import { useState, useCallback, useEffect } from "react";
import { Info, Compass } from "lucide-react";
import FilterBar from "./FilterBar";
import MessageList from "./MessageList";
import ChatInput from "./ChatInput";
import ChapterViewer from "./ChapterViewer";
import type { Citation } from "../../types";
import { useAppStore } from "../../store/useAppStore";

function bookIdFromName(name: string): string {
  return name.toLowerCase().replace(/'/g, "").replace(/ /g, "-");
}

export default function ChatPane() {
  const { exploreViewerCloseSignal, saveChatAndClear, setLiveChatSessionId, selectedBooks, selectedPovs, queryMode } = useAppStore();
  const [activeCitation, setActiveCitation] = useState<Citation | null>(null);
  const [viewerOpen, setViewerOpen] = useState(false);
  const [lightMode, setLightMode] = useState(() => useAppStore.getState().appSettings?.viewer_light_mode ?? true);
  const [inputValue, setInputValue] = useState("");

  useEffect(() => {
    if (!exploreViewerCloseSignal) return;
    setViewerOpen(false);
    setTimeout(() => setActiveCitation(null), 300);
  }, [exploreViewerCloseSignal]);

  // Clear conversation and filter params when navigating away
  useEffect(() => {
    return () => {
      saveChatAndClear();
      setLiveChatSessionId(null);
      const p = new URLSearchParams(window.location.search);
      p.delete("books");
      p.delete("povs");
      p.delete("mode");
      const qs = p.toString();
      history.replaceState(null, "", qs ? `?${qs}` : window.location.pathname);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Sync filters → URL
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (selectedBooks.size > 0) params.set("books", [...selectedBooks].join(","));
    else params.delete("books");
    history.replaceState(null, "", `?${params}`);
  }, [selectedBooks]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (selectedPovs.size > 0) params.set("povs", [...selectedPovs].join(","));
    else params.delete("povs");
    history.replaceState(null, "", `?${params}`);
  }, [selectedPovs]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (queryMode !== "general") params.set("mode", queryMode);
    else params.delete("mode");
    history.replaceState(null, "", `?${params}`);
  }, [queryMode]);

  const handleCitationClick = useCallback((citation: Citation) => {
    const key = (c: Citation) => `${c.book}__${c.chapter}__${c.chunk_index}`;
    if (viewerOpen && activeCitation && key(activeCitation) === key(citation)) {
      setViewerOpen(false);
      setTimeout(() => setActiveCitation(null), 300);
    } else {
      setActiveCitation(citation);
      setViewerOpen(true);
    }
  }, [activeCitation, viewerOpen]);

  const handleClose = useCallback(() => {
    setViewerOpen(false);
    setTimeout(() => setActiveCitation(null), 300);
  }, []);

  return (
    <div className="flex flex-1 flex-col overflow-hidden">

      {/* Title block */}
      <div className="flex-shrink-0 px-6 pt-4 pb-3">
        <div className="flex items-center gap-2">
          <Compass className="h-6 w-6 flex-shrink-0 text-accent" />
          <div>
            <div className="flex items-center gap-2">
              <p className="text-xs font-semibold uppercase tracking-widest text-ink-primary">Explore</p>
              <div className="group relative">
                <Info className="h-3.5 w-3.5 cursor-default text-ink-muted transition-colors hover:text-ink-secondary" />
                <div className="pointer-events-none absolute left-0 top-5 z-50 w-72 rounded-md border border-surface-border bg-surface-card px-3 py-2 text-[11px] leading-relaxed text-ink-muted shadow-lg opacity-0 transition-opacity duration-150 group-hover:opacity-100">
                  Ask AI questions about your book series. Filter by POV, book, or query mode to focus the response.
                </div>
              </div>
            </div>
            <p className="mt-0.5 text-[11px] text-ink-muted">
              Ask AI anything about your series, grounded in extracted knowledge
            </p>
          </div>
        </div>
        <div className="mt-3 border-t border-surface-border" />
      </div>

      <FilterBar />

      {/* Middle area: horizontal split when viewer is open */}
      <div className="flex flex-1 min-h-0 pt-2">

        {/* Message list — narrows from 100% → 60% when viewer opens */}
        <div
          className={`flex flex-col min-h-0 transition-[width] duration-300 ease-in-out overflow-hidden ${
            viewerOpen ? "w-[60%]" : "w-full"
          }`}
        >
          <MessageList onCitationClick={handleCitationClick} activeCitation={activeCitation} />
        </div>

        {/* Chapter viewer — grows from 0 → 40% when viewer opens */}
        <div
          className={`transition-[width] duration-300 ease-in-out overflow-hidden rounded-tl-[8px] ${
            viewerOpen ? "w-[40%]" : "w-0"
          }`}
        >
          {activeCitation && (
            <ChapterViewer
              citation={activeCitation}
              bookId={bookIdFromName(activeCitation.book)}
              onClose={handleClose}
              lightMode={lightMode}
              onToggleLightMode={() => setLightMode((v) => !v)}
            />
          )}
        </div>

      </div>

      <ChatInput value={inputValue} onChange={setInputValue} />
    </div>
  );
}
