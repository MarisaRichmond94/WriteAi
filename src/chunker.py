"""Scene-aware chunker.

Stage 1 — segment: split a book's plain text into narrative segments using
the SAME conventions as the author's existing audiobook/ebook split
(generate_audiobook.sh's awk program):

  * everything before the first structural marker is front matter — skipped
  * a line that is exactly "Prologue"            -> prologue segment
  * a line that is exactly "Part One".."Part Ten" -> part divider; the next
    line is the part's subtitle (e.g. "Part One" / "The First Note")
  * a line of 1-3 digits (e.g. "17")              -> chapter 17

Within a prologue/chapter the header convention is rigid:
  line 1: POV character name (e.g. "Jared Gatlin")
  line 2: optional date line  (e.g. "Monday, November 9th")
  then prose, one paragraph per line.

Stage 2 — chunk: in these manuscripts scenes are not explicitly marked
(there are no *** separators), so the chapter IS the scene unit for now.
Chapters larger than MAX_CHUNK_TOKENS are split at paragraph boundaries;
every continuation chunk carries the last 1-2 sentences of the previous
chunk as a context prefix, and all sub-chunks share the chapter's metadata.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Rough tokens-per-word ratio for fiction prose; used only for sizing chunks.
TOKENS_PER_WORD = 1.35

PART_WORDS = {
    "One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5,
    "Six": 6, "Seven": 7, "Eight": 8, "Nine": 9, "Ten": 10,
}
PART_RE = re.compile(r"^Part (One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten)$")
CHAPTER_RE = re.compile(r"^\d{1,3}$")
PROLOGUE_RE = re.compile(r"^Prologue$")

# Date headers look like "Monday, November 9th" / "Wednesday, September 29th"
DATE_RE = re.compile(
    r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b"
    r"|^(January|February|March|April|May|June|July|August|September|October|November|December)\b"
)

_SENTENCE_SPLIT = re.compile(r'(?<=[.!?…"”])\s+')


@dataclass
class Segment:
    """One structural unit of a book: a prologue, a chapter, or a part divider."""
    kind: str                      # 'prologue' | 'chapter' | 'part'
    chapter_number: int | None     # None for prologue (0) and part dividers
    heading: str                   # "Prologue", "Chapter 12", "Part Two"
    pov: str | None = None         # line after the heading
    date_line: str | None = None   # optional date header
    part_number: int | None = None  # which Part this segment belongs to
    part_title: str | None = None   # the part's subtitle line
    paragraphs: list[str] = field(default_factory=list)  # prose only

    @property
    def word_count(self) -> int:
        return sum(len(p.split()) for p in self.paragraphs)


@dataclass
class Chunk:
    """One retrievable unit: a whole scene/chapter, or a piece of one."""
    text: str                      # prose of this chunk (no header lines)
    context_prefix: str            # tail sentences of the previous chunk ('' for first)
    book_number: int
    book_title: str
    chapter_number: int            # 0 = prologue
    chapter_kind: str              # 'prologue' | 'chapter'
    heading: str
    scene_number: int              # chapter == scene for now, so always 1
    chunk_index: int               # 0-based position within the scene
    total_chunks_in_scene: int
    pov_character: str | None
    date_line: str | None
    part_number: int | None
    part_title: str | None
    word_count: int

    @property
    def chunk_id(self) -> str:
        """Stable ID: book 2, chapter 7, chunk 3 -> 'b02.c007.s01.k03'."""
        return (
            f"b{self.book_number:02d}.c{self.chapter_number:03d}"
            f".s{self.scene_number:02d}.k{self.chunk_index:02d}"
        )

    @property
    def embedding_text(self) -> str:
        """Text to embed: a short metadata line plus prefixed prose, so the
        vector captures who/when as well as what happens."""
        where = f"{self.book_title}, {self.heading}"
        who = f"POV: {self.pov_character}" if self.pov_character else ""
        when = f"({self.date_line})" if self.date_line else ""
        header = " — ".join(x for x in (where, who) if x) + (f" {when}" if when else "")
        body = (self.context_prefix + " " + self.text).strip()
        return f"{header}\n{body}"


def split_into_segments(text: str) -> list[Segment]:
    """Port of the awk chapter splitter, with POV/date header extraction."""
    segments: list[Segment] = []
    current: Segment | None = None
    started = False              # False until the first structural marker
    current_part_num: int | None = None
    current_part_title: str | None = None

    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if PROLOGUE_RE.match(line):
            started = True
            current = Segment(kind="prologue", chapter_number=0, heading="Prologue")
            segments.append(current)
        elif started and PART_RE.match(line):
            # Part divider: the next line is its subtitle; it has no body.
            num = PART_WORDS[line.split()[1]]
            subtitle = lines[i + 1].strip() if i + 1 < len(lines) else ""
            segments.append(Segment(
                kind="part", chapter_number=None, heading=line,
                part_number=num, part_title=subtitle,
            ))
            current_part_num, current_part_title = num, subtitle
            current = None       # nothing accumulates into a part divider
            i += 1               # consume the subtitle line too
        elif CHAPTER_RE.match(line):
            started = True
            ch = int(line)
            current = Segment(
                kind="chapter", chapter_number=ch, heading=f"Chapter {ch}",
                part_number=current_part_num, part_title=current_part_title,
            )
            segments.append(current)
        elif started and current is not None and line:
            # Body line. The first is the POV name; an optional date follows.
            if current.pov is None and not current.paragraphs:
                current.pov = line
            elif (current.date_line is None and not current.paragraphs
                  and DATE_RE.match(line)):
                current.date_line = line
            else:
                current.paragraphs.append(line)
        i += 1

    # Prologues that started before any Part still belong to no part (correct);
    # nothing else to fix up.
    return segments


def _sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def _tail_sentences(text: str, n: int = 2, max_words: int = 60) -> str:
    """Last n sentences of a chunk, capped so the prefix stays short."""
    tail = " ".join(_sentences(text)[-n:])
    words = tail.split()
    if len(words) > max_words:
        tail = " ".join(words[-max_words:])
    return tail


def _split_oversized_paragraph(paragraph: str, max_words: int) -> list[str]:
    """A single paragraph longer than a whole chunk: split it at sentence
    boundaries into pieces of at most max_words."""
    pieces, buf, count = [], [], 0
    for s in _sentences(paragraph):
        w = len(s.split())
        if buf and count + w > max_words:
            pieces.append(" ".join(buf))
            buf, count = [], 0
        buf.append(s)
        count += w
    if buf:
        pieces.append(" ".join(buf))
    return pieces


def chunk_segment(seg: Segment, *, book_number: int, book_title: str,
                  max_chunk_tokens: int) -> list[Chunk]:
    """Turn one segment into retrievable chunks. Part dividers yield none."""
    if seg.kind == "part" or not seg.paragraphs:
        return []

    max_words = max(50, int(max_chunk_tokens / TOKENS_PER_WORD))

    # Greedily pack paragraphs into groups of <= max_words.
    groups: list[list[str]] = []
    buf: list[str] = []
    count = 0
    for para in seg.paragraphs:
        w = len(para.split())
        if w > max_words:  # rare: one paragraph bigger than a whole chunk
            if buf:
                groups.append(buf)
                buf, count = [], 0
            groups.extend([p] for p in _split_oversized_paragraph(para, max_words))
            continue
        if buf and count + w > max_words:
            groups.append(buf)
            buf, count = [], 0
        buf.append(para)
        count += w
    if buf:
        groups.append(buf)

    chunks: list[Chunk] = []
    prev_text = ""
    for idx, group in enumerate(groups):
        body = "\n".join(group)
        chunks.append(Chunk(
            text=body,
            context_prefix=_tail_sentences(prev_text) if prev_text else "",
            book_number=book_number,
            book_title=book_title,
            chapter_number=seg.chapter_number or 0,
            chapter_kind=seg.kind,
            heading=seg.heading,
            scene_number=1,               # chapter == scene until markers exist
            chunk_index=idx,
            total_chunks_in_scene=len(groups),
            pov_character=seg.pov,
            date_line=seg.date_line,
            part_number=seg.part_number,
            part_title=seg.part_title,
            word_count=len(body.split()),
        ))
        prev_text = body
    return chunks


def chunk_book(text: str, *, book_number: int, book_title: str,
               max_chunk_tokens: int) -> tuple[list[Segment], list[Chunk]]:
    """Convenience: full text -> (segments, all chunks in reading order)."""
    segments = split_into_segments(text)
    chunks: list[Chunk] = []
    for seg in segments:
        chunks.extend(chunk_segment(
            seg, book_number=book_number, book_title=book_title,
            max_chunk_tokens=max_chunk_tokens,
        ))
    return segments, chunks
