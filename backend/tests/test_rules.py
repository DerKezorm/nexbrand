"""Rules that can be checked: their shape, the checks against the set, and a style sheet held against them."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.services import brandset, checks

from .test_api import _program, _published, _rpc, _token, _tokens_on  # noqa: F401
from .test_brands import SET

PAIR = {"type": "pair", "kind": "dont", "fg": "Weiß", "bg": "Honig"}


def test_a_rule_without_a_type_is_a_text_rule() -> None:
    out = brandset.clean({"rules": [{"kind": "do", "text": "Kurz und klar."}]})
    assert out["rules"] == [{"type": "text", "kind": "do", "text": "Kurz und klar.", "topic": ""}]


def test_checkable_rules_keep_their_parts_and_get_their_defaults() -> None:
    out = brandset.clean({"rules": [
        PAIR,
        {"type": "pair", "kind": "do", "fg": "Kruste", "bg": "Mehl", "size": "large", "text": "Nur Überschriften."},
        {"type": "logo", "kind": "do", "logo": "neg", "grounds": ["Kruste", "Kruste", "Ofenrot"]},
        {"type": "font", "kind": "do", "font": "Inter", "use": "headings", "min_size": 18},
        {"type": "text", "kind": "dont", "text": "Nie duzen.", "topic": "tone"},
    ]})["rules"]
    assert out[0] == {**PAIR, "text": "", "size": "text"}
    assert out[1]["size"] == "large" and out[1]["text"] == "Nur Überschriften."
    assert out[2]["grounds"] == ["Kruste", "Ofenrot"]
    assert out[3] == {"type": "font", "kind": "do", "text": "", "font": "Inter", "use": "headings", "min_size": 18}
    assert out[4]["topic"] == "tone"


@pytest.mark.parametrize(("rule", "where"), [
    ({"type": "maybe", "kind": "do", "text": "x"}, "rules.0.type"),
    ({"type": "text", "kind": "do", "text": ""}, "rules.0.text"),
    ({"type": "text", "kind": "do", "text": "x", "topic": "mood"}, "rules.0.topic"),
    ({"type": "pair", "kind": "do", "fg": "A"}, "rules.0.bg"),
    ({"type": "pair", "kind": "do", "fg": "A", "bg": "B", "size": "huge"}, "rules.0.size"),
    ({"type": "pair", "kind": "do", "fg": "A", "bg": "B", "logo": "x"}, "rules.0.logo"),
    ({"type": "logo", "kind": "do", "logo": "x", "grounds": []}, "rules.0.grounds"),
    ({"type": "logo", "kind": "do", "logo": "x", "grounds": "A"}, "rules.0.grounds"),
    ({"type": "font", "kind": "do", "font": "Inter", "use": "footer"}, "rules.0.use"),
    ({"type": "font", "kind": "do", "font": "Inter", "min_size": 900}, "rules.0.min_size"),
    ({"type": "font", "kind": "maybe", "font": "Inter"}, "rules.0.kind"),
])
def test_a_rule_that_is_wrong_is_refused_with_its_place(rule: dict[str, Any], where: str) -> None:
    with pytest.raises(brandset.SetError) as caught:
        brandset.clean({"rules": [rule]})
    assert str(caught.value).startswith(where + ":")


def test_a_text_rule_is_never_checked() -> None:
    data = {"colors": [{"name": "A", "hex": "#FFFFFF"}], "rules": [{"type": "text", "kind": "dont", "text": "Rot auf Tisch."}]}
    assert checks.rule_hints(data, data["colors"]) == []


def test_a_rule_on_a_renamed_colour_is_named_not_refused() -> None:
    out = brandset.clean({**SET, "rules": [{"type": "pair", "kind": "do", "fg": "Schnee", "bg": "Kruste"}]})
    hints = checks.check(out)
    assert {"level": "warn", "code": "rule_missing", "rule": 0, "missing": "Schnee"} in hints


# --- A style sheet -----------------------------------------------------------------------------------------------------

PALETTE = brandset.clean(SET)["colors"]
RULES = brandset.clean({"rules": [PAIR]})["rules"]


def test_the_sheet_finds_a_forbidden_pair_in_one_rule_through_a_variable() -> None:
    css = """
    :root { --honig: #E9A23B; --paper: #fff }
    /* .x { color: #000; background: #fff } is a comment */
    .badge { color: var(--paper); background: var(--honig) url(x.png) no-repeat; }
    @media (min-width: 40em) { .btn { color: rgb(59, 42, 32); background-color: #F2E3C6 } }
    .faint { color: #999; background-color: white }
    """
    sheet = checks.css_audit(css, PALETTE, RULES)
    assert sheet["checked"] == 3
    pairs = {p["selector"]: p for p in sheet["pairs"]}
    assert set(pairs) == {".badge", ".faint"}
    assert pairs[".badge"]["verdict"] == "forbidden" and pairs[".badge"]["rule"] == 0
    assert pairs[".badge"]["fg_name"] == "Weiß" and pairs[".badge"]["bg_name"] == "Honig"
    assert pairs[".faint"]["verdict"] == "low_contrast" and pairs[".faint"]["fg_name"] is None
    assert "#E9A23B" in sheet["values"] and "#3B2A20" in sheet["values"]


def test_a_pair_split_over_two_rules_is_not_seen() -> None:
    sheet = checks.css_audit(".a { color: #fff } .a { background: #E9A23B }", PALETTE, RULES)
    assert sheet["checked"] == 0 and sheet["pairs"] == []


def test_a_long_sheet_without_braces_is_read_quickly() -> None:
    import time

    started = time.monotonic()
    checks.css_audit("a" * 400_000 + "}" + "{" * 50_000 + "/*" * 20_000, PALETTE, RULES)
    assert time.monotonic() - started < 2


@pytest.mark.usefixtures("_tokens_on")
def test_the_audit_takes_a_sheet_over_the_api_and_mcp(client: TestClient, space: int) -> None:
    _published(client, space, {**SET, "rules": [PAIR]})
    auth = _token(client)
    css = ".badge { color: #FFF; background: #E9A23B }"
    with _program() as program:
        answer = program.post("/api/v1/clients/Bäckerei Morgenrot/audit", headers=auth, json={"css": css}).json()
        assert answer["css"]["pairs"][0]["verdict"] == "forbidden"
        assert [c["verdict"] for c in answer["colors"]] == ["same", "same"]
        empty = program.post("/api/v1/clients/Bäckerei Morgenrot/audit", headers=auth, json={})
        assert empty.status_code == 422
        result = _rpc(program, auth, "tools/call", {"name": "audit", "arguments": {
            "client": "Bäckerei Morgenrot", "css": css}})
        assert result["isError"] is False and result["structuredContent"]["css"]["checked"] == 1
