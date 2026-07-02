import { useEffect, useState } from "react";
import clsx from "clsx";
import { ChevronRight, Library, RefreshCw, Sparkles } from "lucide-react";
import { useApp } from "../../store";
import type { Book } from "../../types";
import { api } from "../../lib/api";
import { bookColor, povColor } from "../../lib/palette";
import { Button, ConfirmModal, SectionLabel, Spinner } from "../ui";

interface IngestStatus {
  running: boolean;
  finished: boolean;
  exit_code: number | null;
  log_tail: string;
}

interface EnrichStatus {
  state: string;
  done: number;
  total: number;
  cost_usd: number;
}

export function BooksPane() {
  const { books, lastSynced, loadBooks, toast } = useApp();
  const [selected, setSelected] = useState<Book | null>(null);
  const [rebuild, setRebuild] = useState<{ estimated_cost_usd: number; changed_chunks: number } | null>(null);
  const [rebuildBusy, setRebuildBusy] = useState(false);
  const [ingest, setIngest] = useState<IngestStatus | null>(null);
  const [enrichStatus, setEnrichStatus] = useState<EnrichStatus | null>(null);
  const [enrichPreview, setEnrichPreview] = useState<{ estimated_cost_usd: number } | null>(null);

  // poll background jobs while they run
  useEffect(() => {
    const tick = async () => {
      try {
        const [i, e] = await Promise.all([
          api<IngestStatus>("/api/ingest/status"),
          api<EnrichStatus>("/api/enrich/status"),
        ]);
        setIngest(i);
        setEnrichStatus(e);
        if (i.finished || e.state === "done") loadBooks().catch(() => undefined);
      } catch {
        /* server briefly busy */
      }
    };
    tick();
    const id = setInterval(tick, 4000);
    return () => clearInterval(id);
  }, []);

  const startRebuild = async () => {
    setRebuildBusy(true);
    try {
      setRebuild(await api("/api/ingest/preview"));
    } catch (e) {
      toast(String(e), "error");
    } finally {
      setRebuildBusy(false);
    }
  };

  const confirmRebuild = async () => {
    try {
      await api("/api/ingest/run", { method: "POST" });
      toast("Ingestion started", "success");
    } catch (e) {
      toast(String(e), "error");
    }
    setRebuild(null);
  };

  const startEnrich = async () => {
    try {
      setEnrichPreview(await api("/api/enrich/preview"));
    } catch (e) {
      toast(String(e), "error");
    }
  };

  const confirmEnrich = async () => {
    try {
      await api("/api/enrich/run", { method: "POST" });
      toast("Enrichment started", "success");
    } catch (e) {
      toast(String(e), "error");
    }
    setEnrichPreview(null);
  };

  const fmt = (iso: string | null) =>
    iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "never";

  return (
    <div className="flex h-full">
      {/* book list */}
      <div className={clsx("flex min-w-0 flex-col", selected ? "w-1/2" : "flex-1")}>
        <div className="flex items-center justify-between border-b border-surface-border px-6 py-3">
          <div className="text-xs text-ink-secondary">
            Last synced <span className="text-ink-primary">{fmt(lastSynced)}</span>
          </div>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={startEnrich} className="!px-3 !py-1">
              <Sparkles className="h-3.5 w-3.5" strokeWidth={1.5} /> Enrich
            </Button>
            <Button onClick={startRebuild} disabled={rebuildBusy || ingest?.running} className="!px-3 !py-1">
              {rebuildBusy || ingest?.running ? (
                <Spinner className="h-3.5 w-3.5" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" strokeWidth={1.5} />
              )}
              {ingest?.running ? "Ingesting…" : "Sync Books"}
            </Button>
          </div>
        </div>

        {(ingest?.running || (enrichStatus && enrichStatus.state === "running")) && (
          <div className="border-b border-surface-border bg-accent-subtle/40 px-6 py-2 text-[11px] text-ink-secondary">
            {ingest?.running && <span>Ingestion running… </span>}
            {enrichStatus?.state === "running" && (
              <span>
                Enrichment {enrichStatus.done}/{enrichStatus.total} (${enrichStatus.cost_usd.toFixed(2)} spent)
              </span>
            )}
          </div>
        )}

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
          <div className="flex flex-col gap-2">
            {books.map((b) => (
              <button
                key={b.id}
                onClick={() => setSelected(selected?.id === b.id ? null : b)}
                className={clsx(
                  "flex items-center gap-4 rounded-lg border px-4 py-3 text-left transition-colors",
                  selected?.id === b.id
                    ? "border-accent bg-accent/10"
                    : "border-surface-border bg-surface-card hover:bg-surface-hover",
                )}
              >
                <span className={clsx("rounded-full px-2 py-0.5 text-[10px] font-medium", bookColor(b.id))}>
                  Book {b.id}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium text-ink-primary">{b.name}</span>
                  <span className="text-[11px] text-ink-muted">
                    {b.chapter_count} chapters · {b.word_count.toLocaleString()} words
                  </span>
                </span>
                <span className="hidden gap-3 text-[10px] text-ink-secondary sm:flex">
                  <span>{b.stats.characters} chars</span>
                  <span>{b.stats.events} events</span>
                  <span>{b.stats.knowledge_facts} facts</span>
                </span>
                <ChevronRight className="h-4 w-4 text-ink-muted" strokeWidth={1.5} />
              </button>
            ))}
            {books.length === 0 && (
              <div className="py-16 text-center text-xs text-ink-muted">
                <Library className="mx-auto mb-3 h-8 w-8" strokeWidth={1} />
                No books ingested yet — run <code>python ingest.py</code> or press Sync Books.
              </div>
            )}
          </div>
        </div>
      </div>

      {/* book drawer */}
      {selected && (
        <div className="flex w-1/2 flex-col border-l border-surface-border bg-surface-card">
          <div className="border-b border-surface-border px-5 py-4">
            <div className="text-sm font-semibold">{selected.name}</div>
            <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-ink-secondary">
              {Object.entries(selected.stats).map(([k, v]) => (
                <span key={k}>
                  <span className="font-medium text-ink-primary">{v.toLocaleString()}</span> {k.replace(/_/g, " ")}
                </span>
              ))}
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3">
            <SectionLabel>Chapters</SectionLabel>
            <table className="w-full text-left text-[11px]">
              <thead className="text-[9px] uppercase tracking-wider text-ink-muted">
                <tr>
                  <th className="py-1 pr-2 font-medium">#</th>
                  <th className="py-1 pr-2 font-medium">POV</th>
                  <th className="py-1 pr-2 font-medium">Date</th>
                  <th className="py-1 text-right font-medium">Words</th>
                </tr>
              </thead>
              <tbody>
                {selected.chapters.map((c) => {
                  const pc = c.pov ? povColor(c.pov) : null;
                  return (
                    <tr key={c.chapter} className="border-t border-surface-border/60">
                      <td className="py-1.5 pr-2 text-ink-secondary">
                        {c.kind === "prologue" ? "Pro" : c.chapter}
                      </td>
                      <td className="py-1.5 pr-2">
                        {c.pov && pc ? (
                          <span className={clsx("rounded-full px-1.5 py-px text-[9px] ring-1", pc.text, pc.ring, pc.bg)}>
                            {c.pov}
                          </span>
                        ) : (
                          <span className="text-ink-muted">—</span>
                        )}
                      </td>
                      <td className="py-1.5 pr-2 text-ink-muted">{c.date ?? "—"}</td>
                      <td className="py-1.5 text-right text-ink-secondary">{c.word_count.toLocaleString()}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {rebuild && (
        <ConfirmModal
          title="Sync all books?"
          body={
            <p>
              {rebuild.changed_chunks} chunk(s) changed since the last ingest. Estimated cost:{" "}
              <span className="font-semibold text-ink-primary">${rebuild.estimated_cost_usd}</span>. Your
              manuscript files are read-only throughout.
            </p>
          }
          confirmLabel={rebuild.changed_chunks ? `Spend ~$${rebuild.estimated_cost_usd}` : "Run anyway"}
          onConfirm={confirmRebuild}
          onClose={() => setRebuild(null)}
        />
      )}
      {enrichPreview && (
        <ConfirmModal
          title="Run enrichment?"
          body={
            <p>
              Derives timeline events and character profiles from already-extracted metadata. Estimated cost:{" "}
              <span className="font-semibold text-ink-primary">${enrichPreview.estimated_cost_usd}</span>.
              Only changed chapters are re-processed.
            </p>
          }
          confirmLabel={`Spend ~$${enrichPreview.estimated_cost_usd}`}
          onConfirm={confirmEnrich}
          onClose={() => setEnrichPreview(null)}
        />
      )}
    </div>
  );
}
