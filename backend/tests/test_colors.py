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
