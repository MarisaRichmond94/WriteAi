"""Sentence-boundary snapping for verified source_quotes.

Extraction-time source_quotes (src/extractor.py) are verified as verbatim
substrings of their chunk text, but the model often starts or stops
mid-sentence, so the quotes read poorly wherever they surface (note lines
sent to the answerer, the book drawer, character panes).

This module is the single source of truth for fixing that, shared by the
extractor (parse-time snapping for future extractions) and
scripts/snap_quote_sentences.py (one-time pass over stored quotes): given a
verified quote and its chunk text, expand the quote outward to the enclosing
sentence boundaries and return the snapped text — verbatim manuscript prose
by construction, since it is a literal slice of the chunk text.

Boundary rules are tuned for fiction prose:
  * Sentence enders are . ! ? and the ellipsis, optionally followed by
    closing quote marks (so `..."` / `!'` end a sentence *including* the
    closing quote).
  * Dialogue tags stay attached: an ender inside quotes followed by a
    lowercase continuation (`"Stop!" she said.`) does NOT end the sentence.
  * Em-dash and ellipsis interruptions stay inside the sentence: an ellipsis
    counts as an ender only at end of text / line or when followed by a
    closing quote that itself ends the sentence (`He trailed off…` at line
    end), never mid-line (`I don't… I can't` is one sentence).
  * Common abbreviations (Mr., Dr., …) and single-letter initials do not end
    sentences.
  * Newlines are hard sentence boundaries (chunk text is one paragraph per
    line).

Snapping is conservative: if the enclosing sentence(s) would exceed
MAX_SNAPPED_CHARS or more than MAX_GROWTH_FACTOR times the original quote's
length, the verified original is kept unchanged — a verbose model quote is
better than half a page of context.
"""

from __future__ import annotations

import re

# Caps: never let a snapped quote balloon past what a note line can carry.
MAX_SNAPPED_CHARS = 450
MAX_GROWTH_FACTOR = 3.0

# Light normalization shared with the extractor's verbatim-quote verification:
# models straighten curly quotes/apostrophes and collapse whitespace when
# copying; the words themselves must still match exactly.
QUOTE_CHAR_MAP = str.maketrans({
    "‘": "'", "’": "'",      # curly single quotes / apostrophes
    "“": '"', "”": '"',      # curly double quotes
    "…": "...",                   # ellipsis character
})

# Sentence-ender characters ('…' is handled specially, see _is_sentence_end).
_ENDERS = ".!?…"
# Closing quote marks an ender may be wrapped in.
_CLOSERS = "\"'”’"
# Characters that plausibly open a new sentence (after the ender+whitespace).
_OPENERS = "\"'“‘(—–-"

# Abbreviations whose trailing period never ends a sentence (fiction-typical).
_ABBREVIATIONS = frozenset({
    "mr", "mrs", "ms", "dr", "st", "prof", "jr", "sr", "sgt", "capt", "lt",
    "gen", "col", "vs", "etc", "no",
})

_WORD_BEFORE_DOT_RE = re.compile(r"([A-Za-z]+)\.$")


def normalize_quote(s: str) -> str:
    """The exact normalization the extractor's verifier applies to both sides
    before the substring check (see src/extractor.py)."""
    return re.sub(r"\s+", " ", s.translate(QUOTE_CHAR_MAP)).strip()


def _normalized_with_offsets(text: str) -> tuple[str, list[int]]:
    """normalize_quote(text) plus, for every normalized character, the index
    of the original character it came from — so a match position in the
    normalized string maps back to a span of the original text."""
    chars: list[str] = []
    offsets: list[int] = []
    pending_space_at = -1  # original index of a pending collapsed space
    for i, ch in enumerate(text):
        if ch.isspace():
            if chars:  # strip leading whitespace; collapse runs
                pending_space_at = i if pending_space_at < 0 else pending_space_at
            continue
        if pending_space_at >= 0:
            chars.append(" ")
            offsets.append(pending_space_at)
            pending_space_at = -1
        for out in ch.translate(QUOTE_CHAR_MAP):  # '…' expands to '...'
            chars.append(out)
            offsets.append(i)
    return "".join(chars), offsets


def locate_quote(quote: str, chunk_text: str) -> tuple[int, int] | None:
    """(start, end) span of `quote` in the ORIGINAL chunk text, found under
    the verifier's normalization. None when the quote does not occur (which
    parse-time verification should have prevented)."""
    norm_quote = normalize_quote(quote)
    if not norm_quote:
        return None
    norm_text, offsets = _normalized_with_offsets(chunk_text)
    pos = norm_text.find(norm_quote)
    if pos < 0:
        return None
    start = offsets[pos]
    end = offsets[pos + len(norm_quote) - 1] + 1
    return start, end


def _is_abbreviation(text: str, dot: int) -> bool:
    """True when the '.' at `dot` terminates a known abbreviation or a
    single-letter initial (as in "B. C. Stryker")."""
    m = _WORD_BEFORE_DOT_RE.search(text[max(0, dot - 12):dot + 1])
    if not m:
        return False
    word = m.group(1)
    return len(word) == 1 and word.isupper() or word.lower() in _ABBREVIATIONS


def _sentence_end(text: str, i: int) -> int | None:
    """If the ender character at `i` truly ends a sentence, return the
    exclusive end of the boundary (past any closing quote marks); else None."""
    ch = text[i]
    if ch not in _ENDERS:
        return None
    if ch == ".":
        if i + 1 < len(text) and text[i + 1] == ".":
            return None  # not the final dot of a '...' run
        ellipsis = i >= 1 and text[i - 1] == "."  # final dot of '...'
        if not ellipsis and _is_abbreviation(text, i):
            return None
    else:
        ellipsis = ch == "…"

    k = i + 1
    while k < len(text) and text[k] in _CLOSERS:
        k += 1
    closed = k > i + 1  # ender was wrapped in closing quotes

    if k >= len(text) or text[k] == "\n":
        return k
    if text[k] not in " \t":
        return None  # ender glued to more text (e.g. "3.5", mid-token)

    m = k
    while m < len(text) and text[m] in " \t":
        m += 1
    if m >= len(text) or text[m] == "\n":
        return k
    nxt = text[m]

    # Ellipsis mid-line is an interruption, not an end — unless it sat inside
    # closing quotes and the continuation clearly starts a new sentence.
    if ellipsis and not closed:
        return None

    # Dialogue tags: `"Stop!" she said.` — lowercase continuation after a
    # quoted ender keeps the sentence going.
    if nxt.isupper() or nxt.isdigit() or nxt in _OPENERS:
        return k
    return None


def _snap_start(text: str, start: int) -> int:
    """Walk left from `start` to the beginning of the enclosing sentence."""
    j = start - 1
    while j >= 0:
        if text[j] == "\n":
            j += 1
            break
        end = _sentence_end(text, j)
        if end is not None and end <= start:
            j = end
            break
        j -= 1
    j = max(j, 0)
    while j < start and text[j] in " \t":
        j += 1
    return j


def _snap_end(text: str, start: int, end: int) -> int:
    """Walk right from `end` to the end of the enclosing sentence."""
    # Already sentence-terminated? Find the ender just inside the quote's
    # tail (skipping closing quote marks) and check whether the boundary it
    # defines covers `end` (== end: aligned; > end: the quote merely dropped
    # an adjacent closing quote mark, which we pull in).
    j = end - 1
    while j > start and text[j] in _CLOSERS:
        j -= 1
    if j >= start:
        bend = _sentence_end(text, j)
        if bend is not None and bend >= end:
            return bend

    k = end
    while k < len(text):
        if text[k] == "\n":
            return k
        bend = _sentence_end(text, k)
        if bend is not None:
            return bend
        k += 1
    return len(text)


def snap_quote_to_sentences(quote: str, chunk_text: str,
                            max_chars: int = MAX_SNAPPED_CHARS,
                            max_growth: float = MAX_GROWTH_FACTOR) -> str:
    """Expand a verified quote to its enclosing sentence boundaries within
    `chunk_text`. Returns the snapped text (a literal slice of the chunk
    text), or the original quote unchanged when it cannot be located, is
    already sentence-aligned, or snapping would exceed the caps."""
    span = locate_quote(quote, chunk_text)
    if span is None:
        return quote
    start, end = span
    new_start = _snap_start(chunk_text, start)
    new_end = _snap_end(chunk_text, start, end)
    if new_start == start and new_end == end:
        return quote  # already aligned — keep the verified original verbatim
    snapped = chunk_text[new_start:new_end].strip()
    # A quote may itself span a paragraph break (snapping never crosses one);
    # render it single-line — still verbatim under the verifier's
    # whitespace-collapsing normalization, and note lines stay one line.
    snapped = re.sub(r"\s*\n\s*", " ", snapped)
    if not snapped:
        return quote
    if len(snapped) > max_chars or len(snapped) > max_growth * max(len(quote), 1):
        return quote  # conservative: never balloon a short quote
    return snapped
