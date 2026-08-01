import { BookOpen } from "lucide-react";
import clsx from "clsx";

import type { ChapterLink } from "../../api/writerEvents";
import { loomHref } from "../../lib/loomLinks";

// Which Loom chapters reference an event (LOOM-32).
//
// Replaces the "{n} tags" count that came from `book_chapters`, which stored
// {book title, chapter number} — both of which move. Inserting a chapter in
// Loom renumbered every tag in that book silently, so the counts were often
// wrong and there was no way to tell. These come from Loom, which keys the
// join by chapter cuid, so the number shown is the number now.

/** Loom is closed. Said out loud rather than rendered as an absent row: an
 *  event with no chip and an event Loom cannot be asked about look identical,
 *  and only one of them means "referenced nowhere". */
export function ChapterLinksUnavailable({ compact = false }: { compact?: boolean }) {
  return (
    <p className={clsx("italic text-ink-muted", compact ? "text-[11px]" : "text-[11px]")}>
      Loom isn’t running — chapter links unavailable
    </p>
  );
}

export function ChapterLinkChips({
  links,
  /** Cards are narrow; the detail pane is not. */
  max,
}: {
  links: ChapterLink[];
  max?: number;
}) {
  if (links.length === 0) return null;
  const shown = max ? links.slice(0, max) : links;
  const hidden = links.length - shown.length;

  return (
    <div className="flex flex-wrap gap-1.5">
      {shown.map((link) => {
        const label = `${link.bookTitle} — ${
          link.chapterNumber === null ? link.chapterTitle : `Ch. ${link.chapterNumber}`
        }`;
        const chip = (
          <span className="flex items-center gap-1.5 rounded-full border border-surface-border px-3 py-1 text-[11px] text-ink-secondary">
            <BookOpen className="h-3 w-3 flex-shrink-0" />
            {label}
          </span>
        );
        // An unnumbered chapter has no canon address, so it cannot be linked —
        // but it is still a real tag and is shown rather than dropped.
        return link.readPath ? (
          <a
            key={link.chapterId}
            href={loomHref(link.readPath)}
            target="_blank"
            rel="noreferrer"
            title={`Open ${label} in Loom`}
            className="transition-colors hover:text-ink-primary [&>span]:hover:border-accent/50"
          >
            {chip}
          </a>
        ) : (
          <span key={link.chapterId} title="This chapter has no canon number, so it can’t be opened directly">
            {chip}
          </span>
        );
      })}
      {hidden > 0 && (
        <span className="flex items-center px-1 text-[11px] text-ink-muted">
          +{hidden} more
        </span>
      )}
    </div>
  );
}
