"""The content of a design set, checked.

A version of a client's design set is one JSON document. Whatever sends it (the interface, a program over the API, an
AI over MCP, a review the client answered), it passes through ``clean`` here and only what comes out is stored:
known keys, known values, lengths and counts bounded, colours as ``#RRGGBB`` in upper case, files only those of the
client's space and of a kind that fits. Anything else is refused with the place it was found, never mended silently.

The shape::

    {
      "colors":  [{"name", "hex", "role", "pantone", "cmyk", "note"}],
      "fonts":   [{"family", "role", "weights", "italic", "license", "license_note", "source", "catalog",
                   "files", "fallback"}],
      "logos":   [{"id", "name", "media", "files", "wordmark", "fg", "accent", "ground", "compact", "min_width",
                   "clear_space"}],
      "scale":   [{"name", "use", "size", "weight", "font", "line_height"}],
      "rules":   [{"type", "kind", "text", ...}],
      "samples": [{"name", "media"}],
      "dark":    {"ground", "surface", "text", "muted", "primary", "on_primary"}   (colour names; optional)
    }

``dark`` is the set's dark mode: which of its colours is the page ground, a raised surface, body text, quieter
text, the main colour for links and buttons, and text on that main colour. Missing: the set has no dark mode.

``catalog`` names a font that ships with nexbrand (free licences, drawn in every browser without an upload);
``files`` are uploaded font files. ``wordmark`` stands in for a logo until there is one: the name set in a font.

A rule is ``do`` or ``dont`` and of a ``type``; all but ``text`` point at parts of the set by name and are checked
(``services/checks.py``), ``text`` is free words with a ``topic`` and checked by nobody::

    {"type": "text", "kind", "text", "topic": "" | logo | color | font | image | tone}
    {"type": "pair", "kind", "fg": colour name, "bg": colour name, "size": text | large, "text": note}
    {"type": "logo", "kind", "logo": logo id, "grounds": [colour names], "text": note}
    {"type": "font", "kind", "font": family, "use": "" | headings | a step's use, "min_size": px or 0, "text": note}

A rule without a type (stored before 05.10.2026) is a ``text`` rule. A name that is gone is not refused here: the
checks name it, so an old version stays readable.
"""

from __future__ import annotations

import math
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Media

ROLES = ("primary", "secondary", "accent", "neutral")
LICENSES = ("free", "internal", "system")
FALLBACKS = ("serif", "sans-serif", "monospace", "cursive")
RULE_KINDS = ("do", "dont")
RULE_TYPES = ("text", "pair", "logo", "font")
RULE_TOPICS = ("", "logo", "color", "font", "image", "tone")
PAIR_SIZES = ("text", "large")
#: What a step of the type scale is for; empty: just a size with a name.
USES = ("", "h1", "h2", "h3", "h4", "lead", "body", "small", "caption", "label")
#: Fonts that ship with the interface (``frontend/src/lib/fonts.ts``), all under the SIL Open Font License.
#: What a font rule is about: every step, the headings (h1 to h4), or the steps of one use.
RULE_USES = ("", "headings", *USES[1:])
CATALOG = ("fraunces", "playfair", "lora", "sourceserif", "inter", "dmsans", "outfit", "spacegrotesk", "nunito")

MOST = {"colors": 48, "fonts": 12, "logos": 24, "scale": 12, "rules": 60, "samples": 60}
DARK_PARTS = ("ground", "surface", "text", "muted", "primary", "on_primary")
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
SHORT_HEX = re.compile(r"^#[0-9A-Fa-f]{3}$")
LOGO_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
MEDIA_ID = re.compile(r"^[A-Za-z0-9_-]{8,40}$")

#: What a logo may be shown from; other kinds (EPS, AI, PDF) go along as downloads.
LOGO_KINDS = {"svg", "png", "jpeg", "webp", "gif", "avif"}
FONT_KINDS = {"woff2", "woff", "otf", "ttf"}


class SetError(ValueError):
    """``where`` names the place, such as ``colors.3.hex``."""

    def __init__(self, where: str, text: str = "This value is not valid.") -> None:
        super().__init__(f"{where}: {text}")
        self.where = where
        self.text = text


def empty() -> dict[str, Any]:
    return {key: [] for key in MOST}


def _text(value: Any, where: str, most: int, *, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise SetError(where)
    text = " ".join(value.split()) if most <= 200 else value.strip()
    if any(ord(char) < 32 and char not in "\n\t" for char in text):
        raise SetError(where)
    if len(text) > most:
        raise SetError(where, f"At most {most} characters.")
    if required and not text:
        raise SetError(where, "This may not be empty.")
    return text


def color_value(value: Any, where: str, *, transparent: bool = False) -> str:
    if transparent and value == "transparent":
        return "transparent"
    if not isinstance(value, str):
        raise SetError(where)
    value = value.strip()
    if SHORT_HEX.match(value):
        value = "#" + "".join(char * 2 for char in value[1:])
    if not HEX.match(value):
        raise SetError(where, "A colour is written #RRGGBB.")
    return value.upper()


def _choice(value: Any, allowed: tuple[str, ...], where: str, default: str | None = None) -> str:
    if value is None and default is not None:
        return default
    if value not in allowed:
        raise SetError(where)
    return str(value)


def _bool(value: Any, where: str) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise SetError(where)
    return value


def _number(value: Any, where: str, low: float, high: float, *, whole: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or math.isnan(value):
        raise SetError(where)
    if whole and int(value) != value:
        raise SetError(where)
    if not low <= value <= high:
        raise SetError(where, f"Between {low:g} and {high:g}.")
    return int(value) if whole else round(float(value), 3)


def _list(data: dict[str, Any], key: str) -> list[Any]:
    value = data.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise SetError(key)
    if len(value) > MOST[key]:
        raise SetError(key, f"At most {MOST[key]}.")
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise SetError(f"{key}.{index}")
    return value


class Files:
    """The files of one space, looked up once per check."""

    def __init__(self, db: Session | None, space_id: int | None) -> None:
        self.kinds: dict[str, str] = {}
        if db is not None and space_id is not None:
            self.kinds = dict(db.execute(select(Media.id, Media.kind).where(Media.space_id == space_id)).all())

    def one(self, value: Any, where: str, kinds: set[str] | None) -> str:
        if not isinstance(value, str) or not MEDIA_ID.match(value) or value not in self.kinds:
            raise SetError(where, "No such file among the client's files.")
        if kinds is not None and self.kinds[value] not in kinds:
            raise SetError(where, "This file is not of a kind that fits here.")
        return value

    def many(self, value: Any, where: str, kinds: set[str] | None, most: int = 12) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list) or len(value) > most:
            raise SetError(where)
        return list(dict.fromkeys(self.one(item, f"{where}.{index}", kinds) for index, item in enumerate(value)))


def clean_colors(items: Any, where: str = "colors") -> list[dict[str, Any]]:
    """Colours alone: what a project adds also passes here."""
    if items is None:
        return []
    if not isinstance(items, list) or len(items) > MOST["colors"]:
        raise SetError(where)
    out = []
    names: set[str] = set()
    for index, item in enumerate(items):
        at = f"{where}.{index}"
        if not isinstance(item, dict):
            raise SetError(at)
        name = _text(item.get("name"), f"{at}.name", 60, required=True)
        if name.casefold() in names:
            raise SetError(f"{at}.name", "Two colours may not have the same name.")
        names.add(name.casefold())
        out.append({
            "name": name,
            "hex": color_value(item.get("hex"), f"{at}.hex"),
            "role": _choice(item.get("role"), ROLES, f"{at}.role", "secondary"),
            "pantone": _text(item.get("pantone"), f"{at}.pantone", 40),
            # A print value the printer gave, kept as written; the computed one is never stored.
            "cmyk": _text(item.get("cmyk"), f"{at}.cmyk", 40),
            "note": _text(item.get("note"), f"{at}.note", 200),
        })
    return out


def clean(data: Any, db: Session | None = None, space_id: int | None = None) -> dict[str, Any]:
    """The design set as it may be stored, or ``SetError``. Without a database, no file may be named."""
    if not isinstance(data, dict):
        raise SetError("data")
    unknown = set(data) - set(MOST) - {"dark", "inherit"}
    if unknown:
        raise SetError(min(unknown), "Not a part of a design set.")
    files = Files(db, space_id)
    out = empty()
    out["colors"] = clean_colors(data.get("colors"))

    families: set[str] = set()
    for index, item in enumerate(_list(data, "fonts")):
        at = f"fonts.{index}"
        family = _text(item.get("family"), f"{at}.family", 80, required=True)
        if any(char in family for char in "\"'\\;{}<>"):
            raise SetError(f"{at}.family")
        families.add(family.casefold())
        weights = item.get("weights") or [400]
        if not isinstance(weights, list) or not 1 <= len(weights) <= 12:
            raise SetError(f"{at}.weights")
        catalog = item.get("catalog") or ""
        if catalog and catalog not in CATALOG:
            raise SetError(f"{at}.catalog")
        out["fonts"].append({
            "family": family,
            "role": _text(item.get("role"), f"{at}.role", 80),
            "weights": sorted({int(_number(w, f"{at}.weights.{n}", 100, 1000)) for n, w in enumerate(weights)}),
            "italic": _bool(item.get("italic"), f"{at}.italic"),
            "license": _choice(item.get("license"), LICENSES, f"{at}.license", "internal"),
            "license_note": _text(item.get("license_note"), f"{at}.license_note", 300),
            "source": _text(item.get("source"), f"{at}.source", 120),
            "catalog": catalog,
            "files": files.many(item.get("files"), f"{at}.files", FONT_KINDS),
            "fallback": _choice(item.get("fallback"), FALLBACKS, f"{at}.fallback", "sans-serif"),
        })

    ids: set[str] = set()
    for index, item in enumerate(_list(data, "logos")):
        at = f"logos.{index}"
        logo_id = item.get("id")
        if not isinstance(logo_id, str) or not LOGO_ID.match(logo_id) or logo_id in ids:
            raise SetError(f"{at}.id")
        ids.add(logo_id)
        media = item.get("media") or ""
        wordmark = item.get("wordmark")
        if media:
            media = files.one(media, f"{at}.media", LOGO_KINDS)
        if wordmark is not None:
            if not isinstance(wordmark, dict) or set(wordmark) - {"text", "font"}:
                raise SetError(f"{at}.wordmark")
            wordmark = {"text": _text(wordmark.get("text"), f"{at}.wordmark.text", 60, required=True),
                        "font": _text(wordmark.get("font"), f"{at}.wordmark.font", 80)}
        if not media and wordmark is None:
            raise SetError(f"{at}.media", "A logo needs a file or a word mark.")
        out["logos"].append({
            "id": logo_id,
            "name": _text(item.get("name"), f"{at}.name", 60, required=True),
            "media": media,
            "files": files.many(item.get("files"), f"{at}.files", None),
            "wordmark": wordmark,
            "fg": color_value(item.get("fg") or "#000000", f"{at}.fg"),
            "accent": color_value(item.get("accent") or item.get("fg") or "#000000", f"{at}.accent"),
            "ground": color_value(item.get("ground") or "transparent", f"{at}.ground", transparent=True),
            "compact": _bool(item.get("compact"), f"{at}.compact"),
            "min_width": _text(item.get("min_width"), f"{at}.min_width", 40),
            "clear_space": _text(item.get("clear_space"), f"{at}.clear_space", 80),
        })

    for index, item in enumerate(_list(data, "scale")):
        at = f"scale.{index}"
        out["scale"].append({
            "name": _text(item.get("name"), f"{at}.name", 60, required=True),
            "use": _choice(item.get("use"), USES, f"{at}.use", ""),
            "size": _number(item.get("size"), f"{at}.size", 6, 400, whole=False),
            "weight": int(_number(item.get("weight", 400), f"{at}.weight", 100, 1000)),
            "font": _text(item.get("font"), f"{at}.font", 80),
            "line_height": _number(item.get("line_height", 1.4), f"{at}.line_height", 0.5, 4, whole=False),
        })

    for index, item in enumerate(_list(data, "rules")):
        out["rules"].append(clean_rule(item, f"rules.{index}"))

    for index, item in enumerate(_list(data, "samples")):
        at = f"samples.{index}"
        out["samples"].append({
            "name": _text(item.get("name"), f"{at}.name", 120, required=True),
            "media": files.one(item.get("media"), f"{at}.media", None),
        })

    inherit = data.get("inherit")
    if inherit is not None:
        from .inherit import MODES, PARTS

        if not isinstance(inherit, dict):
            raise SetError("inherit")
        for part, mode in inherit.items():
            if part not in PARTS:
                raise SetError(f"inherit.{part}", "Not a part of a design set.")
            if mode not in MODES:
                raise SetError(f"inherit.{part}", "inherit, extend or own.")
        # Only what is not inherited is written down: a part not named is inherited.
        kept = {part: mode for part, mode in inherit.items() if mode != "inherit"}
        if kept:
            out["inherit"] = kept

    dark = data.get("dark")
    if dark is not None:
        if not isinstance(dark, dict):
            raise SetError("dark")
        unknown = set(dark) - set(DARK_PARTS)
        if unknown:
            raise SetError(f"dark.{min(unknown)}", "Not a part of the dark mode.")
        # A name the palette no longer has is not refused: the checks name it (as with rules).
        out["dark"] = {part: _text(dark.get(part), f"dark.{part}", 60, required=True) for part in DARK_PARTS}
    return out


RULE_KEYS = {
    "text": {"topic"},
    "pair": {"fg", "bg", "size"},
    "logo": {"logo", "grounds"},
    "font": {"font", "use", "min_size"},
}


def clean_rule(item: dict[str, Any], at: str) -> dict[str, Any]:
    kind = item.get("type") or "text"
    kind = _choice(kind, RULE_TYPES, f"{at}.type")
    unknown = set(item) - {"type", "kind", "text"} - RULE_KEYS[kind]
    if unknown:
        raise SetError(f"{at}.{min(unknown)}", "Not a part of this kind of rule.")
    rule: dict[str, Any] = {"type": kind, "kind": _choice(item.get("kind"), RULE_KINDS, f"{at}.kind"),
                            "text": _text(item.get("text"), f"{at}.text", 400, required=kind == "text")}
    if kind == "text":
        rule["topic"] = _choice(item.get("topic"), RULE_TOPICS, f"{at}.topic", "")
    elif kind == "pair":
        rule["fg"] = _text(item.get("fg"), f"{at}.fg", 60, required=True)
        rule["bg"] = _text(item.get("bg"), f"{at}.bg", 60, required=True)
        rule["size"] = _choice(item.get("size"), PAIR_SIZES, f"{at}.size", "text")
    elif kind == "logo":
        rule["logo"] = _text(item.get("logo"), f"{at}.logo", 32, required=True)
        grounds = item.get("grounds")
        if not isinstance(grounds, list) or not 1 <= len(grounds) <= MOST["colors"]:
            raise SetError(f"{at}.grounds", "One colour or more.")
        names = [_text(g, f"{at}.grounds.{n}", 60, required=True) for n, g in enumerate(grounds)]
        rule["grounds"] = list(dict.fromkeys(names))
    else:
        rule["font"] = _text(item.get("font"), f"{at}.font", 80, required=True)
        rule["use"] = _choice(item.get("use"), RULE_USES, f"{at}.use", "")
        rule["min_size"] = _number(item.get("min_size", 0), f"{at}.min_size", 0, 400, whole=False)
    return rule


def media_of(data: Any) -> set[str]:
    """Every file a stored design set points at (for the clean-up and for copying)."""
    found: set[str] = set()
    if not isinstance(data, dict):
        return found
    for font in data.get("fonts") or []:
        found.update(font.get("files") or [])
    for logo in data.get("logos") or []:
        if logo.get("media"):
            found.add(logo["media"])
        found.update(logo.get("files") or [])
    for sample in data.get("samples") or []:
        if sample.get("media"):
            found.add(sample["media"])
    return {item for item in found if isinstance(item, str)}


def internal_media(data: Any) -> set[str]:
    """Files of fonts whose licence keeps them in the house: never out over a public page or a program."""
    found: set[str] = set()
    for font in (data or {}).get("fonts") or []:
        if font.get("license") != "free":
            found.update(font.get("files") or [])
    return found


def for_public(data: dict[str, Any], elsewhere: set[str] | frozenset[str] = frozenset()) -> dict[str, Any]:
    """What a page outside sees: fonts kept in the house by name only, without their files, their licence note or
    where they came from. Their files go nowhere else either: not as an example, not as a logo's download, not in a
    free font's files (A4: the same file named twice came out the other way). ``elsewhere``: files kept in the house
    by other versions of the client (``brands.kept_in_house``), left out the same way."""
    copy = {key: dict(value) if isinstance(value, dict) else [dict(item) for item in value]
            for key, value in data.items() if value is not None}
    kept = internal_media(data) | set(elsewhere)
    for font in copy.get("fonts", []):
        if font.get("license") != "free":
            font["files"] = []
            font["license_note"] = ""
            font["source"] = ""
        else:
            font["files"] = [item for item in font.get("files") or [] if item not in kept]
    for logo in copy.get("logos", []):
        logo["files"] = [item for item in logo.get("files") or [] if item not in kept]
        if logo.get("media") in kept:
            logo["media"] = ""
    if "samples" in copy:
        copy["samples"] = [sample for sample in copy["samples"] if sample.get("media") not in kept]
    return copy
