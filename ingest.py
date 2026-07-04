"""Ingestion CLI — incremental by default, driven by the chunk hash index.

Usage:
    python ingest.py              # normal run with confirmation prompts
    python ingest.py --yes        # skip confirmations (for cron)
    python ingest.py --dry-run    # show what would be processed; no API calls,
                                  #   no database writes
    python ingest.py --full       # ignore stored hashes, re-ingest everything
    python ingest.py --book 2     # limit the run to one book
    python ingest.py --batches    # extract via the Message Batches API
                                  #   (50% token pricing, up to 1h latency)

Source files under BOOKS_DIR are READ ONLY — all conversion happens on
staged copies under DATA_DIR, which are removed at the end of the run.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from config import load_config


def _notify(title: str, body: str, ok: bool = True) -> None:
    """Post to the UI notification bell — best-effort; the CLI never fails
    because of it (and quietly skips if the server package is unavailable)."""
    try:
        from server import notify
        notify.add("sync_complete" if ok else "error", title, body,
                   action_url="/?pane=status")
    except Exception:
        pass

from src.discovery import discover_books
from src.extractor import estimate_extraction_cost
from src.ingestion import (BookDiff, chunk_text_hash, clear_staging,
                           diff_chunks, ingest_chunks, load_and_chunk_book,
                           load_hash_index, save_hash_index)

log = logging.getLogger("ingest")


def confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    return input(f"{prompt} (yes/no): ").strip().lower() == "yes"


def main() -> int:
    ap = argparse.ArgumentParser(description="Incremental series ingestion")
    ap.add_argument("--yes", action="store_true", help="skip confirmation prompts")
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would be processed; no API calls or DB writes")
    ap.add_argument("--full", action="store_true",
                    help="ignore stored hashes and re-ingest everything")
    ap.add_argument("--book", type=int, default=None, help="only this book number")
    ap.add_argument("--batches", action="store_true",
                    help="extract via the Anthropic Message Batches API "
                         "(50%% token pricing; results may take up to an hour)")
    ap.add_argument("--label", default="Sync",
                    help='notification label, e.g. --label "Nightly sync"')
    args = ap.parse_args()

    started = time.time()
    cfg = load_config()
    if args.batches:  # CLI flag overrides EXTRACTION_USE_BATCHES on
        cfg.extraction_use_batches = True

    # ── discovery + source-file gate ───────────────────────────────────────
    books = discover_books(cfg)
    if args.book is not None:
        books = [b for b in books if b.number == args.book]
    if not books:
        print("No books found — check BOOKS_DIR and BOOK_PREFIX_PATTERN.")
        return 1

    print(f"Series: {cfg.series_name}")
    print("Source files that will be READ (never modified):")
    for b in books:
        print(f"  [READ ONLY] {b.manuscript}")

    if not args.dry_run and cfg.confirm_before_ingest:
        if not confirm("\nProceed with reading and analyzing these files?", args.yes):
            print("aborted")
            return 0

    # ── chunk + diff (no API calls yet) ────────────────────────────────────
    index = {} if args.full else load_hash_index(cfg)
    stored_index = load_hash_index(cfg)  # kept for correct bookkeeping on --full
    diffs: dict[int, tuple] = {}   # book_number -> (book, chunks, BookDiff)
    for b in books:
        chunks = load_and_chunk_book(cfg, b)
        if chunks is None:
            continue  # logged; skip bad file, never crash
        diffs[b.number] = (b, chunks, diff_chunks(chunks, index, b.number))

    changed = [c for _, _, d in diffs.values() for c in d.changed]
    deleted = [cid for _, _, d in diffs.values() for cid in d.deleted_ids]
    unchanged = sum(len(d.unchanged) for _, _, d in diffs.values())

    print(f"\nPlan: {sum(len(d.new) for _, _, d in diffs.values())} new, "
          f"{sum(len(d.updated) for _, _, d in diffs.values())} updated, "
          f"{unchanged} unchanged, {len(deleted)} deleted")
    for num in sorted(diffs):
        b, chunks, d = diffs[num]
        print(f"  {num}. {b.title}: +{len(d.new)} ~{len(d.updated)} "
              f"={len(d.unchanged)} -{len(d.deleted_ids)}")

    est = estimate_extraction_cost(changed, cfg.extraction_model)
    print(f"\nEstimated extraction cost for {len(changed)} chunk(s): "
          f"${est['estimated_cost_usd']} "
          f"({est['estimated_input_tokens']:,} in / "
          f"{est['estimated_output_tokens']:,} out tokens on {est['model']})")

    if cfg.extraction_use_batches:
        print("\nBatch mode is ON: extraction goes through the Anthropic "
              "Message Batches API at 50% token pricing.\n"
              "Results may take up to an hour to come back (typically much less).")

    if args.dry_run:
        print("\n--dry-run: stopping before any API calls or database writes.")
        return 0

    # Rich-text sidecar for the UI's chapter viewers (italics, alignment,
    # colors). Content-hash cached and no API cost; runs even on no-change
    # syncs so books indexed before this feature gain their sidecar files.
    from src.richtext import sync_rich_text
    for num in sorted(diffs):
        sync_rich_text(cfg, diffs[num][0])

    if not changed and not deleted:
        print("\nNothing to do.")
        clear_staging(cfg)
        _notify(f"{args.label} complete",
                "No changes — every chapter matches the index.")
        return 0

    # ── cost gate (before any API call) ────────────────────────────────────
    if cfg.confirm_before_ingest:
        if not confirm("Proceed with API calls?", args.yes):
            print("aborted — no API calls made")
            return 0

    # Heavy imports only once we know there's work to do.
    from src.embedder import Embedder
    from src.extractor import MetadataExtractor
    from src.storage import SeriesStore

    embedder = Embedder(cfg)
    store = SeriesStore(cfg)
    extractor = MetadataExtractor(cfg)

    # ── ingest per book ────────────────────────────────────────────────────
    new_index = dict(stored_index)
    book_reports: list[str] = []
    total_failed = 0
    for num in sorted(diffs):
        b, chunks, d = diffs[num]
        if not d.changed and not d.deleted_ids:
            continue
        print(f"\n== book {num}: {b.title} "
              f"({len(d.changed)} chunk(s) to process) ==")
        book_reports.append(f"{b.title} ({len(d.changed)} chunk(s))")
        summary = ingest_chunks(cfg, d.changed, extractor, embedder, store)
        if d.deleted_ids:
            store.delete_chunks(d.deleted_ids)
            print(f"  removed {len(d.deleted_ids)} stale chunk(s)")

        failed = set(summary.get("failed_chunk_ids", []))
        total_failed += len(failed)
        # Record hashes only for chunks that fully succeeded, so failures
        # are retried on the next run. --full also refreshes unchanged ones.
        for c in chunks:
            if c.chunk_id not in failed:
                new_index[c.chunk_id] = chunk_text_hash(c)
        for cid in failed:
            new_index.pop(cid, None)
        for cid in d.deleted_ids:
            new_index.pop(cid, None)

    save_hash_index(cfg, new_index)
    clear_staging(cfg)

    # ── run summary ────────────────────────────────────────────────────────
    elapsed = time.time() - started
    u = extractor.usage
    print(f"\n== run summary ==")
    print(f"  processed: {len(changed)} chunk(s) "
          f"({total_failed} with null metadata, will retry next run)")
    print(f"  deleted:   {len(deleted)}")
    print(f"  unchanged: {unchanged}")
    print(f"  api calls: {u['api_calls']}  "
          f"({u['input_tokens']:,} in / {u['output_tokens']:,} out tokens)")
    if u.get("batch_input_tokens") or u.get("batch_output_tokens"):
        print(f"  via batches api (billed at 50%): "
              f"{u['batch_input_tokens']:,} in / "
              f"{u['batch_output_tokens']:,} out tokens")
    print(f"  actual cost: ${extractor.actual_cost_usd}")
    print(f"  elapsed: {elapsed/60:.1f} min")
    from src.costlog import log_cost
    log_cost(cfg, surface="ingest", model=extractor.model, usage=u,
             cost_usd=extractor.actual_cost_usd,
             latency_ms=int(elapsed * 1000),
             extra={"api_calls": u["api_calls"], "chunks": len(changed),
                    "failed_chunks": total_failed})
    failures = (f" {total_failed} chunk(s) failed and will retry next run."
                if total_failed else "")
    _notify(f"{args.label} complete",
            f"{len(book_reports)} book(s) updated: {', '.join(book_reports)}. "
            f"Cost ${extractor.actual_cost_usd}.{failures}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:  # scheduled runs must surface failures in the UI
        _notify("Sync failed", f"{type(e).__name__}: {e}", ok=False)
        raise
