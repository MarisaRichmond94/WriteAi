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
import time

from .notes import NOTE_TABLES, render_note
from .query_prep import expand_characters
from .query_router import QueryPlan, Scope

log = logging.getLogger(__name__)


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
        # Keyword fusion only pays off on entity-bearing queries (eval: lookup
        # and temporal_knowledge improve; continuity/general regress because
        # BM25's literal matches dilute the semantic list on abstract wording).
        if (self.cfg.enable_hybrid_search
                and plan.qtype in ("lookup", "temporal_knowledge")):
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
        where, params = _scope_sql(plan.scope)
        aliases = self._alias_map(plan.characters)
        notes = []
        for name in plan.characters or [""]:
            clause, likes = _like_clause("k.character", aliases.get(name, [name]))
            rows = self.db.execute(
                f"""SELECT c.book_number, c.chapter_number, k.character, k.learns
                    FROM character_knowledge k JOIN chunks c ON c.chunk_id = k.chunk_id
                    WHERE {clause} AND {where}
                    ORDER BY c.book_number, c.chapter_number, c.chunk_index""",
                [*likes, *params]).fetchall()
            notes.extend(
                f"[Book {b}, Ch {ch}] {who} learns: {fact}"
                for b, ch, who, fact in rows)
        if len(notes) > 400:  # keep the prompt sane on very broad questions
            log.info("truncating knowledge notes: %d -> 400", len(notes))
            notes = notes[:400]
        return self._semantic(plan), notes

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
                beats = json.loads(meta_json).get("emotional_beats", [])
                notes.extend(f"[Book {b}, Ch {ch}] {beat}" for beat in beats)
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

        # a chunk's beats "tie" the characters when they mention at least two
        # of the named characters (or the single one, on one-name questions)
        need = min(2, len(plan.characters))

        def ties(meta_json: str | None) -> bool:
            text = " ".join(beats_of(meta_json)).lower()
            matched = sum(1 for n in plan.characters
                          if any(a.lower() in text for a in aliases.get(n, [n])))
            return matched >= need

        beats_by_id = {r[0]: beats_of(r[7]) for r in rows}
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

        docs = []
        for e in union:
            cid = e["chunk_id"]
            if cid not in beats_by_id:  # semantic hit outside the SQL rows
                row = self.db.execute(
                    "SELECT metadata_json FROM chunks WHERE chunk_id = ?",
                    (cid,)).fetchone()
                beats_by_id[cid] = beats_of(row[0]) if row else []
            beats = beats_by_id[cid]
            if beats:
                docs.extend({**e, "text": b} for b in beats)
            else:
                docs.append(e)
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
                return self._semantic(plan, top_k=5), notes
        where, params = _scope_sql(plan.scope)
        notes = []
        for table, column, kind in NOTE_TABLES:
            rows = self.db.execute(
                f"""SELECT c.book_number, c.chapter_number, t.{column}
                    FROM {table} t JOIN chunks c ON c.chunk_id = t.chunk_id
                    WHERE {where}
                    ORDER BY c.book_number, c.chapter_number, c.chunk_index""",
                params).fetchall()
            notes.extend(render_note(kind, b, ch, v) for b, ch, v in rows)
        # continuity leans on the aggregate; a few excerpts anchor the voice
        return self._semantic(plan, top_k=5), notes

    def _ranked_continuity_notes(self, plan: QueryPlan) -> list[str] | None:
        """Top continuity_notes_cap notes by semantic similarity to the
        question, re-sorted into chronological order (same line format as the
        unranked path — the notes collection stores the rendered lines).
        Returns None when the collection is empty so the caller falls back
        to the exact legacy behavior."""
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
            if len(kept) >= cap:
                break
        kept.sort()  # (book, chapter, text): chronological, deterministic ties
        return [text for _, _, text in kept]

    def _lookup(self, plan: QueryPlan) -> tuple[list[dict], list[str]]:
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
