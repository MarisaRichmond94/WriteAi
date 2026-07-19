// Spend dashboard: reads the aggregated cost ledger from the server. The
// server does all bucketing (surface -> category) and day rollups; the client
// just renders. See server/routers/metrics.py.

export interface SpendBucket {
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  calls: number;
}

export interface SpendDay {
  date: string; // YYYY-MM-DD (server-local day)
  sync: number;
  enrichment: number;
  exploration: number;
  reviews: number;
  other: number;
  total: number;
}

export interface SpendMetrics {
  days: number;
  start: string;
  end: string;
  categories: string[];
  daily: SpendDay[];
  totals: Record<string, SpendBucket>;
  by_model: Record<string, SpendBucket>;
  grand_total_usd: number;
}

export async function fetchSpend(days: number): Promise<SpendMetrics> {
  const res = await fetch(`/api/metrics/spend?days=${days}`);
  if (!res.ok) throw new Error(`Failed to load spend metrics: ${res.statusText}`);
  return (await res.json()) as SpendMetrics;
}
