"""Writer-authored data: plan outlines, character intent, merge decisions,
UI profile. Lives in writer_data/ — separate from data/ (machine-generated,
rebuildable) and deliberately untracked by git. These files are the user's
decisions; nothing here is ever produced or modified by AI.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from config import REPO_ROOT

WRITER_DATA_DIR = REPO_ROOT / "writer_data"

_LOCK = threading.Lock()


def _path(name: str) -> Path:
    WRITER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    return WRITER_DATA_DIR / name


def load(name: str, default):
    p = _path(name)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # never lose user data: preserve the corrupt file and start fresh
        p.rename(p.with_suffix(".corrupt"))
        return default


def save(name: str, value) -> None:
    with _LOCK:
        p = _path(name)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(p)  # atomic on POSIX


# ── typed accessors ─────────────────────────────────────────────────────────

def character_map() -> dict:
    """User decisions about extracted character names.
      map:    {"variant name": "canonical name"}   (merge/assign)
      hidden: ["name", ...]                        (exclude from UI)
    """
    return load("character_map.json", {"map": {}, "hidden": []})


def save_character_map(value: dict) -> None:
    save("character_map.json", value)


def plan_outline() -> dict:
    """{book_number(str): [outline chapter dicts]}"""
    return load("plan_outline.json", {})


def save_plan_outline(value: dict) -> None:
    save("plan_outline.json", value)


def writer_characters() -> list:
    return load("writer_characters.json", [])


def save_writer_characters(value: list) -> None:
    save("writer_characters.json", value)


def ui_settings() -> dict:
    defaults = {"writer_name": "Writer", "site_name": "The Archive",
                "sync_time": "02:30", "auto_sync_enabled": True,
                "backup_retention_days": 30}
    return {**defaults, **load("ui_settings.json", {})}


def save_ui_settings(value: dict) -> None:
    save("ui_settings.json", value)


def writer_events() -> dict:
    """Writer-authored timeline events (distinct from AI-extracted events).
      events:    [{id, title, date, description, characters, location,
                   book_chapters:[{book, chapter}], created_at, updated_at}]
      locations: ["name", ...]   writer-created location pool
    """
    return load("writer_events.json", {"events": [], "locations": []})


def save_writer_events(value: dict) -> None:
    save("writer_events.json", value)
