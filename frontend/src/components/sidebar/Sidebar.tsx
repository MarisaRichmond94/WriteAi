import { Compass, Clock, Library, MapPin, Users, Kanban, PenLine, ScanText, FlaskConical, DollarSign } from "lucide-react";
import { FaTimeline } from "react-icons/fa6";
import { clsx } from "clsx";
import { useAppStore } from "../../store/useAppStore";
import ChatHistory from "./ChatHistory";
import PipelineStatusBar from "./PipelineStatusBar";
import ReviewHistory from "./ReviewHistory";

const NAV_GROUPS = [
  {
    label: "Tools",
    items: [
      { pane: "plan", label: "Plan", icon: Kanban },
      { pane: "writer-timeline", label: "Timeline", icon: FaTimeline },
      // Not a pane — jumps to the companion Loom app (see the map below).
      { pane: "loom-write", label: "Write", icon: PenLine },
      { pane: "review", label: "Review", icon: ScanText },
      { pane: "explore", label: "Explore", icon: Compass },
    ],
  },
  {
    label: "Insights",
    items: [
      { pane: "status", label: "Books", icon: Library },
      { pane: "characters", label: "Characters", icon: Users },
      { pane: "timeline", label: "Events", icon: Clock },
      { pane: "locations", label: "Locations", icon: MapPin },
      { pane: "spend", label: "Spend", icon: DollarSign },
    ],
  },
] as const;

export default function Sidebar({ collapsed = false }: { collapsed?: boolean }) {
  const { activePane, setActivePane, siteName } = useAppStore();

  return (
    <aside
      className={clsx(
        "flex h-full flex-shrink-0 flex-col overflow-hidden bg-surface-card transition-[width] duration-300 ease-in-out",
        collapsed ? "w-0 border-r-0" : "w-64 border-r border-surface-border"
      )}
    >
      {/* Identity block deleted (KAN-7): the logo, site name, tagline and the
          ⓘ RAG explainer all lived here. Brand moved to the header, matching
          Loom, and the sidebar is now navigation only — as Loom's already is.

          The tagline and explainer were removed rather than rehomed. Under the
          new model the text in that header slot becomes a project name rather
          than a site name, so a product tagline beneath it would read as
          nonsense. Writer's call.

          siteName is still used below, for the Loom jump URL. */}

      {/* Nav */}
      <nav className="flex flex-col py-2">
        {NAV_GROUPS.map(({ label: groupLabel, items }) => (
          <div key={groupLabel}>
            <p className="px-4 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-widest text-ink-muted">
              {groupLabel}
            </p>
            {items.map(({ pane, label, icon: Icon }) => {
              // "Write" is an external jump into Loom rather than a pane.
              // Loom resolves the series by name (our site name) and lands
              // on its author view; same tab so Back returns here.
              if (pane === "loom-write") {
                const loomUrl = import.meta.env.VITE_LOOM_URL ?? "http://localhost:3000";
                return (
                  <a
                    key={pane}
                    href={`${loomUrl}/author/by-title/${encodeURIComponent(siteName)}`}
                    className="flex w-full items-center gap-3 border-l-2 border-transparent px-4 py-2.5 text-sm text-ink-secondary transition-colors hover:bg-surface hover:text-ink-primary"
                  >
                    <Icon className="h-4 w-4 flex-shrink-0" strokeWidth={1.5} />
                    {label}
                  </a>
                );
              }
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

      <PipelineStatusBar />
    </aside>
  );
}
