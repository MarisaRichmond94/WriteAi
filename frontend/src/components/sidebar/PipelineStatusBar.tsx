import { useEffect, useState } from "react";
import { RefreshCw, Sparkles } from "lucide-react";
import { useAppStore } from "../../store/useAppStore";

const POLL_MS = 8000;

interface EnrichStatus {
  state: string;
  done: number;
  total: number;
  cost_usd: number;
}

/** Slim always-visible-while-running indicator pinned to the sidebar bottom:
 * indeterminate shimmer while a sync (ingest) runs, a real progress bar while
 * enrichment runs. Hidden entirely when both are idle. */
export default function PipelineStatusBar() {
  const { setActivePane } = useAppStore();
  const [ingestRunning, setIngestRunning] = useState(false);
  const [enrich, setEnrich] = useState<EnrichStatus | null>(null);

  useEffect(() => {
    let alive = true;
    async function poll() {
      try {
        const [ing, enr] = await Promise.all([
          fetch("/api/ingest/status").then((r) => (r.ok ? r.json() : null)),
          fetch("/api/enrich/status").then((r) => (r.ok ? r.json() : null)),
        ]);
        if (!alive) return;
        setIngestRunning(Boolean(ing?.running));
        setEnrich(enr && enr.state === "running" ? enr : null);
      } catch {
        /* server briefly away — keep the last known state */
      }
    }
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  if (!ingestRunning && !enrich) return null;
  const pct = enrich && enrich.total > 0
    ? Math.round((enrich.done / enrich.total) * 100)
    : 0;

  return (
    <button
      onClick={() => setActivePane("status")}
      title="View the Books page"
      className="w-full flex-shrink-0 border-t border-surface-border bg-surface-card px-4 py-3 text-left transition-colors hover:bg-surface-hover"
    >
      {ingestRunning && (
        <div>
          <div className="flex items-center gap-1.5 text-[10px] font-medium text-ink-secondary">
            <RefreshCw className="h-3 w-3 animate-spin text-accent" />
            Syncing books…
          </div>
          <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-surface-border">
            <div className="animate-indeterminate h-full w-1/3 rounded-full bg-accent" />
          </div>
        </div>
      )}
      {enrich && (
        <div className={ingestRunning ? "mt-2.5" : undefined}>
          <div className="flex items-center justify-between text-[10px] font-medium text-ink-secondary">
            <span className="flex items-center gap-1.5">
              <Sparkles className="h-3 w-3 text-accent" />
              Enriching insights
            </span>
            <span className="text-ink-muted">
              {enrich.done}/{enrich.total} · {pct}%
            </span>
          </div>
          <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-surface-border">
            <div
              className="h-full rounded-full bg-accent transition-all duration-700"
              style={{ width: `${Math.max(pct, 2)}%` }}
            />
          </div>
        </div>
      )}
    </button>
  );
}
