"""Query classification and retrieval planning.

Turns a natural-language question (plus optional --scope / --type flags)
into a QueryPlan the retriever can execute:

  temporal_knowledge : "what does X know …", "by the end of book N"
  sentiment          : "how does X feel about Y", "relationship between"
  continuity         : "plot holes", "contradictions", "unresolved"
  lookup             : "every scene where", "list all …"
  general            : everything else -> plain semantic search

Scope strings: "book:2", "book:1-3", "book:2,chapter:5".
When the question itself says "book N" / "chapter M", that becomes the
temporal bound unless an explicit --scope overrides it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_TEMPORAL = re.compile(
    r"\bwhat do(?:es)? \w+ know\b|\bknow about\b|\bby the (?:end|start|beginning) of\b"
    r"|\blearned\b|\baware of\b", re.I)
_SENTIMENT = re.compile(
    r"\bfeel(?:s|ings)? (?:about|toward)\b|\brelationship\b|\bsentiments?\b"
    r"|\bdynamic between\b|\bthink(?:s)? (?:of|about)\b", re.I)
_CONTINUITY = re.compile(
    r"\bplot holes?\b|\bcontinuity\b|\bcontradict\w*\b|\binconsistenc\w+\b"
    r"|\bunresolved\b|\bforeshadow\w*\b|\bpaid? off\b|\bresolved\b|\bloose (?:ends?|threads?)\b", re.I)
_LOOKUP = re.compile(
    r"\bevery (?:scene|chapter|time)\b|\blist (?:all|every)\b|\ball the (?:scenes|chapters)\b"
    r"|\bhow many (?:scenes|chapters|times)\b", re.I)

_BOOK_RE = re.compile(r"\bbook (\d+)\b", re.I)
_CHAPTER_RE = re.compile(r"\bchapter (\d+)\b", re.I)
# Quoted names or Capitalized First [Last] sequences — candidate character names.
_NAME_RE = re.compile(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+)?)\b")
_NAME_STOPWORDS = {
    "What", "Where", "When", "Who", "Why", "How", "Does", "Do", "Is", "Are",
    "Book", "Chapter", "Part", "The", "List", "Describe", "Has", "Have", "By",
    "At", "In", "Of", "And", "Or", "Any", "All", "Every", "Their", "His", "Her",
}


@dataclass
class Scope:
    book_min: int | None = None
    book_max: int | None = None
    chapter_max: int | None = None   # applies to book_max only

    def describe(self) -> str:
        if self.book_min is None and self.book_max is None:
            return "the whole series"
        lo = self.book_min or 1
        hi = self.book_max if self.book_max is not None else "end"
        s = f"books {lo}-{hi}" if lo != hi else f"book {hi}"
        if self.chapter_max is not None:
            s += f" up to chapter {self.chapter_max}"
        return s


@dataclass
class QueryPlan:
    question: str
    qtype: str                      # temporal_knowledge|sentiment|continuity|lookup|general
    scope: Scope = field(default_factory=Scope)
    characters: list[str] = field(default_factory=list)  # names found in the question


def parse_scope(scope_str: str) -> Scope:
    """"book:1-3" / "book:2" / "book:2,chapter:5" -> Scope."""
    scope = Scope()
    for part in scope_str.split(","):
        key, _, value = part.strip().partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key == "book":
            if "-" in value:
                lo, hi = value.split("-", 1)
                scope.book_min, scope.book_max = int(lo), int(hi)
            else:
                scope.book_min = scope.book_max = int(value)
        elif key == "chapter":
            scope.chapter_max = int(value)
    return scope


def classify(question: str, scope_str: str | None = None,
             forced_type: str | None = None) -> QueryPlan:
    if forced_type:
        qtype = forced_type
    elif _CONTINUITY.search(question):
        qtype = "continuity"
    elif _TEMPORAL.search(question):
        qtype = "temporal_knowledge"
    elif _SENTIMENT.search(question):
        qtype = "sentiment"
    elif _LOOKUP.search(question):
        qtype = "lookup"
    else:
        qtype = "general"

    if scope_str:
        scope = parse_scope(scope_str)
    else:
        # Derive a bound from the question itself ("by the end of book 2").
        scope = Scope()
        books = [int(m) for m in _BOOK_RE.findall(question)]
        if books:
            scope.book_max = max(books)
            if len(books) > 1:
                scope.book_min = min(books)
        chapters = [int(m) for m in _CHAPTER_RE.findall(question)]
        if chapters and scope.book_max is not None:
            scope.chapter_max = max(chapters)

    names = []
    for m in _NAME_RE.findall(question):
        first = m.split()[0]
        if first not in _NAME_STOPWORDS and m not in names:
            names.append(m)

    return QueryPlan(question=question, qtype=qtype, scope=scope, characters=names)
