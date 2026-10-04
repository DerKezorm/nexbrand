"""Colour arithmetic, against known values and against the interface.

``tests/data/color_cases.json`` holds what the server computes for a set of colours; the interface's ``color.test.ts``
reads the same file, so the numbers in the browser and on the server can never part ways. After a deliberate change
to the arithmetic, write the file anew with ``UPDATE_COLOR_CASES=1 pytest tests/test_colors.py``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.services import checks, colors

CASES = Path(__file__).parent / "data" / "color_cases.json"
SAMPLES = ["#B8322A", "#E9A23B", "#F2E3C6", "#3B2A20", "#FFFFFF", "#000000", "#2F7BFF", "#7F9C7A", "#808080",
           "#E255F5", "#FFE14A", "#123456"]


def _compute() -> dict:
    out: dict = {"colors": {}, "pairs": []}
    for value in SAMPLES:
        out["colors"][value] = {
            "luminance": round(colors.luminance(value), 6),
            "hsl": list(colors.hsl(value)),
            "cmyk": list(colors.cmyk(value)),
            "simulate": {v: colors.simulate(value, v) for v in colors.VISIONS},
            "scale": [hex_value for _, hex_value in colors.scale(value)],
        }
    for i, a in enumerate(SAMPLES):
        for b in SAMPLES[i + 1:]:
            out["pairs"].append({"a": a, "b": b, "contrast": round(colors.contrast(a, b), 6),
                                 "delta_e": round(colors.delta_e(a, b), 6), "reach": colors.reach(a, b, 4.5)})
    return out


def test_the_cases_file_is_what_the_server_computes() -> None:
    computed = _compute()
    if os.environ.get("UPDATE_COLOR_CASES"):
        CASES.parent.mkdir(exist_ok=True)
        CASES.write_bytes((json.dumps(computed, indent=1) + "\n").encode())
    assert json.loads(CASES.read_text(encoding="utf-8")) == computed


CHECK_CASES = Path(__file__).parent / "data" / "check_cases.json"
CHECK_SETS = [
    {"colors": [{"name": "Ofenrot", "hex": "#B8322A", "role": "primary"},
                {"name": "Honig", "hex": "#E9A23B", "role": "accent"},
                {"name": "Mehl", "hex": "#F2E3C6", "role": "neutral"},
                {"name": "Kruste", "hex": "#3B2A20", "role": "neutral"},
                {"name": "Kruste 2", "hex": "#3C2A20", "role": "neutral"},
                {"name": "Weiss", "hex": "#FFFFFF", "role": "neutral"}],
     "fonts": [{"family": "House", "license": "internal"}, {"family": "Verdana", "license": "system"}],
     "logos": [{"name": "Neg", "wordmark": {"text": "M", "font": ""}, "fg": "#F2E3C6", "accent": "#B8322A",
                "ground": "#3B2A20"},
               {"name": "File", "media": "abcdefghij", "fg": "#000000", "accent": "#000000", "ground": "#000000"}],
     "scale": [{"name": "Body", "use": "body", "size": 15}]},
    {"colors": [{"name": "Gruen", "hex": "#3FA34D", "role": "secondary"},
                {"name": "Signal", "hex": "#F5A400", "role": "accent"},
                {"name": "Blau", "hex": "#0B5CAD", "role": "primary"},
                {"name": "Blau hell", "hex": "#1569BC", "role": "secondary"},
                {"name": "Nebel", "hex": "#EEF2F6", "role": "neutral"}],
     "fonts": [], "logos": [], "scale": []},
    {"colors": [{"name": "Gelb", "hex": "#FFE14A", "role": "primary"}], "fonts": [], "logos": [], "scale": []},
    # Every rule check once: a pair allowed too faint and also forbidden, a forbidden pair a logo shows, names gone,
    # a logo on a ground not allowed and on one forbidden, a font where another is asked for, too small, forbidden.
    {"colors": [{"name": "Ofenrot", "hex": "#B8322A", "role": "primary"},
                {"name": "Honig", "hex": "#E9A23B", "role": "accent"},
                {"name": "Mehl", "hex": "#F2E3C6", "role": "neutral"},
                {"name": "Kruste", "hex": "#3B2A20", "role": "neutral"},
                {"name": "Weiss", "hex": "#FFFFFF", "role": "neutral"},
                {"name": "Tanne", "hex": "#3D8A80", "role": "secondary"}],
     "fonts": [{"family": "Fraunces", "license": "free"}, {"family": "Inter", "license": "free"}],
     "logos": [{"id": "neg", "name": "Neg", "wordmark": {"text": "M", "font": ""}, "fg": "#F2E3C6",
                "accent": "#B8322A", "ground": "#3B2A20"},
               {"id": "pos", "name": "Pos", "wordmark": {"text": "M", "font": ""}, "fg": "#3B2A20",
                "accent": "#B8322A", "ground": "#FFFFFF"},
               {"id": "file", "name": "File", "media": "abcdefghij", "fg": "#000000", "accent": "#000000",
                "ground": "#E9A23B"}],
     "scale": [{"name": "H1", "use": "h1", "size": 40, "font": "Fraunces"},
               {"name": "Body", "use": "body", "size": 15, "font": "Fraunces"},
               {"name": "Small", "use": "small", "size": 12, "font": "Inter"}],
     "rules": [{"type": "pair", "kind": "do", "fg": "Weiss", "bg": "Honig", "size": "text"},
               {"type": "pair", "kind": "dont", "fg": "Weiss", "bg": "Honig"},
               {"type": "pair", "kind": "dont", "fg": "mehl", "bg": "Kruste"},
               {"type": "pair", "kind": "do", "fg": "Weiss", "bg": "Ofenrot", "size": "large"},
               {"type": "pair", "kind": "do", "fg": "Weiss", "bg": "Lila"},
               {"type": "logo", "kind": "do", "logo": "neg", "grounds": ["Weiss", "Honig"]},
               {"type": "logo", "kind": "dont", "logo": "pos", "grounds": ["Weiss"]},
               {"type": "logo", "kind": "do", "logo": "gone", "grounds": ["Weiss"]},
               {"type": "font", "kind": "do", "font": "Inter", "use": "body", "min_size": 16},
               {"type": "font", "kind": "dont", "font": "Fraunces", "use": "headings", "min_size": 0},
               {"type": "font", "kind": "do", "font": "Comic", "use": ""},
               {"type": "text", "kind": "dont", "topic": "tone", "text": "Nie duzen."},
               {"kind": "do", "text": "Ohne Typ: frei."},
               {"type": "logo", "kind": "do", "logo": "file", "grounds": ["Honig"]},
               {"type": "pair", "kind": "do", "fg": "Weiss", "bg": "Tanne", "size": "text"},
               {"type": "pair", "kind": "do", "fg": "Weiss", "bg": "Tanne", "size": "large"}]},
]


def test_the_check_cases_file_is_what_the_server_says() -> None:
    computed = [checks.check(case) for case in CHECK_SETS]
    if os.environ.get("UPDATE_COLOR_CASES"):
        CHECK_CASES.write_bytes((json.dumps({"sets": CHECK_SETS, "hints": computed}, indent=1) + "\n").encode())
    assert json.loads(CHECK_CASES.read_text(encoding="utf-8")) == {"sets": CHECK_SETS, "hints": computed}


def test_known_values() -> None:
    assert colors.contrast("#FFFFFF", "#000000") == pytest.approx(21)
    assert colors.contrast("#777777", "#FFFFFF") == pytest.approx(4.48, abs=0.01)
    assert colors.delta_e("#FF0000", "#00FF00") == pytest.approx(86.6, abs=0.1)
    assert colors.delta_e("#123456", "#123456") == 0
    assert colors.delta_e("#123456", "#654321") == pytest.approx(colors.delta_e("#654321", "#123456"))
    assert colors.simulate("#FF0000", "achromat") == "#7F7F7F" or colors.simulate("#FF0000", "achromat") == "#7E7E7E"
    assert colors.grade(4.5) == "AA" and colors.grade(4.49) == "AA large" and colors.grade(3, large=True) == "AA"


def test_reach_finds_a_passing_colour_of_the_same_hue() -> None:
    found = colors.reach("#E9A23B", "#FFFFFF", 4.5)
    assert found is not None and colors.contrast(found, "#FFFFFF") >= 4.5
    assert abs(colors.hsl(found)[0] - colors.hsl("#E9A23B")[0]) <= 2


def test_the_checks_name_what_is_wrong() -> None:
    data = {"colors": [{"name": "Honig", "hex": "#E9A23B", "role": "accent"},
                       {"name": "Weiß", "hex": "#FFFFFF", "role": "neutral"},
                       {"name": "Kruste", "hex": "#3B2A20", "role": "neutral"},
                       {"name": "Kruste 2", "hex": "#3C2A20", "role": "neutral"}],
            "scale": [{"name": "Text", "use": "body", "size": 15}],
            "logos": [{"name": "Neg", "wordmark": {"text": "X"}, "fg": "#F2E3C6", "accent": "#B8322A",
                       "ground": "#3B2A20", "compact": False}]}
    codes = {hint["code"] for hint in checks.check(data)}
    assert {"white_on", "nearly_same", "body_small", "logo_mark"} <= codes
    white = next(h for h in checks.check(data) if h["code"] == "white_on")
    assert white["better"] in ("Kruste", "Kruste 2") and white["ratio"] == 2.17
