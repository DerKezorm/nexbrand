"""A design set as code: CSS variables, a Tailwind 4 theme, SCSS variables, or design tokens (JSON).

The same text the interface offers for copying and the API and MCP hand to programs. Every colour with a job (not a
neutral) brings its web scale from 50 to 950 along (``colors.scale``); fonts as stacks with their fallback.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from . import colors

FORMATS = ("css", "tailwind", "scss", "json")


def slug(name: str) -> str:
    text = name.casefold().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-") or "color"


def _unique(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for name in names:
        count = seen.get(name, 0)
        seen[name] = count + 1
        out.append(name if count == 0 else f"{name}-{count + 1}")
    return out


def font_stack(font: dict[str, Any]) -> str:
    return f"'{font['family']}', {font.get('fallback') or 'sans-serif'}"


def _font_names(fonts: list[dict[str, Any]]) -> list[tuple[str, str]]:
    names = _unique([slug((font.get("role") or font["family"]).split(",")[0]) for font in fonts])
    return list(zip(names, (font_stack(font) for font in fonts), strict=True))


def _sizes(data: dict[str, Any]) -> list[tuple[str, str]]:
    """The type scale as sizes in rem (16 px = 1 rem), named by what each step is for, else by its name."""
    steps = data.get("scale", [])
    names = _unique([step.get("use") or slug(step["name"]) for step in steps])
    return [(name, f"{float(step['size']) / 16:g}rem") for name, step in zip(names, steps, strict=True)]


def render(data: dict[str, Any], fmt: str, *, color_list: list[dict[str, Any]] | None = None, title: str = "") -> str:
    """``color_list`` stands in for the set's colours (a project's own come along that way)."""
    if fmt not in FORMATS:
        raise ValueError(fmt)
    items = color_list if color_list is not None else data.get("colors", [])
    names = _unique([slug(color["name"]) for color in items])
    plain = list(zip(names, (color["hex"] for color in items), strict=True))
    steps = [
        (f"{name}-{step}", value)
        for name, color in zip(names, items, strict=True) if color.get("role") != "neutral"
        for step, value in colors.scale(color["hex"])
    ]
    fonts = _font_names(data.get("fonts", []))
    head = f"/* {title} */\n" if title and fmt != "json" else ""
    # The dark mode as names pointing at the colours above: (part, colour token name). A name gone is left out.
    slug_of = {color["name"].lower(): name for name, color in zip(names, items, strict=True)}
    dark = [(part.replace("_", "-"), slug_of[str(value).lower()]) for part, value in (data.get("dark") or {}).items()
            if str(value).lower() in slug_of]
    if fmt == "css":
        lines = [f"  --color-{n}: {h};" for n, h in plain]
        lines += [""] + [f"  --color-{n}: {h};" for n, h in steps] if steps else []
        lines += [""] + [f"  --font-{n}: {s};" for n, s in fonts] if fonts else []
        sizes = _sizes(data)
        lines += [""] + [f"  --text-{n}: {v};" for n, v in sizes] if sizes else []
        if dark:
            lines += ["", "  /* Dark mode: which colour is what. Map them onto your own variables. */"]
            lines += [f"  --dark-{p}: var(--color-{n});" for p, n in dark]
        return head + ":root {\n" + "\n".join(lines) + "\n}\n"
    if fmt == "tailwind":
        lines = [f"  --color-{n}: {h};" for n, h in plain + steps] + [f"  --font-{n}: {s};" for n, s in fonts]
        lines += [f"  --text-{n}: {v};" for n, v in _sizes(data)]
        # bg-dark-ground, text-dark-text …, for use with the dark: variant.
        lines += [f"  --color-dark-{p}: var(--color-{n});" for p, n in dark]
        intro = "/* Tailwind 4: in your CSS after @import 'tailwindcss'; */\n"
        return head + intro + "@theme {\n" + "\n".join(lines) + "\n}\n"
    if fmt == "scss":
        lines = [f"$color-{n}: {h};" for n, h in plain + steps] + [f"$font-{n}: {s};" for n, s in fonts]
        lines += [f"$text-{n}: {v};" for n, v in _sizes(data)]
        lines += [f"$dark-{p}: $color-{n};" for p, n in dark]
        return head + "\n".join(lines) + "\n"
    color_tokens: dict[str, Any] = {}
    for name, color in zip(names, items, strict=True):
        token: dict[str, Any] = {"$type": "color", "$value": color["hex"], "$description": color.get("role", "")}
        if color.get("pantone"):
            token["$extensions"] = {"nexbrand": {"pantone": color["pantone"]}}
        color_tokens[name] = token
        if color.get("role") != "neutral":
            for step, value in colors.scale(color["hex"]):
                color_tokens[f"{name}-{step}"] = {"$type": "color", "$value": value}
    font_tokens = {
        name: {"$type": "fontFamily", "$value": [font["family"], font.get("fallback") or "sans-serif"]}
        for (name, _), font in zip(fonts, data.get("fonts", []), strict=True)
    }
    size_tokens = {name: {"$type": "dimension", "$value": value} for name, value in _sizes(data)}
    out = {"color": color_tokens, "font": font_tokens}
    if size_tokens:
        out["text"] = size_tokens
    if dark:
        out["dark"] = {p: {"$type": "color", "$value": f"{{color.{n}}}"} for p, n in dark}
    return json.dumps(out, indent=2, ensure_ascii=False) + "\n"
