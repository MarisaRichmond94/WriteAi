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

from .query_router import QueryPlan, Scope

log = logging.getLogger(__name__)


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


def _header(meta: dict) -> str:
    parts = [f"Book {meta.get('book_number')} \"{meta.get('book_title')}\"",
             f"Chapter {meta.get('chapter_number')}"]
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
        self.db = store.db

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
        embedding = self.embedder.embed_query(plan.question)
        # over-fetch slightly so a post-hoc chapter filter can't starve us
        hits = self.store.semantic_search(embedding, top_k * 2,
                                          where=_scope_chroma(plan.scope))
        excerpts = []
        for h in hits:
            if not _within_scope(h["metadata"], plan.scope):
                continue
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
            if len(excerpts) >= top_k:
                break
        return excerpts

    def _general(self, plan: QueryPlan) -> tuple[list[dict], list[str]]:
        return self._semantic(plan), []

    def _temporal(self, plan: QueryPlan) -> tuple[list[dict], list[str]]:
        where, params = _scope_sql(plan.scope)
        notes = []
        for name in plan.characters or [""]:
            rows = self.db.execute(
                f"""SELECT c.book_number, c.chapter_number, k.character, k.learns
                    FROM character_knowledge k JOIN chunks c ON c.chunk_id = k.chunk_id
                    WHERE k.character LIKE ? AND {where}
                    ORDER BY c.book_number, c.chapter_number, c.chunk_index""",
                [f"%{name}%", *params]).fetchall()
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
            like_join = " AND ".join(
                f"c.chunk_id IN (SELECT chunk_id FROM characters WHERE name LIKE ?)"
                for _ in plan.characters)
            likes = [f"%{n}%" for n in plan.characters]
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
        return self._semantic(plan), notes

    def _continuity(self, plan: QueryPlan) -> tuple[list[dict], list[str]]:
        where, params = _scope_sql(plan.scope)
        notes = []
        for table, column, label in (("foreshadowing", "detail", "FORESHADOWING"),
                                     ("unresolved_questions", "question", "QUESTION")):
            rows = self.db.execute(
                f"""SELECT c.book_number, c.chapter_number, t.{column}
                    FROM {table} t JOIN chunks c ON c.chunk_id = t.chunk_id
                    WHERE {where}
                    ORDER BY c.book_number, c.chapter_number, c.chunk_index""",
                params).fetchall()
            notes.extend(f"[Book {b}, Ch {ch}] {label}: {v}" for b, ch, v in rows)
        # continuity leans on the aggregate; a few excerpts anchor the voice
        return self._semantic(plan, top_k=5), notes

    def _lookup(self, plan: QueryPlan) -> tuple[list[dict], list[str]]:
        where, params = _scope_sql(plan.scope)
        notes = []
        for name in plan.characters:
            for table, label in (("locations", "location"), ("characters", "character")):
                rows = self.db.execute(
                    f"""SELECT DISTINCT c.book_number, c.book_title, c.chapter_number, t.name
                        FROM {table} t JOIN chunks c ON c.chunk_id = t.chunk_id
                        WHERE t.name LIKE ? AND {where}
                        ORDER BY c.book_number, c.chapter_number""",
                    [f"%{name}%", *params]).fetchall()
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
        like_join = " AND ".join(
            "c.chunk_id IN (SELECT chunk_id FROM characters WHERE name LIKE ?)"
            for _ in names)
        rows = self.db.execute(
            f"""SELECT c.book_number, c.chapter_number, c.metadata_json
                FROM chunks c WHERE {like_join}
                ORDER BY c.book_number, c.chapter_number, c.chunk_index""",
            [f"%{n}%" for n in names]).fetchall()

        notes = []
        for b, ch, meta_json in rows:
            if not meta_json:
                continue
            meta = json.loads(meta_json)
            cite = f"[Book {b}, Ch {ch}]"
            notes.extend(f"{cite} EVENT: {e}" for e in meta.get("key_events", []))
            for who, facts in meta.get("character_knowledge_updates", {}).items():
                if any(n.split()[0].lower() in who.lower() for n in names):
                    notes.extend(f"{cite} {who} LEARNS: {f}" for f in facts)
            notes.extend(f"{cite} EMOTION: {e}" for e in meta.get("emotional_beats", []))
        if len(notes) > max_notes:
            log.info("truncating dossier notes: %d -> %d", len(notes), max_notes)
            notes = notes[:max_notes]
        return notes
