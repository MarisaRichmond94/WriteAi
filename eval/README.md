# Golden evaluation set

Ground-truth Q&A items for evaluating retrieval quality over the 5-book Dark
Horse series, derived from the system's own extracted metadata in
`data/series_metadata.sqlite`.

## Files

- `golden_candidates.jsonl` — ~100 machine-generated candidates (≥15 per query
  type), regenerable at any time.
- `golden_set.jsonl` — 40 hand-curated items (8 per query type) whose expected
  chunks were manually checked against the actual chunk text.
- `build_golden_candidates.py` — generator + verifier (read-only against the DB).

## Item format (one JSON object per line)

```json
{"id": "tk-001",
 "question": "What does Jared know about Emma by the end of book 1?",
 "qtype": "temporal_knowledge",
 "scope": "book:1",
 "expected_chunk_ids": ["b01.c001.s01.k02"],
 "expected_citations": [[1, 1]],
 "answer_must_mention": ["called", "spend time"],
 "tags": [],
 "notes": "derived from character_knowledge rowid 3: ..."}
```

- `qtype` — one of `temporal_knowledge | sentiment | continuity | lookup |
  general`, and is guaranteed to equal what `src.query_router.classify()`
  returns for the raw question (scope is embedded in the question phrasing,
  e.g. "in book 2", "by the end of book 3").
- `scope` — the Scope that `classify()` derives from the question, recorded
  for reference: `"book:2"`, `"books:1-3"`, `"book:2,chapter:5"`, or `null`
  for whole-series questions.
- `expected_chunk_ids` — chunks that contain/support the answer (retrieval
  ground truth).
- `expected_citations` — `[book, chapter]` pairs a correct answer should cite.
- `answer_must_mention` — 1-4 strings for future answer-level spot checks.
  For `sentiment` items these are emotion words taken from scene-level
  `emotional_beats` metadata; the prose depicts the emotion but may not use
  the literal word.
- `tags: ["alias"]` — the question uses a character's short name where the DB
  rows use the full name (e.g. "Cat" vs "Cat Kissinger"). These items are
  EXPECTED to fail retrieval today and exist to measure future alias
  resolution.

## How candidates were generated

`build_golden_candidates.py` derives questions from metadata tables, then
keeps only phrasings that `classify()` routes to the intended qtype:

| qtype              | source                                                   |
|--------------------|----------------------------------------------------------|
| temporal_knowledge | `character_knowledge` rows (what X learns, where)        |
| sentiment          | `emotional_beats` in chunk `metadata_json`               |
| continuity         | `foreshadowing` / `unresolved_questions` rows            |
| lookup             | `characters` / `locations` side tables (scene lists)     |
| general            | `events` rows (plot questions from event titles)         |

Selection is deterministic (fixed SQL ordering + per-book quotas, no
randomness); running the generator twice yields identical output. The DB is
opened with `mode=ro`, so it can never be written.

## How the golden set was curated

40 items were selected from the candidates (plus a few hand-crafted ones for
scope diversity and alias coverage), with each item checked so that:

1. `classify()` routes the question to the intended qtype and scope,
2. the expected chunk text actually contains/supports the answer,
3. the question reads as natural author-phrased English,
4. scopes mix single-book (35), multi-book (2), and whole-series (3) items,
5. 4 items are tagged `alias` (tk-008, lk-006, lk-007, lk-008).

Known data quirks accounted for during curation:

- The `characters` table mixes short and full name forms ("Noah" vs "Noah
  Gatlin"); non-alias lookup items only use names whose usage is single-form
  in that book.
- Metadata (beats, knowledge, tags) is scene-level while chunks are splits of
  a scene, so an entity named in a beat can live in an adjacent chunk; such
  items list both chunks.
- Raw location tags vary ("cemetery" vs "Dead Falls Cemetery"); `location_map`
  was used to union variants where they refer to the same place.

## Regenerating and verifying

```bash
# regenerate candidates (deterministic, read-only)
.venv/bin/python eval/build_golden_candidates.py

# verify the curated golden set (qtype routing, scope, chunk ids, citations)
.venv/bin/python eval/build_golden_candidates.py --verify

# verify any other items file
.venv/bin/python eval/build_golden_candidates.py --verify eval/golden_candidates.jsonl
```

The golden set is hand-curated: regenerating candidates does NOT overwrite
`golden_set.jsonl`.
