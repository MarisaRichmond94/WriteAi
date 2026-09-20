#!/usr/bin/env python3
"""Scan a review for citations of chapters past the one under review.

A review of Chapter N may reference chapters > N only inside its
"## Where This Is Heading" section (see UPCOMING_INSTRUCTION in
server/routers/review.py). Every reference outside that section is a
leak — the reviewer used future material in its critique.

Usage:
    python scripts/check_future_citations.py --chapter 5 [--book 2] review.md [...]
    pbpaste | python scripts/check_future_citations.py --chapter 5

Bare citations ("Ch 65", "Chapter 65") are assumed to mean the book under
review. Book-qualified citations ("Book 2, Chapter 65") are only checked
when --book is given, since without it an earlier book's late chapters
would false-positive. Exits 1 when any violation is found.
"""

from __future__ import annotations

import argparse
import re
import sys

HEADING_RE = re.compile(r"^#{1,4}\s*(.+?)\s*$")
FORWARD_HEADING_RE = re.compile(r"where\s+this\s+is\s+heading", re.IGNORECASE)
BOOK_CH_RE = re.compile(r"\bBook\s+(\d+)\s*,\s*Ch(?:apter)?\.?\s*(\d+)",
                        re.IGNORECASE)
BARE_CH_RE = re.compile(r"\bCh(?:apter)?\.?\s*(\d+)", re.IGNORECASE)


def find_violations(text: str, chapter: int,
                    book: int | None) -> list[tuple[int, str, str]]:
    """(line_number, citation, line snippet) for each future citation
    outside the Where This Is Heading section."""
    violations = []
    in_forward = False
    for lineno, line in enumerate(text.splitlines(), 1):
        h = HEADING_RE.match(line)
        if h:
            in_forward = bool(FORWARD_HEADING_RE.search(h.group(1)))
            continue
        if in_forward:
            continue
        # book-qualified first; mask them so the bare pattern doesn't
        # re-match their chapter number
        masked = line
        for m in BOOK_CH_RE.finditer(line):
            b, c = int(m.group(1)), int(m.group(2))
            if book is not None and (b > book or (b == book and c > chapter)):
                violations.append((lineno, m.group(0), line.strip()))
            masked = masked.replace(m.group(0), " " * len(m.group(0)), 1)
        for m in BARE_CH_RE.finditer(masked):
            if int(m.group(1)) > chapter:
                violations.append((lineno, m.group(0), line.strip()))
    return violations


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="*",
                    help="review markdown files (default: stdin)")
    ap.add_argument("--chapter", type=int, required=True,
                    help="chapter number under review")
    ap.add_argument("--book", type=int, default=None,
                    help="book number under review (enables Book N, Ch M checks)")
    args = ap.parse_args()

    sources = ([(f, open(f, encoding="utf-8").read()) for f in args.files]
               if args.files else [("<stdin>", sys.stdin.read())])
    total = 0
    for name, text in sources:
        violations = find_violations(text, args.chapter, args.book)
        total += len(violations)
        for lineno, citation, snippet in violations:
            if len(snippet) > 120:
                snippet = snippet[:117] + "..."
            print(f"{name}:{lineno}: [{citation}] {snippet}")
    if total:
        print(f"\n{total} future-chapter citation(s) outside "
              f"'Where This Is Heading' (reviewing Chapter {args.chapter})")
        return 1
    print(f"OK — no future-chapter citations outside 'Where This Is Heading' "
          f"(reviewing Chapter {args.chapter})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
