# Loom ↔ WriteAI integration contract

Loom and WriteAI are separate apps coupled only through the filesystem and
URLs — neither calls the other's API. If you change any seam below, update
the other repo (Loom has a mirror of this file).

## Seams

### 1. Manuscript files (Loom → WriteAI)

Loom's canon export (`⌥⇧E`, or the Review button) writes
`<root>/<n>. <Book Title>/<subfolder>/<Book Title>.pages`, where `<root>` is
configured in Settings → Export. WriteAI ingests from its `BOOKS_DIR`
(default `~/Writing`), matching book folders by numeric prefix and the
manuscript file by folder title. Point both at the same folder.

Inside the manuscript, WriteAI's chunker identifies chapters by heading
lines: a bare number (`14`) is Chapter 14, a literal `Prologue` line is
chapter 0. Loom's canon walk produces exactly these labels (numbered
chapters render as bare numbers; unnumbered chapters render their title).
Unnumbered chapters other than "Prologue" are not addressable in WriteAI.

Alongside the `.pages`, every canon export also writes three machine
sidecars to the same folder:

- `<Book Title>.txt` — deterministic plain text (one line per paragraph,
  hard breaks as newlines, footnote bodies excluded). **This is the file
  WriteAI actually ingests** (format preference `.txt > .docx > .pages`) —
  fully headless, no Pages.app round-trip.
- `<Book Title>.docx` — the same manuscript in Word format.
- `<Book Title>.manifest.json` — per-chapter identity for drift detection:
  `{ id, number, label, pov, date, wordCount, contentHash }` plus
  `exportedAt` and a whole-book `contentHash`. WriteAI's
  `GET /api/sync/status` compares it against the index; the Status pane
  shows a drift banner (with per-book Resync) when the index is behind.

### 2. Jump links

Each direction has an **id-addressed** form (preferred) and a **title-addressed**
form (fallback, retained indefinitely). WriteAI configures `VITE_LOOM_URL`
(default `http://localhost:3000`). Both are built by
`frontend/src/lib/loomLinks.ts` — never hand-assemble one, or the fallback
logic ends up implemented three different ways.

- **WriteAI → Loom (author):**
  - `GET <LOOM_URL>/author/by-id/<seriesId>` — preferred; `<seriesId>` is
    `appSettings.loom_series_id`, served by `GET /api/settings`.
  - `GET <LOOM_URL>/author/by-title/<series title>` — fallback, using the
    configured site name.

  Both land on the series' last-touched chapter.
- **WriteAI → Loom (reader):**
  - `GET <LOOM_URL>/read/by-id/<seriesId>/<bookId>/<chapter number>` —
    preferred, from `citation.loom_series_id` / `citation.loom_book_id`.
  - `GET <LOOM_URL>/read/by-title/<series title>/<book title>/<chapter number>`
    — fallback, from the site name and `citation.book`.

  The "Open in Loom" action on an Explore citation card, opened in a new tab.
  `<chapter number>` is `citation.chapter` (0 = prologue) in **both** forms:
  the chapter is addressed by number because that is what the reader sees and
  what we ingested. Loom re-runs its canon walk to map the number to the
  chapter's cuid, mints a reader session, and redirects into `/read/...` at
  that chapter.

  > This previously read "requires no new fields on the citation payload".
  > That is no longer true: citations carry `loom_book_id` and
  > `loom_series_id` as of LOOM-12. They are nullable, and a null means fall
  > back to the title form.
- **Loom → WriteAI:** plain link to `NEXT_PUBLIC_WRITEAI_URL`
  (default `http://localhost:5173`), plus the review deep link below.

### 3. Review — now runs inside Loom (LOOM-22)

The chapter editor's Review button opens Loom's own review panel. It no
longer opens WriteAI, and **Loom no longer constructs the deep link below** —
the round trip through a second tab was the point of removing it.

Loom calls three of its own routes, each proxying to us server-side so
the browser never talks to `:8000` (no CORS, no WriteAI URL in client code,
and — for the session list — no 6 MB of conversations shipped to render one):

| Loom route | Proxies to | Purpose |
|---|---|---|
| `GET /api/writeai/review` | `GET /api/sessions` | Newest review for a chapter. Filters server-side by book title + canon chapter number. |
| `POST /api/writeai/review/run` | `POST /api/review/stream` | Runs a review, streaming SSE straight through. |
| `PUT`/`DELETE /api/writeai/review/session` | `PUT`/`DELETE /api/sessions/review/{id}` | Persist or remove a session. |

**`chapter_text` carries the live editor content**, which is what removes the
resync step: WriteAI documents that field as winning over the index, so no
export, ingest, or disk write happens first. Loom derives the canon display
number read-only via `reviewNumberForChapter()` — the canon export returns the
same number but writes the manuscript as a side effect.

**Spend stays WriteAI's.** It makes the Anthropic call and books it under
`surface="review"`; `ANTHROPIC_API_KEY` exists only in WriteAI's `.env`, so
Loom cannot bypass that. The `usage` event returns `cost_usd`, which Loom
displays at the point of action.

> **`PUT /api/sessions/{kind}/{sid}` REPLACES the whole session object** — it
> does not merge. A partial body silently discards everything omitted,
> including the conversation. Loom's proxy refuses incomplete sessions and
> empty message arrays before they can reach WriteAI.

WriteAI's own review pane is unchanged and remains fully usable.

---

#### Legacy: the review deep link (Loom → WriteAI)

**Retained, but no longer produced by Loom.** The WriteAI-side route still
works, so links already saved or shared keep resolving. Note it is
title-addressed, which LOOM-12 exists to move away from — do not extend it.

The chapter editor's Review button used to save the book's canon manuscript,
then open:

```
<WRITEAI_URL>/?pane=review&book=<title>&chapter=<n>&focus=<persona>&draft=1
```

- `book` — book title; WriteAI matches it punctuation-insensitively.
- `chapter` — WriteAI chapter number (0 = prologue), computed by Loom from
  the canon walk (`reviewChapter` in the canon export response). Omitted
  when the chapter isn't addressable.
- `focus` — reviewer persona; must be one of WriteAI's focus options
  (Loom sends `Literary Agent`).
- `draft=1` — WriteAI reads the chapter's text (and rich formatting)
  straight from the freshly exported manuscript file — no ingest, no LLM
  cost — and badges the session as an unindexed draft. The writer iterates
  (re-export in Loom, "Send Updated Draft" in WriteAI) and reindexes with
  the Resync button once the revision lands. (`sync=1` was this parameter's
  earlier form, retired in favor of draft mode.)

WriteAI applies these once and strips them from the URL.

### 4. Event outbox (Loom → any subscriber)

Loom appends events to `data/events/events.jsonl` (append-only JSONL,
monotonic `seq`) and serves them at `GET <LOOM_URL>/api/events?since=<seq>`
— cursor pull; the response carries the cursor to store for the next poll.
Event types: `export.completed` (a consistent canon snapshot is on disk —
the signal consumers ingest on), `chapter.created`, `chapter.deleted`,
`book.renamed`. Events are hints, not truth: consumers reconcile against
the manifests for anything missed.

WriteAI's server polls this endpoint every 2 minutes
(`server/loom_events.py`; cursor in `writer_data/loom_event_cursor.json`;
`LOOM_URL` env var, default `http://localhost:3000`) and triggers an
incremental ingest of a book once its exports have been quiet for 10
minutes. The nightly scheduler (Settings → Sync) remains the
reconciliation safety net when either app was closed.

### 5. Event tagging (Loom ↔ WriteAI)

Which chapters a writer-event is referenced in. **Loom owns the join; WriteAI
owns the event.** Loom stores only the event id — never a copy of the title,
date or body — so there is no second source of truth and nothing to sync.

The join is keyed by **chapter cuid** (`ChapterEvent` in Loom's schema). That
is the whole point: WriteAI used to store `book_chapters`, a list of
`{book title, chapter number}`, and both halves move. Inserting a chapter in
Loom renumbered every tag in that book silently, with nothing to report it —
which is why the feature went unused. A cuid-keyed tag simply follows its
chapter.

| Direction | Route | Purpose |
|---|---|---|
| Loom → WriteAI | `GET/POST /api/writeai/events`, `PATCH/DELETE /api/writeai/events/[id]`, `POST /api/writeai/events/locations` | Loom's server-side proxies onto `/api/writer-events*`. Full CRUD from the Events tab. |
| Loom → WriteAI | `GET /api/writeai/characters` | Character pool for the event form. |
| Loom → WriteAI | `GET /api/writeai/photo/[file]` | Character portraits, proxied from `/api/plan/photos/`. |
| WriteAI → Loom | `GET /api/writer-events/chapter-links?ids=…` → `GET <LOOM_URL>/api/chapter-events?eventIds=…` | The reverse lookup the timeline renders. |

**Loom never writes `writer_events.json` directly.** Every mutation goes
through WriteAI's HTTP API so the FastAPI process stays the file's single
writer — `writer_store` rewrites the whole file per save under an in-process
lock, which a second process would defeat.

> ⚠️ **`PATCH /api/writer-events/{id}` REPLACES the whole event.** Every field
> on `WriterEventBody` has a default, so an omitted key is silently reset
> rather than left alone — editing a title would erase the cast. Loom's proxy
> refuses incomplete bodies before they can land. This is the same hazard as
> `PUT /api/sessions/{kind}/{sid}` (§3) and `PUT /api/plan/characters/{id}`,
> which takes a raw dict with no model at all. **Three endpoints now share this
> shape: assume replace, not merge, unless a route says otherwise.**

> ⚠️ **`GET /api/plan/characters` writes to disk.** It seeds from canon on
> first call, prunes entries canon has reclassified, and self-heals `books`,
> saving whenever any of that changes. Fetch it on open; never poll it.

**`GET /api/chapter-events` is read-only and must stay that way.** It runs on
every timeline render. Chapter numbers come from the canon **walk**
(`canonNumbersForBook`), never the canon **export** — the export returns the
same numbers but writes `.pages`/`.txt`/`.docx` to `<root>` on the way, so
wiring it there would rewrite the manuscript on every page load and trigger an
ingest each time. `tests/unit/chapterEventsRoute.test.ts` pins this at source
level.

`readPath` in that response is **relative**. Loom has no reliable way to know
its own external origin; WriteAI prefixes `VITE_LOOM_URL` via
`loomLinks.loomHref()`. A `null` `readPath` means the chapter has no canon
number (unnumbered, not the prologue) — still a real tag, shown unlinked
rather than dropped.

**Accepted constraint: a symmetric hard dependency, with no cache.** Loom's
Events tab is inert when WriteAI is down; WriteAI's chapter chips are absent
when Loom is down. Both run under launchd, so this is acceptable — but each
side must NAME the outage ("WriteAI isn't running" / "Loom isn't running")
rather than render an empty list, which would claim the opposite of what is
true. Do not "fix" this by adding a mirror: a cached answer reintroduces
exactly the staleness this seam exists to remove.

**Degradation.** An event id Loom holds that WriteAI no longer knows is
*unknown identity*: hidden from the UI, never auto-deleted. Every requested id
gets a key in the response — an event tagged nowhere maps to `[]`, so "no
chapters" stays distinguishable from "lookup failed". Unknown or malformed ids
are dropped rather than failing the request, so one stale id cannot blank every
other event's links.

## Identity

**Loom's cuids are the identity of a series and a book across both apps.**
Loom mints them; WriteAI reads them from the manifest sidecar and stores them.
They are stable across renaming, reordering, and re-ingestion.

Resolved by LOOM-12. The former caveat — *"identity is title-based, so renaming
breaks the jump links and folder matching"* — no longer describes the contract.

**Where WriteAI holds them**

- `Book.loom_book_id` / `Book.loom_series_id` on discovered books
  (`src/discovery.py`), read from the manifest at scan time.
- `loom_book_id` / `loom_series_id` columns on `chunks`, `events`,
  `chapter_timeline`, `chapter_summaries`, `location_map_v2`. Created by
  `migrate_schema()` and populated on write.
- `citation.loom_book_id` / `.loom_series_id` on the citations payload;
  `appSettings.loom_series_id` from `GET /api/settings`.

**`book_chapters` was a fourth, and is now REMOVED.** WriteAI's
writer-events used to carry `[{book title, chapter number}]`. It was the exact
pattern LOOM-12 moved away from, it drifted the first time a chapter was
inserted above a tagged one, and it is gone from the model, the TypeScript
types and the stored JSON (LOOM-40). It is **not** a fallback and must not be
reintroduced — the cuid-keyed join in §5 replaces it.

**Three things are still positional or title-derived, deliberately:**

1. **Locating** a book folder and its manifest — `<number>. <title>/`. This is
   the last title-dependent step; once the manifest is open, identity is
   stable. A rename is invisible to everything downstream.
2. **The chapter number** in reader deep links (0 = prologue). Citations are
   anchored to what the reader sees.
3. **`site_name`** is display only. It is *not* identity and must never be used
   as such again — doing so is what made renaming the site break every jump
   link.

**Degradation contract.** A book that has never been canon-exported has no
manifest and therefore no cuid. Every consumer treats a missing id as *unknown
identity* and falls back to `book_number` or title matching — never as *no
match*. So the pre-LOOM-12 behaviour remains the worst case, never a regression.

`book_number` and `book_title` columns are retained and still written. They are
no longer load-bearing for identity, but plenty of queries and the UI read them.
