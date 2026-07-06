"""Answer generation: retrieved excerpts + structured notes -> QUERY_MODEL.

The model is instructed to answer ONLY from the provided material and to
cite (Book X, Chapter Y) for every claim. Temporal questions get an extra
instruction confining the answer to what has been revealed by the bound.
"""

from __future__ import annotations

import logging

from .extractor import PRICING_PER_MTOK
from .query_router import QueryPlan

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are analyzing a fiction series for its author. Answer based only on the provided excerpts and extracted story notes. Be specific about which book and chapter every part of your answer comes from, citing as (Book N, Chapter M). Never invent details that are not present in the provided material. If the material is insufficient to answer confidently, say what is missing rather than guessing."""

TEMPORAL_INSTRUCTION = """IMPORTANT: This is a point-in-time knowledge question. Only consider what has been revealed within {bound}. Distinguish carefully between what the READER knows and what the named CHARACTER has personally witnessed, been told, or deduced — answer for the character's knowledge, not the reader's."""

FIRST_OCCURRENCE_INSTRUCTION = """This asks when something FIRST happens for a character. The earliest-mentions excerpts and ledger entries are drawn CHRONOLOGICALLY from an exhaustive index of the whole series — the earliest entry shown IS the first occurrence in the indexed text. Answer decisively from them. Distinguish first EXPOSURE (seeing/hearing the term) from first UNDERSTANDING (learning what it means) when the material shows both moments."""

QUOTE_INSTRUCTION = """When the provided excerpts contain the relevant passage, support your claims with short verbatim quotes: reproduce the exact words inside double quotation marks, immediately followed by the citation (Book N, Chapter M). Quote COMPLETE sentences only — start each quote at the first word of a sentence and end it at the sentence's closing punctuation, never mid-sentence; if only part of a sentence is relevant, quote the whole sentence anyway. One or two sentences per quote, contiguous — do not splice separate sentences together with ellipses. Preserve capitalization and punctuation exactly as written. Quote only text that appears word-for-word in the excerpts — never reconstruct dialogue or narration from memory. Story notes sometimes end with a verbatim manuscript quote after an em dash — you may re-quote THAT quoted portion, but never place a note's summary wording inside quotation marks; if only a note's summary supports a claim, cite it without quotation marks."""

CONTINUITY_INSTRUCTION = """For each foreshadowing element or open question in the notes, judge from the excerpts and notes whether it is: Resolved (say where), Unresolved, or Potentially Contradicted (explain the conflict). Group your answer by those three categories and cite (Book N, Chapter M) throughout. Merge duplicate notes that describe the same underlying thread."""


class Answerer:
    def __init__(self, cfg, model: str | None = None):
        import anthropic

        self.client = anthropic.Anthropic(api_key=cfg.anthropic_api_key or None,
                                          max_retries=3)
        # per-request override (e.g. the review pane's model dropdown, which
        # drops to a cheaper model for interim iterations)
        self.model = model or cfg.query_model
        # ENABLE_PROMPT_CACHE_V2: also mark the last prior chat turn as a
        # cache breakpoint so multi-turn sessions reuse the prefix. Flag off
        # -> request payloads are byte-identical to the legacy shape.
        self.enable_prompt_cache_v2 = getattr(cfg, "enable_prompt_cache_v2",
                                              False)
        # ENABLE_DIRECT_QUOTES: append a verbatim-quoting instruction to the
        # system prompt. Flag off -> build_request output is byte-identical
        # to the legacy shape.
        self.enable_direct_quotes = getattr(cfg, "enable_direct_quotes", False)
        # ENABLE_FIRST_OCCURRENCE: first-occurrence plans swap the temporal
        # instruction for FIRST_OCCURRENCE_INSTRUCTION. Flag off -> requests
        # are byte-identical to the legacy shape.
        self.enable_first_occurrence = getattr(cfg, "enable_first_occurrence",
                                               False)
        self.usage = {"input_tokens": 0, "output_tokens": 0,
                      "cache_write_tokens": 0, "cache_read_tokens": 0}

    def _record_usage(self, u) -> None:
        self.usage["input_tokens"] += u.input_tokens
        self.usage["output_tokens"] += u.output_tokens
        self.usage["cache_write_tokens"] += \
            getattr(u, "cache_creation_input_tokens", 0) or 0
        self.usage["cache_read_tokens"] += \
            getattr(u, "cache_read_input_tokens", 0) or 0

    @property
    def actual_cost_usd(self) -> float:
        in_p, out_p = PRICING_PER_MTOK.get(self.model, (3.00, 15.00))
        # cache writes bill at 1.25x input, cache reads at 0.1x
        return round((self.usage["input_tokens"] * in_p
                      + self.usage["cache_write_tokens"] * in_p * 1.25
                      + self.usage["cache_read_tokens"] * in_p * 0.10
                      + self.usage["output_tokens"] * out_p) / 1_000_000, 4)

    def build_request(self, plan: QueryPlan, excerpts: list[dict],
                      notes: list[str],
                      history: list[dict] | None = None,
                      system_extra: str = "",
                      system_base: str | None = None,
                      notes_header: str | None = None,
                      max_tokens: int | None = None) -> dict:
        """Assemble the messages.create kwargs. Shared by the blocking
        answer() path and the server's SSE streaming path."""
        parts: list[str] = []

        if notes:
            parts.append(notes_header
                         or "== EXTRACTED STORY NOTES (from ingestion metadata) ==")
            parts.extend(notes)
            parts.append("")

        if excerpts:
            parts.append("== EXCERPTS FROM THE MANUSCRIPTS ==")
            for e in excerpts:
                parts.append(f"--- [{e['header']}] ---")
                parts.append(e["text"])
                parts.append("")

        if plan.qtype == "temporal_knowledge":
            # first_occurrence wins over the plain temporal instruction (same
            # condition the retriever's first-occurrence branch gates on)
            if (self.enable_first_occurrence
                    and getattr(plan, "first_occurrence", False)
                    and getattr(plan, "topic", None)):
                parts.append(FIRST_OCCURRENCE_INSTRUCTION)
            else:
                parts.append(TEMPORAL_INSTRUCTION.format(bound=plan.scope.describe()))
        elif plan.qtype == "continuity":
            parts.append(CONTINUITY_INSTRUCTION)
        parts.append(f"QUESTION: {plan.question}")

        # Continuity reports and exports run long; 12K keeps them un-truncated
        # while staying inside non-streaming HTTP-timeout territory. Callers
        # with longer outputs (the review's full-chapter revision) override.
        if max_tokens is None:
            max_tokens = 12000 if plan.qtype in ("continuity", "general") else 6000
        messages = list(history or [])
        if self.enable_prompt_cache_v2 and messages:
            messages = self._mark_history_breakpoint(messages)
        messages.append({"role": "user", "content": "\n".join(parts)})
        # ENABLE_DIRECT_QUOTES: the quoting instruction is appended in a fixed
        # position (right after the base prompt, before system_extra) so the
        # system string stays byte-stable across turns and the prompt-cache
        # prefix is preserved. Flag off -> identical to the legacy string.
        system = ((system_base or SYSTEM_PROMPT)
                  + (f"\n\n{QUOTE_INSTRUCTION}" if self.enable_direct_quotes else "")
                  + (f"\n\n{system_extra}" if system_extra else ""))
        # Cache the system block (base prompt + injected reference material,
        # e.g. Explore's story bibles). Messages come after the breakpoint, so
        # follow-up turns reuse the cache as long as the system text is stable.
        # Below the model's minimum cacheable size this is a silent no-op.
        return {"model": self.model, "max_tokens": max_tokens,
                "system": [{"type": "text", "text": system,
                            "cache_control": {"type": "ephemeral"}}],
                "messages": messages}

    @staticmethod
    def _mark_history_breakpoint(messages: list[dict]) -> list[dict]:
        """ENABLE_PROMPT_CACHE_V2 only: mark the last content block of the
        last history message with cache_control, so on turn N+1 the whole
        prefix (system + all prior turns) is a cache read instead of a full-
        price re-process. String content is converted to the block form —
        semantically identical on the wire, required to carry the marker.
        Two breakpoints total (system + here), well under the API's max 4.
        Copies, never mutates, the caller's message dicts."""
        messages = list(messages)
        last = dict(messages[-1])
        content = last.get("content")
        if isinstance(content, str):
            blocks = [{"type": "text", "text": content}]
        elif isinstance(content, list) and content:
            blocks = [dict(b) if isinstance(b, dict) else b for b in content]
            if not isinstance(blocks[-1], dict):
                return messages  # unexpected shape — leave untouched
        else:
            return messages
        blocks[-1] = {**blocks[-1], "cache_control": {"type": "ephemeral"}}
        last["content"] = blocks
        messages[-1] = last
        return messages

    def answer(self, plan: QueryPlan, excerpts: list[dict], notes: list[str]) -> str:
        response = self.client.messages.create(
            **self.build_request(plan, excerpts, notes))
        self._record_usage(response.usage)

        if response.stop_reason == "refusal":
            return "(the model declined to answer this question)"
        return next((b.text for b in response.content if b.type == "text"), "")

    def answer_stream(self, plan: QueryPlan, excerpts: list[dict],
                      notes: list[str], history: list[dict] | None = None,
                      system_extra: str = "",
                      system_base: str | None = None,
                      notes_header: str | None = None,
                      max_tokens: int | None = None):
        """Generator of text deltas; records usage when the stream ends."""
        request = self.build_request(plan, excerpts, notes, history, system_extra,
                                     system_base, notes_header, max_tokens)
        with self.client.messages.stream(**request) as stream:
            yield from stream.text_stream
            final = stream.get_final_message()
        self._record_usage(final.usage)

    # ── export modes ────────────────────────────────────────────────────────

    def export(self, mode: str, names: list[str], notes: list[str],
               excerpts: list[dict]) -> str:
        if mode == "character_timeline":
            task = (f"Produce a chronological markdown summary of {names[0]}'s arc "
                    "across the series: their knowledge state as it evolves, key "
                    "events they participate in, their emotional journey, and how "
                    "their relationships shift. Organize by book, then chapter "
                    "ranges. Cite (Book N, Chapter M) for every claim.")
        elif mode == "relationship_map":
            task = (f"Trace the full evolution of the relationship between "
                    f"{names[0]} and {names[1]} across the series. Identify each "
                    "scene where the relationship meaningfully shifts, what "
                    "changed, and why. Organize chronologically and cite "
                    "(Book N, Chapter M) for every claim.")
        else:
            raise ValueError(f"unknown export mode: {mode}")

        plan = QueryPlan(question=task, qtype="general")
        return self.answer(plan, excerpts, notes)
