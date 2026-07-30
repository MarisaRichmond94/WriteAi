import { useState, useCallback, useEffect } from "react";

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
