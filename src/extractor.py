"""LLM metadata extraction for chunks (EXTRACTION_MODEL, cheap + fast).

For every chunk we extract the narrative metadata the query layer depends on:
characters present, locations, key events, what each character *learns*,
emotional beats, foreshadowing, and unresolved questions.

Design decisions:
  * Structural fields (book/chapter/POV/date/part) come from the chunker,
    NOT from the LLM — they are already known exactly, so the model only
    extracts what genuinely requires reading comprehension.
  * Chunks are packed into batches (many chunks per API call) to cut cost.
  * Output validity is enforced with the API's structured-outputs feature
    (output_config.format with a JSON schema), so responses are guaranteed
    parseable JSON — no fragile "please return JSON" prompting.
  * Failures never crash the pipeline: an oversized or failed batch is split
    in half and retried; chunks that still fail come back with metadata=None
    and a logged warning. The SDK itself retries 429/5xx with backoff.
  * Optional batches mode (EXTRACTION_USE_BATCHES / ingest.py --batches):
    every packed batch is submitted as one request in a single Anthropic
    Message Batch, which bills tokens at 50% of standard prices. Results can
    take up to an hour (usually much less). Requests that come back errored/
    expired/canceled fall back to the normal synchronous path (billed at
    standard prices).
"""

from __future__ import annotations

import json
import logging
import re
import time

from .chunker import Chunk

log = logging.getLogger(__name__)

# $ per million tokens (input, output) — used for estimates and run summaries.
PRICING_PER_MTOK = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-fable-5": (10.00, 50.00),
}

TOKENS_PER_WORD = 1.35          # prose heuristic, same as the chunker
# Observed metadata size per chunk. 450 before source quotes; the verbatim
# source_quote fields plus the exhaustive-extraction instruction put measured
# output at ~800 tokens per chunk.
EST_OUTPUT_TOKENS_PER_CHUNK = 800

# Batching limits: keep well inside the 200K context of claude-haiku-4-5 and
# inside a 16K non-streaming output budget (~18 chunks * 800 tokens ≈ 14.4K).
MAX_BATCH_WORDS = 9000
MAX_BATCH_CHUNKS = 18
MAX_OUTPUT_TOKENS = 16000

# Message Batches API: 50% of standard token prices; poll cadence for the
# batch status while we wait for processing to end.
BATCH_PRICE_MULTIPLIER = 0.5
BATCH_POLL_SECONDS = 30

SYSTEM_PROMPT = """You are analyzing chunks of a fiction series the way a careful reader would.

For EVERY chunk you receive, extract metadata based only on what the text of that chunk says. Never invent details that are not present in the text.

Be exhaustive. List every distinct key event, revealed fact, character knowledge update, emotional beat, foreshadowing hint, and unresolved question the chunk supports — a typical chunk yields 2-5 entries per field, and rich chunks more. Do not merge distinct items into one, and do not drop minor items for brevity: a small planted detail or a passing emotional shift still gets its own entry.

Field guidance:
- characters_present: characters who appear or speak in the chunk (canonical full names when known, e.g. "Maria Santos" rather than "Maria").
- locations: physical places where the chunk's action occurs or that are meaningfully referenced.
- timeline_position: when this happens relative to the story (use the chunk's date header and in-text time cues), or null if nothing indicates it.
- key_events: the concrete plot events that happen in this chunk.
- new_information_revealed: facts the READER learns for the first time in this chunk.
- character_knowledge_updates: for each character who LEARNS something in this chunk, what they learn — include every character who learns anything, even small facts (a name, a location, another character's feelings), and list each distinct fact as its own entry: a character often learns several separate things in one chunk. Only include knowledge gained here, by that character — not things the reader knows but the character does not. Never use "Reader" as a character here; what the reader learns belongs in new_information_revealed.
- emotional_beats: character emotional states and shifts (e.g. "the narrator feels cornered and ashamed").
- foreshadowing: hints, planted details, or ominous notes that seem intended to pay off later. Err on the side of inclusion: subtle imagery, repeated motifs, and offhand remarks that could pay off later all count.
- unresolved_questions: questions this chunk raises that it does not answer — every question a careful reader would still have: unexplained motives, unidentified people or objects, unstated outcomes, and questions the characters themselves voice.

Verbatim evidence (source_quote): each learned fact, emotional beat, foreshadowing item, and unresolved question also carries a source_quote field. COMPLETENESS IS PARAMOUNT AND UNCHANGED: first decide the full list of items for each field exactly as you would if the source_quote field did not exist, then attach quotes. The quote is a bonus — an item must NEVER be dropped, merged, or softened because no clean supporting quote exists; set its source_quote to null and keep the item. When you do give a quote, it is the single most probative passage (at most 1-2 sentences) copied EXACTLY from the chunk text, character for character, including capitalization and punctuation — never paraphrase, trim, reorder words, or stitch together non-adjacent sentences. Before writing a quote, check that it appears verbatim in the chunk; if you cannot copy a passage exactly or are unsure, use null. Many items naturally have no single clean quote — source_quote: null is common and expected, and quote-finding must never influence which items you list.

Return metadata for every chunk, in the same order, each tagged with its exact chunk_id. Empty lists are fine when a field has nothing."""

# Structured-output schema. Note character_knowledge_updates is an array of
# {character, learns} pairs (not a dict) because structured outputs require
# additionalProperties: false — we convert to a dict after parsing.
#
# Quote-bearing items ({detail/question/beat/fact, source_quote}) replaced
# plain strings when source-quote support landed; _split_items still accepts
# the old string form so cached/batch results from before the change parse.
def _quoted_item_schema(key: str) -> dict:
    """One evidence-backed item: the summary text plus a verbatim quote."""
    return {
        "type": "object",
        "properties": {
            key: {"type": "string"},
            "source_quote": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
        "required": [key, "source_quote"],
        "additionalProperties": False,
    }


_CHUNK_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "chunk_id": {"type": "string"},
        "characters_present": {"type": "array", "items": {"type": "string"}},
        "locations": {"type": "array", "items": {"type": "string"}},
        "timeline_position": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "key_events": {"type": "array", "items": {"type": "string"}},
        "new_information_revealed": {"type": "array", "items": {"type": "string"}},
        "character_knowledge_updates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "character": {"type": "string"},
                    "learns": {"type": "array", "items": _quoted_item_schema("fact")},
                },
                "required": ["character", "learns"],
                "additionalProperties": False,
            },
        },
        "emotional_beats": {"type": "array", "items": _quoted_item_schema("beat")},
        "foreshadowing": {"type": "array", "items": _quoted_item_schema("detail")},
        "unresolved_questions": {"type": "array",
                                 "items": _quoted_item_schema("question")},
    },
    "required": [
        "chunk_id", "characters_present", "locations", "timeline_position",
        "key_events", "new_information_revealed", "character_knowledge_updates",
        "emotional_beats", "foreshadowing", "unresolved_questions",
    ],
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"chunks": {"type": "array", "items": _CHUNK_ITEM_SCHEMA}},
    "required": ["chunks"],
    "additionalProperties": False,
}

# Light normalization for verbatim-quote verification: models straighten curly
# quotes/apostrophes and collapse whitespace when copying; the words themselves
# must still match exactly.
_QUOTE_CHAR_MAP = str.maketrans({
    "‘": "'", "’": "'",     # curly single quotes / apostrophes
    "“": '"', "”": '"',     # curly double quotes
    "…": "...",                  # ellipsis character
})


def _normalize_quote(s: str) -> str:
    return re.sub(r"\s+", " ", s.translate(_QUOTE_CHAR_MAP)).strip()


def _split_items(raw, key: str) -> tuple[list[str], list[str | None]]:
    """Split a model item list into (texts, source_quotes), accepting BOTH the
    old plain-string form and the new {key, source_quote} object form (old
    cached/batch results and partial failures must keep parsing)."""
    texts: list[str] = []
    quotes: list[str | None] = []
    for it in raw or []:
        if isinstance(it, dict):
            text = str(it.get(key) or "").strip()
            q = it.get("source_quote")
            quote = q.strip() if isinstance(q, str) and q.strip() else None
        else:
            text, quote = str(it).strip(), None
        if text:
            texts.append(text)
            quotes.append(quote)
    return texts, quotes


def estimate_extraction_cost(chunks: list[Chunk], model: str) -> dict:
    """Rough token + dollar estimate for extracting metadata for `chunks`."""
    if not chunks:
        return {"model": model, "chunks": 0, "estimated_input_tokens": 0,
                "estimated_output_tokens": 0, "estimated_cost_usd": 0.0}
    total_words = sum(c.word_count for c in chunks)
    n_batches = -(-len(chunks) // MAX_BATCH_CHUNKS)
    input_tokens = int(total_words * TOKENS_PER_WORD) + n_batches * 700  # + system prompt
    output_tokens = len(chunks) * EST_OUTPUT_TOKENS_PER_CHUNK
    in_price, out_price = PRICING_PER_MTOK.get(model, (1.00, 5.00))
    cost = (input_tokens * in_price + output_tokens * out_price) / 1_000_000
    return {
        "model": model,
        "chunks": len(chunks),
        "estimated_input_tokens": input_tokens,
        "estimated_output_tokens": output_tokens,
        "estimated_cost_usd": round(cost, 4),
    }


def _chunk_header(c: Chunk) -> str:
    """The structural context we already know — given to the model for free."""
    parts = [f"Book {c.book_number}: {c.book_title} — {c.heading}"]
    if c.pov_character:
        parts.append(f"POV: {c.pov_character}")
    if c.date_line:
        parts.append(f"Date: {c.date_line}")
    if c.part_number:
        parts.append(f"Part {c.part_number}: {c.part_title}")
    parts.append(f"(chunk {c.chunk_index + 1} of {c.total_chunks_in_scene} in this chapter)")
    return " | ".join(parts)


def _batches(chunks: list[Chunk]) -> list[list[Chunk]]:
    """Greedily pack chunks into batches under the word/count limits."""
    batches: list[list[Chunk]] = []
    buf: list[Chunk] = []
    words = 0
    for c in chunks:
        if buf and (words + c.word_count > MAX_BATCH_WORDS or len(buf) >= MAX_BATCH_CHUNKS):
            batches.append(buf)
            buf, words = [], 0
        buf.append(c)
        words += c.word_count
    if buf:
        batches.append(buf)
    return batches


def _batch_custom_id(batch: list[Chunk]) -> str:
    """Stable Batches-API custom_id for a packed batch: the first chunk's id,
    sanitized (custom_ids only allow [a-zA-Z0-9_-], chunk_ids contain dots)."""
    return re.sub(r"[^a-zA-Z0-9_-]", "-", batch[0].chunk_id)


class MetadataExtractor:
    """Extracts per-chunk narrative metadata via EXTRACTION_MODEL."""

    def __init__(self, cfg):
        import anthropic  # imported here so the parser/chunker stay dependency-free

        self._anthropic = anthropic
        # SDK already retries 429/5xx with exponential backoff; raise the
        # ceiling a bit since ingestion is a batch job, not interactive.
        self.client = anthropic.Anthropic(
            api_key=cfg.anthropic_api_key or None, max_retries=4
        )
        self.model = cfg.extraction_model
        self.use_batches = getattr(cfg, "extraction_use_batches", False)
        # Actual usage accumulated across the run, for the run summary.
        # batch_* buckets are tokens billed through the Message Batches API
        # (50% pricing); the plain buckets are standard synchronous calls.
        self.usage = {
            "input_tokens": 0, "output_tokens": 0,
            "batch_input_tokens": 0, "batch_output_tokens": 0,
            "api_calls": 0,
        }
        # source_quote verification tallies (kept = verbatim in the chunk
        # text after light normalization; rejected = fabricated -> nulled).
        self.quote_stats = {"kept": 0, "rejected": 0}

    @property
    def actual_cost_usd(self) -> float:
        in_price, out_price = PRICING_PER_MTOK.get(self.model, (1.00, 5.00))
        sync_cost = (self.usage["input_tokens"] * in_price
                     + self.usage["output_tokens"] * out_price)
        batch_cost = BATCH_PRICE_MULTIPLIER * (
            self.usage["batch_input_tokens"] * in_price
            + self.usage["batch_output_tokens"] * out_price
        )
        return round((sync_cost + batch_cost) / 1_000_000, 4)

    def extract(self, chunks: list[Chunk]) -> list[dict | None]:
        """Extract metadata for all chunks. Returns one dict per chunk, in
        order; a chunk whose extraction failed gets None (log-and-continue)."""
        stats_before = dict(self.quote_stats)
        batches = _batches(chunks)
        results: list[dict | None] = []
        if self.use_batches and batches:
            results.extend(self._extract_batched(batches))
        else:
            for batch in batches:
                results.extend(self._extract_batch(batch))

        # Second pass: in large batches the model occasionally skips a chunk
        # entirely. Retry any misses one at a time — a single-chunk request
        # is trivially reliable, and misses are rare so this stays cheap.
        missing = [i for i, r in enumerate(results) if r is None]
        if missing:
            log.info("retrying %d missed chunk(s) individually", len(missing))
            for i in missing:
                results[i] = self._extract_batch([chunks[i]], depth=3)[0]

        kept = self.quote_stats["kept"] - stats_before["kept"]
        rejected = self.quote_stats["rejected"] - stats_before["rejected"]
        if kept or rejected:
            log.info("source quotes: %d kept / %d rejected (not verbatim in "
                     "chunk text; nulled)", kept, rejected)
        return results

    # ── internals ───────────────────────────────────────────────────────────

    def _request_params(self, batch: list[Chunk]) -> dict:
        """Messages-API params for one packed batch. Shared by the synchronous
        path (messages.create(**params)) and the Batches path (the per-request
        `params` of batches.create), so the two can never drift apart."""
        prompt_parts = [
            f"Extract metadata for the following {len(batch)} chunk(s).\n"
        ]
        for c in batch:
            prompt_parts.append(
                f"=== CHUNK {c.chunk_id} ===\n{_chunk_header(c)}\n\n{c.text}\n"
            )
        user_prompt = "\n".join(prompt_parts)
        return {
            "model": self.model,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "system": SYSTEM_PROMPT,
            "output_config": {"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
            "messages": [{"role": "user", "content": user_prompt}],
        }

    def _extract_batch(self, batch: list[Chunk], depth: int = 0) -> list[dict | None]:
        """Synchronous extraction for one packed batch (also the fallback and
        retry path when batches mode hits an errored/expired request)."""
        try:
            response = self.client.messages.create(**self._request_params(batch))
        except self._anthropic.APIError as e:
            log.warning("extraction call failed (%s): %s", type(e).__name__, e)
            return self._split_and_retry(batch, depth)

        self.usage["input_tokens"] += response.usage.input_tokens
        self.usage["output_tokens"] += response.usage.output_tokens
        self.usage["api_calls"] += 1

        return self._parse_response(batch, response, depth)

    def _extract_batched(self, batches: list[list[Chunk]]) -> list[dict | None]:
        """Submit all packed batches as one Message Batch (50% token pricing),
        poll until it ends, then parse results. Results arrive in arbitrary
        order and are matched by custom_id, never by position. Requests that
        errored/expired/were canceled fall back to the synchronous path."""
        requests = [
            {"custom_id": _batch_custom_id(batch), "params": self._request_params(batch)}
            for batch in batches
        ]
        try:
            message_batch = self.client.messages.batches.create(requests=requests)
        except self._anthropic.APIError as e:
            log.warning("message batch submission failed (%s): %s — "
                        "falling back to synchronous extraction", type(e).__name__, e)
            results: list[dict | None] = []
            for batch in batches:
                results.extend(self._extract_batch(batch))
            return results

        log.info("submitted message batch %s (%d request(s), %d chunk(s)); "
                 "results may take up to an hour, typically much less",
                 message_batch.id, len(requests), sum(len(b) for b in batches))

        while message_batch.processing_status != "ended":
            time.sleep(BATCH_POLL_SECONDS)
            message_batch = self.client.messages.batches.retrieve(message_batch.id)
            rc = message_batch.request_counts
            log.info("batch %s: %d processing / %d succeeded / %d errored / "
                     "%d canceled / %d expired", message_batch.id, rc.processing,
                     rc.succeeded, rc.errored, rc.canceled, rc.expired)

        by_custom_id = {r.custom_id: r for r in
                        self.client.messages.batches.results(message_batch.id)}

        results = []
        for batch in batches:
            cid = _batch_custom_id(batch)
            result = by_custom_id.get(cid)
            if result is not None and result.result.type == "succeeded":
                msg = result.result.message
                # Batch-billed buckets: 50% pricing in actual_cost_usd.
                self.usage["batch_input_tokens"] += msg.usage.input_tokens
                self.usage["batch_output_tokens"] += msg.usage.output_tokens
                self.usage["api_calls"] += 1
                results.extend(self._parse_response(batch, msg, depth=0))
            else:
                status = result.result.type if result is not None else "missing"
                log.warning("batch request %s came back %s; retrying its %d "
                            "chunk(s) synchronously", cid, status, len(batch))
                results.extend(self._extract_batch(batch))
        return results

    def _parse_response(self, batch: list[Chunk], response,
                        depth: int) -> list[dict | None]:
        """Turn one Messages-API response (sync or from a batch result) into
        per-chunk metadata dicts; failures split-and-retry synchronously."""
        if response.stop_reason == "refusal":
            log.warning("extraction refused for batch starting %s", batch[0].chunk_id)
            return [None] * len(batch)
        if response.stop_reason == "max_tokens":
            log.warning("extraction output truncated; splitting batch")
            return self._split_and_retry(batch, depth)

        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:  # should not happen with structured outputs
            log.warning("unparseable extraction output: %s", e)
            return self._split_and_retry(batch, depth)

        by_id = {item.get("chunk_id"): item for item in data.get("chunks", [])}
        results: list[dict | None] = []
        for c in batch:
            item = by_id.get(c.chunk_id)
            if item is None:
                log.warning("model returned no metadata for %s", c.chunk_id)
                results.append(None)
                continue
            results.append(self._merge(c, item))
        return results

    def _split_and_retry(self, batch: list[Chunk], depth: int) -> list[dict | None]:
        """Halve a failing batch and retry each half; give up after 3 levels."""
        if len(batch) == 1 or depth >= 3:
            log.warning("giving up on %d chunk(s) starting %s — storing null metadata",
                        len(batch), batch[0].chunk_id)
            return [None] * len(batch)
        mid = len(batch) // 2
        return (self._extract_batch(batch[:mid], depth + 1)
                + self._extract_batch(batch[mid:], depth + 1))

    def _verify_quotes(self, quotes: list[str | None],
                       normalized_chunk_text: str) -> list[str | None]:
        """Keep a source_quote only when it is a true substring of the chunk
        text (after light normalization on both sides); fabricated quotes are
        nulled and counted — a bad quote NEVER fails the chunk."""
        out: list[str | None] = []
        for q in quotes:
            if q is None:
                out.append(None)
            elif _normalize_quote(q) in normalized_chunk_text:
                out.append(q)
                self.quote_stats["kept"] += 1
            else:
                out.append(None)
                self.quote_stats["rejected"] += 1
        return out

    def _merge(self, chunk: Chunk, item: dict) -> dict:
        """Combine known structural fields with the model's narrative fields.

        List fields keep their historical list-of-strings shape (every
        metadata_json reader depends on it); the verified verbatim quotes ride
        alongside in parallel `*_quotes` lists, index-aligned with the values.
        """
        norm_text = _normalize_quote(chunk.text)
        foreshadowing, fs_quotes = _split_items(item.get("foreshadowing"), "detail")
        questions, q_quotes = _split_items(item.get("unresolved_questions"), "question")
        beats, beat_quotes = _split_items(item.get("emotional_beats"), "beat")
        knowledge: dict[str, list[str]] = {}
        knowledge_quotes: dict[str, list[str | None]] = {}
        for entry in item.get("character_knowledge_updates", []):
            facts, fact_quotes = _split_items(entry.get("learns"), "fact")
            if facts:
                knowledge[entry["character"]] = facts
                knowledge_quotes[entry["character"]] = self._verify_quotes(
                    fact_quotes, norm_text)
        return {
            # structural (from the chunker — exact, free)
            "chunk_id": chunk.chunk_id,
            "book_number": chunk.book_number,
            "book_title": chunk.book_title,
            "chapter_number": chunk.chapter_number,
            "chapter_kind": chunk.chapter_kind,
            "scene_number": chunk.scene_number,
            "chunk_index": chunk.chunk_index,
            "pov_character": chunk.pov_character,
            "date_line": chunk.date_line,
            "part_number": chunk.part_number,
            "part_title": chunk.part_title,
            # narrative (from the LLM)
            "characters_present": item.get("characters_present", []),
            "locations": item.get("locations", []),
            "timeline_position": item.get("timeline_position"),
            "key_events": item.get("key_events", []),
            "new_information_revealed": item.get("new_information_revealed", []),
            "character_knowledge_updates": knowledge,
            "emotional_beats": beats,
            "foreshadowing": foreshadowing,
            "unresolved_questions": questions,
            # verified verbatim quotes, index-aligned with the lists above
            # (None where the model gave no quote or the quote failed the
            # verbatim check)
            "character_knowledge_quotes": knowledge_quotes,
            "emotional_beat_quotes": self._verify_quotes(beat_quotes, norm_text),
            "foreshadowing_quotes": self._verify_quotes(fs_quotes, norm_text),
            "unresolved_question_quotes": self._verify_quotes(q_quotes, norm_text),
        }
