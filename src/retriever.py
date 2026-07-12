"""Retrieval execution: turn a QueryPlan into excerpts + structured context.

Strategy per query type (see query_router):
  general            : semantic top-K, scope-filtered
  temporal_knowledge : character_knowledge facts up to the scope bound
                       + scope-filtered semantic search
  sentiment          : chunks where the named characters co-occur (SQLite)
                       with their emotional beats + semantic search
  continuity         : ALL foreshadowing + unresolved questions in scope
                       (structured aggregate; no embedding needed)
  lookup             : SQLite structured hits first, semantic as garnish

Everything returns the same shape so the answerer doesn't care which path
produced it: (excerpts, notes) where excerpts are text passages with
citation headers and notes are structured facts rendered as lines.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time

from .notes import NOTE_TABLES, pair_quotes, render_note, with_quote
from .query_prep import expand_characters
from .query_router import QueryPlan, Scope

log = logging.getLogger(__name__)

# ENABLE_FIRST_OCCURRENCE: header line prepended to the ledger notes so the
# answerer's FIRST_OCCURRENCE_INSTRUCTION can reference them explicitly.
FIRST_OCC_NOTES_HEADER = ("== EARLIEST KNOWLEDGE-LEDGER ENTRIES (chronological; "
                          "drawn from an exhaustive per-chunk index) ==")


def _like_clause(column: str, aliases: list[str]) -> tuple[str, list[str]]:
    """`column LIKE ?` for one alias, `(… OR … )` over several — parameterized
    only, never interpolating names into SQL. The single-alias form is exactly
    the pre-alias-resolution SQL, so the flag-off path is unchanged."""
    likes = [f"%{a}%" for a in aliases]
    if len(aliases) == 1:
        return f"{column} LIKE ?", likes
    return "(" + " OR ".join(f"{column} LIKE ?" for _ in aliases) + ")", likes


def _scope_sql(scope: Scope) -> tuple[str, list]:
    """WHERE fragment (on aliased table c) implementing the scope bound."""
    clauses, params = [], []
    if scope.book_min is not None:
        clauses.append("c.book_number >= ?")
        params.append(scope.book_min)
    if scope.book_max is not None:
        if scope.chapter_max is not None:
            clauses.append("(c.book_number < ? OR (c.book_number = ? AND c.chapter_number <= ?))")
            params.extend([scope.book_max, scope.book_max, scope.chapter_max])
        else:
            clauses.append("c.book_number <= ?")
            params.append(scope.book_max)
    return (" AND ".join(clauses) or "1=1"), params


def _scope_chroma(scope: Scope) -> dict | None:
    """Chroma `where` filter for the scope (chapter bound handled post-hoc)."""
    clauses = []
    if scope.book_min is not None:
        clauses.append({"book_number": {"$gte": scope.book_min}})
    if scope.book_max is not None:
        clauses.append({"book_number": {"$lte": scope.book_max}})
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def _within_scope(meta: dict, scope: Scope) -> bool:
    if scope.chapter_max is not None and scope.book_max is not None:
        if (meta.get("book_number") == scope.book_max
                and meta.get("chapter_number", 0) > scope.chapter_max):
            return False
    return True


def _rrf_fuse(semantic_hits: list[dict], keyword_hits: list[dict],
              k: int = 60) -> list[dict]:
    """Reciprocal Rank Fusion: score(chunk) = Σ 1/(k + rank) over both ranked
    lists (rank starts at 1). When a chunk appears in both, the semantic hit
    dict wins so its `distance` survives. Ties break on chunk_id (determinism).
    """
    scores: dict[str, float] = {}
    best: dict[str, dict] = {}
    for hit_list in (semantic_hits, keyword_hits):
        for rank, hit in enumerate(hit_list, 1):
            cid = hit["chunk_id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
            if cid not in best:  # semantic list first -> its dict wins
                best[cid] = hit
    return [best[cid] for cid in sorted(scores, key=lambda c: (-scores[c], c))]


# Interrogative templates the query types are phrased with (see query_router).
# Stripping them leaves the content words that actually appear in prose.
_QUERY_BOILERPLATE = re.compile(
    r"^(?:what|how|why|when|where|who)\s+(?:does|do|did|is|was|are|were|has|have)\s+"
    r"|^what\s+(?:happens|happened)\s+(?:when|to|in)\s+"
    r"|\b(?:know|learn|reveal|feel|think)s?\s+about\b"
    r"|\bin\s+this\s+(?:chapter|passage|scene)\b"
    r"|\bthis\s+(?:chapter|passage)\s+reveal(?:s)?\s+about\b",
    re.I)


def _strip_question_boilerplate(question: str) -> str:
    """Remove interrogative scaffolding, keep the content words. Applied
    repeatedly so stacked templates all fall away; returns "" when nothing
    but scaffolding is left (caller then skips the variant)."""
    prev = None
    text = question.strip().rstrip("?.! ")
    while text != prev:
        prev = text
        text = _QUERY_BOILERPLATE.sub(" ", text).strip()
    return " ".join(text.split())


def _header(meta: dict) -> str:
    ch = meta.get("chapter_number")
    parts = [f"Book {meta.get('book_number')} \"{meta.get('book_title')}\"",
             "Prologue" if ch == 0 else f"Chapter {ch}"]
    if meta.get("pov_character"):
        parts.append(f"POV {meta['pov_character']}")
    if meta.get("date_line"):
        parts.append(meta["date_line"])
    return ", ".join(str(p) for p in parts)


class Retriever:
    def __init__(self, cfg, store, embedder):
        self.cfg = cfg
        self.store = store
        self.embedder = embedder
        self._reranker = None

    @property
    def db(self):
        return self.store.db

    @property
    def reranker(self):
        """Lazy (mirrors server/deps.py): CLI queries that never rerank must
        not pay the cross-encoder model load."""
        if self._reranker is None:
            from .reranker import Reranker
            self._reranker = Reranker(self.cfg)
        return self._reranker

    def _alias_map(self, names: list[str]) -> dict[str, list[str]]:
        """name -> grounded alias list; identity mapping unless
        ENABLE_ALIAS_RESOLUTION is on. Only the SQL LIKE filters consume
        this — the semantic query text is never rewritten."""
        if self.cfg.enable_alias_resolution and names:
            return expand_characters(self.db, names)
        return {n: [n] for n in names}

    # ── entry point ─────────────────────────────────────────────────────────

    def retrieve(self, plan: QueryPlan) -> tuple[list[dict], list[str]]:
        """Returns (excerpts, notes). excerpts: [{header, text, chunk_id}]."""
        handler = {
            "temporal_knowledge": self._temporal,
            "sentiment": self._sentiment,
            "continuity": self._continuity,
            "lookup": self._lookup,
        }.get(plan.qtype, self._general)
        return handler(plan)

    # ── strategies ──────────────────────────────────────────────────────────

    def _semantic(self, plan: QueryPlan, top_k: int | None = None) -> list[dict]:
        top_k = top_k or self.cfg.top_k_results
        # over-fetch slightly so a post-hoc chapter filter can't starve us;
        # the reranker wants a deeper pool to rescore (it reorders pool -> top_k)
        pool_n = top_k * 2
        if self.cfg.enable_reranker:
            pool_n = max(self.cfg.rerank_candidates, top_k * 2)
        embedding = self.embedder.embed_query(plan.question)
        hits = self.store.semantic_search(embedding, pool_n,
                                          where=_scope_chroma(plan.scope))
        # MULTI_QUERY=strip: also search with the question's template
        # boilerplate removed ("What does X know about …" -> the topic words).
        # Interrogative framing pushes the query vector away from narrative
        # prose; the stripped variant recovers chunks the full question misses,
        # and the cross-encoder re-sorts the union.
        if os.environ.get("MULTI_QUERY") == "strip":
            alt = _strip_question_boilerplate(plan.question)
            if alt and alt.lower() != plan.question.lower():
                alt_hits = self.store.semantic_search(
                    self.embedder.embed_query(alt), pool_n,
                    where=_scope_chroma(plan.scope))
                hits = _rrf_fuse(hits, alt_hits)
        # Keyword fusion pays off on entity-bearing queries (eval: lookup and
        # temporal_knowledge improve). HYBRID_QTYPES extends it (e.g. general):
        # BM25's literal matches dilute the pool on abstract wording, which
        # only a strong reranker can afford to clean up.
        hybrid_qtypes = tuple(
            s.strip() for s in os.environ.get(
                "HYBRID_QTYPES", "lookup,temporal_knowledge").split(","))
        if (self.cfg.enable_hybrid_search
                and plan.qtype in hybrid_qtypes):
            keyword_hits = self.store.keyword_search(plan.question, pool_n,
                                                     plan.scope)
            hits = _rrf_fuse(hits, keyword_hits)  # also dedupes on chunk_id
        keep = pool_n if self.cfg.enable_reranker else top_k
        excerpts, seen = [], set()
        for h in hits:
            if not _within_scope(h["metadata"], plan.scope):
                continue
            if h["chunk_id"] in seen:
                continue
            seen.add(h["chunk_id"])
            m = h["metadata"]
            excerpts.append({"chunk_id": h["chunk_id"],
                             "header": _header(m),
                             "text": h["text"],
                             # extra fields for UI citations (answerer ignores)
                             "book_number": m.get("book_number"),
                             "book_title": m.get("book_title"),
                             "chapter_number": m.get("chapter_number"),
                             "pov_character": m.get("pov_character"),
                             "distance": h.get("distance")})
            if len(excerpts) >= keep:
                break
        if self.cfg.enable_reranker and len(excerpts) > 1:
            t0 = time.perf_counter()
            n_candidates = len(excerpts)
            excerpts = self.reranker.rerank(plan.question, excerpts, top_k)
            log.debug("rerank: %d candidates -> top %d in %.1f ms",
                      n_candidates, top_k, (time.perf_counter() - t0) * 1000)
        return excerpts[:top_k]

    def _general(self, plan: QueryPlan) -> tuple[list[dict], list[str]]:
        return self._semantic(plan), []

    def _temporal(self, plan: QueryPlan) -> tuple[list[dict], list[str]]:
        if (getattr(self.cfg, "enable_first_occurrence", False)
                and getattr(plan, "first_occurrence", False)
                and getattr(plan, "topic", None)):
            return self._first_occurrence(plan)
        where, params = _scope_sql(plan.scope)
        aliases = self._alias_map(plan.characters)
        notes = []
        for name in plan.characters or [""]:
            clause, likes = _like_clause("k.character", aliases.get(name, [name]))
            rows = self.db.execute(
                f"""SELECT c.book_number, c.chapter_number, k.character, k.learns,
                           k.source_quote
                    FROM character_knowledge k JOIN chunks c ON c.chunk_id = k.chunk_id
                    WHERE {clause} AND {where}
                    ORDER BY c.book_number, c.chapter_number, c.chunk_index""",
                [*likes, *params]).fetchall()
            notes.extend(
                f"[Book {b}, Ch {ch}] {who} learns: {with_quote(fact, quote)}"
                for b, ch, who, fact, quote in rows)
        if len(notes) > 400:  # keep the prompt sane on very broad questions
            log.info("truncating knowledge notes: %d -> 400", len(notes))
            notes = notes[:400]
        return self._semantic(plan), notes

    def _first_occurrence(self, plan: QueryPlan) -> tuple[list[dict], list[str]]:
        """ENABLE_FIRST_OCCURRENCE: "when does X first learn about Y".

        Semantic top-k cannot establish FIRSTNESS — the topic may appear in
        prose across 20+ chapters, mostly in other characters' POV, so the
        sample never proves which mention is earliest for X. Both halves of
        the answer exist mechanically:

          notes    — the earliest character_knowledge ledger rows where X's
                     `learns` mentions the topic, in chronological order,
                     under FIRST_OCC_NOTES_HEADER (never truncated/reordered
                     by the generic 400-cap: this branch caps at 30).
          excerpts — the earliest prose chunks containing the topic where X
                     is on the page, PREPENDED before the usual semantic
                     hits (normal excerpt shape, so citations/quotes work).

        Prose candidates prefer X's own POV chunks (strongest evidence of
        first exposure) and only then chunks where X is tagged present — the
        `characters` side table also tags mere narration mentions, so a flat
        chronological OR would surface scenes X never witnessed. A word-
        boundary post-filter drops LIKE substring false positives (topic
        "Black Hand" must not match "black handle").
        """
        where, params = _scope_sql(plan.scope)
        aliases = self._alias_map(plan.characters)
        topic = plan.topic

        # ── (a) earliest knowledge-ledger entries ────────────────────────────
        def ledger_rows(learns_clause: str, learns_params: list[str]) -> list:
            rows = []
            for name in plan.characters or [""]:
                clause, likes = _like_clause("k.character",
                                             aliases.get(name, [name]))
                rows.extend(self.db.execute(
                    f"""SELECT c.book_number, c.chapter_number, c.chunk_index,
                               k.character, k.learns, k.source_quote
                        FROM character_knowledge k
                        JOIN chunks c ON c.chunk_id = k.chunk_id
                        WHERE {clause} AND {learns_clause} AND {where}
                        ORDER BY c.book_number, c.chapter_number, c.chunk_index""",
                    [*likes, *learns_params, *params]).fetchall())
            rows.sort(key=lambda r: (r[0], r[1], r[2]))
            return rows

        rows = ledger_rows("k.learns LIKE ?", [f"%{topic}%"])
        if len(rows) < 3:
            # tolerant fallback: AND the topic tokens ("Black" AND "Hand")
            tokens = [t for t in re.findall(r"[\w'’-]+", topic)
                      if t.lower() not in ("the", "a", "an", "of")]
            if len(tokens) > 1:
                rows = ledger_rows(
                    " AND ".join("k.learns LIKE ?" for _ in tokens),
                    [f"%{t}%" for t in tokens])
        notes = []
        if rows:
            notes.append(FIRST_OCC_NOTES_HEADER)
            notes.extend(
                f"[Book {b}, Ch {ch}] {who} learns: {with_quote(fact, quote)}"
                for b, ch, _, who, fact, quote in rows[:30])

        # ── (b) earliest prose mentions, then the usual semantic hits ───────
        char_sql, char_likes = "", []
        if plan.characters:
            names = [a for n in plan.characters for a in aliases.get(n, [n])]
            pov_clause, pov_likes = _like_clause("c.pov_character", names)
            tag_clause, tag_likes = _like_clause("ch.name", names)
            char_sql = (f" AND ({pov_clause} OR EXISTS "
                        f"(SELECT 1 FROM characters ch "
                        f"WHERE ch.chunk_id = c.chunk_id AND {tag_clause}))")
            char_likes = [*pov_likes, *tag_likes]
        chunk_rows = self.db.execute(
            f"""SELECT c.chunk_id, c.book_number, c.book_title,
                       c.chapter_number, c.pov_character, c.date_line, c.text
                FROM chunks c
                WHERE c.text LIKE ?{char_sql} AND {where}
                ORDER BY c.book_number, c.chapter_number, c.chunk_index""",
            [f"%{topic}%", *char_likes, *params]).fetchall()
        topic_re = re.compile(r"(?<!\w)" + re.escape(topic) + r"(?!\w)", re.I)
        pov_names = ([a.lower() for n in plan.characters
                      for a in aliases.get(n, [n])])

        def is_pov(pov: str | None) -> bool:
            return bool(pov) and any(a in pov.lower() for a in pov_names)

        prose = []
        for pov_only in (True, False) if pov_names else (False,):
            for cid, bn, bt, ch, pov, dl, text in chunk_rows:
                if not topic_re.search(text):
                    continue
                if pov_names and is_pov(pov) != pov_only:
                    continue
                if any(e["chunk_id"] == cid for e in prose):
                    continue
                prose.append({"chunk_id": cid,
                              "header": _header({"book_number": bn,
                                                 "book_title": bt,
                                                 "chapter_number": ch,
                                                 "pov_character": pov,
                                                 "date_line": dl}),
                              "text": text,
                              "book_number": bn, "book_title": bt,
                              "chapter_number": ch, "pov_character": pov,
                              "distance": None})
                if len(prose) >= 4:
                    break
            if len(prose) >= 4:
                break
        prose_ids = {e["chunk_id"] for e in prose}
        semantic = [e for e in self._semantic(plan)
                    if e["chunk_id"] not in prose_ids]
        return prose + semantic, notes

    def _sentiment(self, plan: QueryPlan) -> tuple[list[dict], list[str]]:
        where, params = _scope_sql(plan.scope)
        notes = []
        if plan.characters:
            aliases = self._alias_map(plan.characters)
            clauses, likes = [], []
            for n in plan.characters:
                clause, ls = _like_clause("name", aliases.get(n, [n]))
                clauses.append(
                    f"c.chunk_id IN (SELECT chunk_id FROM characters WHERE {clause})")
                likes.extend(ls)
            like_join = " AND ".join(clauses)
            rows = self.db.execute(
                f"""SELECT c.chunk_id, c.book_number, c.chapter_number, c.metadata_json
                    FROM chunks c WHERE {like_join} AND {where}
                    ORDER BY c.book_number, c.chapter_number, c.chunk_index""",
                [*likes, *params]).fetchall()
            for cid, b, ch, meta_json in rows:
                if not meta_json:
                    continue
                meta = json.loads(meta_json)
                notes.extend(
                    f"[Book {b}, Ch {ch}] {with_quote(beat, quote)}"
                    for beat, quote in pair_quotes(
                        meta.get("emotional_beats", []),
                        meta.get("emotional_beat_quotes")))
            if len(notes) > 400:
                notes = notes[:400]
            if self.cfg.enable_sentiment_v2:
                return self._sentiment_v2_excerpts(plan, where, params, aliases), notes
        return self._semantic(plan), notes

    def _sentiment_v2_excerpts(self, plan: QueryPlan, where: str, params: list,
                               aliases: dict[str, list[str]]) -> list[dict]:
        """SQL-first excerpt pool for sentiment questions (ENABLE_SENTIMENT_V2).

        Eval finding: the chunks that answer "how does X feel about Y" sit at
        semantic rank 48-300+, so no reranker over a semantic pool can surface
        them — but they are trivially findable structurally: X and Y co-occur
        in the `characters` side table and/or an extracted emotional beat
        names them both.

        Candidate pool (chronological within each tier, most specific first):
          1. all named characters co-occur AND the beats tie them together
          2. beats tie only (extraction sometimes misses a character tag)
          3. co-occurrence only
        capped at rerank_candidates by round-robin across books, so a
        series-wide question keeps candidates from every book instead of only
        the earliest chapters; then unioned with the semantic hits.

        Ranking: with ENABLE_RERANKER on, every emotional beat becomes its own
        cross-encoder scoring doc (chunks without beats score on their text)
        and the full ordering is deduped by chunk_id — a chunk ranks as its
        best beat. Beats are the distilled emotional content; scoring whole
        prose passages buries the signal (eval: hit@k 0.5 vs 1.0 on the
        sentiment set). With the reranker flag off we keep concerns separate
        and do NOT load the cross-encoder here either: SQL candidates come
        first in chronological order, then the semantic hits, cut to top_k.

        Beat scoring docs stay the beat SUMMARY only, even now that beats can
        carry a verbatim source_quote — appending the quote might improve the
        cross-encoder signal, but that is an eval-gated follow-up, not a side
        effect of the quote-extraction work (this keeps sentiment v2 behavior
        bit-identical whether quotes are present or absent).
        """
        top_k = self.cfg.top_k_results
        cols = """c.chunk_id, c.book_number, c.book_title, c.chapter_number,
                  c.pov_character, c.date_line, c.text, c.metadata_json"""
        clauses, likes = [], []
        for n in plan.characters:
            clause, ls = _like_clause("name", aliases.get(n, [n]))
            clauses.append(
                f"c.chunk_id IN (SELECT chunk_id FROM characters WHERE {clause})")
            likes.extend(ls)
        order = "ORDER BY c.book_number, c.chapter_number, c.chunk_index"
        # every chunk where ANY named character appears (superset of tier 3)
        rows = self.db.execute(
            f"""SELECT {cols} FROM chunks c
                WHERE ({' OR '.join(clauses)}) AND {where} {order}""",
            [*likes, *params]).fetchall()
        all_ids = {r[0] for r in self.db.execute(
            f"""SELECT c.chunk_id FROM chunks c
                WHERE {' AND '.join(clauses)} AND {where}""",
            [*likes, *params]).fetchall()}

        def beats_of(meta_json: str | None) -> list[str]:
            return json.loads(meta_json).get("emotional_beats", []) if meta_json else []

        # Scoring-doc text for the cross-encoder (SENTIMENT_RERANK_DOCS=
        # beats+quotes): the beat summary plus its verbatim manuscript quote —
        # distilled signal plus literal prose the question's content words can
        # match. Tie-tier detection above always uses the bare summaries.
        def beat_docs_of(meta_json: str | None) -> list[str]:
            if not meta_json:
                return []
            meta = json.loads(meta_json)
            beats = meta.get("emotional_beats", [])
            if os.environ.get("SENTIMENT_RERANK_DOCS") == "beats+quotes":
                return [with_quote(b, q) for b, q in
                        pair_quotes(beats, meta.get("emotional_beat_quotes"))]
            return beats

        # a chunk's beats "tie" the characters when they mention at least two
        # of the named characters (or the single one, on one-name questions)
        need = min(2, len(plan.characters))

        def ties(meta_json: str | None) -> bool:
            text = " ".join(beats_of(meta_json)).lower()
            matched = sum(1 for n in plan.characters
                          if any(a.lower() in text for a in aliases.get(n, [n])))
            return matched >= need

        beats_by_id = {r[0]: beat_docs_of(r[7]) for r in rows}
        tie_ids = {r[0] for r in rows if ties(r[7])}
        pool, seen = [], set()
        for keep in (lambda cid: cid in all_ids and cid in tie_ids,
                     lambda cid: cid in tie_ids,
                     lambda cid: cid in all_ids):
            for r in rows:
                if r[0] not in seen and keep(r[0]):
                    seen.add(r[0])
                    cid, bn, bt, ch, pov, dl, text, _ = r
                    pool.append({"chunk_id": cid,
                                 "header": _header({"book_number": bn,
                                                    "book_title": bt,
                                                    "chapter_number": ch,
                                                    "pov_character": pov,
                                                    "date_line": dl}),
                                 "text": text,
                                 "book_number": bn, "book_title": bt,
                                 "chapter_number": ch, "pov_character": pov,
                                 "distance": None})
            if len(pool) >= self.cfg.rerank_candidates:
                break
        if len(pool) > self.cfg.rerank_candidates:
            by_book: dict[int, list[dict]] = {}
            for e in pool:
                by_book.setdefault(e["book_number"], []).append(e)
            queues = [by_book[b] for b in sorted(by_book)]
            pool = []
            while len(pool) < self.cfg.rerank_candidates:
                for q in queues:
                    if q and len(pool) < self.cfg.rerank_candidates:
                        pool.append(q.pop(0))

        semantic = self._semantic(plan)
        pool_ids = {e["chunk_id"] for e in pool}
        union = pool + [e for e in semantic if e["chunk_id"] not in pool_ids]

        if not self.cfg.enable_reranker:
            # deliberate fallback (see docstring): structural hits first,
            # oldest to newest, then whatever semantic search added
            pool.sort(key=lambda e: (e["book_number"], e["chapter_number"],
                                     e["chunk_id"]))
            return (pool + [e for e in semantic
                            if e["chunk_id"] not in pool_ids])[:top_k]

        # Scoring-doc shape for the cross-encoder (SENTIMENT_RERANK_DOCS):
        #   beats        — beat summaries only (legacy; tuned for MiniLM)
        #   beats+quotes — summary plus its verbatim manuscript quote: keeps
        #                  the distilled signal but adds literal prose the
        #                  question's content words can match
        #   prose        — the full chunk text (no beat expansion)
        doc_mode = os.environ.get("SENTIMENT_RERANK_DOCS", "beats")
        docs = []
        for e in union:
            cid = e["chunk_id"]
            if cid not in beats_by_id:  # semantic hit outside the SQL rows
                row = self.db.execute(
                    "SELECT metadata_json FROM chunks WHERE chunk_id = ?",
                    (cid,)).fetchone()
                beats_by_id[cid] = beat_docs_of(row[0]) if row else []
            beats = beats_by_id[cid]
            if doc_mode == "prose" or not beats:
                docs.append(e)
            else:
                docs.extend({**e, "text": b} for b in beats)
        t0 = time.perf_counter()
        ranked = self.reranker.rerank(plan.question, docs, len(docs))
        log.debug("sentiment_v2 rerank: %d beat docs over %d chunks in %.1f ms",
                  len(docs), len(union), (time.perf_counter() - t0) * 1000)
        by_id = {e["chunk_id"]: e for e in union}
        out, out_seen = [], set()
        for d in ranked:
            if d["chunk_id"] not in out_seen:
                out_seen.add(d["chunk_id"])
                out.append(by_id[d["chunk_id"]])
                if len(out) >= top_k:
                    break
        return out

    def _continuity(self, plan: QueryPlan) -> tuple[list[dict], list[str]]:
        if self.cfg.enable_note_ranking and self.cfg.continuity_notes_cap > 0:
            notes = self._ranked_continuity_notes(plan)
            if notes is not None:
                # full top_k, not the legacy 5: capped notes leave prompt room,
                # and "this chapter" questions need the chapter's own prose in
                # context to anchor which thread the question is about
                return self._semantic(plan), notes
        where, params = _scope_sql(plan.scope)
        notes = []
        for table, column, kind in NOTE_TABLES:
            rows = self.db.execute(
                f"""SELECT c.book_number, c.chapter_number, t.{column},
                           t.source_quote
                    FROM {table} t JOIN chunks c ON c.chunk_id = t.chunk_id
                    WHERE {where}
                    ORDER BY c.book_number, c.chapter_number, c.chunk_index""",
                params).fetchall()
            notes.extend(render_note(kind, b, ch, v, q) for b, ch, v, q in rows)
        # continuity leans on the aggregate; a few excerpts anchor the voice
        return self._semantic(plan, top_k=5), notes

    def _ranked_continuity_notes(self, plan: QueryPlan) -> list[str] | None:
        """Top continuity_notes_cap notes by relevance to the question (same
        line format as the unranked path — the notes collection stores the
        rendered lines). Returns None when the collection is empty so the
        caller falls back to the exact legacy behavior.

        With the reranker enabled, the bi-encoder shortlist is rescored by the
        cross-encoder and emitted MOST RELEVANT FIRST under a header saying so:
        similar threads recur across five books, and chronological order gives
        the answerer no way to tell which note the question is actually about.
        Reranker off -> bi-encoder ranking, chronological order (legacy)."""
        if self.store.notes_count() == 0:
            log.warning("ENABLE_NOTE_RANKING is on but the notes collection is "
                        "empty — run scripts/backfill_note_embeddings.py; "
                        "falling back to unranked continuity notes")
            return None
        cap = self.cfg.continuity_notes_cap
        embedding = self.embedder.embed_query(plan.question)
        # over-fetch so the post-hoc chapter filter can't starve the cap
        hits = self.store.note_search(embedding, cap * 2,
                                      where=_scope_chroma(plan.scope))
        kept = []
        for text, meta in hits:
            if not _within_scope(meta, plan.scope):
                continue
            kept.append((meta.get("book_number", 0),
                         meta.get("chapter_number", 0), text))
        if not self.cfg.enable_reranker:
            kept = kept[:cap]
            kept.sort()  # (book, chapter, text): chronological, deterministic
            return [text for _, _, text in kept]
        docs = [{"chunk_id": str(i), "header": "", "text": text}
                for i, (_, _, text) in enumerate(kept)]
        t0 = time.perf_counter()
        ranked = self.reranker.rerank(plan.question, docs, cap)
        log.debug("continuity note rerank: %d notes -> top %d in %.1f ms",
                  len(docs), cap, (time.perf_counter() - t0) * 1000)
        return ["== NOTES RANKED BY RELEVANCE TO THE QUESTION, MOST RELEVANT "
                "FIRST =="] + [d["text"] for d in ranked]

    def _lookup(self, plan: QueryPlan) -> tuple[list[dict], list[str]]:
        if re.search(r"\bmention", plan.question, re.I) and plan.characters:
            result = self._mention_scan(plan)
            if result is not None:
                return result
        where, params = _scope_sql(plan.scope)
        aliases = self._alias_map(plan.characters)
        notes = []
        for name in plan.characters:
            clause, likes = _like_clause("t.name", aliases.get(name, [name]))
            for table, label in (("locations", "location"), ("characters", "character")):
                rows = self.db.execute(
                    f"""SELECT DISTINCT c.book_number, c.book_title, c.chapter_number, t.name
                        FROM {table} t JOIN chunks c ON c.chunk_id = t.chunk_id
                        WHERE {clause} AND {where}
                        ORDER BY c.book_number, c.chapter_number""",
                    [*likes, *params]).fetchall()
                notes.extend(
                    f"[Book {b} \"{title}\", Ch {ch}] {label} match: {n}"
                    for b, title, ch, n in rows)
        if len(notes) > 500:
            notes = notes[:500]
        return self._semantic(plan, top_k=8), notes

    # Enumeration questions can name a character with a large tag footprint;
    # past this many literal-mention chunks the exhaustive-excerpt promise
    # gets too expensive and the legacy tag-notes path handles it instead.
    _MENTION_SCAN_CAP = 24

    def _mention_scan(self, plan: QueryPlan) -> tuple[list[dict], list[str]] | None:
        """"List every scene where X is mentioned": a mention is the name
        appearing in prose, which the corpus answers exactly with a text scan —
        semantic sampling can only approximate it (it under-enumerates, and the
        alias-expanded tag notes over-enumerate chapters where the name never
        appears on the page). Matches the literal asked-for name only, word-
        bounded ("Bri" must not match "Brielle"), chronological. Returns None
        (legacy path) when nothing matches or the footprint exceeds the cap."""
        where, params = _scope_sql(plan.scope)
        matched, seen = [], set()
        for name in plan.characters:
            name_re = re.compile(r"(?<!\w)" + re.escape(name) + r"(?!\w)")
            rows = self.db.execute(
                f"""SELECT c.chunk_id, c.book_number, c.book_title,
                           c.chapter_number, c.pov_character, c.date_line, c.text
                    FROM chunks c WHERE c.text LIKE ? AND {where}
                    ORDER BY c.book_number, c.chapter_number, c.chunk_index""",
                [f"%{name}%", *params]).fetchall()
            for cid, bn, bt, ch, pov, dl, text in rows:
                if cid in seen or not name_re.search(text):
                    continue
                seen.add(cid)
                matched.append({"chunk_id": cid,
                                "header": _header({"book_number": bn,
                                                   "book_title": bt,
                                                   "chapter_number": ch,
                                                   "pov_character": pov,
                                                   "date_line": dl}),
                                "text": text,
                                "book_number": bn, "book_title": bt,
                                "chapter_number": ch, "pov_character": pov,
                                "distance": None})
        if not matched or len(matched) > self._MENTION_SCAN_CAP:
            return None
        matched.sort(key=lambda e: (e["book_number"], e["chapter_number"],
                                    e["chunk_id"]))
        names = " / ".join(plan.characters)
        notes = [f"The {len(matched)} excerpts below are EVERY passage in "
                 f"{plan.scope.describe()} where \"{names}\" appears verbatim "
                 f"— the list is exhaustive; enumerate each excerpt as its own "
                 f"scene and do not add scenes from memory."]
        return matched, notes

    # ── export-mode dossiers ─────────────────────────────────────────────────

    def character_dossier(self, name: str, require_all: list[str] | None = None,
                          max_notes: int = 900) -> list[str]:
        """Chronological structured notes for a character (or a pair when
        require_all is given): key events, knowledge gained, emotional beats."""
        names = require_all or [name]
        alias_map = self._alias_map(names)
        clauses, likes = [], []
        for n in names:
            clause, ls = _like_clause("name", alias_map.get(n, [n]))
            clauses.append(
                f"c.chunk_id IN (SELECT chunk_id FROM characters WHERE {clause})")
            likes.extend(ls)
        like_join = " AND ".join(clauses)
        # every alias participates in the LEARNS attribution check below
        # (flag off: alias_map is the identity, so this is exactly `names`)
        match_names = [a for n in names for a in alias_map.get(n, [n])]
        rows = self.db.execute(
            f"""SELECT c.book_number, c.chapter_number, c.metadata_json
                FROM chunks c WHERE {like_join}
                ORDER BY c.book_number, c.chapter_number, c.chunk_index""",
            likes).fetchall()

        notes = []
        for b, ch, meta_json in rows:
            if not meta_json:
                continue
            meta = json.loads(meta_json)
            cite = f"[Book {b}, Ch {ch}]"
            notes.extend(f"{cite} EVENT: {e}" for e in meta.get("key_events", []))
            for who, facts in meta.get("character_knowledge_updates", {}).items():
                if any(n.split()[0].lower() in who.lower() for n in match_names):
                    notes.extend(f"{cite} {who} LEARNS: {f}" for f in facts)
            notes.extend(f"{cite} EMOTION: {e}" for e in meta.get("emotional_beats", []))
        if len(notes) > max_notes:
            log.info("truncating dossier notes: %d -> %d", len(notes), max_notes)
            notes = notes[:max_notes]
        return notes
