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

### Chapter insights (LOOM-91)

Loom's chapter dock has an Insights tab rendering WriteAI's extraction for the
open chapter. It reads one endpoint, through a Loom-side proxy:

| WriteAI endpoint | Read by | Carries |
|---|---|---|
| `GET /api/books/{book}/chapters/{chapter}/extracted` | Loom's `GET /api/writeai/insights` | `summary_text`, `summary`, `facts` |

Three obligations on this side:

- **Keep it a pure read.** `chapter_extracted` seeds nothing, prunes nothing and
  writes nothing today, and Loom calls it on tab open on that assumption. Giving
  it a seed-or-save — the pattern `GET /api/plan/characters` uses — would turn an
  idle editor into a writer of this store.
- **`{book}` is the positional `book_number`.** Loom resolves it by matching the
  book title against `GET /api/books`. Rename a book on one side only and
  insights go quiet for it; that is the title-coupling LOOM-12 moves away from,
  and the reason the match is normalised (NFC, curly apostrophes) rather than
  compared raw.
- **A 404 here means "not ingested yet", not "error".** Loom renders it as an
  ordinary empty state, so keep 404 for the missing-chapter case rather than
  promoting it to a 500.

Two keys this endpoint returns are deliberately **not** consumed. `characters`,
because Loom's Characters tab shows the writer's own tags and the chunk-derived
roster would contradict it; and `locations`, which Loom rendered briefly and
dropped as not worth its space. Both stay in the response for WriteAI's own book
drawer — nothing here asks WriteAI to stop returning them.

### Plan outline (LOOM-95)

Loom's book page edits the same outline as the plan pane, through four proxied
endpoints:

| WriteAI endpoint | Loom route |
|---|---|
| `GET /api/plan/outline/{book}` | `GET /api/writeai/outline` |
| `PUT /api/plan/outline/{book}` | `PUT /api/writeai/outline` |
| `POST /api/plan/outline/{book}/chapter` | `POST /api/writeai/outline/chapter` |
| `DELETE /api/plan/outline/{book}/chapter/{id}` | `DELETE /api/writeai/outline/chapter?cardId=` |

This works because `plan_outline.json` is keyed by Loom's book cuid (KAN-24), so
both apps address the same outline the same way even after a book is inserted or
reordered. `{book}` in the route is still the positional number; Loom resolves it
by title, as it does for insights.

Four obligations on this side:

- **`get_outline` seeds, reconciles and saves on a GET.** Loom knows, and only
  calls it on section open and after mutations. Worth keeping in mind before
  adding more write-on-read behaviour to it — the cost is now paid by two UIs.
- **Keep `put_outline` refusing nothing and replacing everything, or change it
  deliberately.** Loom validates every card before sending, because the endpoint
  cannot tell an intentional deletion from a client that forgot a field. If
  per-card updates ever land, say so here — Loom would drop a whole layer of
  guard code.
- **`loom_id` and `summary_source` are load-bearing but appear in no published
  type.** `_auto_reconcile` keys on the first; the second is how a hand-edited
  summary is told apart from generated text. Anything that rewrites cards on
  either side must carry them.
- **`writer_summary` holds HTML.** Every card in the live store does. A client
  writing plain text into it destroys the writer's paragraph breaks.

> ⚠️ **Two editors, no locking.** Loom and the plan pane can both write this
> store, and the second save silently wins. Accepted deliberately for a
> single-writer setup rather than mitigated — recorded so missing cards are
> recognised rather than debugged.

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

### 6. Character tagging (Loom ↔ WriteAI)

Which chapters a writer-character appears in. **Loom owns the join; we own the
character.** The sibling of §5, built from the same shared parts on Loom's side
so the two tabs cannot drift apart.

Keyed by **chapter cuid** (`ChapterCharacter` in Loom's schema). We can already
say which *books* a character is in — `books`, matched by title — but nothing
here is chapter-aware, and any chapter-level answer we stored would be
renumbered out from under us by an insert in Loom. This is the one question
only Loom can answer.

| Direction | Route | Purpose |
|---|---|---|
| Loom → us | `GET /api/plan/characters` | The character pool, behind Loom's `/api/writeai/characters` proxy. |
| Loom → us | `PUT/DELETE /api/plan/characters/{char_id}` | Create, edit and delete from Loom's Characters tab. |
| Loom → us | `POST /api/plan/characters/{char_id}/photo` | Portrait upload (multipart). |
| Loom → us | `GET /api/plan/photos/{file}` | Portraits, behind Loom's `/api/writeai/photo/[file]`. |
| us → Loom | `GET /api/plan/characters/chapter-links?ids=…` → `GET <LOOM_URL>/api/chapter-characters?characterIds=…` | The reverse lookup the Plan character card renders. |

`character_chapter_links` in `server/routers/plan.py` is a **pass-through, not a
second source of truth**, and is deliberately **uncached** — the point of the
seam is that these numbers track Loom, and a mirror reintroduces the drift it
exists to remove. It is declared **before** `/characters/{char_id}` so the
literal path wins the route match. Loom unreachable returns **503** with
`unreachable: true` (nothing is broken, it simply isn't running), distinct from
**502** for an upstream error — the card must say which, since an empty box
would otherwise claim the character appears nowhere.

> ⚠️ **`PUT /api/plan/characters/{char_id}` is ours, and it is the worst of the
> three replace-shaped endpoints.** It takes a **raw `dict` with no model** and
> does `chars[i] = body`, so an omitted key does not reset to a default — it
> *disappears*. It is also an **upsert**: an unknown id appends rather than
> 404ing, which is exactly how Loom's Characters tab creates a character. Both
> behaviours are load-bearing; neither is guessable from the method.

Ids are minted **by Loom**, client-side, as `wc-` + 8 hex to match ours, and
handed straight to that upsert. Anywhere an id reaches the filesystem it must
pass `_safe_photo_stem()`: LOOM-43 found `char_id` interpolated into a **glob
whose matches are then unlinked**, where `*` widened the pattern to every
portrait in the directory and deleted them all. It checks filename *safety*,
not id *format* — one live character predates the `wc-` shape (`draft-<ms>`),
and `*` is no more allowed in one shape than the other. `settings.py`'s
`_safe_slug` guards the book-cover routes the same way; this was the missed one.

**Rendering.** `frontend/src/components/plan/character/ChapterAppearances.tsx`,
fed by the generalised `useChapterLinks` hook. It is rendered
**unconditionally at a fixed height**, including for a character with no tags:
the cards share a grid row, so one that collapses leaves the row ragged. Books
group into one row each in **`bookOrder`** — Loom's `Book.order`, the reading
order — never by title, which is alphabetical order wearing chronology's
clothes. Chapter pills scroll **sideways** rather than wrapping, because a POV
character can appear in forty chapters of one book and wrapping would let a
single row swallow the viewport. `readPath` is relative and prefixed with
`VITE_LOOM_URL` through `loomHref()`; a null one means an unnumbered chapter —
a real appearance, shown unlinked rather than dropped.

**Degradation** matches §5: unknown ids hidden and never auto-deleted, every
requested id gets a key, malformed ids dropped rather than failing the request.

**Non-canon tags never cross this seam (LOOM-63).** Loom owns a branching CYOA
story; WriteAI holds canon data only. A character tag can be marked as
appearing solely on a non-canon branch, and `GET /api/chapter-characters`
filters those rows out **in the query**. The flag lives on the TAG rather than
on the character or the chapter, because non-canon in Loom is a path THROUGH an
otherwise canon chapter — the same character can be canon in chapter 4 and
branch-only in chapter 7. Enforcing it at the seam rather than in WriteAI keeps
the boundary true by construction: the non-canon story is not filtered out of
WriteAI, it never reaches it. `tests/unit/chapterCharactersRoute.test.ts` pins
this, because the failure is invisible from the response — WriteAI would just
start showing chapters from a story it should not know exists.

> ⚠️ **Renaming a writer character detaches it from its canon entity.**
> Cross-references were resolved by LOOM-45: `events[].characters` and
> `relationships[].target` hold `wc-` ids, and the display name is derived at
> read time, so a rename reaches every event and relationship instead of
> orphaning them. `scripts/migrate_character_refs.py` performed the
> conversion — idempotent, and it aborts rather than dropping a reference it
> cannot resolve. Both write paths also coerce an incoming NAME to an id, so an
> older client cannot undo the migration one save at a time.
>
> What LOOM-45 deliberately did NOT change is the canon lookup in `plan.py` —
> `s.canon.entities.get(c["name"])` — which still matches **by name**. Canon is
> rebuilt from the manuscript and has no notion of `wc-` ids, so there is
> nothing to key it on. The consequence is real: renaming a writer character to
> something the manuscript does not call them detaches it from its canon
> entity, and the features relying on that lookup — junk-pruning and
> `/characters/{id}/extracted` — stop finding it. Nothing errors; the extracted
> data just goes quiet. Rename to match the manuscript, or accept losing the
> canon tie-in for that character.

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
