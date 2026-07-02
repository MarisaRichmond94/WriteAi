"""Phase 2 smoke test: parser + chunker on a single book / single chapter.

Usage:
    python smoke_phase2.py "~/Writing/2. Faded/Faded.pages" --book-number 2
    python smoke_phase2.py <book file> --chapter 1        # which chapter to chunk
    python smoke_phase2.py <book file> --probe            # also force-test each
                                                          # conversion method
Reads only. Writes only under DATA_DIR (cache + transient staging).
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from config import load_config
from src.parser import extract_text
from src.chunker import chunk_segment, split_into_segments


def probe_methods(source: Path, cfg, include_applescript: bool) -> None:
    """Force each conversion method individually and report which ones work."""
    methods = ["textutil", "zip-xml", "zip-preview"]
    if include_applescript:
        methods.insert(0, "applescript")
    print("\n== conversion-method probe (each forced individually) ==")
    for m in methods:
        text, method = extract_text(source, cfg, force_method=m)
        status = f"OK ({len(text.split())} words)" if text else "failed"
        print(f"  {m:<12} {status}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("book_file", help="path to one book's manuscript file")
    ap.add_argument("--book-number", type=int, default=2)
    ap.add_argument("--chapter", type=int, default=1,
                    help="chapter to run the chunker on (default 1)")
    ap.add_argument("--probe", action="store_true",
                    help="force-test each conversion method")
    ap.add_argument("--probe-applescript", action="store_true",
                    help="include the Pages/AppleScript method in the probe "
                         "(opens Pages.app)")
    args = ap.parse_args()

    cfg = load_config()
    source = Path(args.book_file).expanduser()
    book_title = source.stem

    print(f"== extract: {source} ==")
    text, method = extract_text(source, cfg)
    if text is None:
        print("extraction FAILED with every method")
        return 1
    print(f"method: {method}   words: {len(text.split()):,}   lines: {len(text.splitlines()):,}")

    if args.probe or args.probe_applescript:
        probe_methods(source, cfg, include_applescript=args.probe_applescript)

    print("\n== segment split ==")
    segments = split_into_segments(text)
    kinds = Counter(s.kind for s in segments)
    print(f"segments: {len(segments)} total -> {dict(kinds)}")

    povs = Counter(s.pov for s in segments if s.kind != "part")
    print(f"POVs: {dict(povs)}")

    dated = sum(1 for s in segments if s.date_line)
    print(f"segments with a date line: {dated}")

    parts = [s for s in segments if s.kind == "part"]
    if parts:
        print("parts:", "; ".join(f"{p.heading} — {p.part_title}" for p in parts))

    chapters = [s.chapter_number for s in segments if s.kind == "chapter"]
    if chapters:
        gaps = [n for n in range(chapters[0], chapters[-1] + 1) if n not in chapters]
        print(f"chapters: {chapters[0]}..{chapters[-1]}"
              + (f"  MISSING: {gaps}" if gaps else "  (contiguous)"))

    print(f"\n== chunk ONE chapter: Chapter {args.chapter} ==")
    target = next((s for s in segments
                   if s.kind == "chapter" and s.chapter_number == args.chapter), None)
    if target is None:
        print(f"chapter {args.chapter} not found")
        return 1
    print(f"heading={target.heading!r} pov={target.pov!r} date={target.date_line!r} "
          f"part={target.part_number} ({target.part_title})")
    print(f"chapter length: {target.word_count:,} words, {len(target.paragraphs)} paragraphs")

    chunks = chunk_segment(target, book_number=args.book_number,
                           book_title=book_title,
                           max_chunk_tokens=cfg.max_chunk_tokens)
    print(f"chunks: {len(chunks)} (MAX_CHUNK_TOKENS={cfg.max_chunk_tokens})")
    for c in chunks:
        first = c.text.replace("\n", " ")[:70]
        print(f"\n  [{c.chunk_id}] {c.word_count} words"
              f"{'  (has context prefix)' if c.context_prefix else ''}")
        print(f"    starts: {first}…")
    print("\n  embedding_text of first chunk, first 3 lines:")
    for line in chunks[0].embedding_text.split("\n")[0:2]:
        print(f"    | {line[:100]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
