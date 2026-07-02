"""Shared application state: config, stores, retrieval stack, canonicalizer.

Heavy pieces (the embedding model) load lazily on first use so the server
starts instantly; everything is a process-wide singleton because this is a
single-user local app.
"""

from __future__ import annotations

import logging
import threading

from config import load_config
from src.storage import SeriesStore

from .canonical import Canonicalizer

log = logging.getLogger(__name__)


class AppState:
    def __init__(self):
        self.cfg = load_config()
        self.store = SeriesStore(self.cfg)
        self.canon = Canonicalizer(self.store.db)
        self._embedder = None
        self._retriever = None
        # RLock: the retriever property calls the embedder property while
        # holding the lock — a plain Lock would deadlock.
        self._lock = threading.RLock()

    @property
    def db(self):
        return self.store.db

    @property
    def embedder(self):
        with self._lock:
            if self._embedder is None:
                log.info("loading embedding model (first query)…")
                from src.embedder import Embedder
                self._embedder = Embedder(self.cfg)
            return self._embedder

    @property
    def retriever(self):
        with self._lock:
            if self._retriever is None:
                from src.retriever import Retriever
                self._retriever = Retriever(self.cfg, self.store, self.embedder)
            return self._retriever

    def new_answerer(self):
        """Fresh Answerer per request so usage/cost is per-request."""
        from src.answerer import Answerer
        return Answerer(self.cfg)


state: AppState | None = None


def get_state() -> AppState:
    global state
    if state is None:
        state = AppState()
    return state
