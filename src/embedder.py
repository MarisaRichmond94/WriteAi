"""Embedding generation — local sentence-transformers or OpenAI.

EMBEDDING_PROVIDER=local  -> sentence-transformers, runs on this machine,
                             no API cost. Default model is
                             nomic-ai/nomic-embed-text-v1 (override with
                             EMBEDDING_MODEL in .env).
EMBEDDING_PROVIDER=openai -> text-embedding-3-small (requires OPENAI_API_KEY).

Nomic embed models are asymmetric: documents must be prefixed with
"search_document: " and queries with "search_query: " — retrieval quality
degrades noticeably without the prefixes, so this module owns them and
callers never see them.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

DEFAULT_LOCAL_MODEL = "nomic-ai/nomic-embed-text-v1"
OPENAI_MODEL = "text-embedding-3-small"


class Embedder:
    def __init__(self, cfg):
        self.provider = cfg.embedding_provider.lower()

        if self.provider == "local":
            from sentence_transformers import SentenceTransformer  # heavy import

            # `or`, not a .get() default: Settings writes EMBEDDING_MODEL= (empty)
            # to mean "use the default" — treat blank the same as unset
            self.model_name = os.environ.get("EMBEDDING_MODEL") or DEFAULT_LOCAL_MODEL
            # (optional) pin the torch device, e.g. EMBEDDING_DEVICE=cpu for
            # bit-reproducible query embeddings; unset -> library auto-select
            device = os.environ.get("EMBEDDING_DEVICE") or None
            log.info("loading local embedding model %s (device=%s) …",
                     self.model_name, device or "auto")
            # trust_remote_code is required by the nomic models (custom pooling)
            self.model = SentenceTransformer(self.model_name, trust_remote_code=True,
                                             device=device)
            self._is_nomic = "nomic" in self.model_name.lower()
        elif self.provider == "openai":
            from openai import OpenAI

            if not cfg.openai_api_key:
                raise ValueError("EMBEDDING_PROVIDER=openai requires OPENAI_API_KEY")
            self.model_name = OPENAI_MODEL
            self.client = OpenAI(api_key=cfg.openai_api_key)
        else:
            raise ValueError(f"unknown EMBEDDING_PROVIDER: {self.provider}")

    # ── public API ──────────────────────────────────────────────────────────

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self.provider == "local":
            if self._is_nomic:
                texts = [f"search_document: {t}" for t in texts]
            return self._encode_local(texts)
        return self._encode_openai(texts)

    def embed_query(self, text: str) -> list[float]:
        if self.provider == "local":
            if self._is_nomic:
                text = f"search_query: {text}"
            return self._encode_local([text])[0]
        return self._encode_openai([text])[0]

    # ── internals ───────────────────────────────────────────────────────────

    def _encode_local(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(
            texts, batch_size=16, normalize_embeddings=True, show_progress_bar=False
        )
        return [v.tolist() for v in vectors]

    def _encode_openai(self, texts: list[str]) -> list[list[float]]:
        # The embeddings endpoint accepts up to 2048 inputs; stay well under.
        vectors: list[list[float]] = []
        for i in range(0, len(texts), 512):
            response = self.client.embeddings.create(
                model=self.model_name, input=texts[i:i + 512]
            )
            vectors.extend(item.embedding for item in response.data)
        return vectors
