import { useEffect } from "react";
import {
  BookOpen,
  Clock,
  Compass,
  Kanban,
  Library,
  ScanText,
  Settings,
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

const TOOLS: { pane: Pane; label: string; icon: typeof Kanban }[] = [
  { pane: "plan", label: "Plan", icon: Kanban },
  { pane: "review", label: "Review", icon: ScanText },
  { pane: "explore", label: "Explore", icon: Compass },
  { pane: "timeline", label: "Timeline", icon: Clock },
];

const INSIGHTS: { pane: Pane; label: string; icon: typeof Library }[] = [
  { pane: "books", label: "Books", icon: Library },
  { pane: "characters", label: "Characters", icon: Users },
];

function NavItem({ pane, label, icon: Icon }: { pane: Pane; label: string; icon: typeof Kanban }) {
  const { pane: active, setPane } = useApp();
  const isActive = active === pane;
  return (
    <button
      onClick={() => setPane(pane)}
      className={clsx(
        "flex w-full items-center gap-2.5 border-l-2 px-4 py-2 text-left text-[13px] transition-colors duration-150",
        isActive
          ? "border-accent bg-accent/10 font-medium text-accent"
          : "border-transparent text-ink-secondary hover:bg-surface hover:text-ink-primary",
      )}
    >
      <Icon className="h-4 w-4" strokeWidth={1.5} />
      {label}
    </button>
  );
}

function greeting(): string {
  const h = new Date().getHours();
  return h < 12 ? "Good Morning" : h < 18 ? "Good Afternoon" : "Good Evening";
}

export function AppShell() {
  const { pane, setPane, loadBooks, loadProfile, writerName, siteName } = useApp();

  useEffect(() => {
    loadBooks().catch(() => undefined);
    loadProfile();
  }, []);

  return (
    <div className="flex h-screen w-screen flex-col bg-surface font-sans text-ink-primary">
      <div className="flex min-h-0 flex-1">
        {/* sidebar */}
        <aside className="flex w-64 shrink-0 flex-col border-r border-surface-border bg-surface-card">
          <div className="flex items-center gap-2.5 px-4 py-5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-subtle">
              <BookOpen className="h-4.5 w-4.5 h-5 w-5 text-accent" strokeWidth={1.5} />
            </div>
            <div>
              <div className="text-sm font-semibold">{siteName}</div>
              <div className="text-[10px] text-ink-muted">Series intelligence</div>
            </div>
          </div>
          <nav className="mt-2 flex flex-col gap-0.5">
            <div className="px-4 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-widest text-ink-muted">
              Tools
            </div>
            {TOOLS.map((t) => (
              <NavItem key={t.pane} {...t} />
            ))}
            <div className="px-4 pb-1 pt-4 text-[10px] font-semibold uppercase tracking-widest text-ink-muted">
              Insights
            </div>
            {INSIGHTS.map((t) => (
              <NavItem key={t.pane} {...t} />
            ))}
          </nav>
        </aside>

        {/* main area */}
        <main className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-14 shrink-0 items-center justify-between border-b border-surface-border px-6">
            <div className="text-sm text-ink-secondary">
              {greeting()}, <span className="font-medium text-ink-primary">{writerName}</span>
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={() => setPane("settings")}
                className={clsx(
                  "rounded-md p-1.5 transition-colors",
                  pane === "settings" ? "text-accent" : "text-ink-secondary hover:text-ink-primary",
                )}
                title="Settings"
              >
                <Settings className="h-4 w-4" strokeWidth={1.5} />
              </button>
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-accent-subtle text-xs font-semibold text-accent">
                {writerName
                  .split(/\s+/)
                  .slice(0, 2)
                  .map((w) => w[0]?.toUpperCase())
                  .join("")}
              </div>
            </div>
          </header>
          <div className="min-h-0 flex-1">
            {pane === "explore" && <ExplorePane />}
            {pane === "review" && <ReviewPane />}
            {pane === "timeline" && <TimelinePane />}
            {pane === "plan" && <PlanPane />}
            {pane === "books" && <BooksPane />}
            {pane === "characters" && <CharactersPane />}
            {pane === "settings" && <SettingsPane />}
          </div>
        </main>
      </div>
      <Toasts />
    </div>
  );
}
