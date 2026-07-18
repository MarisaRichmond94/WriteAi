"""Cross-encoder reranking of retrieved excerpts (ENABLE_RERANKER).

A bi-encoder (the embedder) scores question and passage independently, so it
can only measure similarity in a shared vector space. A cross-encoder reads
the (question, passage) pair jointly and scores actual relevance — much more
accurate, but too slow to run over the whole corpus. So retrieval over-fetches
a candidate pool (RERANK_CANDIDATES) with the fast bi-encoder and this module
reorders just that pool before the final top-K cut.

The model (default cross-encoder/ms-marco-MiniLM-L-6-v2, ~90MB) loads lazily
on first use so code paths that never rerank (flag off, structured-only
queries) never pay for it. Runs locally via sentence-transformers; the
EMBEDDING_DEVICE env var pins the torch device exactly as in embedder.py
(the eval harness forces cpu for bit-reproducible runs).
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)


class Reranker:
    def __init__(self, cfg, model_name: str | None = None):
        # model_name lets the caller pick a specific model (e.g. Explore's
        # fast/thorough toggle); falls back to the configured default.
        self.model_name = model_name or cfg.reranker_model
        self._model = None

    @property
    def model(self):
        """Lazy: constructing a Reranker is free; the first rerank() loads."""
        if self._model is None:
            from sentence_transformers import CrossEncoder  # heavy import

            # (optional) pin the torch device, e.g. EMBEDDING_DEVICE=cpu for
            # bit-reproducible scores; unset -> library auto-select
            device = os.environ.get("EMBEDDING_DEVICE") or None
            log.info("loading reranker model %s (device=%s) …",
                     self.model_name, device or "auto")
            self._model = CrossEncoder(self.model_name, device=device)
        return self._model

    def rerank(self, question: str, excerpts: list[dict], top_k: int) -> list[dict]:
        """Score (question, header + text) pairs and return the top_k excerpts
        by descending relevance. Ties break on chunk_id (determinism)."""
        if len(excerpts) <= 1:
            return excerpts[:top_k]
        pairs = [(question, f"{e['header']}\n{e['text']}") for e in excerpts]
        scores = self.model.predict(pairs, show_progress_bar=False)
        order = sorted(range(len(excerpts)),
                       key=lambda i: (-float(scores[i]), excerpts[i]["chunk_id"]))
        return [excerpts[i] for i in order[:top_k]]
