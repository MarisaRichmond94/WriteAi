import { useEffect, useState } from "react";
import clsx from "clsx";
import { BookOpen, ChevronRight, Library, RefreshCw, Sparkles } from "lucide-react";
import { useApp } from "../../store";
import type { Book } from "../../types";
import { api } from "../../lib/api";
import { povColor } from "../../lib/palette";
import { ConfirmModal, Spinner } from "../ui";
import { FooterAction, PaneHeader } from "../shared";

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
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [rebuild, setRebuild] = useState<{ estimated_cost_usd: number; changed_chunks: number } | null>(null);
  const [rebuildBusy, setRebuildBusy] = useState(false);
  const [ingest, setIngest] = useState<IngestStatus | null>(null);
  const [enrichStatus, setEnrichStatus] = useState<EnrichStatus | null>(null);
  const [enrichPreview, setEnrichPreview] = useState<{ estimated_cost_usd: number } | null>(null);

  const selected = books.find((b) => b.id === selectedId) ?? null;
  const totalChunks = books.reduce((n, b) => n + b.chunk_count, 0);

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
        /* transient */
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

  const startEnrich = async () => {
    try {
      setEnrichPreview(await api("/api/enrich/preview"));
    } catch (e) {
      toast(String(e), "error");
    }
  };

  const fmt = (iso: string | null) =>
    iso
      ? new Date(iso).toLocaleString(undefined, { month: "long", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" })
      : "never";

  return (
    <div className="flex h-full flex-col">
      <PaneHeader
        icon={Library}
        title="Books"
        info="Everything the pipeline has extracted per book. Sync re-ingests changed chapters; Enrich refreshes timeline events and character profiles."
        subtitle="Click on a book to view expanded details showing the insights that has been extracted"
      />

      {(ingest?.running || enrichStatus?.state === "running") && (
        <div className="mx-6 mb-2 flex-shrink-0 rounded-md border border-accent/30 bg-accent-subtle/40 px-4 py-2 text-[11px] text-ink-secondary">
          {ingest?.running && <span>Ingestion running… </span>}
          {enrichStatus?.state === "running" && (
            <span>
              Enrichment {enrichStatus.done}/{enrichStatus.total} (${enrichStatus.cost_usd.toFixed(2)} spent)
            </span>
          )}
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        {/* book accordion list */}
        <div className={clsx("flex min-w-0 flex-col overflow-y-auto px-6 py-1", selected ? "w-[40%]" : "flex-1")}>
          <div className="flex flex-col gap-2.5">
            {books.map((b) => (
              <button
                key={b.id}
                onClick={() => setSelectedId(selectedId === b.id ? null : b.id)}
                className={clsx(
                  "flex items-center gap-3 rounded-lg border px-4 py-3 transition-colors",
                  selectedId === b.id
                    ? "border-accent/50 bg-accent/10"
                    : "border-surface-border bg-surface-card hover:bg-surface-hover",
                )}
              >
                <BookOpen className="h-4 w-4 flex-shrink-0 text-ink-secondary" strokeWidth={1.5} />
                <span className="min-w-0 flex-1 truncate text-left text-[11px] font-semibold uppercase tracking-widest text-ink-primary">
                  {b.name}
                </span>
                <ChevronRight
                  className={clsx("h-4 w-4 flex-shrink-0 text-ink-muted transition-transform", selectedId === b.id && "rotate-90")}
                  strokeWidth={1.5}
                />
              </button>
            ))}
            {books.length === 0 && (
              <div className="py-16 text-center text-xs text-ink-muted">
                No books ingested yet — press Rebuild Index below.
              </div>
            )}
          </div>
        </div>

        {/* book drawer */}
        {selected && (
          <div className="flex min-h-0 flex-1 flex-col overflow-y-auto border-l border-surface-border bg-surface-card">
            <div className="flex gap-5 border-b border-surface-border px-6 py-5">
              <BookCover book={selected} />
              <div className="min-w-0 flex-1">
                <div className="flex items-start justify-between gap-3">
                  <h2 className="text-lg font-bold text-ink-primary">{selected.name}</h2>
                  <button
                    onClick={startRebuild}
                    className="flex-shrink-0 rounded border border-surface-border px-2.5 py-1 text-[10px] text-ink-secondary transition-colors hover:border-accent hover:text-ink-primary"
                  >
                    Resync Book
                  </button>
                </div>
                <div className="mt-3 grid grid-cols-3 gap-2">
                  {[
                    { label: "Chapters", value: selected.chapter_count },
                    { label: "Characters", value: selected.stats.characters },
                    { label: "Locations", value: selected.stats.locations },
                    { label: "Events", value: selected.stats.events },
                    { label: "Facts", value: selected.stats.knowledge_facts },
                    { label: "Open questions", value: selected.stats.open_questions },
                  ].map((s) => (
                    <div key={s.label} className="rounded-md border border-surface-border bg-surface px-3 py-2 text-center">
                      <div className="text-sm font-bold text-ink-primary">{s.value?.toLocaleString() ?? 0}</div>
                      <div className="text-[9px] uppercase tracking-wider text-ink-muted">{s.label}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
            <div className="flex flex-col px-4 py-3">
              {selected.chapters.map((c) => {
                const pc = c.pov ? povColor(c.pov) : null;
                return (
                  <div
                    key={c.chapter}
                    className="flex items-center gap-3 border-b border-surface-border/50 px-2 py-2 text-[12px] last:border-0"
                  >
                    <span className="w-24 flex-shrink-0 font-medium text-ink-primary">
                      {c.kind === "prologue" ? "Prologue" : `Chapter ${c.chapter}`}
                    </span>
                    <span className="rounded bg-emerald-400/15 px-1.5 py-px text-[9px] font-semibold uppercase tracking-wide text-emerald-300">
                      Synced
                    </span>
                    {c.pov && pc && (
                      <span className={clsx("rounded-full px-1.5 py-px text-[9px] font-medium ring-1", pc.text, pc.ring, pc.bg)}>
                        {c.pov}
                      </span>
                    )}
                    <span className="flex-1" />
                    <span className="text-[10px] text-ink-muted">{c.date ?? ""}</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>

      <FooterAction
        status={
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-400" />
            {totalChunks.toLocaleString()} chunks indexed · last synced {fmt(lastSynced)}
          </span>
        }
      >
        <div className="flex items-center justify-center gap-2">
          <button
            onClick={startRebuild}
            disabled={rebuildBusy || ingest?.running}
            className="flex items-center justify-center gap-2 rounded-md border border-surface-border px-6 py-1.5 text-[11px] text-ink-secondary transition-colors hover:border-accent hover:text-ink-primary disabled:opacity-40"
          >
            {rebuildBusy || ingest?.running ? <Spinner className="h-3 w-3" /> : <RefreshCw className="h-3 w-3" strokeWidth={1.5} />}
            {ingest?.running ? "Ingesting…" : "Rebuild Index"}
          </button>
          <button
            onClick={startEnrich}
            className="flex items-center justify-center gap-2 rounded-md border border-surface-border px-6 py-1.5 text-[11px] text-ink-secondary transition-colors hover:border-accent hover:text-ink-primary"
          >
            <Sparkles className="h-3 w-3" strokeWidth={1.5} /> Enrich
          </button>
        </div>
      </FooterAction>

      {rebuild && (
        <ConfirmModal
          title="Sync books?"
          body={
            <p>
              {rebuild.changed_chunks} chunk(s) changed since the last ingest. Estimated cost:{" "}
              <span className="font-semibold text-ink-primary">${rebuild.estimated_cost_usd}</span>. Your
              manuscript files are read-only throughout.
            </p>
          }
          confirmLabel={rebuild.changed_chunks ? `Spend ~$${rebuild.estimated_cost_usd}` : "Run anyway"}
          onConfirm={async () => {
            await api("/api/ingest/run", { method: "POST" }).catch((e) => toast(String(e), "error"));
            toast("Ingestion started", "success");
            setRebuild(null);
          }}
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
          onConfirm={async () => {
            await api("/api/enrich/run", { method: "POST" }).catch((e) => toast(String(e), "error"));
            toast("Enrichment started", "success");
            setEnrichPreview(null);
          }}
          onClose={() => setEnrichPreview(null)}
        />
      )}
    </div>
  );
}

function BookCover({ book }: { book: Book }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [book.id]);
  if (failed) {
    return (
      <div className="flex h-40 w-28 flex-shrink-0 items-center justify-center rounded-md border border-surface-border bg-surface">
        <BookOpen className="h-8 w-8 text-ink-muted" strokeWidth={1} />
      </div>
    );
  }
  return (
    <img
      src={`/api/books/${book.id}/cover`}
      alt={book.name}
      onError={() => setFailed(true)}
      className="h-40 w-28 flex-shrink-0 rounded-md border border-surface-border object-cover shadow-lg"
    />
  );
}
