"""The dark mode of a design set: which colour is what, checked against each other, and in the export."""

from __future__ import annotations

import json

import pytest

from app.services import brandset, checks, tokens

from .test_brands import SET

NIGHT = {"name": "Nacht", "hex": "#14110F", "role": "neutral"}
DARK = {"ground": "Nacht", "surface": "Kruste", "text": "Mehl", "muted": "Mehl", "primary": "Honig",
        "on_primary": "Nacht"}


def _set(**dark: str) -> dict:
    return brandset.clean({**SET, "colors": [*SET["colors"], NIGHT], "dark": {**DARK, **dark}})


def test_a_set_without_a_dark_mode_stays_without_one() -> None:
    assert "dark" not in brandset.clean(SET)
    assert "dark" not in brandset.clean({**SET, "dark": None})


def test_the_dark_mode_keeps_its_six_parts() -> None:
    assert _set()["dark"] == DARK


@pytest.mark.parametrize(("dark", "where"), [
    ("Nacht", "dark"),
    ({**DARK, "glow": "Honig"}, "dark.glow"),
    ({k: v for k, v in DARK.items() if k != "muted"}, "dark.muted"),
    ({**DARK, "text": ""}, "dark.text"),
])
def test_a_wrong_dark_mode_is_refused_with_its_place(dark: object, where: str) -> None:
    with pytest.raises(brandset.SetError) as caught:
        brandset.clean({**SET, "dark": dark})
    assert str(caught.value).startswith(where + ":")


def test_a_good_dark_mode_has_nothing_to_say() -> None:
    assert [h for h in checks.check(_set()) if h["code"].startswith("dark_")] == []


def test_the_dark_mode_says_which_pair_does_not_carry() -> None:
    hints = {h["code"]: h for h in checks.check(_set(text="Kruste", primary="Ofenrot", on_primary="Kruste"))}
    assert hints["dark_text"]["level"] == "bad" and hints["dark_text"]["colors"] == ["Kruste", "Nacht"]
    assert "dark_surface" not in hints or hints["dark_surface"]["colors"] == ["Kruste", "Kruste"]
    assert hints["dark_primary"]["colors"] == ["Ofenrot", "Nacht"] and hints["dark_primary"]["ratio"] < 4.5
    assert hints["dark_on_primary"]["colors"] == ["Kruste", "Ofenrot"]


def test_a_dark_mode_pointing_at_a_colour_gone_names_it() -> None:
    hints = checks.check(_set(ground="Mitternacht"))
    assert {"level": "warn", "code": "dark_missing", "missing": "Mitternacht"} in hints
    assert not any(h["code"] in ("dark_text", "dark_muted", "dark_primary") for h in hints)


def test_the_export_says_which_colour_is_what_in_the_dark() -> None:
    data = _set()
    css = tokens.render(data, "css")
    assert "--dark-ground: var(--color-nacht);" in css and "--dark-on-primary: var(--color-nacht);" in css
    assert "--color-dark-text: var(--color-mehl);" in tokens.render(data, "tailwind")
    assert "$dark-primary: $color-honig;" in tokens.render(data, "scss")
    assert json.loads(tokens.render(data, "json"))["dark"]["surface"] == {"$type": "color", "$value": "{color.kruste}"}
    assert "--dark-" not in tokens.render(brandset.clean(SET), "css")


def test_a_public_page_keeps_the_dark_mode() -> None:
    assert brandset.for_public(_set())["dark"] == DARK


def test_quiet_text_has_to_read_too() -> None:
    hints = {h["code"]: h for h in checks.check(_set(muted="Ofenrot"))}
    assert hints["dark_muted"]["colors"] == ["Ofenrot", "Nacht"]
