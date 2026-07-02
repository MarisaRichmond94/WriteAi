import { useEffect } from "react";
import {
  BookOpen,
  Clock,
  Compass,
  Info,
  Kanban,
  Library,
  ScanText,
  Settings as SettingsIcon,
  Users,
} from "lucide-react";
import clsx from "clsx";
import { useApp } from "../store";
import type { Pane } from "../types";
import { Toasts } from "./ui";
import { ExplorePane } from "./panes/ExplorePane";
import { ReviewPane } from "./panes/ReviewPane";
import { TimelinePane } from "./panes/TimelinePane";
import { PlanPane } from "./panes/PlanPane";
import { BooksPane } from "./panes/BooksPane";
import { CharactersPane } from "./panes/CharactersPane";
import { SettingsPane } from "./panes/SettingsPane";

const NAV_GROUPS: { label: string; items: { pane: Pane; label: string; icon: typeof Kanban }[] }[] = [
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
      { pane: "books", label: "Books", icon: Library },
      { pane: "characters", label: "Characters", icon: Users },
    ],
  },
];

function timeOfDay(): string {
  const h = new Date().getHours();
  if (h >= 5 && h < 12) return "Morning";
  if (h < 18) return "Afternoon";
  return "Evening";
}

function Sidebar() {
  const { pane: active, setPane, siteName } = useApp();
  return (
    <aside className="flex h-full w-64 flex-shrink-0 flex-col border-r border-surface-border bg-surface-card">
      <div className="flex items-center gap-2 border-b border-surface-border px-4 py-4">
        <BookOpen className="h-5 w-5 text-accent" strokeWidth={1.5} />
        <div className="flex flex-col">
          <span className="text-sm font-semibold tracking-wide text-ink-primary">{siteName}</span>
          <div className="flex items-center gap-1">
            <span className="text-[10px] text-ink-muted">A RAG-Powered Analysis Hub 📚</span>
            <div className="group relative">
              <Info className="h-2.5 w-2.5 cursor-default text-ink-muted transition-colors hover:text-ink-secondary" strokeWidth={1.5} />
              <div className="pointer-events-none absolute left-0 top-4 z-50 w-64 rounded-md border border-surface-border bg-surface-card px-3 py-2 text-[11px] leading-relaxed text-ink-muted opacity-0 shadow-lg transition-opacity duration-150 group-hover:opacity-100">
                Everything here is derived from your manuscripts — extraction, retrieval, and answers are
                grounded in the books themselves.
              </div>
            </div>
          </div>
        </div>
      </div>
      <nav className="flex flex-col py-2">
        {NAV_GROUPS.map(({ label: groupLabel, items }) => (
          <div key={groupLabel}>
            <p className="px-4 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-widest text-ink-muted">
              {groupLabel}
            </p>
            {items.map(({ pane, label, icon: Icon }) => {
              const isActive = active === pane;
              return (
                <button
                  key={pane}
                  onClick={() => setPane(pane)}
                  className={clsx(
                    "flex w-full items-center gap-3 border-l-2 px-4 py-2.5 text-sm transition-colors",
                    isActive
                      ? "border-accent bg-accent/10 text-accent"
                      : "border-transparent text-ink-secondary hover:bg-surface hover:text-ink-primary",
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
    </aside>
  );
}

export function AppShell() {
  const { pane, setPane, loadBooks, loadProfile, writerName, siteName } = useApp();

  useEffect(() => {
    loadBooks().catch(() => undefined);
    loadProfile();
  }, []);

  useEffect(() => {
    document.title = siteName;
  }, [siteName]);

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden">
      <div className="flex flex-1 overflow-hidden bg-surface font-sans text-ink-primary">
        <Sidebar />
        <main className="relative flex min-w-0 flex-1 flex-col overflow-hidden">
          {/* greeting overlay, matching the reference placement */}
          <div className="absolute right-6 top-5 z-40 flex items-center gap-2">
            <span className="text-xs text-ink-primary">
              Good {timeOfDay()}, {writerName}
            </span>
            <button
              onClick={() => setPane("settings")}
              title="Settings"
              className={clsx(
                "rounded-md p-1 transition-colors",
                pane === "settings" ? "text-accent" : "text-ink-secondary hover:text-ink-primary",
              )}
            >
              <SettingsIcon className="h-4 w-4" strokeWidth={1.5} />
            </button>
            <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center overflow-hidden rounded-full bg-accent/20 text-[10px] font-semibold text-accent ring-1 ring-surface-border">
              {writerName
                .split(/\s+/)
                .slice(0, 2)
                .map((w) => w[0]?.toUpperCase())
                .join("")}
            </div>
          </div>

          {pane === "explore" && <ExplorePane />}
          {pane === "review" && <ReviewPane />}
          {pane === "timeline" && <TimelinePane />}
          {pane === "plan" && <PlanPane />}
          {pane === "books" && <BooksPane />}
          {pane === "characters" && <CharactersPane />}
          {pane === "settings" && <SettingsPane />}
        </main>
      </div>
      <Toasts />
    </div>
  );
}
