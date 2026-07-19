import { useEffect, useMemo, useRef, useState } from "react";
import { BarChart3, Info } from "lucide-react";
import { clsx } from "clsx";
import { fetchSpend, type SpendMetrics } from "../../api/metrics";
import { useAppStore } from "../../store/useAppStore";

// The four spend buckets, in a fixed order (color follows the entity, never
// its rank). Hues are the dataviz reference palette's first four categorical
// slots — validated colorblind-safe as an adjacent set in both themes. Actual
// hex values are theme-scoped CSS vars defined in <ChartStyles/> below.
const CATS = [
  { key: "sync", label: "Sync", blurb: "Indexing your books into the searchable archive." },
  { key: "enrichment", label: "Enrichment", blurb: "Extracting characters, events, locations & timeline." },
  { key: "exploration", label: "Exploration", blurb: "Questions you ask in Explore (RAG chat)." },
  { key: "reviews", label: "Reviews", blurb: "AI manuscript reviews." },
] as const;

type CatKey = (typeof CATS)[number]["key"];

const RANGES = [
  { days: 7, label: "7d" },
  { days: 30, label: "30d" },
  { days: 90, label: "90d" },
] as const;

function usd(n: number): string {
  if (n === 0) return "$0.00";
  if (n < 0.01) return "<$0.01";
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

// Theme-scoped category colors. The app flips to light mode by adding
// `.light-body` to an ancestor (<main>), so we switch hues off that class
// rather than a media query.
function ChartStyles() {
  return (
    <style>{`
      .spend-viz {
        --c-sync: #3987e5;
        --c-enrichment: #008300;
        --c-exploration: #d55181;
        --c-reviews: #c98500;
      }
      .light-body .spend-viz {
        --c-sync: #2a78d6;
        --c-enrichment: #008300;
        --c-exploration: #e87ba4;
        --c-reviews: #eda100;
      }
    `}</style>
  );
}

function fmtDay(iso: string, opts: Intl.DateTimeFormatOptions): string {
  // iso is a bare YYYY-MM-DD; parse as local, not UTC, so the label matches
  // the server-local day the bar represents.
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", opts);
}

function StatCard({ catKey, label, blurb, bucket, share }: {
  catKey: CatKey | "total";
  label: string;
  blurb: string;
  bucket: { cost_usd: number; calls: number } | undefined;
  share: number | null;
}) {
  const cost = bucket?.cost_usd ?? 0;
  const calls = bucket?.calls ?? 0;
  const isTotal = catKey === "total";
  return (
    <div className={clsx(
      "flex flex-col gap-1 rounded-lg border bg-surface-card p-3.5",
      isTotal ? "border-accent/40" : "border-surface-border"
    )}>
      <div className="flex items-center gap-1.5">
        {!isTotal && (
          <span
            className="h-2.5 w-2.5 flex-shrink-0 rounded-[3px]"
            style={{ background: `var(--c-${catKey})` }}
          />
        )}
        <span className="text-[11px] font-medium uppercase tracking-wide text-ink-muted" title={blurb}>
          {label}
        </span>
      </div>
      <span className={clsx("text-2xl font-semibold tabular-nums", isTotal ? "text-accent" : "text-ink-primary")}>
        {usd(cost)}
      </span>
      <span className="text-[11px] text-ink-muted">
        {calls.toLocaleString()} call{calls === 1 ? "" : "s"}
        {share !== null && share > 0 ? ` · ${Math.round(share * 100)}%` : ""}
      </span>
    </div>
  );
}

function SpendChart({ data }: { data: SpendMetrics }) {
  const [hover, setHover] = useState<number | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  const maxTotal = useMemo(
    () => Math.max(...data.daily.map((d) => d.total), 0),
    [data.daily]
  );

  // Round the axis ceiling up to a "nice" number for readable gridlines.
  const ceiling = useMemo(() => niceCeil(maxTotal), [maxTotal]);
  const ticks = useMemo(() => [1, 0.75, 0.5, 0.25, 0].map((f) => f * ceiling), [ceiling]);

  const CHART_H = 240;
  // With many days, label only a handful of x ticks to avoid collisions.
  const labelEvery = Math.ceil(data.daily.length / 8);

  if (maxTotal === 0) {
    return (
      <div className="flex h-64 items-center justify-center rounded-lg border border-surface-border bg-surface-card">
        <p className="text-sm text-ink-muted">No spend recorded in this window.</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-surface-border bg-surface-card p-4">
      <div className="flex gap-2">
        {/* Y axis */}
        <div className="flex flex-shrink-0 flex-col justify-between text-right" style={{ height: CHART_H }}>
          {ticks.map((t, i) => (
            <span key={i} className="text-[10px] leading-none text-ink-muted tabular-nums">
              {usd(t)}
            </span>
          ))}
        </div>

        {/* Plot */}
        <div className="relative min-w-0 flex-1" ref={wrapRef}>
          {/* Gridlines */}
          <div className="absolute inset-0 flex flex-col justify-between">
            {ticks.map((_, i) => (
              <div key={i} className="border-t border-surface-border/60" />
            ))}
          </div>

          {/* Bars */}
          <div className="relative flex items-end gap-[3px]" style={{ height: CHART_H }}>
            {data.daily.map((d, i) => {
              const active = hover === i;
              return (
                <div
                  key={d.date}
                  className="flex h-full flex-1 flex-col justify-end"
                  onMouseEnter={() => setHover(i)}
                  onMouseLeave={() => setHover((h) => (h === i ? null : h))}
                >
                  <div className={clsx("flex flex-col-reverse transition-opacity", hover !== null && !active && "opacity-40")}>
                    {CATS.map((c, ci) => {
                      const v = d[c.key];
                      if (v <= 0) return null;
                      const h = (v / ceiling) * CHART_H;
                      // topmost visible segment gets rounded data-ends
                      const isTop = CATS.slice(ci + 1).every((cc) => d[cc.key] <= 0);
                      return (
                        <div
                          key={c.key}
                          style={{ height: Math.max(h, 1), background: `var(--c-${c.key})` }}
                          className={clsx("w-full", isTop && "rounded-t-[3px]")}
                        />
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Hover tooltip */}
          {hover !== null && (
            <DayTooltip
              day={data.daily[hover]}
              left={(hover + 0.5) / data.daily.length}
            />
          )}

          {/* X axis */}
          <div className="mt-1.5 flex gap-[3px]">
            {data.daily.map((d, i) => (
              <div key={d.date} className="flex-1 overflow-hidden text-center">
                {i % labelEvery === 0 && (
                  <span className="text-[9px] leading-none text-ink-muted">
                    {fmtDay(d.date, { month: "numeric", day: "numeric" })}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function DayTooltip({ day, left }: { day: SpendMetrics["daily"][number]; left: number }) {
  const rows = CATS.filter((c) => day[c.key] > 0);
  return (
    <div
      className="pointer-events-none absolute -top-2 z-20 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-md border border-surface-border bg-surface-card px-3 py-2 shadow-lg"
      style={{ left: `${left * 100}%` }}
    >
      <p className="mb-1 text-[11px] font-semibold text-ink-primary">
        {fmtDay(day.date, { weekday: "short", month: "short", day: "numeric" })}
      </p>
      {rows.length === 0 ? (
        <p className="text-[11px] text-ink-muted">No spend</p>
      ) : (
        rows.map((c) => (
          <div key={c.key} className="flex items-center gap-2 text-[11px]">
            <span className="h-2 w-2 flex-shrink-0 rounded-[2px]" style={{ background: `var(--c-${c.key})` }} />
            <span className="text-ink-secondary">{c.label}</span>
            <span className="ml-auto font-medium tabular-nums text-ink-primary">{usd(day[c.key])}</span>
          </div>
        ))
      )}
      <div className="mt-1 flex items-center gap-2 border-t border-surface-border pt-1 text-[11px]">
        <span className="font-semibold text-ink-primary">Total</span>
        <span className="ml-auto font-semibold tabular-nums text-accent">{usd(day.total)}</span>
      </div>
    </div>
  );
}

// Round up to a readable axis ceiling (1/2/5 x 10^n).
function niceCeil(v: number): number {
  if (v <= 0) return 1;
  const mag = Math.pow(10, Math.floor(Math.log10(v)));
  const norm = v / mag;
  const step = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10;
  return step * mag;
}

export default function MetricsPane() {
  const { showToast } = useAppStore();
  const [days, setDays] = useState<number>(30);
  const [data, setData] = useState<SpendMetrics | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchSpend(days)
      .then((d) => { if (!cancelled) setData(d); })
      .catch(() => { if (!cancelled) showToast("Failed to load spend metrics."); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [days]);

  const grand = data?.grand_total_usd ?? 0;

  return (
    <div className="spend-viz flex flex-1 flex-col overflow-hidden">
      <ChartStyles />

      {/* Header — title only on the left; the top-right corner is reserved
          for the app's global toolbar (theme toggle, bell, settings). */}
      <div className="flex-shrink-0 px-6 pt-4">
        <div className="flex items-center gap-2">
          <BarChart3 className="h-6 w-6 flex-shrink-0 text-accent" />
          <div>
            <div className="flex items-center gap-1">
              <p className="text-xs font-semibold uppercase tracking-widest text-ink-primary">Spend</p>
              <div className="group relative">
                <Info className="h-3.5 w-3.5 cursor-default text-ink-muted transition-colors hover:text-ink-secondary" />
                <div className="pointer-events-none absolute left-0 top-5 z-50 w-72 rounded-md border border-surface-border bg-surface-card px-3 py-2 text-[11px] leading-relaxed text-ink-muted opacity-0 shadow-lg transition-opacity duration-150 group-hover:opacity-100">
                  Actual AI spend, taken from a ledger of every model request. Each request is bucketed into one of four kinds of work. Offline benchmark runs are excluded, so this reflects what you actually spent using the app.
                </div>
              </div>
            </div>
            <p className="mt-0.5 text-[11px] text-ink-muted">
              Day-to-day AI cost, broken down by sync, enrichment, exploration, and reviews
            </p>
          </div>
        </div>
        <div className="mt-3 border-t border-surface-border" />
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {loading && !data ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
              {[...Array(5)].map((_, i) => (
                <div key={i} className="h-24 animate-pulse rounded-lg border border-surface-border bg-surface-card" />
              ))}
            </div>
            <div className="h-72 animate-pulse rounded-lg border border-surface-border bg-surface-card" />
          </div>
        ) : data ? (
          <div className={clsx("space-y-5 transition-opacity", loading && "opacity-60")}>
            {/* Summary cards */}
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
              <StatCard
                catKey="total"
                label={`Total · ${data.days}d`}
                blurb="Total AI spend in this window"
                bucket={{
                  cost_usd: grand,
                  calls: Object.values(data.totals).reduce((s, b) => s + b.calls, 0),
                }}
                share={null}
              />
              {CATS.map((c) => (
                <StatCard
                  key={c.key}
                  catKey={c.key}
                  label={c.label}
                  blurb={c.blurb}
                  bucket={data.totals[c.key]}
                  share={grand > 0 ? (data.totals[c.key]?.cost_usd ?? 0) / grand : null}
                />
              ))}
            </div>

            {/* Legend + range selector + date span */}
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
              {CATS.map((c) => (
                <div key={c.key} className="flex items-center gap-1.5">
                  <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: `var(--c-${c.key})` }} />
                  <span className="text-[11px] text-ink-secondary">{c.label}</span>
                </div>
              ))}
              <div className="ml-auto flex items-center gap-3">
                <span className="text-[11px] text-ink-muted">
                  {fmtDay(data.start, { month: "short", day: "numeric" })} – {fmtDay(data.end, { month: "short", day: "numeric" })}
                </span>
                <div className="flex flex-shrink-0 gap-1 rounded-md border border-surface-border bg-surface-card p-0.5">
                  {RANGES.map((r) => (
                    <button
                      key={r.days}
                      onClick={() => setDays(r.days)}
                      className={clsx(
                        "rounded px-2.5 py-1 text-xs transition-colors",
                        days === r.days ? "bg-accent/15 text-accent" : "text-ink-muted hover:text-ink-primary"
                      )}
                    >
                      {r.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Daily chart */}
            <SpendChart data={data} />

            {/* By-model footnote */}
            {Object.keys(data.by_model).length > 0 && (
              <div className="rounded-lg border border-surface-border bg-surface-card p-4">
                <p className="mb-2.5 text-[11px] font-semibold uppercase tracking-wide text-ink-muted">By model</p>
                <div className="space-y-1.5">
                  {Object.entries(data.by_model).map(([model, b]) => (
                    <div key={model} className="flex items-center gap-3 text-xs">
                      <span className="font-mono text-ink-secondary">{model}</span>
                      <span className="ml-auto text-ink-muted tabular-nums">
                        {(b.input_tokens + b.output_tokens).toLocaleString()} tok
                      </span>
                      <span className="w-16 text-right font-medium tabular-nums text-ink-primary">{usd(b.cost_usd)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
