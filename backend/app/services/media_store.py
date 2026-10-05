"""The files of brands: logos, fonts, examples.

Each lies in the media folder under its id, with a row in ``media`` that says what it is (found from the bytes, never
from the name), in which space it lives, and its size. The rights of the space decide who may see it. The same bytes
uploaded twice into one space are kept once.

On the way in, place and device are taken out of photos and videos (``services/media.py``, the operator can turn it
off); a HEIC photo, which browsers cannot show, is kept as an upright WebP instead. PDFs learn their page count.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Account, Media
from . import avatars, media, settings_service

logger = logging.getLogger("nexbrand.media")

#: What a browser shows by itself, by kind; everything else is offered as a download.
SHOWN = {
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
    "avif": "image/avif",
    "bmp": "image/bmp",
    "mp4": "video/mp4",
    "mov": "video/quicktime",
    # An SVG runs nothing here: shown in an <img>, or opened alone under a policy without scripts (routers/media).
    "svg": "image/svg+xml",
    "woff2": "font/woff2",
    "woff": "font/woff",
    "otf": "font/otf",
    "ttf": "font/ttf",
}
IMAGES = {"jpeg", "png", "gif", "webp", "avif", "bmp"}
MAX_NAME = 200


class MediaError(Exception):
    def __init__(self, code: str, text: str, status: int = 422) -> None:
        super().__init__(text)
        self.code = code
        self.text = text
        self.status = status

    def values(self) -> dict[str, int]:
        """What the message names, for the page to say it in its language."""
        return {"max_million": MAX_PIXELS // 1_000_000} if self.code == "too_many_pixels" else {}


@dataclass
class Stored:
    id: str
    name: str
    kind: str
    mime: str
    size: int
    width: int
    height: int
    pages: int
    #: What was taken out of a photo: ``location``, ``device``, ``metadata``, ``unchecked``.
    removed: list[str]
    #: The same bytes were in the space already; this is that file.
    known: bool


def root() -> Path:
    path = get_settings().media_dir
    assert path is not None
    path.mkdir(parents=True, exist_ok=True)
    return path


def path_of(media_id: str) -> Path:
    return root() / media_id


#: Pictures larger than this (on their longer side) get a smaller copy for showing in the interface.
PREVIEW_SIDE = 1600


def preview_of(media_id: str) -> Path:
    """The smaller copy of a photo, next to it (ids never hold a dot, so the name is never another id)."""
    return root() / f"{media_id}.p"


def _make_preview(source: Path, target: Path) -> bool:
    """A WebP of at most ``PREVIEW_SIDE`` pixels on its longer side, upright, without any metadata."""
    try:
        from PIL import Image, ImageOps

        with Image.open(source) as image:
            if getattr(image, "is_animated", False):
                return False
            upright = ImageOps.exif_transpose(image)
            upright.thumbnail((PREVIEW_SIDE, PREVIEW_SIDE))
            if upright.mode not in ("RGB", "RGBA"):
                upright = upright.convert("RGBA" if "A" in upright.getbands() else "RGB")
            upright.save(target, "WEBP", quality=82, method=4)
        return True
    except Exception as exc:  # noqa: BLE001 - a broken picture fails in the decoder's own way
        logger.info("No preview for a picture: %s", type(exc).__name__)
        target.unlink(missing_ok=True)
        return False


def temporary() -> Path:
    return root() / f".upload-{secrets.token_hex(8)}"


def clean_name(name: str) -> str:
    text = "".join(char for char in name if ord(char) >= 32 and char not in '\\/:*?"<>|').strip(" .")
    return (text or "file")[:MAX_NAME]


def max_bytes(db: Session) -> int:
    return settings_service.upload_max_mb(db) * 1024 * 1024


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _picture_size(path: Path) -> tuple[int, int]:
    try:
        from PIL import Image

        with Image.open(path) as image:
            # Upright as shown: a portrait photo is stored lying with an orientation tag.
            orientation = image.getexif().get(0x0112, 1)
            width, height = image.size
            if orientation in (5, 6, 7, 8):
                width, height = height, width
            return width, height
    except Exception:  # noqa: BLE001 - a broken picture fails in the decoder's own way
        return 0, 0


def _pdf_pages(path: Path) -> int:
    try:
        from pypdf import PdfReader

        return len(PdfReader(path).pages)
    except Exception:  # noqa: BLE001 - a broken or encrypted PDF is still kept, without a page count
        return 0


def is_svg(head: bytes) -> bool:
    """An SVG by its beginning: optional byte order mark, XML declaration, comments or doctype, then ``<svg``."""
    text = head.lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    return text.startswith((b"<?xml", b"<svg", b"<!--", b"<!doctype svg")) and b"<svg" in text


#: Pixels a picture may have, the same line as for profile pictures: a PNG of a few kilobytes can open as gigabytes.
MAX_PIXELS = avatars.MAX_PIXELS
#: The SVG a logo may be is read whole; larger is no drawing anybody made by hand or in a program.
MAX_SVG_BYTES = 8 * 1024 * 1024
#: Inside an SVG, elements that run or embed something other than a drawing.
SVG_REFUSED = {"script", "foreignobject", "iframe", "embed", "object", "handler", "listener"}


def _pixels(path: Path, kind: str) -> int:
    """Width times height from the picture's header, before a pixel is decoded; 0 when it cannot be read."""
    try:
        from PIL import Image

        if kind in ("heic", "avif"):
            import pillow_heif

            pillow_heif.register_heif_opener()
        with Image.open(path) as image:
            return int(image.width) * int(image.height)
    except Exception as exc:  # noqa: BLE001 - a broken picture fails in the decoder's own way
        # Pillow refuses a header beyond twice its own limit before reading on: as many pixels as that, at least.
        if type(exc).__name__ == "DecompressionBombError":
            return MAX_PIXELS + 1
        return 0


def svg_problem(data: bytes) -> str | None:
    """Why an SVG may not come in, or None. Refused, never mended (A12): a script, an event attribute (``on…``), a
    ``javascript:`` address, embedded HTML (``foreignObject``), a DOCTYPE or entity, or XML that does not read.
    A logo travels into the client's websites and design systems; there it would run."""
    from xml.etree import ElementTree

    lowered = data.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        return "doctype"
    try:
        root = ElementTree.fromstring(data)
    except (ElementTree.ParseError, ValueError):
        return "unreadable"
    for element in root.iter():
        tag = str(element.tag).rsplit("}", 1)[-1].lower()
        if tag in SVG_REFUSED:
            return tag
        for key, value in element.attrib.items():
            if key.rsplit("}", 1)[-1].lower().startswith("on"):
                return "event"
            # Browsers drop control characters and blanks inside a scheme: "java\tscript:" runs as well; and an
            # animation's list of values ("x;javascript:…") sets the address one after another.
            plain = "".join(char for char in value if ord(char) > 32).lower()
            if any(scheme in plain for scheme in ("javascript:", "vbscript:", "data:text/html")):
                return "javascript"
    return None


def _svg_bytes(path: Path) -> bytes:
    """The text of an SVG, unpacked when it is an SVGZ; more than ``MAX_SVG_BYTES`` is refused."""
    import gzip

    with open(path, "rb") as handle:
        data = handle.read(MAX_SVG_BYTES + 1)
    if data.startswith(b"\x1f\x8b"):
        try:
            with gzip.open(path, "rb") as packed:
                data = packed.read(MAX_SVG_BYTES + 1)
        except (OSError, EOFError):
            return b""
    if len(data) > MAX_SVG_BYTES:
        raise MediaError("svg_too_large", "This SVG is larger than a logo can be.", 413)
    return data


def finish(db: Session, account: Account, space_id: int, received: Path, name: str) -> Stored:
    """The file at ``received`` (a temporary file in the media folder) becomes a media file, or is found as one.
    ``MediaError`` for a file refused: an SVG that could run something, a picture of too many pixels."""
    with open(received, "rb") as handle:
        head = handle.read(1024)
    kind = media.sniff(head[:64]) or ("svg" if is_svg(head) else "file")
    # Named an SVG and holding one, but not starting as one (junk in front, packed): checked all the same, it opens as
    # one elsewhere. A text that holds no drawing stays a file.
    named_svg = kind == "file" and name.lower().rstrip(" .").endswith((".svg", ".svgz"))
    text = _svg_bytes(received) if kind == "svg" or named_svg else b""
    if kind == "svg" or (named_svg and b"<svg" in text.lower()):
        problem = svg_problem(text)
        if problem is not None:
            logger.info("SVG refused why=%s by=%s", problem, account.name)
            raise MediaError("svg_unsafe", "This SVG holds a script, an event, embedded HTML or a DOCTYPE; save it "
                             "as a plain drawing and upload it again.", 422)
    if kind in IMAGES | {"heic", "avif"} and _pixels(received, kind) > MAX_PIXELS:
        raise MediaError("too_many_pixels", "This picture has more pixels than nexbrand takes.", 422)
    removed: set[str] = set()
    if kind in IMAGES | media.VIDEOS | {"heic"} and settings_service.get(db, "strip_location"):
        removed = media.strip(received, kind)
    name = clean_name(name)
    if kind == "heic":
        webp = received.with_name(received.name + ".webp")
        if media.to_webp(received, webp):
            os.replace(webp, received)
            kind = "webp"
            name = Path(name).stem + ".webp"
        else:
            webp.unlink(missing_ok=True)
    digest = _hash(received)
    existing = db.scalar(select(Media).where(Media.space_id == space_id, Media.sha256 == digest))
    if existing is not None and path_of(existing.id).is_file():
        received.unlink(missing_ok=True)
        return _stored(existing, sorted(removed), known=True)
    width, height = _picture_size(received) if kind in IMAGES else (0, 0)
    pages = _pdf_pages(received) if kind == "pdf" else 0
    media_id = secrets.token_urlsafe(12)
    size = received.stat().st_size
    row = Media(id=media_id, space_id=space_id, owner_id=account.id, name=name, kind=kind,
                mime=SHOWN.get(kind, "application/pdf" if kind == "pdf" else "application/octet-stream"),
                size=size, sha256=digest, width=width, height=height, pages=pages)
    # The row first: the clean-up removes files without one, and must never meet this one in between.
    db.add(row)
    db.commit()
    try:
        os.replace(received, path_of(media_id))
    except OSError:
        db.delete(row)
        db.commit()
        raise
    if kind in IMAGES and max(width, height) > PREVIEW_SIDE:
        _make_preview(path_of(media_id), preview_of(media_id))
    logger.info("Media stored id=%s kind=%s bytes=%s by=%s", media_id, kind, size, account.name)
    return _stored(row, sorted(removed), known=False)


def _stored(row: Media, removed: list[str], *, known: bool) -> Stored:
    return Stored(id=row.id, name=row.name, kind=row.kind, mime=row.mime, size=row.size, width=row.width,
                  height=row.height, pages=row.pages, removed=removed, known=known)
