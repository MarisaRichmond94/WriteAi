import type { ChapterLink } from "../../../api/writerEvents";
import { loomHref } from "../../../lib/loomLinks";

// Which Loom chapters a writer-character appears in (LOOM-33).
//
// WriteAI already knows which BOOKS a character is in — `books`, matched by
// title. Chapters are the thing it cannot know: nothing here is chapter-aware,
// and the tags live in Loom keyed by chapter cuid so they survive a chapter
// being inserted above them.
//
// Deliberately built to the Relationships block's spec, down to the header
// weight and tracking: they are two lists of the same kind of fact about a
// character, sitting one above the other, and any difference between them
// reads as one of them being foreign rather than as emphasis.
//
// Fixed height and ALWAYS rendered, even when empty — the caller must not gate
// it on there being links. Cards sit in a grid, so one that shrinks because
// its character has no tags leaves its whole row uneven.

/** Same as the relationships list directly above it. */
const VIEWPORT_PX = 112;

/** One row per book: the title, then that book's chapters.
 *
 *  Ordered by Loom's Book.order, not by title — reading order, so book two
 *  never lists above book one because of its initial. Loom already sorts this
 *  way; re-sorting here means the grouping doesn't silently depend on it. */
function groupByBook(links: ChapterLink[]): { book: string; order: number; links: ChapterLink[] }[] {
  const byBook = new Map<string, { book: string; order: number; links: ChapterLink[] }>();
  for (const link of links) {
    const group = byBook.get(link.bookId) ?? {
      book: link.bookTitle,
      order: link.bookOrder,
      links: [],
    };
    group.links.push(link);
    byBook.set(link.bookId, group);
  }
  return [...byBook.values()].sort((a, b) => a.order - b.order);
}

/** Chapter 0 IS the prologue — that is the canon numbering both apps share.
 *  Rendering a bare "0" is technically correct and reads as a bug. */
function chapterLabel(link: ChapterLink): string {
  if (link.chapterNumber === null) return link.chapterTitle;
  if (link.chapterNumber === 0) return "Prologue";
  return `Ch. ${link.chapterNumber}`;
}

export function ChapterAppearances({
  links,
  loomUnreachable,
}: {
  links: ChapterLink[];
  loomUnreachable: boolean;
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-ink-muted">
          Chapter(s) {links.length > 0 && `(${links.length})`}
        </span>
        {/* No "add" affordance on purpose: tagging happens in Loom's Characters
            tab, keyed by chapter cuid. A control here would have to invent a
            chapter picker and would drift the moment chapters were renumbered. */}
      </div>

      <div
        className="divide-y divide-surface-border rounded-lg border border-surface-border overflow-y-auto"
        style={{ height: VIEWPORT_PX }}
      >
        {loomUnreachable ? (
          // "Loom isn't running" and "appears in no chapters" look identical as
          // an empty box, and only one of them is a fact about the story.
          <div className="flex items-center justify-center h-full px-2">
            <p className="text-[10px] text-ink-muted/50 italic text-center">
              Loom isn’t running — chapter appearances unavailable
            </p>
          </div>
        ) : links.length === 0 ? (
          <div className="flex items-center justify-center h-full px-2">
            <p className="text-[10px] text-ink-muted/50 italic text-center">
              No chapter appearances to display
            </p>
          </div>
        ) : (
          groupByBook(links).map((group) => (
            <div key={group.book} className="flex items-center gap-2 px-2 py-1.5">
              {/* Truncates rather than wraps: a long title must not make this
                  book's row taller than the next one's. */}
              <span
                title={group.book}
                className="flex-shrink-0 max-w-[45%] truncate text-[10px] text-ink-muted"
              >
                {group.book}
              </span>
              {/* Scrolls sideways instead of wrapping — a POV character can be
                  in forty chapters of one book, and wrapping would let a single
                  row swallow the whole viewport. Scrollbar hidden because a
                  visible one would not fit inside a 34px row. */}
              <div className="flex-1 min-w-0 flex gap-1 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
                {group.links.map((link) =>
                  // An unnumbered chapter has no canon address, so it cannot be
                  // linked — but it is a real appearance and is named rather
                  // than dropped.
                  link.readPath ? (
                    <a
                      key={link.chapterId}
                      href={loomHref(link.readPath)}
                      target="_blank"
                      rel="noreferrer"
                      title={`Open ${group.book} — ${link.chapterTitle} in Loom`}
                      className="flex-shrink-0 rounded-full border border-surface-border px-2 py-0.5 text-[10px] text-ink-secondary transition-colors hover:border-accent/50 hover:text-accent"
                    >
                      {chapterLabel(link)}
                    </a>
                  ) : (
                    <span
                      key={link.chapterId}
                      title="This chapter has no canon number, so it can’t be opened directly"
                      className="flex-shrink-0 rounded-full border border-dashed border-surface-border px-2 py-0.5 text-[10px] italic text-ink-muted"
                    >
                      {chapterLabel(link)}
                    </span>
                  ),
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
