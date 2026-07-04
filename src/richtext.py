"""Rich-text sidecar for the UI's chapter viewers.

The plain-text extraction (parser.py) is canonical — chunking, hashing,
embeddings, and the LLM all work from it, and Pages' "unformatted text"
export strips italics, colors, and alignment on the way out. This module
recovers that formatting for *display only*: the manuscript is exported to
.docx (via the same proven Pages AppleScript route), word/document.xml is
converted to a compact list of paragraphs — runs with italic/bold/underline/
color plus paragraph alignment — and the result is split into per-chapter
JSON files under {DATA_DIR}/rich_text/book_{n}/.

Everything here is best-effort and content-hash cached: an unchanged
manuscript never re-opens Pages, and any failure logs a warning and leaves
the viewers on their plain-text fallback. No LLM calls, no API cost.

SOURCE FILE PROTECTION: as in parser.py, originals under BOOKS_DIR are only
ever opened read-only; conversions run on staged copies.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from .chunker import CHAPTER_RE, DATE_RE, PART_RE, PROLOGUE_RE
from .parser import _stage_copy, file_sha256

log = logging.getLogger(__name__)

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# A paragraph is {"align": "center"|"right"|"justify"?, "runs": [run, …]};
# a run is {"text": str, "i": True?, "b": True?, "u": True?, "color": "#…"?}.
# Only truthy keys are written, keeping the JSON close to the text's size.

_ALIGN = {"center": "center", "right": "right", "both": "justify", "end": "right"}

_OFF_VALS = {"0", "false", "none"}


def _prop_on(rpr: ET.Element | None, tag: str) -> bool:
    if rpr is None:
        return False
    el = rpr.find(f"{_W}{tag}")
    if el is None:
        return False
    return el.get(f"{_W}val", "1").lower() not in _OFF_VALS


def _run_props(rpr: ET.Element | None) -> dict:
    props: dict = {}
    if _prop_on(rpr, "i"):
        props["i"] = True
    if _prop_on(rpr, "b"):
        props["b"] = True
    if _prop_on(rpr, "u"):
        # <w:u w:val="none"/> is how underline is switched OFF
        u = rpr.find(f"{_W}u") if rpr is not None else None
        if u is None or u.get(f"{_W}val", "single").lower() != "none":
            props["u"] = True
    if rpr is not None:
        color = rpr.find(f"{_W}color")
        if color is not None:
            val = (color.get(f"{_W}val") or "").strip()
            if val and val.lower() != "auto":
                props["color"] = f"#{val}"
    return props


def paragraphs_from_docx_xml(xml_bytes: bytes) -> list[dict]:
    """Convert word/document.xml into the paragraph/run structure above.
    Empty paragraphs are dropped — the plain-text pipeline's chunker skips
    blank lines the same way, keeping the two views' content aligned."""
    root = ET.fromstring(xml_bytes)
    body = root.find(f"{_W}body")
    if body is None:
        return []

    paragraphs: list[dict] = []
    for p in body.iter(f"{_W}p"):
        para: dict = {"runs": []}
        ppr = p.find(f"{_W}pPr")
        if ppr is not None:
            jc = ppr.find(f"{_W}jc")
            if jc is not None:
                align = _ALIGN.get((jc.get(f"{_W}val") or "").lower())
                if align:
                    para["align"] = align

        for r in p.iter(f"{_W}r"):
            props = _run_props(r.find(f"{_W}rPr"))
            text = ""
            for child in r:
                tag = child.tag
                if tag == f"{_W}t":
                    text += child.text or ""
                elif tag == f"{_W}br":
                    text += "\n"
                elif tag == f"{_W}tab":
                    text += "\t"
            if not text:
                continue
            runs = para["runs"]
            # merge with the previous run when the formatting is identical
            if runs and _run_key(runs[-1]) == _run_key({"text": "", **props}):
                runs[-1]["text"] += text
            else:
                runs.append({"text": text, **props})

        if any(run["text"].strip() for run in para["runs"]):
            paragraphs.append(para)
    return paragraphs


def _run_key(run: dict) -> tuple:
    return (run.get("i"), run.get("b"), run.get("u"), run.get("color"))


def _para_text(para: dict) -> str:
    return "".join(run["text"] for run in para["runs"]).strip()


def split_rich_chapters(paragraphs: list[dict]) -> dict[int, list[dict]]:
    """Mirror of chunker.split_into_segments over rich paragraphs: the same
    heading regexes decide chapter boundaries, and the heading, POV line,
    date line, and part-divider pages are excluded — matching what the
    chapter-text endpoint reconstructs from chunks."""
    chapters: dict[int, list[dict]] = {}
    current: list[dict] | None = None
    started = False
    seen_pov = False
    seen_body = False
    skip_next = False  # a part divider's subtitle paragraph

    for para in paragraphs:
        text = _para_text(para)
        if skip_next:
            skip_next = False
            continue
        if PROLOGUE_RE.match(text):
            started = True
            current = chapters.setdefault(0, [])
            seen_pov = seen_body = False
        elif started and PART_RE.match(text):
            current = None
            skip_next = True
        elif CHAPTER_RE.match(text):
            started = True
            current = chapters.setdefault(int(text), [])
            seen_pov = seen_body = False
        elif started and current is not None and text:
            if not seen_pov and not seen_body:
                seen_pov = True  # first body line is the POV name
            elif seen_pov and not seen_body and DATE_RE.match(text):
                seen_body = True  # optional date line directly after the POV
            else:
                seen_body = True
                current.append(para)
    return chapters


def _export_docx_via_pages(staged: Path) -> Path | None:
    """Drive Pages.app to export the staged copy as Word (macOS). Same
    AppleScript route parser.py uses for unformatted text."""
    if shutil.which("osascript") is None:
        return None
    out = staged.with_suffix(".rich.docx")
    script = (
        'on run argv\n'
        ' tell application "Pages"\n'
        '  set d to open (POSIX file (item 1 of argv) as alias)\n'
        '  delay 1\n'
        '  export d to (POSIX file (item 2 of argv)) as Microsoft Word\n'
        '  close d saving no\n'
        ' end tell\n'
        'end run'
    )
    try:
        subprocess.run(
            ["osascript", "-e", script, str(staged), str(out)],
            check=True, capture_output=True, timeout=120,
        )
        if out.exists():
            return out
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        log.debug("Pages Word export failed for %s: %s", staged.name, e)
    return None


def extract_rich_paragraphs(source: Path, cfg) -> list[dict] | None:
    """Whole-book rich paragraphs, content-hash cached. None when the source
    format has no formatting to recover or every conversion failed."""
    source = source.expanduser().resolve()
    suffix = source.suffix.lower()
    if suffix not in (".pages", ".docx"):
        return None

    cfg.ensure_data_dirs()
    cache_file = cfg.extracted_text_dir / f"{file_sha256(source)}.rich.json"
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass  # corrupt cache — regenerate below

    staged = _stage_copy(source, cfg.staging_dir)
    exported: Path | None = None
    try:
        docx = staged if suffix == ".docx" else _export_docx_via_pages(staged)
        exported = docx if docx is not staged else None
        if docx is None:
            return None
        with zipfile.ZipFile(docx) as z:
            paragraphs = paragraphs_from_docx_xml(z.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError, OSError) as e:
        log.warning("rich-text conversion failed for %s: %s", source.name, e)
        return None
    finally:
        if exported is not None:
            exported.unlink(missing_ok=True)
        if staged.is_dir():
            shutil.rmtree(staged, ignore_errors=True)
        else:
            staged.unlink(missing_ok=True)

    cache_file.write_text(json.dumps(paragraphs, ensure_ascii=False),
                          encoding="utf-8")
    log.info("rich text extracted for %s (%d paragraphs)",
             source.name, len(paragraphs))
    return paragraphs


def sync_rich_text(cfg, book) -> None:
    """Refresh {DATA_DIR}/rich_text/book_{n}/ for one discovered book.
    Best-effort: any failure leaves existing sidecar files in place and the
    viewers on their plain-text fallback."""
    try:
        paragraphs = extract_rich_paragraphs(book.manuscript, cfg)
        if paragraphs is None:
            return
        chapters = split_rich_chapters(paragraphs)
        book_dir = cfg.rich_text_dir / f"book_{book.number}"
        if book_dir.exists():
            shutil.rmtree(book_dir)  # drop chapters that no longer exist
        book_dir.mkdir(parents=True, exist_ok=True)
        for num, paras in chapters.items():
            (book_dir / f"chapter_{num}.json").write_text(
                json.dumps(paras, ensure_ascii=False), encoding="utf-8")
        log.info("rich text: book %d (%s) -> %d chapter file(s)",
                 book.number, book.title, len(chapters))
    except Exception as e:  # never let display polish break a sync
        log.warning("rich-text sync failed for book %d (%s): %s",
                    book.number, book.title, e)
