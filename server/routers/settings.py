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
    return {"fields": fields, "profile": writer_store.ui_settings(),
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


@router.get("/settings/book-cover/{slug}")
def book_cover_by_slug(slug: str):
    """The status pane requests covers by slugified book name."""
    from src.discovery import discover_books

    from .books import book_cover
    s = get_state()
    for b in discover_books(s.cfg):
        b_slug = "".join(ch if ch.isalnum() else "-" for ch in b.title.lower())
        b_slug = "-".join(part for part in b_slug.split("-") if part)
        if b_slug == slug or b.title.lower() == slug.lower():
            return book_cover(b.number)
    raise HTTPException(404, "unknown book")


@router.post("/settings/validate")
def validate_settings():
    values = settings_cli.read_env(settings_cli.ENV_PATH)
    problems = settings_cli.run_checks(values, verbose=False)
    books = settings_cli.find_books(values)
    return {"ok": not problems, "problems": problems,
            "books": books if isinstance(books, list) else []}
