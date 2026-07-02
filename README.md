# Series RAG — a continuity brain for an ongoing fiction series

Ask questions of your own books: *"What does a character know at a given
point in the story?"*, *"How does their relationship evolve?"*, *"Which
foreshadowing is still unresolved?"* The system reads the manuscripts the
way a careful reader would — nothing is hand-annotated; everything is
derived from the text itself.

The books are the single source of truth, and the source files are treated
as **strictly read-only**: all processing happens on staged copies, and
nothing under your writing directory is ever opened with write access.

## How it works

```
manuscripts (.pages/.docx/.txt/.md/.pdf)      BOOKS_DIR — read-only
   │  text extraction (cached by content hash; staged copies only)
   ▼
scene-aware chunker         chapter/prologue/part structure, POV + date
   │                        headers, ~800-token chunks w/ sentence overlap
   ▼
metadata extraction         EXTRACTION_MODEL (cheap): characters, locations,
   │                        events, per-character knowledge, emotional beats,
   │                        foreshadowing, unresolved questions
   ▼
storage                     ChromaDB (semantic search, local embeddings)
   │                        + SQLite (structured lookups)
   ▼
query.py                    routes each question to the right retrieval
                            strategy, answers with QUERY_MODEL + citations
```

Incremental by design: every chunk's text is SHA-256 hashed; nightly runs
re-process only chunks that changed. A run against unchanged books costs $0.

## Prerequisites

- Python 3.11+ (developed on 3.14)
- An Anthropic API key
- For `.pages` manuscripts: **macOS with Pages installed.** Apple's current
  `.pages` format stores the body as binary `.iwa`, so the only reliable
  converter is Pages itself (driven via AppleScript, on a staged copy).
  `textutil` and ZIP/XML fallbacks are implemented but do not work on
  current-format files. On other platforms, use `.docx`/`.txt`/`.md`
  exports — or point `TEXT_EXPORT_DIR` at a folder of pre-exported text.
- Embeddings run locally by default (`sentence-transformers`); no API cost.

## Installation

```sh
git clone <this repo> && cd <repo>
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## First-time setup

```sh
.venv/bin/python settings.py
```

Walks you through every setting, validates as it goes (the books directory
must exist, the folder pattern must match at least one book, API keys are
tested with a free call), and finishes by listing the books it found for
your confirmation. Settings live in `.env` (documented in `.env.example`).

Any time later: `settings.py` again to edit, or `settings.py --check` for a
non-interactive health check (handy before a cron run).

Book folders are recognized by `BOOK_PREFIX_PATTERN` (default: names
starting with digits + period, e.g. `1. Nobody's Hero`) and ordered by
their number. The manuscript inside each folder is the file whose name
matches the folder title (`2. Faded/Faded.pages`) — alternates and
`Versions/` folders are ignored.

## First ingestion

```sh
.venv/bin/python ingest.py --dry-run   # see the plan; no API calls
.venv/bin/python ingest.py             # confirmation-gated real run
```

Every run prints the source files it will READ (never modified) and a cost
estimate, and waits for an explicit `yes` before spending anything.

**Real-world cost:** a five-book series of ~727k words ingested for
**$4.01** on `claude-haiku-4-5` (≈ $3.30 per 600k words). Embeddings are
local and free; the first run downloads the embedding model (~500 MB).
Expect roughly 1–1.5 hours for a series this size.

## Keeping it current (nightly cron)

```cron
# refresh the index at 2:30am; only changed chapters are re-processed
30 2 * * * cd /path/to/repo && .venv/bin/python ingest.py --yes >> logs/ingest.log 2>&1
```

`mkdir -p logs` once beforehand. Nightly increments cost pennies: only
chapters you edited are re-extracted and re-embedded.

Tips:
- If another job exports your manuscripts to text nightly (e.g. an
  audiobook/ebook pipeline), point `TEXT_EXPORT_DIR` at it and schedule
  ingestion *after* it — ingestion will reuse those exports and never need
  to open Pages.
- `ingest.py --full` re-ingests everything from scratch (ignores hashes).
- A chunk whose metadata extraction failed is retried automatically on the
  next run.

## Web UI

A local web app ("The Archive") sits on top of the same stores:

```sh
npm install && npm install --prefix frontend   # once
npm run dev                                    # -> open http://localhost:5173
```

`npm run dev` starts the API (:8000, hot-reload) and the Vite dev server
(:5173, proxying /api) together; Ctrl+C stops both. For a production-style
single process: `npm run build` once, then `npm start` and open
http://localhost:8000.

Pages: **Explore** (streaming chat with citations you can open to the exact
passage), **Review** (chapter feedback with focus lenses: Rough Draft /
Continuity / Character Voice / Line Edit / Pacing), **Timeline** (curated
events from the enrichment pass), **Plan** (your chapter outline + character
intent, kept separate from AI-extracted data, with sync-diff and compare),
**Books** (per-book stats, sync + enrichment controls), **Characters**
(canonicalized cast with relationships, knowledge, arcs, and merge/rename/
hide corrections), **Settings**.

Two data disciplines the UI enforces:

- **Prose grounding.** Character names that never appear in your actual prose
  (occasionally invented by extraction) are remapped to the real character
  when unambiguous, otherwise quarantined for your review — heuristics never
  guess. Your merge/rename/hide decisions live in `writer_data/` (untracked;
  add it to your backups) and are keyed by name, so they survive every
  re-index and apply to future books automatically.
- **Cost gates.** Any button that would spend API money (Sync, Resync,
  Enrich) shows a dry-run plan and dollar estimate first.

For frontend development: `cd frontend && npm run dev` (Vite on :5173,
proxying to the API on :8000).

## Asking questions

```sh
.venv/bin/python query.py "What does Noah know about That Night by the end of book 2?"
.venv/bin/python query.py --scope "book:1-3" "Are there any unresolved plot threads?"
.venv/bin/python query.py --scope "book:2,chapter:5" "How does Jared feel about Emma?"
.venv/bin/python query.py --type continuity "Do you see any plot holes or contradictions?"
.venv/bin/python query.py --export character_timeline "Jared Gatlin"
.venv/bin/python query.py --export relationship_map "Jared Gatlin" "Emma Mendoza"
```

Questions are auto-classified (`--show-plan` displays the routing):

| Type | Trigger | Retrieval |
|---|---|---|
| temporal knowledge | "what does X know…", "by the end of book N" | character-knowledge ledger up to the bound + filtered semantic search; the answer distinguishes what the *character* knows from what the *reader* knows |
| sentiment / relationship | "how does X feel about Y", "relationship between" | scenes where the characters co-occur + their emotional beats |
| continuity | "plot holes", "unresolved", "foreshadowing" | *every* foreshadowing note and open question in scope, categorized Resolved / Unresolved / Potentially Contradicted |
| lookup | "every scene where…", "list all…" | indexed SQLite lookups first |
| general | everything else | semantic top-K |

Answers cite `(Book N, Chapter M)` throughout. Typical cost:
**$0.05–$0.17 per question** on `claude-sonnet-4-6` (printed after each
answer). Use full character names in quotes for best results — the name
spotter is capitalization-based.

## Source-file protection

- Files under `BOOKS_DIR` are only ever opened read-only.
- Conversion happens on copies in `data/staging/`, which is cleared after
  every run; extracted text is cached in `data/extracted_text/` keyed by
  content hash so unchanged files are never re-converted.
- No symlinks or hardlinks to source files are created anywhere.
- `--dry-run` labels every source file `[READ ONLY]`.

## Project layout

```
ingest.py / query.py / settings.py    CLI entry points
config.py                             .env loading + validation
src/
  discovery.py    book/folder discovery (BOOK_PREFIX_PATTERN)
  parser.py       .pages/.docx/.txt/.md/.pdf -> text (staged, cached)
  chunker.py      structure-aware splitting + POV/date headers
  extractor.py    LLM metadata extraction (batched, schema-enforced)
  embedder.py     local sentence-transformers or OpenAI
  storage.py      ChromaDB + SQLite
  ingestion.py    pipeline + hash-based change detection
  query_router.py / retriever.py / answerer.py
scripts/diagnose_parsing.py           per-method conversion probe
data/                                 all generated state (gitignored)
```

## Troubleshooting

- **"all extraction methods failed" for a `.pages` file** — run
  `scripts/diagnose_parsing.py <file> --probe` to see which conversion
  methods work on your machine. On macOS make sure Pages is installed and
  the terminal has Automation permission for it (System Settings →
  Privacy & Security → Automation).
- **Empty store / "run ingest.py first"** — ingestion hasn't completed, or
  `DATA_DIR` points somewhere unexpected.
- **A book was skipped** — its folder didn't match `BOOK_PREFIX_PATTERN`,
  or no file inside matched the folder title. The log says which.
- **Model skipped chunks during extraction** — harmless; they're retried
  individually in the same run, and anything still failing is retried on
  the next run.

## Future improvements

- **Web UI** — a small local app over `query.py` with saved questions and
  browsable citations.
- **Character relationship graph** — the `characters` co-occurrence data
  is already in SQLite; render an evolving graph per book.
- **Automatic series bible** — generate/refresh a structured bible
  (characters, locations, timeline, open threads) from the stored metadata
  after each nightly run.
- **Multiple concurrent series** — a `--series` switch selecting between
  `.env` profiles / data directories.
- **Explicit scene markers** — if scene separators (`***`) are ever added
  to the manuscripts, the chunker can split on them directly (it currently
  treats the chapter as the scene unit).
- **Content-anchored chunk IDs** — chunk IDs are positional; inserting a
  paragraph early in a chapter re-processes that chapter's later chunks
  (cost: ~a cent). Anchoring IDs to content would eliminate even that.
