# Index changes from the sync work — handoff for the RAG effort (2026-07-12)

The Loom↔WriteAI sync overhaul shipped today. Per your coordination notes:
`src/retriever.py`, `config.py`, and everything under `eval/` were not
touched. But the **corpus changed**, and the index now updates
**autonomously** — both matter to eval work. Details below.

## 1. What changed in the corpus (your baseline moved)

- **Book 3 re-ingested** (it was stale since Jul 10): `+41 new, ~123
  updated, −36 deleted` chunks. A brand-new chapter was inserted at
  position 34, so former chapters 34–64 are now 35–65 — **their chunk IDs
  all shifted** (`b03.cNNN...`). The final chapter (now 65) gained ~2.2k
  characters.
- **Incremental enrichment re-ran** afterwards (97 tasks, $0.74):
  `chapter_summaries`, `character_profiles`, relationship natures, location
  maps, and story chronology are current through Book 3 chapter 65.
- **Golden-set impact:** text-grounded items anchored to Book 3 chunks at
  old numbers ≥34 now point at shifted IDs; items quoting the old final
  chapter may no longer match verbatim. The shipped answer-correctness
  baseline (0.75, held-out-verified) was measured on the pre-change index
  and is no longer strictly comparable.
- **Before/after snapshot available:** the pre-ingest index backup is
  `data/backups/20260712-224259_pre-ingest`
  (`python scripts/backup_index.py restore 20260712-224259_pre-ingest`).
  If you want an A/B, copy it aside before the next sync overwrites the
  backups rotation.

## 2. More churn lands tonight — re-baseline after, not before

A dry-run shows **12 more updated chunks** pending across all five books
(small prose edits that sat in Loom's DB without ever re-exporting — a bulk
search/replace artifact). The nightly auto-sync (02:30 UTC) will absorb
them. **Recommendation: re-validate/re-baseline the golden sets tomorrow
after that sync**, so you baseline once against the settled corpus instead
of twice.

## 3. The index now changes without a human — and how to freeze it

New behavior shipped today:

- **Nightly sync is ON** (`writer_data/ui_settings.json` →
  `auto_sync_enabled: true`, fires 02:30 UTC).
- **Event-triggered sync:** the server polls Loom's event outbox every 2
  minutes (`server/loom_events.py`) and auto-ingests a book ~10 minutes
  after a writing session's last canon export.
- **The backend is meant to run permanently** under launchd
  (`com.marisarichmond.writeai`). The agent is created but not yet loaded —
  it needs a one-time Full Disk Access grant for Python (macOS blocks
  launchd jobs from reading ~/Documents; instructions are in a comment
  inside the plist). Until that's done the backend runs from a normal
  shell, so treat "backend is up" as the norm either way: **check
  `auto_sync_enabled` before every eval run rather than assuming the
  index is static.**

**To freeze the corpus during an eval run:** set `auto_sync_enabled: false`
(Settings → Sync, or edit `writer_data/ui_settings.json`). That one flag
gates BOTH the nightly scheduler and the event consumer — no ingest can
start while it's off, which protects you from the SQLite lock contention
you flagged. Flip it back on when the eval finishes. (Manual Resync
buttons still work while it's off, so don't press them mid-eval either.)

## 4. New moving parts (none touch your files)

| Piece | Where |
|---|---|
| Ingestion source is now a deterministic `.txt` sidecar Loom exports (no Pages.app; verified chunker-equivalent — the format switch itself changed zero chunks) | `src/discovery.py` (format preference only) |
| Manifest drift check: `GET /api/sync/status` compares Loom's per-chapter manifest vs the index | `server/routers/sync.py` |
| Loom event consumer (poll → debounce → `ingest_run`) | `server/loom_events.py` |
| Drift banner in the Books pane | `frontend/src/components/status/StatusPane.tsx`, `frontend/src/api/books.ts` |
| Seam contract docs updated | `INTEGRATION.md` (both repos) |

Chunk-ID semantics, chunking, embedding, retrieval config, and all eval
tooling are unchanged. Loom's manifests
(`~/Writing/<n>. <Title>/<Title>.manifest.json`) now carry stable Loom
chapter IDs + per-chapter content hashes — potentially useful to you for
detecting "renumbered but textually identical" chapters when re-grounding
golden items.
