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

### 2. Jump links

- **WriteAI → Loom:** `GET <LOOM_URL>/author/by-title/<series title>`
  (case-insensitive title match; lands on the series' last-touched chapter).
  WriteAI configures `VITE_LOOM_URL` (default `http://localhost:3000`).
- **Loom → WriteAI:** plain link to `NEXT_PUBLIC_WRITEAI_URL`
  (default `http://localhost:5173`), plus the review deep link below.

### 3. Review deep link (Loom → WriteAI)

The chapter editor's Review button saves the book's canon manuscript, then
opens:

```
<WRITEAI_URL>/?pane=review&book=<title>&chapter=<n>&focus=<persona>&preview=1&draft=1
```

- `book` — book title; WriteAI matches it punctuation-insensitively.
- `chapter` — WriteAI chapter number (0 = prologue), computed by Loom from
  the canon walk (`reviewChapter` in the canon export response). Omitted
  when the chapter isn't addressable.
- `focus` — reviewer persona; must be one of WriteAI's focus options
  (Loom sends `Literary Agent`).
- `preview=1` — opens the chapter preview panel.
- `draft=1` — WriteAI reads the chapter's text (and rich formatting)
  straight from the freshly exported manuscript file — no ingest, no LLM
  cost — and badges the session as an unindexed draft. The writer iterates
  (re-export in Loom, "Send Updated Draft" in WriteAI) and reindexes with
  the Resync button once the revision lands. (`sync=1` was this parameter's
  earlier form, retired in favor of draft mode.)

WriteAI applies these once and strips them from the URL.

## Identity caveat

Series/book identity across the apps is **title-based** (punctuation-loose).
Renaming a series or book in Loom breaks the jump links and folder matching
until the WriteAI-side folder/series name is updated to match.
