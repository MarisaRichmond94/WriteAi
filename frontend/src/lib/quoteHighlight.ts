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

// ── Sentence-aware windows ───────────────────────────────────────────────────
//
// Citation cards receive the FULL chunk text (citation.text) but display only
// a slice of it. These helpers pick sentence-shaped slices: sentences end at
// [.!?…] optionally followed by closing quotes / em-dashes, and must be
// trailed by whitespace or end-of-text (so decimals like "3.5" or initials
// don't count as boundaries).

const TERMINATORS = ".!?…";
const CLOSERS = "\"'”’»)—"; // " ' ” ’ » ) —

/** If text[i] starts a sentence boundary (terminator + optional closers,
 *  followed by whitespace or end-of-text), return the boundary's exclusive
 *  end index; otherwise -1. */
function sentenceBoundaryEnd(text: string, i: number): number {
  if (!TERMINATORS.includes(text[i])) return -1;
  let j = i + 1;
  while (j < text.length && CLOSERS.includes(text[j])) j++;
  if (j < text.length && !/\s/.test(text[j])) return -1;
  return j;
}

export interface SentenceWindow {
  start: number; // inclusive, in original text coordinates
  end: number;   // exclusive
  leadingEllipsis: boolean;  // window was capped mid-sentence on the left
  trailingEllipsis: boolean; // window was capped mid-sentence on the right
}

/** Expand a highlight range to the boundaries of its enclosing sentence(s),
 *  capped at ~maxChars around the range (ellipsis flags mark capped sides).
 *  Pure; returns coordinates into the original text. */
export function expandToSentenceWindow(
  text: string,
  range: HighlightRange,
  maxChars = 400
): SentenceWindow {
  // Sentence start: just past the last boundary that ends at/before the range.
  let start = 0;
  for (let i = range.start - 1; i >= 0; i--) {
    const be = sentenceBoundaryEnd(text, i);
    if (be !== -1 && be <= range.start) {
      start = be;
      break;
    }
  }
  while (start < range.start && /\s/.test(text[start])) start++;

  // Sentence end: first boundary ending at/after the range (the range's own
  // final character may be the terminator).
  let end = text.length;
  for (let i = Math.max(range.start, range.end - 1); i < text.length; i++) {
    const be = sentenceBoundaryEnd(text, i);
    if (be !== -1 && be >= range.end) {
      end = be;
      break;
    }
  }

  // Cap the window, always keeping the whole matched range visible.
  let leadingEllipsis = false;
  let trailingEllipsis = false;
  if (end - start > maxChars) {
    const rangeLen = range.end - range.start;
    const extra = Math.max(0, maxChars - rangeLen);
    const leftAvail = range.start - start;
    const rightAvail = end - range.end;
    let left = Math.min(leftAvail, Math.ceil(extra / 2));
    const right = Math.min(rightAvail, extra - left);
    left = Math.min(leftAvail, extra - right); // give unused right budget back
    const s = range.start - left;
    const e = range.end + right;
    leadingEllipsis = s > start;
    trailingEllipsis = e < end;
    start = s;
    end = e;
  }
  return { start, end, leadingEllipsis, trailingEllipsis };
}

/** Trim text to the last complete sentence that fits within ~maxChars.
 *  Falls back to the raw maxChars prefix + "…" when no boundary is found.
 *  Pure; used for the card's compact snippet. */
export function snapToSentence(text: string, maxChars = 220): string {
  const t = text.trim();
  if (t.length <= maxChars) return t;
  for (let i = maxChars - 1; i >= 0; i--) {
    const be = sentenceBoundaryEnd(t, i);
    // Allow a couple of closing quote marks to spill past the cap.
    if (be !== -1 && be <= maxChars + 2) return t.slice(0, be);
  }
  return t.slice(0, maxChars).trimEnd() + "…";
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
