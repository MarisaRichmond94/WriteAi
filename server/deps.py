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
        # dedicated connection for the canonicalizer: its build phase runs
        # many queries and must never interleave with request queries
        import sqlite3
        self.canon = Canonicalizer(
            sqlite3.connect(self.cfg.sqlite_path, check_same_thread=False))
        self._embedder = None
        self._retriever = None
        self._local = threading.local()
        # RLock: the retriever property calls the embedder property while
        # holding the lock — a plain Lock would deadlock.
        self._lock = threading.RLock()

    @property
    def db(self):
        """Thread-local SQLite connection. FastAPI serves sync endpoints from
        a threadpool; sharing one connection across those threads interleaves
        cursors and corrupts results (sporadic 500s). One connection per
        worker thread is safe — SQLite coordinates between connections."""
        import sqlite3
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.cfg.sqlite_path, check_same_thread=False)
            conn.execute("PRAGMA foreign_keys = ON")
            self._local.conn = conn
        return conn

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
_state_lock = threading.Lock()


def get_state() -> AppState:
    """Singleton, created under a lock: parallel first requests must not
    construct two AppStates (double-initializing ChromaDB fails)."""
    global state
    if state is None:
        with _state_lock:
            if state is None:
                state = AppState()
    return state
