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

CONTINUITY_INSTRUCTION = """For each foreshadowing element or open question in the notes, judge from the excerpts and notes whether it is: Resolved (say where), Unresolved, or Potentially Contradicted (explain the conflict). Group your answer by those three categories and cite (Book N, Chapter M) throughout. Merge duplicate notes that describe the same underlying thread."""


class Answerer:
    def __init__(self, cfg):
        import anthropic

        self.client = anthropic.Anthropic(api_key=cfg.anthropic_api_key or None,
                                          max_retries=3)
        self.model = cfg.query_model
        self.usage = {"input_tokens": 0, "output_tokens": 0}

    @property
    def actual_cost_usd(self) -> float:
        in_p, out_p = PRICING_PER_MTOK.get(self.model, (3.00, 15.00))
        return round((self.usage["input_tokens"] * in_p
                      + self.usage["output_tokens"] * out_p) / 1_000_000, 4)

    def answer(self, plan: QueryPlan, excerpts: list[dict], notes: list[str]) -> str:
        parts: list[str] = []

        if notes:
            parts.append("== EXTRACTED STORY NOTES (from ingestion metadata) ==")
            parts.extend(notes)
            parts.append("")

        if excerpts:
            parts.append("== EXCERPTS FROM THE MANUSCRIPTS ==")
            for e in excerpts:
                parts.append(f"--- [{e['header']}] ---")
                parts.append(e["text"])
                parts.append("")

        if plan.qtype == "temporal_knowledge":
            parts.append(TEMPORAL_INSTRUCTION.format(bound=plan.scope.describe()))
        elif plan.qtype == "continuity":
            parts.append(CONTINUITY_INSTRUCTION)
        parts.append(f"QUESTION: {plan.question}")

        # Continuity reports and exports run long; 12K keeps them un-truncated
        # while staying inside non-streaming HTTP-timeout territory.
        max_tokens = 12000 if plan.qtype in ("continuity", "general") else 6000
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": "\n".join(parts)}],
        )
        self.usage["input_tokens"] += response.usage.input_tokens
        self.usage["output_tokens"] += response.usage.output_tokens

        if response.stop_reason == "refusal":
            return "(the model declined to answer this question)"
        return next((b.text for b in response.content if b.type == "text"), "")

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
