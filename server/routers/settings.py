"""Settings pane: .env fields (validated, keys masked) + writer profile."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel

import settings as settings_cli  # repo-root settings.py (read/write/validate)

from .. import writer_store
from ..deps import get_state

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

_MASKABLE = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")

# The chat models this deployment offers, served so a second app does not have
# to keep its own copy (LOOM-119). Loom's Explore tab renders whatever this
# returns — a hard-coded list on that side would be the one nobody updates, and
# the failure is silent: an unpriced model still answers, and only the spend
# figure is wrong.
#
# Kept in step with frontend/src/lib/models.ts and with PRICING_PER_MTOK by
# tests/test_model_pricing.py, which parses all three. Fable 5 is deliberately
# absent — $10/$50 per MTok is not a sane default for interrogating prose.
CHAT_MODELS = [
    {"id": "claude-opus-5", "label": "Opus 5"},
    {"id": "claude-opus-4-8", "label": "Opus 4.8"},
    {"id": "claude-sonnet-5", "label": "Sonnet 5"},
    {"id": "claude-haiku-4-5", "label": "Haiku 4.5"},
]
# Sonnet 5, not Opus 5 — $3/$15 against $5/$25, and Explore is asked casual
# questions all day rather than a handful of hard ones. Opus stays one click
# away in the picker for the questions that earn it. The list keeps Opus first
# because it is ordered by capability, not by default-ness.
DEFAULT_CHAT_MODEL = "claude-sonnet-5"


@router.get("/models")
def list_models():
    """Chat models offered, plus the one a request with `model: null` gets.

    ⚠️ `default` MUST be the EFFECTIVE default — `cfg.query_model`, set by
    QUERY_MODEL in .env — not a constant this module would prefer. It read
    `ui_settings()` at first, which does not hold that key, so it fell through
    to DEFAULT_CHAT_MODEL and advertised `claude-sonnet-5` while an unspecified
    request actually ran on `claude-sonnet-4-6`. Verified 2026-08-05 by
    checking a real answer's `usage.model` against what this endpoint claimed.
    Nothing errors when those disagree; the picker just shows one model and
    bills for another.

    The configured model is added to the offered list when it is priced but
    not already there, so the picker can show what is actually selected. A
    configured model with no pricing entry is NOT offered — it would answer
    fine and cost the wrong amount, which is the failure test_model_pricing.py
    exists to prevent.

    A pure read of config plus module constants; safe on tab open.
    """
    from src.extractor import PRICING_PER_MTOK

    configured = get_state().cfg.query_model
    models = list(CHAT_MODELS)
    if (configured
            and configured in PRICING_PER_MTOK
            and not any(m["id"] == configured for m in models)):
        models.append({"id": configured, "label": configured})

    offered = {m["id"] for m in models}
    default = configured if configured in offered else DEFAULT_CHAT_MODEL
    return {"models": models, "default": default}


def _mask(key: str, value: str) -> str:
    if key in _MASKABLE and len(value) > 12:
        return value[:8] + "…" + value[-4:]
    return value


@router.get("/settings")
def get_settings():
    values = settings_cli.read_env(settings_cli.ENV_PATH)
    fields = [{"key": key, "prompt": prompt, "kind": kind,
               "value": _mask(key, values.get(key, default)),
               "secret": key in _MASKABLE}
              for key, prompt, default, kind in settings_cli.FIELDS]
    s = get_state()
    counts = {t: s.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("chunks", "characters", "character_knowledge",
                        "foreshadowing", "unresolved_questions")}
    from src.discovery import discover_books
    loom_series_id = None
    try:
        books = discover_books(get_state().cfg)
        discovered = [b.title for b in books]
        # Stable Loom series id (KAN-12), read from the manifest sidecars. Every
        # book in a series carries the same one, so the first that resolves
        # wins. None when nothing has been canon-exported yet — the UI falls
        # back to title-addressed jump links.
        loom_series_id = next((b.loom_series_id for b in books if b.loom_series_id), None)
    except Exception:
        discovered = []
    return {"fields": fields, "discovered_books": discovered,
            "profile": writer_store.ui_settings(),
            "loom_series_id": loom_series_id,
            "store_counts": counts}


class SettingsPut(BaseModel):
    values: dict[str, str] = {}    # only changed env keys
    profile: dict | None = None


@router.put("/settings")
def put_settings(body: SettingsPut):
    if body.values:
        values = settings_cli.read_env(settings_cli.ENV_PATH)
        for key, value in body.values.items():
            if any(key == f[0] for f in settings_cli.FIELDS) and "…" not in value:
                values[key] = value
        settings_cli.write_env(values)
    if body.profile is not None:
        writer_store.save_ui_settings({**writer_store.ui_settings(),
                                       **body.profile})
    return {"ok": True}


@router.post("/settings/writer-photo")
async def upload_writer_photo(file: UploadFile):
    from pathlib import Path

    from .. import writer_store as ws
    suffix = Path(file.filename or "photo.png").suffix.lower() or ".png"
    if suffix not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        raise HTTPException(400, "unsupported image type")
    photos_dir = ws.WRITER_DATA_DIR / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)
    for old in photos_dir.glob("writer.*"):
        old.unlink()
    dest = photos_dir / f"writer{suffix}"
    dest.write_bytes(await file.read())
    photo_url = f"/api/plan/photos/{dest.name}"
    ws.save_ui_settings({**ws.ui_settings(), "writer_photo_url": photo_url})
    return {"photo_url": photo_url}


@router.delete("/settings/writer-photo")
def delete_writer_photo():
    from .. import writer_store as ws
    photos_dir = ws.WRITER_DATA_DIR / "photos"
    for old in photos_dir.glob("writer.*"):
        old.unlink()
    ws.save_ui_settings({**ws.ui_settings(), "writer_photo_url": None})
    return {"ok": True}


def _safe_slug(slug: str) -> str:
    """Reject anything that isn't a plain slug so file ops can't escape the dir."""
    if not slug or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-" for ch in slug):
        raise HTTPException(400, "invalid slug")
    return slug


@router.get("/settings/book-cover/{slug}")
def book_cover_by_slug(slug: str):
    """The status/settings panes request covers by slugified book name.
    A manual upload overrides the auto-detected dust-jacket cover."""
    from fastapi.responses import FileResponse

    from src.discovery import discover_books

    from .books import book_cover, book_slug, manual_cover_path
    manual = manual_cover_path(slug)
    if manual is not None:
        return FileResponse(manual, headers={"Cache-Control": "no-cache"})
    s = get_state()
    for b in discover_books(s.cfg):
        if book_slug(b.title) == slug or b.title.lower() == slug.lower():
            return book_cover(b.number)
    raise HTTPException(404, "unknown book")


@router.post("/settings/book-cover/{slug}")
async def upload_book_cover(slug: str, file: UploadFile):
    """Store a manual cover override; it wins over the dust-jacket cover."""
    from pathlib import Path

    from .books import COVERS_DIR
    slug = _safe_slug(slug)
    suffix = Path(file.filename or "cover.png").suffix.lower() or ".png"
    if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
        raise HTTPException(400, "unsupported image type")
    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    for old in COVERS_DIR.glob(f"{slug}.*"):
        old.unlink()
    dest = COVERS_DIR / f"{slug}{suffix}"
    dest.write_bytes(await file.read())
    return {"ok": True}


@router.delete("/settings/book-cover/{slug}")
def delete_book_cover(slug: str):
    """Drop the manual override, reverting to the auto-detected cover."""
    from .books import COVERS_DIR
    slug = _safe_slug(slug)
    if COVERS_DIR.exists():
        for old in COVERS_DIR.glob(f"{slug}.*"):
            old.unlink()
    return {"ok": True}


@router.post("/settings/validate")
def validate_settings():
    values = settings_cli.read_env(settings_cli.ENV_PATH)
    problems = settings_cli.run_checks(values, verbose=False)
    books = settings_cli.find_books(values)
    return {"ok": not problems, "problems": problems,
            "books": books if isinstance(books, list) else []}


class PickFolderBody(BaseModel):
    current: str | None = None


@router.post("/settings/pick-folder")
def pick_folder(body: PickFolderBody):
    """Native macOS folder chooser — fine for a local single-user app.
    Returns {path: null} when the user cancels."""
    import os
    import subprocess
    from pathlib import Path as _P

    script = 'POSIX path of (choose folder with prompt "Select a folder")'
    if body.current:
        cur = _P(os.path.expanduser(body.current))
        if cur.is_dir():
            script = ('POSIX path of (choose folder with prompt '
                      f'"Select a folder" default location POSIX file "{cur}")')
    try:
        out = subprocess.run(["osascript", "-e", script],
                             capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return {"path": None}
    if out.returncode != 0:  # user cancelled the dialog
        return {"path": None}
    path = out.stdout.strip().rstrip("/")
    return {"path": path or None}
