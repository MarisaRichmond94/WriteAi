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

# ── first-occurrence questions ("when does X first learn about Y") ──────────
# These always carried routing metadata (first_occurrence/topic on the plan);
# retrieval/answering only consume it when ENABLE_FIRST_OCCURRENCE is on.
_FIRST_VERBS = r"(?:learns?|hears?|finds? out|discovers?|sees?|encounters?|reads?)"
# "when/where does|did X first learn|hear|... (about|of|that) Y"
_FIRST_LEARN = re.compile(
    r"\b(?:when|where)\s+(?:do(?:es)?|did)\s+(?P<who>.+?)\s+first\s+"
    + _FIRST_VERBS + r"(?:\s+(?:about|of|that))?\b\s*(?P<obj>[^?.!]*)", re.I)
# "what is/was the first time X sees|hears|... Y"
_FIRST_TIME = re.compile(
    r"\bwhat(?:'s|’s|\s+is|\s+was)\s+the\s+first\s+time\s+(?:that\s+)?(?P<who>.+?)\s+"
    + _FIRST_VERBS + r"(?:\s+(?:about|of|that))?\b\s*(?P<obj>[^?.!]*)", re.I)
# "when/where is|was Y first mentioned/introduced" — no character X
_FIRST_MENTION = re.compile(
    r"\b(?:when|where)\s+(?:is|was)\s+(?P<obj>.+?)\s+first\s+"
    r"(?:mentioned|introduced|referenced|named|described)\b", re.I)

# Leading fillers stripped off the about-object ("the existence of The Black
# Hand" -> "The Black Hand"). Applied repeatedly until stable.
_TOPIC_FILLERS = re.compile(
    r"^(?:the\s+(?:existence|truth|idea|news|fact|meaning|details?|concept)\s+"
    r"(?:of|about|behind|that)\s+|that\s+|about\s+|of\s+)", re.I)
# Trailing scope phrasing stripped ("... in book 4" belongs to Scope, not topic).
_TOPIC_TRAILING_SCOPE = re.compile(
    r"\s+(?:in|by|before|after|during|until)\s+(?:book|chapter)\s+\d+.*$", re.I)
# Multiword Title-Case run — the preferred topic form ("The Black Hand").
_TITLE_RUN = re.compile(r"\b[A-Z][\w'’-]*(?: [A-Z][\w'’-]*)+\b")


def _clean_topic(obj: str) -> str | None:
    """Normalize the about-object of a first-occurrence question into a topic
    string suitable for LIKE matching: strip fillers and scope tails, then
    prefer the longest Title-Case multiword phrase (proper noun) if present."""
    obj = obj.strip().strip('"“”').rstrip("?.!,;: ").strip()
    obj = _TOPIC_TRAILING_SCOPE.sub("", obj).strip()
    while True:
        stripped = _TOPIC_FILLERS.sub("", obj)
        if stripped == obj:
            break
        obj = stripped
    obj = obj.rstrip("?.!,;: ").strip()
    if not obj:
        return None
    runs = _TITLE_RUN.findall(obj)
    if runs:
        return max(runs, key=len)
    return re.sub(r"^(?:the|a|an)\s+", "", obj, flags=re.I).strip() or None

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
    # "when does X first learn about Y" metadata; consumed by the retriever /
    # answerer only when ENABLE_FIRST_OCCURRENCE is on (harmless otherwise).
    first_occurrence: bool = False
    topic: str | None = None        # the about-object Y ("The Black Hand")


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


def _extract_names(text: str) -> list[str]:
    names = []
    for m in _NAME_RE.findall(text):
        first = m.split()[0]
        if first not in _NAME_STOPWORDS and m not in names:
            names.append(m)
    return names


def classify(question: str, scope_str: str | None = None,
             forced_type: str | None = None) -> QueryPlan:
    # First-occurrence detection ("when does X first learn about Y"). The
    # match only counts when a usable topic Y could be extracted.
    first_who: str | None = None
    first_topic: str | None = None
    m = _FIRST_LEARN.search(question) or _FIRST_TIME.search(question)
    if m:
        first_topic = _clean_topic(m.group("obj"))
        first_who = m.group("who")
    else:
        m = _FIRST_MENTION.search(question)
        if m:  # "when is Y first mentioned" — Y is the topic, no character X
            first_topic = _clean_topic(m.group("obj"))
    first_occurrence = first_topic is not None

    if forced_type:
        qtype = forced_type
    elif _CONTINUITY.search(question):
        qtype = "continuity"
    elif first_occurrence:
        qtype = "temporal_knowledge"
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
        # Enumerations are locative, not cumulative: "in book 4, list every
        # scene…" means book 4 exactly, unlike temporal questions where a book
        # mention is an upper bound on accumulated knowledge.
        if qtype == "lookup" and scope.book_max is not None and scope.book_min is None:
            scope.book_min = scope.book_max

    if first_occurrence:
        # Character = the X in the first-occurrence pattern. This fixes the
        # generic parser mangling topic words into names (e.g. "the existence
        # of The Black Hand" -> ['Noah', 'Hand']). Mention-form questions
        # ("when is Y first mentioned") have no character -> empty list.
        names = _extract_names(first_who) if first_who else []
    else:
        names = _extract_names(question)

    return QueryPlan(question=question, qtype=qtype, scope=scope,
                     characters=names, first_occurrence=first_occurrence,
                     topic=first_topic)
