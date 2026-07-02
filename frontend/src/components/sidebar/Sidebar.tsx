import { BookOpen, Compass, Clock, Library, Users, Info, Kanban, ScanText, FlaskConical } from "lucide-react";
import { clsx } from "clsx";
import { useAppStore } from "../../store/useAppStore";
import ChatHistory from "./ChatHistory";
import ReviewHistory from "./ReviewHistory";

const NAV_GROUPS = [
  {
    label: "Tools",
    items: [
      { pane: "plan", label: "Plan", icon: Kanban },
      { pane: "review", label: "Review", icon: ScanText },
      { pane: "explore", label: "Explore", icon: Compass },
      { pane: "timeline", label: "Timeline", icon: Clock },
    ],
  },
  {
    label: "Insights",
    items: [
      { pane: "status", label: "Books", icon: Library },
      { pane: "characters", label: "Characters", icon: Users },
    ],
  },
] as const;

export default function Sidebar() {
  const { activePane, setActivePane, siteName } = useAppStore();

  return (
    <aside className="flex h-full w-64 flex-shrink-0 flex-col border-r border-surface-border bg-surface-card">
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-surface-border px-4 py-4">
        <BookOpen className="h-5 w-5 text-accent" strokeWidth={1.5} />
        <div className="flex flex-col">
          <span className="text-sm font-semibold tracking-wide text-ink-primary">
            {siteName}
          </span>
          <div className="flex items-center gap-1">
            <span className="text-[10px] text-ink-muted">
              A RAG-Powered Analysis Hub
            </span>
            <div className="group relative">
              <Info className="h-2.5 w-2.5 text-ink-muted hover:text-ink-secondary transition-colors cursor-default" />
              <div className="pointer-events-none absolute left-0 top-4 z-50 w-64 rounded-md border border-surface-border bg-surface-card px-3 py-2 text-[11px] leading-relaxed text-ink-muted shadow-lg opacity-0 group-hover:opacity-100 transition-opacity duration-150">
                This app uses Retrieval-Augmented Generation (RAG) — when you ask a question, it searches a pre-built index of your books to find the most relevant passages, then feeds those directly to an AI to generate a grounded, accurate answer. Rather than relying on the AI's general knowledge, every response is anchored to your actual text.
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex flex-col py-2">
        {NAV_GROUPS.map(({ label: groupLabel, items }) => (
          <div key={groupLabel}>
            <p className="px-4 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-widest text-ink-muted">
              {groupLabel}
            </p>
            {items.map(({ pane, label, icon: Icon }) => {
              const active = activePane === pane;
              return (
                <button
                  key={pane}
                  onClick={() => setActivePane(pane)}
                  className={clsx(
                    "flex w-full items-center gap-3 px-4 py-2.5 text-sm transition-colors",
                    active
                      ? "border-l-2 border-accent bg-accent/10 text-accent"
                      : "border-l-2 border-transparent text-ink-secondary hover:bg-surface hover:text-ink-primary"
                  )}
                >
                  <Icon className="h-4 w-4 flex-shrink-0" strokeWidth={1.5} />
                  {label}
                </button>
              );
            })}
          </div>
        ))}
      </nav>

      {/* Push chat history to the bottom */}
      <div className="flex-1" />

      {/* History panels — visible on their respective pages */}
      {activePane === "explore" && <ChatHistory />}
      {activePane === "review" && <ReviewHistory />}

    </aside>
  );
}
