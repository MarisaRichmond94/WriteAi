// Verbatim-quote highlighting for citation cards.
//
// The answer streams with direct quotes in it (ENABLE_DIRECT_QUOTES): any
// double-quoted span in the answer exists verbatim in one of the retrieved
// excerpts. These helpers extract those spans from the final answer text and
// locate them inside a citation's snippet so the card can <mark> the exact
// quoted passage.
//
// Matching uses the same trick as ChapterViewer's snippet highlight: strip
// both strings to lowercase alphanumeric (with a map back to original
// indices), so typography differences — curly vs straight quotes, em dash vs
// --, ellipsis vs ..., collapsed whitespace, case — never break the match.

/** Strip s to lowercase alphanumeric and return a map from stripped index →
 *  original index, so matches on stripped text can be mapped back to exact
 *  boundaries in the original. */
export function buildStrippedMap(s: string): { stripped: string; map: number[] } {
  let stripped = "";
  const map: number[] = [];
  for (let i = 0; i < s.length; i++) {
    const c = s[i].toLowerCase();
    if (/[a-z0-9]/.test(c)) {
      stripped += c;
      map.push(i);
    }
  }
  return { stripped, map };
}

const QUOTED_SPAN = /["“]([^"“”]+)["”]/g;
const MIN_QUOTE_WORDS = 4;

/** Extract double-quoted spans (straight or curly) of at least four words
 *  from the answer text. Deduped, in order of appearance. */
export function extractQuotedSpans(answer: string): string[] {
  const spans: string[] = [];
  const seen = new Set<string>();
  for (const m of answer.matchAll(QUOTED_SPAN)) {
    const inner = m[1].trim();
    if (inner.split(/\s+/).filter(Boolean).length < MIN_QUOTE_WORDS) continue;
    const key = buildStrippedMap(inner).stripped;
    if (!key || seen.has(key)) continue;
    seen.add(key);
    spans.push(inner);
  }
  return spans;
}

export interface HighlightRange {
  start: number; // inclusive, in original text coordinates
  end: number;   // exclusive
}

/** Find every quote that appears verbatim (modulo typography) inside text,
 *  returned as merged, sorted ranges in original text coordinates. */
export function findQuoteRanges(text: string, quotes: string[]): HighlightRange[] {
  if (!text || quotes.length === 0) return [];
  const { stripped, map } = buildStrippedMap(text);
  if (!stripped) return [];

  const ranges: HighlightRange[] = [];
  for (const quote of quotes) {
    const q = buildStrippedMap(quote).stripped;
    if (!q) continue;
    let idx = stripped.indexOf(q);
    while (idx !== -1) {
      ranges.push({ start: map[idx], end: map[idx + q.length - 1] + 1 });
      idx = stripped.indexOf(q, idx + 1);
    }
  }
  if (ranges.length === 0) return [];

  // Merge overlaps so segments never nest.
  ranges.sort((a, b) => a.start - b.start || a.end - b.end);
  const merged: HighlightRange[] = [ranges[0]];
  for (const r of ranges.slice(1)) {
    const last = merged[merged.length - 1];
    if (r.start <= last.end) last.end = Math.max(last.end, r.end);
    else merged.push(r);
  }
  return merged;
}

export interface HighlightSegment {
  text: string;
  marked: boolean;
}

/** Split text into plain/marked segments per the given ranges — ready to
 *  render as spans and <mark>s. */
export function segmentByRanges(text: string, ranges: HighlightRange[]): HighlightSegment[] {
  const segments: HighlightSegment[] = [];
  let cursor = 0;
  for (const r of ranges) {
    if (r.start > cursor) segments.push({ text: text.slice(cursor, r.start), marked: false });
    segments.push({ text: text.slice(r.start, r.end), marked: true });
    cursor = r.end;
  }
  if (cursor < text.length) segments.push({ text: text.slice(cursor), marked: false });
  return segments;
}
