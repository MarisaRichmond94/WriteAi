// Deterministic color assignment for POVs, books, and event types —
// mirrors the reference app's palettes.

export const POV_PALETTE = [
  { text: "text-rose-300", ring: "ring-rose-400/40", bg: "bg-rose-400/10" },
  { text: "text-sky-300", ring: "ring-sky-400/40", bg: "bg-sky-400/10" },
  { text: "text-violet-300", ring: "ring-violet-400/40", bg: "bg-violet-400/10" },
  { text: "text-amber-300", ring: "ring-amber-400/40", bg: "bg-amber-400/10" },
  { text: "text-teal-300", ring: "ring-teal-400/40", bg: "bg-teal-400/10" },
  { text: "text-fuchsia-300", ring: "ring-fuchsia-400/40", bg: "bg-fuchsia-400/10" },
];

export const BOOK_PALETTE = [
  "bg-violet-400/15 text-violet-300",
  "bg-amber-400/15 text-amber-300",
  "bg-blue-400/15 text-blue-300",
  "bg-emerald-400/15 text-emerald-300",
  "bg-rose-400/15 text-rose-300",
  "bg-pink-400/15 text-pink-300",
  "bg-cyan-400/15 text-cyan-300",
  "bg-orange-400/15 text-orange-300",
];

export const EVENT_TYPE_COLORS: Record<string, string> = {
  discovery: "bg-blue-400/15 text-blue-300 border-blue-400/30",
  confrontation: "bg-rose-400/15 text-rose-300 border-rose-400/30",
  revelation: "bg-violet-400/15 text-violet-300 border-violet-400/30",
  death: "bg-zinc-400/15 text-zinc-300 border-zinc-400/30",
  relationship: "bg-pink-400/15 text-pink-300 border-pink-400/30",
  journey: "bg-cyan-400/15 text-cyan-300 border-cyan-400/30",
  decision: "bg-amber-400/15 text-amber-300 border-amber-400/30",
  loss: "bg-indigo-400/15 text-indigo-300 border-indigo-400/30",
  victory: "bg-emerald-400/15 text-emerald-300 border-emerald-400/30",
  other: "bg-slate-400/15 text-slate-300 border-slate-400/30",
};

export const EVENT_DOT_COLORS: Record<string, string> = {
  discovery: "bg-blue-400",
  confrontation: "bg-rose-400",
  revelation: "bg-violet-400",
  death: "bg-zinc-400",
  relationship: "bg-pink-400",
  journey: "bg-cyan-400",
  decision: "bg-amber-400",
  loss: "bg-indigo-400",
  victory: "bg-emerald-400",
  other: "bg-slate-400",
};

function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

export const povColor = (name: string) => POV_PALETTE[hash(name) % POV_PALETTE.length];
export const bookColor = (n: number) => BOOK_PALETTE[(n - 1 + BOOK_PALETTE.length) % BOOK_PALETTE.length];

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter((w) => /^[A-Z]/.test(w))
    .slice(0, 2)
    .map((w) => w[0])
    .join("");
}
