// Deep links into Loom (KAN-12).
//
// Prefer the id-addressed routes: they survive renaming a series or a book,
// which the title-addressed ones cannot. Fall back to title addressing when no
// Loom id is available — a book that has never been canon-exported has no
// manifest, so no cuid reaches us.
//
// site_name is DISPLAY ONLY. It used to double as the series identity, which
// meant renaming the site silently broke every jump link. Never reintroduce
// that: pass loom_series_id.

const loomBase = () => import.meta.env.VITE_LOOM_URL ?? "http://localhost:3000";

/** Author-side jump: lands on the chapter the writer last had open. */
export function loomAuthorHref(
  loomSeriesId: string | null | undefined,
  siteName: string,
): string {
  const base = loomBase();
  return loomSeriesId
    ? `${base}/author/by-id/${encodeURIComponent(loomSeriesId)}`
    : `${base}/author/by-title/${encodeURIComponent(siteName)}`;
}

/**
 * Reader-side citation deep link.
 *
 * `chapter` is the display counter (prologue = 0), not Loom's Chapter.order —
 * it is the number ingested from the manifest, and Loom resolves it by walking
 * canon the same way the export did.
 */
export function loomReaderHref(
  args: {
    loomSeriesId?: string | null;
    loomBookId?: string | null;
    siteName: string;
    bookTitle: string;
    chapter: number;
  },
): string {
  const base = loomBase();
  const { loomSeriesId, loomBookId, siteName, bookTitle, chapter } = args;
  if (loomSeriesId && loomBookId) {
    return `${base}/read/by-id/${encodeURIComponent(loomSeriesId)}`
      + `/${encodeURIComponent(loomBookId)}/${chapter}`;
  }
  return `${base}/read/by-title/${encodeURIComponent(siteName)}`
    + `/${encodeURIComponent(bookTitle)}/${chapter}`;
}
