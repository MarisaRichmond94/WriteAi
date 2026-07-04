"""Loads and validates settings from .env and exposes them as a Config object.

The .env file is parsed manually (KEY=VALUE lines, # comments) so the core
pipeline has zero third-party dependencies. Values already present in the
process environment win over the file, which makes overrides easy:

    DATA_DIR=/tmp/test-data python ingest.py --dry-run
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent


def _load_env_file(path: Path) -> None:
    """Read KEY=VALUE lines into os.environ (existing env vars take priority)."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _expand(p: str) -> Path:
    """Expand ~ and resolve relative paths against the repo root."""
    path = Path(os.path.expanduser(p))
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def _get_bool(key: str, default: bool) -> bool:
    return os.environ.get(key, str(default)).strip().lower() in ("1", "true", "yes")


def _get_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except ValueError:
        logging.warning("%s is not an integer; using default %d", key, default)
        return default


@dataclass
class Config:
    books_dir: Path
    series_name: str
    book_prefix_pattern: re.Pattern
    data_dir: Path
    text_export_dir: Path | None

    extraction_model: str
    query_model: str
    embedding_provider: str
    anthropic_api_key: str
    openai_api_key: str

    max_chunk_tokens: int
    top_k_results: int
    confirm_before_ingest: bool
    enable_hybrid_search: bool
    enable_alias_resolution: bool
    extraction_use_batches: bool
    log_level: str
    cost_log_enabled: bool = True
    enable_prompt_cache_v2: bool = False

    # Derived data locations (all under data_dir; created on demand)
    staging_dir: Path = field(init=False)
    extracted_text_dir: Path = field(init=False)
    chroma_dir: Path = field(init=False)
    sqlite_path: Path = field(init=False)
    chunk_hashes_path: Path = field(init=False)
    rich_text_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        self.staging_dir = self.data_dir / "staging"
        self.extracted_text_dir = self.data_dir / "extracted_text"
        self.chroma_dir = self.data_dir / "chroma_db"
        self.sqlite_path = self.data_dir / "series_metadata.sqlite"
        self.chunk_hashes_path = self.data_dir / "chunk_hashes.json"
        self.rich_text_dir = self.data_dir / "rich_text"

    def ensure_data_dirs(self) -> None:
        """Create the writable data directories. Never touches books_dir."""
        for d in (self.data_dir, self.staging_dir, self.extracted_text_dir):
            d.mkdir(parents=True, exist_ok=True)

    def assert_never_inside_books_dir(self, path: Path) -> None:
        """Guard: refuse any writable path that lives under BOOKS_DIR."""
        try:
            path.resolve().relative_to(self.books_dir.resolve())
        except ValueError:
            return  # not inside books_dir — fine
        raise RuntimeError(
            f"Refusing to use {path} — it is inside BOOKS_DIR ({self.books_dir}), "
            "which is strictly read-only."
        )


def load_config(env_file: Path | None = None) -> Config:
    """Load .env (if present), validate the essentials, return a Config."""
    _load_env_file(env_file or REPO_ROOT / ".env")

    books_dir = _expand(os.environ.get("BOOKS_DIR", "~/Writing"))
    if not books_dir.is_dir():
        raise FileNotFoundError(
            f"BOOKS_DIR does not exist: {books_dir} — run `python settings.py` to configure."
        )

    try:
        prefix = re.compile(os.environ.get("BOOK_PREFIX_PATTERN", r"^\d+\."))
    except re.error as e:
        raise ValueError(f"BOOK_PREFIX_PATTERN is not a valid regex: {e}") from e

    export_raw = os.environ.get("TEXT_EXPORT_DIR", "").strip()
    text_export_dir = _expand(export_raw) if export_raw else None
    if text_export_dir and not text_export_dir.is_dir():
        logging.warning("TEXT_EXPORT_DIR does not exist (%s); ignoring it.", text_export_dir)
        text_export_dir = None

    cfg = Config(
        books_dir=books_dir,
        series_name=os.environ.get("SERIES_NAME", "My Series"),
        book_prefix_pattern=prefix,
        data_dir=_expand(os.environ.get("DATA_DIR", "./data")),
        text_export_dir=text_export_dir,
        extraction_model=os.environ.get("EXTRACTION_MODEL", "claude-haiku-4-5"),
        query_model=os.environ.get("QUERY_MODEL", "claude-sonnet-4-6"),
        embedding_provider=os.environ.get("EMBEDDING_PROVIDER", "local"),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
        max_chunk_tokens=_get_int("MAX_CHUNK_TOKENS", 800),
        top_k_results=_get_int("TOP_K_RESULTS", 15),
        confirm_before_ingest=_get_bool("CONFIRM_BEFORE_INGEST", True),
        enable_hybrid_search=_get_bool("ENABLE_HYBRID_SEARCH", False),
        enable_alias_resolution=_get_bool("ENABLE_ALIAS_RESOLUTION", False),
        extraction_use_batches=_get_bool("EXTRACTION_USE_BATCHES", False),
        log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        cost_log_enabled=_get_bool("COST_LOG_ENABLED", True),
        enable_prompt_cache_v2=_get_bool("ENABLE_PROMPT_CACHE_V2", False),
    )
    cfg.assert_never_inside_books_dir(cfg.data_dir)

    logging.basicConfig(
        level=getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    return cfg
