"""The checks a design set runs on itself: every hint comes from the numbers, none is written by hand.

The same rules as ``frontend/src/lib/checks.ts`` (the interface runs them live while somebody edits); here they serve
programs and AI over ``/api/v1`` and MCP. Each hint has a stable ``code`` and its numbers, so a program can act on it
and the interface can word it in its language.
"""

from __future__ import annotations

from typing import Any

from . import colors

WHITE = "#FFFFFF"


def _r(value: float) -> float:
    return round(value, 2)


def vision_clashes(items: list[dict[str, Any]], vision: str) -> list[tuple[dict[str, Any], dict[str, Any], float]]:
    """Pairs clearly different for most people, but nearly the same for some."""
    loud = [c for c in items if c.get("role") != "neutral"]
    out = []
    for i, a in enumerate(loud):
        for b in loud[i + 1:]:
            if colors.delta_e(a["hex"], b["hex"]) < 15:
                continue
            d = colors.delta_e(colors.simulate(a["hex"], vision), colors.simulate(b["hex"], vision))
            if d < 10:
                out.append((a, b, d))
    return out


def check(data: dict[str, Any], color_list: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """``bad``, ``warn`` and ``info`` hints, the serious ones first."""
    items = color_list if color_list is not None else data.get("colors", [])
    hints: list[dict[str, Any]] = []
    white = any(c["hex"].upper() == WHITE for c in items)

    for bg in items:
        others = [t for t in items if t is not bg]
        readable = [t for t in others if colors.contrast(t["hex"], bg["hex"]) >= 4.5]
        large = [t for t in others if colors.contrast(t["hex"], bg["hex"]) >= 3]
        if not readable and large:
            hints.append({"level": "warn", "code": "ground_large_only", "colors": [bg["name"]], "hex": [bg["hex"]]})
        elif not readable and others:
            hints.append({"level": "bad", "code": "ground_unreadable", "colors": [bg["name"]], "hex": [bg["hex"]]})

    if white:
        for bg in (c for c in items if c.get("role") != "neutral"):
            ratio = colors.contrast(WHITE, bg["hex"])
            if ratio >= 4.5:
                continue
            better = sorted((t for t in items if t is not bg and colors.contrast(t["hex"], bg["hex"]) >= 4.5),
                            key=lambda t: -colors.contrast(t["hex"], bg["hex"]))
            hint = {"level": "bad" if ratio < 3 else "warn", "code": "white_on", "colors": [bg["name"]],
                    "hex": [WHITE, bg["hex"]], "ratio": _r(ratio)}
            if better:
                hint["better"] = better[0]["name"]
                hint["better_ratio"] = _r(colors.contrast(better[0]["hex"], bg["hex"]))
            hints.append(hint)

    for primary in (c for c in items if c.get("role") == "primary"):
        for bg in (c for c in items if c.get("role") == "neutral" and colors.luminance(c["hex"]) > 0.6):
            ratio = colors.contrast(primary["hex"], bg["hex"])
            if ratio < 4.5:
                hints.append({"level": "warn", "code": "primary_as_text", "colors": [primary["name"], bg["name"]],
                              "hex": [primary["hex"], bg["hex"]], "ratio": _r(ratio)})

    for i, a in enumerate(items):
        for b in items[i + 1:]:
            d = colors.delta_e(a["hex"], b["hex"])
            if d < 4:
                hints.append({"level": "warn", "code": "nearly_same", "colors": [a["name"], b["name"]],
                              "hex": [a["hex"], b["hex"]], "delta_e": _r(d)})

    for vision in ("deutan", "protan"):
        for a, b, d in vision_clashes(items, vision):
            hints.append({"level": "warn", "code": f"vision_{vision}", "colors": [a["name"], b["name"]],
                          "hex": [a["hex"], b["hex"]], "delta_e": _r(d)})

    for logo in data.get("logos", []):
        if logo.get("ground") == "transparent" or not logo.get("wordmark") and not logo.get("media"):
            continue
        if logo.get("media") and not logo.get("wordmark"):
            continue  # an uploaded file: its colours are in the file, not here
        parts = [("mark", logo["accent"])] + ([] if logo.get("compact") else [("word", logo["fg"])])
        for part, value in parts:
            ratio = colors.contrast(value, logo["ground"])
            if ratio < 3:
                hints.append({"level": "warn", "code": f"logo_{part}", "logo": logo["name"],
                              "hex": [value, logo["ground"]], "ratio": _r(ratio)})

    body = next((step for step in data.get("scale", []) if step.get("use") == "body"), None)
    if body is not None and body["size"] < 16:
        hints.append({"level": "warn", "code": "body_small", "size": body["size"]})

    for font in data.get("fonts", []):
        if font.get("license") == "internal":
            hints.append({"level": "info", "code": "font_internal", "font": font["family"]})
        elif font.get("license") == "system":
            hints.append({"level": "info", "code": "font_system", "font": font["family"]})

    order = {"bad": 0, "warn": 1, "info": 2}
    return sorted(hints, key=lambda hint: order[hint["level"]])


def pair(fg: str, bg: str) -> dict[str, Any]:
    """Everything about one pair, for a program asking."""
    ratio = colors.contrast(fg, bg)
    out: dict[str, Any] = {
        "ratio": _r(ratio),
        "text": colors.grade(ratio),
        "large_text": colors.grade(ratio, large=True),
        "graphics": "pass" if ratio >= 3 else "fail",
        "vision": {v: _r(colors.contrast(colors.simulate(fg, v), colors.simulate(bg, v))) for v in colors.VISIONS[1:]},
    }
    if ratio < 4.5:
        out["nearest_passing"] = colors.reach(fg, bg, 4.5)
    return out
