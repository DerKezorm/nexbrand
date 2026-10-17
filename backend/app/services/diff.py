"""What changed from one design set to another, in every part: colours, fonts, logos, the type scale, rules, examples
and the dark mode (a comparison that saw only colours, fonts and logos said "no differences" over a new type
scale).

The same as ``frontend/src/lib/diff.ts``; ``tests/data/diff_cases.json`` holds both to it. A change names its part,
whether the item was added, removed or changed, the item's name, and for a change each field with its value before and
after. Items are matched by what names them: a colour, a font and a step by their name, a logo by its id, an example by
its file. A rule has no name: one reworded counts as one removed and one added.
"""

from __future__ import annotations

from typing import Any

PARTS = ("colors", "fonts", "logos", "scale", "rules", "samples", "dark")
FIELDS: dict[str, tuple[str, ...]] = {
    "colors": ("hex", "role", "pantone", "cmyk", "note"),
    "fonts": ("role", "weights", "italic", "license", "license_note", "source", "catalog", "files", "fallback"),
    "logos": ("name", "media", "files", "wordmark", "fg", "accent", "ground", "compact", "min_width", "clear_space"),
    "scale": ("use", "size", "weight", "font", "line_height"),
    "samples": ("name",),
    "dark": ("ground", "surface", "text", "muted", "primary", "on_primary"),
}
_NAME = {"colors": "name", "fonts": "family", "logos": "name", "scale": "name", "samples": "name"}
_KEY = {"colors": "name", "fonts": "family", "logos": "id", "scale": "name", "samples": "media"}


def canon(value: Any) -> Any:
    """A value as compared: empty (nothing, "", [], {}, false) is nothing, text keeps its case except colours, an
    object without its empty fields."""
    if isinstance(value, dict):
        out = {key: canon(item) for key, item in sorted(value.items())}
        return {key: item for key, item in out.items() if item is not None} or None
    if isinstance(value, list):
        return [canon(item) for item in value] or None
    if value is False or value == "" or value is None:
        return None
    if isinstance(value, str) and value.startswith("#") and len(value) in (4, 7):
        return value.upper()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _keyed(part: str, items: list[Any]) -> list[tuple[str, dict[str, Any]]]:
    """Each item with its key; the second of two items with the same key gets ``#2``."""
    seen: dict[str, int] = {}
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        key = str(item.get(_KEY[part]) or "").lower()
        seen[key] = seen.get(key, 0) + 1
        out.append((key if seen[key] == 1 else f"{key}#{seen[key]}", item))
    return out


def _fields(part: str, a: dict[str, Any], b: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"field": field, "from": canon(a.get(field)), "to": canon(b.get(field))}
            for field in FIELDS[part] if canon(a.get(field)) != canon(b.get(field))]


def diff(a: Any, b: Any) -> list[dict[str, Any]]:
    """Every change from the set ``a`` to the set ``b``, part by part in the order of ``PARTS``: within a part the items
    of ``a`` in their order (changed or removed), then the items only ``b`` has."""
    a = a if isinstance(a, dict) else {}
    b = b if isinstance(b, dict) else {}
    out: list[dict[str, Any]] = []
    for part in PARTS:
        if part == "dark":
            before, after = a.get("dark") or None, b.get("dark") or None
            if before is None and after is not None:
                out.append({"part": part, "change": "added", "name": "", "fields": []})
            elif before is not None and after is None:
                out.append({"part": part, "change": "removed", "name": "", "fields": []})
            elif before is not None and after is not None:
                fields = _fields(part, before, after)
                if fields:
                    out.append({"part": part, "change": "changed", "name": "", "fields": fields})
            continue
        if part == "rules":
            left = [canon(rule) for rule in a.get("rules") or []]
            right = [canon(rule) for rule in b.get("rules") or []]
            rest = list(right)
            for rule in left:
                if rule in rest:
                    rest.remove(rule)
                else:
                    out.append({"part": part, "change": "removed", "name": "", "rule": rule, "fields": []})
            for rule in right:
                if rule in rest:
                    rest.remove(rule)
                    out.append({"part": part, "change": "added", "name": "", "rule": rule, "fields": []})
            continue
        before_items = _keyed(part, a.get(part) or [])
        after_items = dict(_keyed(part, b.get(part) or []))
        known = set()
        for key, item in before_items:
            known.add(key)
            other = after_items.get(key)
            if other is None:
                out.append({"part": part, "change": "removed", "name": str(item.get(_NAME[part]) or ""),
                            "fields": []})
                continue
            fields = _fields(part, item, other)
            if fields:
                out.append({"part": part, "change": "changed", "name": str(other.get(_NAME[part]) or ""),
                            "fields": fields})
        for key, item in after_items.items():
            if key not in known:
                out.append({"part": part, "change": "added", "name": str(item.get(_NAME[part]) or ""), "fields": []})
    return out
