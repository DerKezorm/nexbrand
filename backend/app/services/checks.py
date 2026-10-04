"""The checks a design set runs on itself: every hint comes from the numbers, none is written by hand.

The same rules as ``frontend/src/lib/checks.ts`` (the interface runs them live while somebody edits); here they serve
programs and AI over ``/api/v1`` and MCP. Each hint has a stable ``code`` and its numbers, so a program can act on it
and the interface can word it in its language.
"""

from __future__ import annotations

import re
from typing import Any

from . import colors

WHITE = "#FFFFFF"
HEADINGS = ("h1", "h2", "h3", "h4")


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

    hints.extend(rule_hints(data, items))

    order = {"bad": 0, "warn": 1, "info": 2}
    return sorted(hints, key=lambda hint: order[hint["level"]])


def _missing(index: int, name: str) -> dict[str, Any]:
    return {"level": "warn", "code": "rule_missing", "rule": index, "missing": name}


def rule_hints(data: dict[str, Any], items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What the rules of a set say against the set itself. A ``text`` rule is words: nothing here reads it."""
    by_name = {c["name"].lower(): c for c in items}
    by_hex: dict[str, dict[str, Any]] = {}
    for c in items:
        by_hex.setdefault(c["hex"].upper(), c)
    logos = {logo.get("id"): logo for logo in data.get("logos", [])}
    families = {f["family"].lower() for f in data.get("fonts", [])}
    rules = data.get("rules", [])
    hints: list[dict[str, Any]] = []

    def drawn(logo: dict[str, Any]) -> list[str]:
        """The colours of a logo drawn from values here; an uploaded file keeps its own."""
        if not logo.get("wordmark"):
            return []
        return [logo["accent"]] + ([] if logo.get("compact") else [logo["fg"]])

    forbidden = {(r["fg"].lower(), r["bg"].lower()) for r in rules
                 if r.get("type") == "pair" and r.get("kind") == "dont"}

    for index, rule in enumerate(rules):
        kind = rule.get("type") or "text"
        if kind == "pair":
            fg, bg = by_name.get(rule["fg"].lower()), by_name.get(rule["bg"].lower())
            gone = [name for name, found in ((rule["fg"], fg), (rule["bg"], bg)) if found is None]
            if gone:
                hints.extend(_missing(index, name) for name in gone)
                continue
            assert fg is not None and bg is not None
            ratio = colors.contrast(fg["hex"], bg["hex"])
            if rule["kind"] == "do":
                need = 4.5 if rule.get("size", "text") == "text" else 3
                if ratio < need:
                    hints.append({"level": "bad" if ratio < 3 else "warn", "code": "rule_pair_low", "rule": index,
                                  "colors": [fg["name"], bg["name"]], "hex": [fg["hex"], bg["hex"]],
                                  "ratio": _r(ratio), "need": need})
                if (fg["name"].lower(), bg["name"].lower()) in forbidden:
                    hints.append({"level": "bad", "code": "rule_conflict", "rule": index,
                                  "colors": [fg["name"], bg["name"]], "hex": [fg["hex"], bg["hex"]]})
            else:
                for logo in data.get("logos", []):
                    ground = logo.get("ground", "transparent").upper()
                    if ground == bg["hex"].upper() and fg["hex"].upper() in (v.upper() for v in drawn(logo)):
                        hints.append({"level": "bad", "code": "rule_pair_logo", "rule": index, "logo": logo["name"],
                                      "colors": [fg["name"], bg["name"]], "hex": [fg["hex"], bg["hex"]]})
        elif kind == "logo":
            logo = logos.get(rule["logo"])
            if logo is None:
                hints.append(_missing(index, rule["logo"]))
                continue
            grounds = []
            for name in rule["grounds"]:
                found = by_name.get(name.lower())
                if found is None:
                    hints.append(_missing(index, name))
                else:
                    grounds.append(found)
            ground = logo.get("ground", "transparent")
            if ground != "transparent" and grounds:
                listed = ground.upper() in {g["hex"].upper() for g in grounds}
                if listed != (rule["kind"] == "do"):
                    named = by_hex.get(ground.upper())
                    hints.append({"level": "bad" if listed else "warn", "code": f"rule_logo_ground_{rule['kind']}",
                                  "rule": index, "logo": logo["name"],
                                  "colors": [named["name"] if named else ground], "hex": [ground]})
            if rule["kind"] == "do":
                for g in grounds:
                    ratios = [colors.contrast(value, g["hex"]) for value in drawn(logo)]
                    if ratios and min(ratios) < 3:
                        weakest = drawn(logo)[ratios.index(min(ratios))]
                        hints.append({"level": "warn", "code": "rule_logo_contrast", "rule": index,
                                      "logo": logo["name"], "colors": [g["name"]], "hex": [weakest, g["hex"]],
                                      "ratio": _r(min(ratios))})
        elif kind == "font":
            family = rule["font"]
            if family.lower() not in families:
                hints.append(_missing(index, family))
                continue
            use = rule.get("use", "")
            steps = [s for s in data.get("scale", [])
                     if not use or s.get("use") == use or use == "headings" and s.get("use") in HEADINGS]
            for step in steps:
                same = (step.get("font") or "").lower() == family.lower()
                if rule["kind"] == "dont" and same:
                    hints.append({"level": "bad", "code": "rule_font_forbidden", "rule": index, "font": family,
                                  "step": step["name"]})
                elif rule["kind"] == "do" and step.get("font") and not same:
                    hints.append({"level": "warn", "code": "rule_font_wrong", "rule": index, "font": family,
                                  "step": step["name"]})
                if rule["kind"] == "do" and rule.get("min_size") and step["size"] < rule["min_size"]:
                    hints.append({"level": "warn", "code": "rule_font_small", "rule": index, "font": family,
                                  "step": step["name"], "size": step["size"], "min": rule["min_size"]})
    return hints


# --- Colours in a style sheet ----------------------------------------------------------------------------------------

_VAR_SET = re.compile(r"(--[A-Za-z0-9_-]{1,80})\s*:\s*([^;{}]{1,200})")
_VAR_USE = re.compile(r"var\(\s*(--[A-Za-z0-9_-]{1,80})\s*(?:,\s*([^()]{0,200}))?\)")
_HEX = re.compile(r"#([0-9A-Fa-f]{8}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3,4})\b")
_RGB = re.compile(r"rgba?\(\s*(\d{1,3})[\s,]+(\d{1,3})[\s,]+(\d{1,3})")
_NAMED = {"white": "#FFFFFF", "black": "#000000"}
MOST_CSS = 500_000


def css_color(value: str, variables: dict[str, str]) -> str | None:
    """The first colour in a declaration's value, as ``#RRGGBB``; ``var()`` resolved through the sheet's own custom
    properties. ``None``: no colour that could be read (a gradient's first stop counts, a keyword like
    ``currentColor`` does not)."""
    for _ in range(4):
        replaced = _VAR_USE.sub(lambda m: variables.get(m.group(1), m.group(2) or ""), value)
        if replaced == value:
            break
        value = replaced
    hexed = _HEX.search(value)
    rgb = _RGB.search(value)
    if hexed and (not rgb or hexed.start() < rgb.start()):
        digits = hexed.group(1)
        if len(digits) in (3, 4):
            digits = "".join(char * 2 for char in digits[:3])
        return "#" + digits[:6].upper()
    if rgb:
        parts = [int(rgb.group(n)) for n in (1, 2, 3)]
        if all(p <= 255 for p in parts):
            return "#" + "".join(f"{p:02X}" for p in parts)
    word = value.strip().lower()
    return _NAMED.get(word)


def _without_comments(css: str) -> str:
    """The sheet without ``/* … */``, in one pass (a regular expression slows down on many unclosed ones)."""
    out, at = [], 0
    while True:
        start = css.find("/*", at)
        if start < 0:
            out.append(css[at:])
            return "".join(out)
        out.append(css[at:start] + " ")
        end = css.find("*/", start + 2)
        if end < 0:
            return "".join(out)
        at = end + 2


def css_blocks(css: str) -> list[tuple[str, dict[str, str]]]:
    """``(selector, {property: value})`` for every innermost block, read without a regular expression over the
    whole sheet (a long run without a brace would make one slow)."""
    css = _without_comments(css[:MOST_CSS])
    out = []
    for chunk in css.split("}"):
        head, brace, body = chunk.rpartition("{")
        if not brace:
            continue
        selector = head.rsplit("{", 1)[-1].rsplit(";", 1)[-1].strip()
        declarations: dict[str, str] = {}
        for part in body.split(";"):
            name, colon, value = part.partition(":")
            if colon:
                declarations[name.strip().lower()] = value.strip()
        out.append((selector[:200], declarations))
    return out


def css_audit(css: str, palette: list[dict[str, Any]], rules: list[dict[str, Any]]) -> dict[str, Any]:
    """Text colour and ground set in the same CSS rule, against the forbidden pairs of the set and against 4.5:1.

    Deliberately simple: what the browser puts together from several rules (a ground from the parent, a class from
    elsewhere) is not seen. ``values`` are all colours found, for the colour audit."""
    blocks = css_blocks(css)
    variables: dict[str, str] = {}
    for _, declarations in blocks:
        for name, value in declarations.items():
            if name.startswith("--"):
                variables[name] = value
    for name, value in _VAR_SET.findall(_without_comments(css[:MOST_CSS])):
        variables.setdefault(name, value.strip())

    def named(value: str) -> dict[str, Any] | None:
        if not palette:
            return None
        nearest = min(palette, key=lambda c: colors.delta_e(c["hex"], value))
        return nearest if colors.delta_e(nearest["hex"], value) < 8 else None

    forbidden = {(r["fg"].lower(), r["bg"].lower()): index for index, r in enumerate(rules)
                 if r.get("type") == "pair" and r.get("kind") == "dont"}
    values: list[str] = []
    found: list[dict[str, Any]] = []
    checked = 0
    for selector, declarations in blocks:
        fg = css_color(declarations["color"], variables) if "color" in declarations else None
        ground = declarations.get("background-color") or declarations.get("background")
        bg = css_color(ground, variables) if ground else None
        for name, value in declarations.items():
            if not name.startswith("--") and ("color" in name or name in ("background", "fill", "stroke")):
                read = css_color(value, variables)
                if read and read not in values:
                    values.append(read)
        if not fg or not bg:
            continue
        checked += 1
        a, b = named(fg), named(bg)
        ratio = colors.contrast(fg, bg)
        item: dict[str, Any] = {"selector": selector, "fg": fg, "bg": bg, "ratio": _r(ratio),
                                "fg_name": a["name"] if a else None, "bg_name": b["name"] if b else None}
        rule = forbidden.get((a["name"].lower(), b["name"].lower())) if a and b else None
        if rule is not None:
            found.append({**item, "verdict": "forbidden", "rule": rule})
        elif ratio < 4.5:
            found.append({**item, "verdict": "low_contrast"})
    return {"checked": checked, "pairs": found[:200], "values": values[:500]}


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
