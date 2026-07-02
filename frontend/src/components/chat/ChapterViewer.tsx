import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { BookOpen, ChevronLeft, Moon, Sun } from "lucide-react";
import { clsx } from "clsx";
import type { Citation } from "../../types";
import { fetchChapterText } from "../../api/books";

const POV_PALETTE = [
  { bg: "bg-rose-500/25",    text: "text-rose-300",    ring: "ring-rose-500/40"    },
  { bg: "bg-sky-500/25",     text: "text-sky-300",     ring: "ring-sky-500/40"     },
  { bg: "bg-violet-500/25",  text: "text-violet-300",  ring: "ring-violet-500/40"  },
  { bg: "bg-amber-500/25",   text: "text-amber-300",   ring: "ring-amber-500/40"   },
  { bg: "bg-teal-500/25",    text: "text-teal-300",    ring: "ring-teal-500/40"    },
  { bg: "bg-fuchsia-500/25", text: "text-fuchsia-300", ring: "ring-fuchsia-500/40" },
];

function povColor(pov: string) {
  let hash = 0;
  for (let i = 0; i < pov.length; i++) hash = (hash * 31 + pov.charCodeAt(i)) & 0xffff;
  return POV_PALETTE[hash % POV_PALETTE.length];
}

interface Props {
  citation: Citation;
  bookId: string;
  lightMode: boolean;
  onToggleLightMode: () => void;
  onClose?: () => void;
  onBack?: () => void;
}

// Strip s to lowercase alphanumeric only and return a map from stripped index →
// original index. This lets us locate a snippet in chapter text regardless of
// typography differences (em dash vs --, ellipsis vs ..., curly vs straight
// quotes, extra spaces, etc.) and then map back to the original text boundaries
// for an exact highlight.
function buildStrippedMap(s: string): { stripped: string; map: number[] } {
  let stripped = "";
  const map: number[] = [];
  for (let i = 0; i < s.length; i++) {
    const c = s[i].toLowerCase();
    if (/[a-z0-9]/.test(c)) {
      stripped += c;
      map.push(i);
    }
  }
  return { stripped, map };
}

export default function ChapterViewer({ citation, bookId, lightMode, onToggleLightMode, onClose, onBack }: Props) {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const highlightRef = useRef<HTMLElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const prevChapterKeyRef = useRef<string | null>(null);

  useEffect(() => {
    setText(null);
    setError(null);
    const controller = new AbortController();
    fetchChapterText(bookId, citation.chapter, citation.snippet)
      .then((t) => { if (!controller.signal.aborted) setText(t); })
      .catch((e: Error) => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [bookId, citation.chapter]);

  const scrollBehaviorRef = useRef<ScrollBehavior>("instant");

  const scrollToMark = useCallback(() => {
    const container = scrollContainerRef.current;
    const mark = highlightRef.current;
    if (!container || !mark) return;
    const markRect = mark.getBoundingClientRect();
    const markTop = markRect.top - container.getBoundingClientRect().top + container.scrollTop;
    const target = Math.max(0, markTop - container.clientHeight / 2 + markRect.height / 2);
    container.scrollTo({ top: target, behavior: scrollBehaviorRef.current });
  }, []);

  useLayoutEffect(() => {
    const chapterKey = `${bookId}::${citation.chapter}`;
    const chapterChanged = prevChapterKeyRef.current !== chapterKey;
    prevChapterKeyRef.current = chapterKey;
    if (!text) return;
    scrollBehaviorRef.current = chapterChanged ? "instant" : "smooth";
    scrollToMark();
  }, [text, citation.snippet, scrollToMark]);

  useEffect(() => {
    if (!text) return;
    const container = scrollContainerRef.current;
    if (!container) return;
    let rafId: number | null = null;
    const observer = new ResizeObserver(() => {
      if (rafId !== null) cancelAnimationFrame(rafId);
      rafId = requestAnimationFrame(() => {
        rafId = null;
        scrollToMark();
      });
    });
    observer.observe(container);
    return () => {
      observer.disconnect();
      if (rafId !== null) cancelAnimationFrame(rafId);
    };
  }, [text, scrollToMark]);

  const renderText = () => {
    if (!text) return null;

    const baseClass = clsx(
      "text-sm leading-relaxed whitespace-pre-wrap",
      lightMode ? "text-gray-700" : "text-ink-secondary"
    );

    const snippet = citation.snippet;
    if (!snippet) return <p className={baseClass}>{text}</p>;

    const { stripped: textStripped, map: textMap } = buildStrippedMap(text);
    const { stripped: snippetStripped } = buildStrippedMap(snippet);
    if (!snippetStripped) return <p className={baseClass}>{text}</p>;

    const strippedIdx = textStripped.indexOf(snippetStripped);
    if (strippedIdx === -1) return <p className={baseClass}>{text}</p>;

    const originalStart = textMap[strippedIdx];
    const originalEnd = textMap[strippedIdx + snippetStripped.length - 1] + 1;

    return (
      <p className={baseClass}>
        {text.slice(0, originalStart)}
        <mark
          ref={highlightRef as React.RefObject<HTMLElement>}
          className={clsx(
            "rounded-sm px-0.5 not-italic",
            lightMode
              ? "bg-yellow-200 text-gray-900"
              : "bg-yellow-300/25 text-ink-primary"
          )}
        >
          {text.slice(originalStart, originalEnd)}
        </mark>
        {text.slice(originalEnd)}
      </p>
    );
  };

  const pov = citation.pov ? povColor(citation.pov) : null;

  return (
    <div className={clsx("flex h-full flex-col border-l border-t border-surface-border shadow-2xl rounded-tl-lg overflow-hidden", lightMode ? "bg-white" : "bg-surface-card")}>
      {/* Header — always dark */}
      <div className="flex-shrink-0 flex items-start gap-3 px-5 pt-6 pb-4 border-b border-surface-border bg-surface-card">
        {onBack && (
          <button
            onClick={onBack}
            title="Back to character"
            className="mt-0.5 flex-shrink-0 rounded-md p-1 text-ink-muted hover:bg-surface-hover hover:text-ink-primary transition-colors"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
        )}
        <BookOpen className="mt-1 h-6 w-6 flex-shrink-0 text-accent" />
        <div className="flex-1 min-w-0">
          {/* Row 1: title + POV pill */}
          <div className="flex items-center gap-4 flex-wrap">
            <p className="text-base font-semibold text-ink-primary truncate">{citation.book}</p>
            {pov && (
              <span className={clsx("inline-flex items-center rounded-full px-1.5 py-px text-[9px] font-medium ring-1", pov.bg, pov.text, pov.ring)}>
                {citation.pov}
              </span>
            )}
          </div>
          {/* Row 2: chapter */}
          <p className="mt-1.5 text-[11px] text-ink-muted">
            {citation.chapter === 0 ? "Prologue" : `Chapter ${citation.chapter}`}
            {citation.chapter_heading !== String(citation.chapter) &&
              ` · "${citation.chapter_heading}"`}
          </p>
          {/* Row 3: date */}
          {citation.date && (
            <p className="mt-0.5 text-[11px] text-ink-muted">{citation.date}</p>
          )}
        </div>

        {/* Right controls */}
        <div className="flex items-center gap-1">
          <button
            onClick={onToggleLightMode}
            title={lightMode ? "Switch to dark mode" : "Switch to light mode"}
            className="rounded-md p-1.5 text-ink-muted hover:bg-surface-hover hover:text-ink-primary transition-colors"
          >
            {lightMode ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}
          </button>
        </div>
      </div>

      {/* Content */}
      <div ref={scrollContainerRef} className="flex-1 min-h-0 overflow-y-auto px-6 py-5 select-text cursor-default">
        {error ? (
          <p className="text-sm text-red-400">{error}</p>
        ) : text === null ? (
          <p className={clsx("text-sm animate-pulse", lightMode ? "text-gray-400" : "text-ink-muted")}>Loading chapter...</p>
        ) : (
          renderText()
        )}
      </div>
    </div>
  );
}
