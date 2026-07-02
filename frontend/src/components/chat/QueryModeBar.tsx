import { clsx } from "clsx";
import { useAppStore } from "../../store/useAppStore";
import type { QueryMode } from "../../types";

interface ModeConfig {
  id: QueryMode;
  label: string;
  description: string;
  color: string;
  activeColor: string;
}

const MODES: ModeConfig[] = [
  {
    id: "plot_hole",
    label: "Plot Holes",
    description: "Find continuity errors and contradictions",
    color: "border-mode-plot/30 text-mode-plot/70 hover:border-mode-plot hover:text-mode-plot",
    activeColor: "border-mode-plot bg-mode-plot/10 text-mode-plot",
  },
  {
    id: "timeline",
    label: "Timeline",
    description: "Trace chronological events",
    color: "border-mode-timeline/30 text-mode-timeline/70 hover:border-mode-timeline hover:text-mode-timeline",
    activeColor: "border-mode-timeline bg-mode-timeline/10 text-mode-timeline",
  },
  {
    id: "character",
    label: "Characters",
    description: "Track character arcs and knowledge",
    color: "border-mode-character/30 text-mode-character/70 hover:border-mode-character hover:text-mode-character",
    activeColor: "border-mode-character bg-mode-character/10 text-mode-character",
  },
  {
    id: "alternate",
    label: "Alternate",
    description: "Explore what-if scenarios",
    color: "border-mode-alternate/30 text-mode-alternate/70 hover:border-mode-alternate hover:text-mode-alternate",
    activeColor: "border-mode-alternate bg-mode-alternate/10 text-mode-alternate",
  },
];

export default function QueryModeBar() {
  const { queryMode, setQueryMode } = useAppStore();

  return (
    <div className="flex items-center gap-2 px-4 py-3 border-b border-surface-border">
      <span className="text-[10px] uppercase tracking-widest text-ink-muted mr-1">
        Mode
      </span>
      {MODES.map((mode) => (
        <button
          key={mode.id}
          title={mode.description}
          onClick={() => setQueryMode(mode.id)}
          className={clsx(
            "rounded-full border px-3 py-1 text-xs font-medium transition-all",
            queryMode === mode.id ? mode.activeColor : mode.color
          )}
        >
          {mode.label}
        </button>
      ))}
    </div>
  );
}
