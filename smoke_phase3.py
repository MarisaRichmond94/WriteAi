"""Phase 3 smoke test: metadata extraction on ONE chapter (same one as Phase 2).

Usage:
    .venv/bin/python smoke_phase3.py "~/Writing/2. Faded/Faded.pages" --chapter 1 [--yes]

Shows a cost estimate and asks for confirmation before making any API calls
(unless --yes). Reads only; writes nothing outside DATA_DIR.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from config import load_config
from src.chunker import chunk_segment, split_into_segments
from src.extractor import MetadataExtractor, estimate_extraction_cost
from src.parser import extract_text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("book_file")
    ap.add_argument("--book-number", type=int, default=2)
    ap.add_argument("--chapter", type=int, default=1)
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = ap.parse_args()

    cfg = load_config()
    source = Path(args.book_file).expanduser()

    text, method = extract_text(source, cfg)
    if text is None:
        print("extraction failed")
        return 1
    print(f"text via {method}; splitting…")

    segments = split_into_segments(text)
    target = next((s for s in segments
                   if s.kind == "chapter" and s.chapter_number == args.chapter), None)
    if target is None:
        print(f"chapter {args.chapter} not found")
        return 1

    chunks = chunk_segment(target, book_number=args.book_number,
                           book_title=source.stem,
                           max_chunk_tokens=cfg.max_chunk_tokens)
    print(f"chapter {args.chapter}: {len(chunks)} chunks, "
          f"{sum(c.word_count for c in chunks):,} words")

    est = estimate_extraction_cost(chunks, cfg.extraction_model)
    print("\n== cost estimate ==")
    for k, v in est.items():
        print(f"  {k}: {v}")

    if not args.yes:
        answer = input("\nProceed with API calls? (yes/no): ").strip().lower()
        if answer != "yes":
            print("aborted — no API calls made")
            return 0

    extractor = MetadataExtractor(cfg)
    results = extractor.extract(chunks)

    ok = sum(1 for r in results if r is not None)
    print(f"\n== extraction: {ok}/{len(results)} chunks succeeded ==")
    for r in results:
        if r is None:
            print("  (failed chunk)")
            continue
        print(f"\n--- {r['chunk_id']} ---")
        print(json.dumps(r, indent=2, ensure_ascii=False))

    print("\n== actual usage ==")
    print(f"  api_calls: {extractor.usage['api_calls']}")
    print(f"  input_tokens: {extractor.usage['input_tokens']:,}")
    print(f"  output_tokens: {extractor.usage['output_tokens']:,}")
    print(f"  actual_cost_usd: ${extractor.actual_cost_usd}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
