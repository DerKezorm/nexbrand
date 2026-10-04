"""A project's design set on top of its client's: part by part, inherited, inherited plus its own, or its own.

A version of a project keeps only what is its own, and under ``inherit`` where each part comes from::

    {"inherit": {"colors": "extend", "logos": "own"}, "colors": [...], "logos": [...]}

A part not named is inherited. ``extend`` puts the project's items over the client's: one with the same key (a
colour's or step's name, a font's family, a logo's id) takes its place, the others come after. Rules and examples
are added. The dark mode is inherited or the project's own (``extend`` means own there).

The base is a version of the client (``BrandVersion.base_id``): a published one never changes, so neither does a
project version on it; a project is lifted to a newer one on purpose, by a new draft.

The same as ``frontend/src/lib/inherit.ts``; ``tests/data/inherit_cases.json`` holds both to the same answers.
"""

from __future__ import annotations

from typing import Any

PARTS = ("colors", "fonts", "logos", "scale", "rules", "samples", "dark")
MODES = ("inherit", "extend", "own")

#: What makes two items of a part the same, for ``extend``; None: items are only ever added.
KEYS: dict[str, str | None] = {"colors": "name", "fonts": "family", "logos": "id", "scale": "name", "rules": None,
                               "samples": "media"}


def modes(own: dict[str, Any]) -> dict[str, str]:
    given = own.get("inherit") or {}
    return {part: given.get(part, "inherit") for part in PARTS}


def _merge(part: str, base: list[Any], own: list[Any]) -> list[Any]:
    key = KEYS[part]
    if key is None:
        return [*base, *own]

    def name(item: dict[str, Any]) -> str:
        return str(item.get(key, "")).lower()

    mine = {name(item): item for item in own}
    out = [mine.pop(name(item), item) for item in base]
    return out + [item for item in own if name(item) in mine]


def resolve(base: dict[str, Any], own: dict[str, Any]) -> dict[str, Any]:
    """The design set a project version shows: its client's ``base`` with its ``own`` parts."""
    how = modes(own)
    out: dict[str, Any] = {}
    for part in PARTS:
        mode = how[part]
        if part == "dark":
            dark = base.get("dark") if mode == "inherit" else own.get("dark")
            if dark:
                out["dark"] = dark
            continue
        if mode == "inherit":
            out[part] = list(base.get(part) or [])
        elif mode == "own":
            out[part] = list(own.get(part) or [])
        else:
            out[part] = _merge(part, list(base.get(part) or []), list(own.get(part) or []))
    return out


def origin(base: dict[str, Any], own: dict[str, Any]) -> dict[str, list[str]]:
    """For each list part, where each item of the resolved set comes from: ``client`` or ``project`` (in order)."""
    how = modes(own)
    out: dict[str, list[str]] = {}
    for part in PARTS:
        if part == "dark":
            continue
        resolved = resolve(base, {**own, "inherit": {part: how[part]}}).get(part, [])
        mine = own.get(part) or [] if how[part] != "inherit" else []
        out[part] = ["project" if any(item is m or item == m for m in mine) else "client" for item in resolved]
    return out
