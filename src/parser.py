"""Extract plain text from manuscript files (.pages primary; .txt/.md/.docx/.pdf too).

SOURCE FILE PROTECTION: files under BOOKS_DIR are treated as physically
read-only. Anything that needs converting is first copied into
{DATA_DIR}/staging/ and the conversion runs on that copy. The only reads of
the original are plain read-only opens (hashing, copying).

Extraction methods are tried in order until one succeeds:

  1. cache       — {DATA_DIR}/extracted_text/{sha256}.txt from an earlier run.
                   Keyed by content hash, so an unchanged source is never
                   re-converted.
  2. export-dir  — a pre-exported .txt in TEXT_EXPORT_DIR whose name contains
                   the source's stem and which is at least as new as the
                   source. (Lets an existing nightly export pipeline do the
                   heavy lifting.)
  3. applescript — macOS + Pages.app: scripted "export as unformatted text",
                   run on the STAGED COPY. This mirrors the author's proven
                   audiobook pipeline and is the most faithful converter.
  4. textutil    — macOS textutil on the staged copy. (Historically textutil
                   does NOT support .pages, but it is cheap to try and does
                   handle .docx/.rtf; failures are logged and skipped.)
  5. zip-xml     — .pages/.docx are ZIP archives; older .pages contain
                   index.xml, .docx contain word/document.xml. Tags stripped.
  6. zip-preview — newer .pages store the body as binary .iwa (not parseable
                   here) but usually embed QuickLook/Preview.pdf; extract its
                   text if a PDF reader is available.

A failure of any single method or file logs a warning and moves on — the
pipeline never crashes on one bad file.
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

log = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = {".pages", ".txt", ".md", ".docx", ".pdf"}


def file_sha256(path: Path) -> str:
    """Content hash of a file, streamed read-only in 1 MB blocks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:  # read-only
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


_FOOTNOTE_ANCHOR = "￼"  # object-replacement char: footnote/image anchors


def _strip_footnote_dump(text: str) -> str:
    """Pages' 'unformatted text' export appends every footnote body to the
    END of the document, each prefixed with U+FFFC. Left in place, that
    grab-bag becomes a chunk that vaguely matches every query. Strip it:
    walk paragraphs backwards while they start with the anchor; if the
    boundary paragraph has prose glued before its first anchor, keep the
    prose. Only acts on a document TAIL (never mid-book content)."""
    if _FOOTNOTE_ANCHOR not in text:
        return text
    paragraphs = text.split("\n")
    cut = len(paragraphs)
    for i in range(len(paragraphs) - 1, -1, -1):
        p = paragraphs[i].strip()
        if not p:
            cut = i
            continue
        if p.startswith(_FOOTNOTE_ANCHOR):
            cut = i
            continue
        if _FOOTNOTE_ANCHOR in p:
            # last prose paragraph with the first footnote glued on its end
            paragraphs[i] = paragraphs[i].split(_FOOTNOTE_ANCHOR, 1)[0].rstrip()
            cut = i + 1
        break
    dropped = len(paragraphs) - cut
    if dropped:
        log.info("stripped %d trailing footnote paragraph(s)", dropped)
    # remove any remaining inline anchors (harmless placeholder glyphs)
    return "\n".join(paragraphs[:cut]).replace(_FOOTNOTE_ANCHOR, "")


def _normalize(text: str) -> str:
    """Unify line endings, strip per-line trailing whitespace, and remove
    the trailing footnote dump that Pages exports append."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return _strip_footnote_dump(text)


def _stage_copy(source: Path, staging_dir: Path) -> Path:
    """Copy the source into staging (a real copy — never a symlink/hardlink)."""
    staging_dir.mkdir(parents=True, exist_ok=True)
    dest = staging_dir / source.name
    if dest.exists():
        if dest.is_dir():
            shutil.rmtree(dest)
        else:
            dest.unlink()
    if source.is_dir():  # .pages can be a package directory rather than a flat file
        shutil.copytree(source, dest, symlinks=False)
    else:
        shutil.copy2(source, dest)
    return dest


# ── individual extraction methods ──────────────────────────────────────────

def _try_export_dir(source: Path, export_dir: Path) -> str | None:
    """Find a pre-exported .txt named after this book that is not stale."""
    stem = source.stem.lower()
    candidates = [
        p for p in export_dir.glob("*.txt")
        if stem in p.stem.lower() and p.stat().st_mtime >= source.stat().st_mtime
    ]
    if not candidates:
        return None
    best = max(candidates, key=lambda p: p.stat().st_mtime)
    log.info("using pre-exported text: %s", best)
    return best.read_text(encoding="utf-8", errors="replace")


def _try_applescript(staged: Path) -> str | None:
    """Drive Pages.app to export the staged copy as unformatted text (macOS)."""
    if shutil.which("osascript") is None:
        return None
    out = staged.with_suffix(".export.txt")
    script = (
        'on run argv\n'
        ' tell application "Pages"\n'
        '  set d to open (POSIX file (item 1 of argv) as alias)\n'
        '  delay 1\n'
        '  export d to (POSIX file (item 2 of argv)) as unformatted text\n'
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
            text = out.read_text(encoding="utf-8", errors="replace")
            out.unlink()
            return text
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        log.debug("applescript export failed for %s: %s", staged.name, e)
    return None


def _try_textutil(staged: Path) -> str | None:
    if shutil.which("textutil") is None:
        return None
    out = staged.with_suffix(".textutil.txt")
    try:
        subprocess.run(
            ["textutil", "-convert", "txt", "-output", str(out), str(staged)],
            check=True, capture_output=True, timeout=120,
        )
        if out.exists():
            text = out.read_text(encoding="utf-8", errors="replace")
            out.unlink()
            return text
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        log.debug("textutil failed for %s: %s", staged.name, e)
    return None


def _xml_to_text(xml_bytes: bytes) -> str | None:
    """Strip an XML document down to its text content, paragraph-ish."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None
    parts: list[str] = []
    for elem in root.iter():
        # Paragraph-level tags in iWork ('p') and OOXML ('w:p') get newlines.
        tag = elem.tag.rsplit("}", 1)[-1]
        if tag == "p":
            parts.append("\n")
        if elem.text:
            parts.append(elem.text)
    text = "".join(parts)
    return text if text.strip() else None


def _try_zip_xml(staged: Path) -> str | None:
    """Older .pages: index.xml at the archive root. .docx: word/document.xml."""
    try:
        with zipfile.ZipFile(staged) as z:
            names = z.namelist()
            for candidate in ("index.xml", "word/document.xml"):
                if candidate in names:
                    return _xml_to_text(z.read(candidate))
            # some .pages nest index.xml inside index.zip
            if "index.zip" in names:
                import io
                with zipfile.ZipFile(io.BytesIO(z.read("index.zip"))) as inner:
                    if "index.xml" in inner.namelist():
                        return _xml_to_text(inner.read("index.xml"))
    except (zipfile.BadZipFile, KeyError, OSError) as e:
        log.debug("zip-xml failed for %s: %s", staged.name, e)
    return None


def _pdf_to_text(pdf_path: Path) -> str | None:
    """Extract text from a PDF via pypdf, if installed."""
    try:
        from pypdf import PdfReader  # optional dependency
    except ImportError:
        log.debug("pypdf not installed; cannot extract PDF text")
        return None
    try:
        reader = PdfReader(str(pdf_path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        return text if text.strip() else None
    except Exception as e:  # pypdf raises a zoo of exception types
        log.debug("pypdf failed for %s: %s", pdf_path.name, e)
        return None


def _try_zip_preview(staged: Path) -> str | None:
    """Newer .pages embed QuickLook/Preview.pdf; use it as a last resort."""
    try:
        with zipfile.ZipFile(staged) as z:
            preview = next(
                (n for n in z.namelist() if n.lower().endswith("preview.pdf")), None
            )
            if preview is None:
                return None
            with tempfile.TemporaryDirectory() as td:
                extracted = Path(z.extract(preview, td))
                return _pdf_to_text(extracted)
    except (zipfile.BadZipFile, OSError) as e:
        log.debug("zip-preview failed for %s: %s", staged.name, e)
    return None


# ── public API ──────────────────────────────────────────────────────────────

def extract_text(source: Path, cfg, force_method: str | None = None) -> tuple[str | None, str]:
    """Extract plain text from a manuscript file.

    Returns (text, method). text is None (method='failed') if every method
    failed — callers log-and-skip, never crash.
    force_method limits the chain to one named method (for testing).
    """
    source = source.expanduser().resolve()
    if source.suffix.lower() not in SUPPORTED_SUFFIXES:
        log.warning("unsupported file type, skipping: %s", source.name)
        return None, "failed"

    # Plain-text sources need no conversion — read them read-only, done.
    if source.suffix.lower() in (".txt", ".md"):
        return _normalize(source.read_text(encoding="utf-8", errors="replace")), "txt"

    cfg.ensure_data_dirs()
    src_hash = file_sha256(source)
    cache_file = cfg.extracted_text_dir / f"{src_hash}.txt"

    def finish(text: str, method: str) -> tuple[str, str]:
        text = _normalize(text)
        cache_file.write_text(text, encoding="utf-8")  # cache for next run
        log.info("extracted %s via %s (%d words)", source.name, method, len(text.split()))
        return text, method

    # 1. content-hash cache (re-normalized so normalization improvements
    #    apply to entries written by older versions of this code)
    if force_method in (None, "cache") and cache_file.exists():
        log.info("extracted-text cache hit for %s", source.name)
        return _normalize(cache_file.read_text(encoding="utf-8")), "cache"
    if force_method == "cache":
        return None, "failed"

    # 2. pre-exported text directory
    if force_method in (None, "export-dir") and cfg.text_export_dir:
        text = _try_export_dir(source, cfg.text_export_dir)
        if text:
            return finish(text, "export-dir")
    if force_method == "export-dir":
        return None, "failed"

    # 3-6. conversion methods — all operate on a staged COPY, never the original
    staged = _stage_copy(source, cfg.staging_dir)
    methods = [
        ("applescript", _try_applescript),
        ("textutil", _try_textutil),
        ("zip-xml", _try_zip_xml),
        ("zip-preview", _try_zip_preview),
    ]
    if source.suffix.lower() == ".pdf":
        methods = [("pypdf", _pdf_to_text)]
    if force_method:
        methods = [(n, f) for n, f in methods if n == force_method]

    try:
        for name, fn in methods:
            text = fn(staged)
            if text and text.strip():
                return finish(text, name)
    finally:
        # staging is transient; remove this file's copy immediately
        if staged.is_dir():
            shutil.rmtree(staged, ignore_errors=True)
        else:
            staged.unlink(missing_ok=True)

    log.warning("all extraction methods failed for %s — skipping this file", source.name)
    return None, "failed"
