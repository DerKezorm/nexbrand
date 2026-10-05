"""Comparing two versions in every part (F10), on the server and in the interface alike.

``tests/data/diff_cases.json`` holds pairs of sets and what the server finds between them; ``diff.test.ts`` holds the
interface to the same file. After a deliberate change, write it anew with ``UPDATE_COLOR_CASES=1 pytest
tests/test_diff.py``.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.models import Account
from app.services import brandset, diff

from .test_brands import SET

CASES = Path(__file__).parent / "data" / "diff_cases.json"

BASE: dict[str, Any] = brandset.clean({
    **SET,
    "logos": [{"id": "word", "name": "Wortmarke", "wordmark": {"text": "Morgenrot", "font": "Fraunces"},
               "fg": "#3B2A20", "accent": "#B8322A", "ground": "#FFFFFF"}],
    "scale": [{"name": "Überschrift 1", "use": "h1", "size": 40, "weight": 600, "font": "Fraunces", "line_height": 1.15},
              {"name": "Body", "use": "body", "size": 16, "weight": 400, "font": "Fraunces", "line_height": 1.6}],
})


def _changed(**parts: Any) -> dict[str, Any]:
    out = copy.deepcopy(BASE)
    out.update(parts)
    return out


def _pairs() -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    scale = copy.deepcopy(BASE["scale"])
    scale[0].update(size=52, weight=800, line_height=1.3)
    scale[1]["size"] = 18
    colors = copy.deepcopy(BASE["colors"])
    colors[0]["hex"] = "#A02A22"
    colors[1]["role"] = "secondary"
    fonts = copy.deepcopy(BASE["fonts"])
    fonts[0]["weights"] = [400, 600, 700]
    logos = copy.deepcopy(BASE["logos"])
    logos[0]["ground"] = "transparent"
    reworded = [{"kind": "dont", "text": "No white text on honey."}]
    dark = {"ground": "Kruste", "surface": "Kruste", "text": "Mehl", "muted": "Mehl", "primary": "Honig",
            "on_primary": "Kruste"}
    return [
        ("the same", BASE, copy.deepcopy(BASE)),
        ("only the type scale (the checker's case)", BASE, _changed(scale=scale)),
        ("a rule reworded and one added", BASE, _changed(rules=[*reworded, {"kind": "do", "text": "Warm photos."}])),
        ("a dark mode set", BASE, _changed(dark=dark)),
        ("a dark mode changed", _changed(dark=dark), _changed(dark={**dark, "primary": "Ofenrot"})),
        ("a dark mode taken away", _changed(dark=dark), BASE),
        ("colours, fonts, logos", BASE, _changed(colors=colors, fonts=fonts, logos=logos)),
        ("a colour, a step and an example added and removed", BASE,
         _changed(colors=BASE["colors"][1:] + [{"name": "Salbei", "hex": "#7F9C7A", "role": "accent"}],
                  scale=BASE["scale"][:1], samples=[{"name": "Flyer", "media": "abcdefghijkl"}])),
        ("an empty set against a full one", brandset.empty(), BASE),
    ]


def _compute() -> dict[str, Any]:
    return {"cases": [{"name": name, "a": a, "b": b, "changes": diff.diff(a, b)} for name, a, b in _pairs()]}


def test_the_cases_file_is_what_the_server_finds() -> None:
    computed = json.loads(json.dumps(_compute()))
    if os.environ.get("UPDATE_COLOR_CASES"):
        CASES.write_bytes((json.dumps(computed, indent=1, ensure_ascii=False) + "\n").encode())
    assert json.loads(CASES.read_text(encoding="utf-8")) == computed


def test_a_type_scale_rules_and_a_dark_mode_are_differences() -> None:
    cases = {case["name"]: case["changes"] for case in _compute()["cases"]}
    assert cases["the same"] == []
    scale = cases["only the type scale (the checker's case)"]
    assert [(c["part"], c["change"], c["name"]) for c in scale] == [("scale", "changed", "Überschrift 1"),
                                                                    ("scale", "changed", "Body")]
    assert [(f["field"], f["from"], f["to"]) for f in scale[0]["fields"]] == [
        ("size", 40, 52), ("weight", 600, 800), ("line_height", 1.15, 1.3)]
    assert [c["change"] for c in cases["a rule reworded and one added"]] == ["removed", "added", "added"]
    assert [c["change"] for c in cases["a dark mode set"]] == ["added"]
    assert cases["a dark mode changed"][0]["fields"] == [{"field": "primary", "from": "Honig", "to": "Ofenrot"}]


def test_mcp_compare_names_every_part(client: TestClient, operator: Account, space: int) -> None:
    from .test_api import _program, _rpc
    from .test_brands import make_client

    assert client.put("/api/settings", json={"api_tokens_allowed": True}).status_code == 200
    made = make_client(client, space, BASE)
    cid, first = made["id"], made["versions"][0]["id"]
    _, b = _pairs()[1][1:]
    second = client.post(f"/api/clients/{cid}/versions", json={"label": "B", "data": b}).json()["id"]
    secret = client.post("/api/api-tokens", json={"name": "x", "all_clients": True, "days": None}).json()["secret"]
    with _program() as program:
        answer = _rpc(program, {"Authorization": f"Bearer {secret}"}, "tools/call", {
            "name": "compare_versions", "arguments": {"client": cid, "from": first, "to": second}})
    found = answer["structuredContent"]
    assert found["colors_changed"] == [] and [c["part"] for c in found["changes"]] == ["scale", "scale"]
