"""Clients, versions, projects, the export, and what a design set may hold."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.models import Account
from app.services import brandset, tokens

from .conftest import join, make_account, new_client

SET: dict[str, Any] = {
    "colors": [
        {"name": "Ofenrot", "hex": "#b8322a", "role": "primary", "pantone": "PMS 7621 C"},
        {"name": "Honig", "hex": "#E9A23B", "role": "accent"},
        {"name": "Mehl", "hex": "#F2E3C6", "role": "neutral"},
        {"name": "Kruste", "hex": "#3B2A20", "role": "neutral"},
        {"name": "Weiß", "hex": "#fff", "role": "neutral"},
    ],
    "fonts": [{"family": "Fraunces", "role": "Headings", "weights": [400, 700], "license": "free",
               "catalog": "fraunces", "fallback": "serif"}],
    "scale": [{"name": "Body", "use": "body", "size": 17, "weight": 400, "font": "Fraunces", "line_height": 1.6}],
    "rules": [{"kind": "dont", "text": "No white text on Honig."}],
}


def make_client(client: TestClient, space: int, data: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    answer = client.post("/api/clients", json={"space_id": space, "name": "Bäckerei Morgenrot", "label": "Draft 1",
                                               "data": data if data is not None else SET, **extra})
    assert answer.status_code == 201, answer.text
    return answer.json()


def upload(client: TestClient, space: int, name: str, body: bytes) -> str:
    answer = client.post(f"/api/media?space={space}&name={name}", content=body)
    assert answer.status_code == 201, answer.text
    return str(answer.json()["id"])


SVG = b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>'
WOFF2 = b"wOF2" + bytes(60)


# --- What a design set may hold -------------------------------------------------------------------------------------


def test_a_set_is_cleaned_to_its_known_shape() -> None:
    clean = brandset.clean(SET)
    assert clean["colors"][0]["hex"] == "#B8322A" and clean["colors"][4]["hex"] == "#FFFFFF"
    assert clean["colors"][0]["cmyk"] == "" and clean["fonts"][0]["files"] == []
    assert set(clean) == set(brandset.MOST)


@pytest.mark.parametrize(("change", "where"), [
    ({"colors": [{"name": "A", "hex": "red"}]}, "colors.0.hex"),
    ({"colors": [{"name": "A", "hex": "#123456"}, {"name": "a", "hex": "#654321"}]}, "colors.1.name"),
    ({"colors": [{"name": "A", "hex": "#123456", "role": "boss"}]}, "colors.0.role"),
    ({"fonts": [{"family": "X'; } body { color: red"}]}, "fonts.0.family"),
    ({"fonts": [{"family": "X", "catalog": "comic-sans"}]}, "fonts.0.catalog"),
    ({"fonts": [{"family": "X", "weights": [450.5]}]}, "fonts.0.weights.0"),
    ({"logos": [{"id": "a", "name": "Logo"}]}, "logos.0.media"),
    ({"logos": [{"id": "a", "name": "L", "media": "abcdefghijkl"}]}, "logos.0.media"),
    ({"scale": [{"name": "H", "size": 4000}]}, "scale.0.size"),
    ({"rules": [{"kind": "maybe", "text": "x"}]}, "rules.0.kind"),
    ({"script": []}, "script"),
    ({"colors": [{"name": "A", "hex": "#123456"}] * 49}, "colors"),
])
def test_what_does_not_belong_in_a_set_is_refused_with_its_place(change: dict[str, Any], where: str) -> None:
    with pytest.raises(brandset.SetError) as caught:
        brandset.clean(change)
    assert caught.value.where == where


def test_files_must_be_in_the_clients_space_and_of_a_fitting_kind(client: TestClient, operator: Account,
                                                                   space: int) -> None:
    other = client.post("/api/spaces", json={"name": "Other"}).json()["id"]
    font = upload(client, space, "brand.woff2", WOFF2)
    logo = upload(client, space, "logo.svg", SVG)
    foreign = upload(client, other, "logo.svg", SVG + b" ")
    good = {**SET, "fonts": [{"family": "Brand", "license": "internal", "files": [font]}],
            "logos": [{"id": "main", "name": "Logo", "media": logo, "fg": "#000", "ground": "#FFFFFF"}]}
    made = make_client(client, space, good)
    assert made["versions"][0]["data"]["logos"][0]["media"] == logo
    for bad, where in (({"logos": [{"id": "m", "name": "L", "media": foreign}]}, "logos.0.media"),
                       ({"logos": [{"id": "m", "name": "L", "media": font}]}, "logos.0.media"),
                       ({"fonts": [{"family": "B", "files": [logo]}]}, "fonts.0.files.0")):
        answer = client.post("/api/clients", json={"space_id": space, "name": "X", "data": bad})
        assert answer.status_code == 422 and answer.json()["detail"]["where"] == where


def test_uploads_know_svg_and_fonts_by_their_bytes(client: TestClient, operator: Account, space: int) -> None:
    kinds = {}
    for name, body in (("a.svg", SVG), ("b.woff2", WOFF2), ("c.otf", b"OTTO" + bytes(60)),
                       ("d.svg", b"not an svg at all, only text")):
        answer = client.post(f"/api/media?space={space}&name={name}", content=body)
        kinds[name] = answer.json()["kind"]
    assert kinds == {"a.svg": "svg", "b.woff2": "woff2", "c.otf": "otf", "d.svg": "file"}


def test_an_svg_is_served_where_it_cannot_run(client: TestClient, operator: Account, space: int) -> None:
    media = upload(client, space, "x.svg", SVG)
    answer = client.get(f"/api/media/{media}")
    assert answer.headers["content-type"].startswith("image/svg+xml")
    assert "sandbox" in answer.headers["content-security-policy"]


# --- Versions -------------------------------------------------------------------------------------------------------


def test_a_published_version_never_changes(client: TestClient, operator: Account, space: int) -> None:
    made = make_client(client, space)
    cid, vid = made["id"], made["versions"][0]["id"]
    assert made["current"] is None and made["drafts"] == 1
    published = client.post(f"/api/clients/{cid}/versions/{vid}/publish", json={"label": "2026"}).json()
    assert published["status"] == "published" and published["label"] == "2026" and published["valid_from"]
    refused = client.put(f"/api/clients/{cid}/versions/{vid}", json={"data": {"colors": []}})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "published"
    assert client.delete(f"/api/clients/{cid}/versions/{vid}").status_code == 409
    assert client.post(f"/api/clients/{cid}/versions/{vid}/publish", json={}).status_code == 409


def test_a_new_draft_copies_and_the_current_is_the_latest_day(client: TestClient, operator: Account,
                                                              space: int) -> None:
    made = make_client(client, space)
    cid, first = made["id"], made["versions"][0]["id"]
    client.post(f"/api/clients/{cid}/versions/{first}/publish", json={"label": "2022", "valid_from": "2022-04-11"})
    draft = client.post(f"/api/clients/{cid}/versions", json={"label": "2026", "source": first}).json()
    assert draft["data"] == client.get(f"/api/clients/{cid}").json()["versions"][0]["data"]
    changed = {**SET, "colors": [{**SET["colors"][0], "hex": "#C23B2E"}, *SET["colors"][1:]]}
    assert client.put(f"/api/clients/{cid}/versions/{draft['id']}", json={"data": changed}).status_code == 200
    client.post(f"/api/clients/{cid}/versions/{draft['id']}/publish", json={"valid_from": "2026-01-19"})
    # An old version recorded afterwards does not become the current one.
    old = client.post(f"/api/clients/{cid}/versions", json={"label": "2019"}).json()
    client.post(f"/api/clients/{cid}/versions/{old['id']}/publish", json={"valid_from": "2019-03-01"})
    whole = client.get(f"/api/clients/{cid}").json()
    assert whole["current"] == "2026"
    assert [v["label"] for v in whole["versions"]] == ["2019", "2022", "2026"]


def test_a_draft_a_project_builds_on_stays(client: TestClient, operator: Account, space: int) -> None:
    made = make_client(client, space, project="Website")
    cid, vid = made["id"], made["versions"][0]["id"]
    assert made["projects"][0]["version_id"] == vid
    answer = client.delete(f"/api/clients/{cid}/versions/{vid}")
    assert answer.status_code == 409 and answer.json()["detail"]["code"] == "in_use"


def test_a_project_keeps_its_version_and_its_own_colours(client: TestClient, operator: Account, space: int) -> None:
    made = make_client(client, space)
    cid, first = made["id"], made["versions"][0]["id"]
    client.post(f"/api/clients/{cid}/versions/{first}/publish", json={"valid_from": "2022-01-01"})
    project = client.post(f"/api/clients/{cid}/projects", json={
        "name": "Summer", "version_id": first,
        "own": [{"name": "Sommergelb", "hex": "#F2C230", "role": "accent"},
                {"name": "honig", "hex": "#DDAA00", "role": "accent"}]}).json()
    newer = client.post(f"/api/clients/{cid}/versions", json={"label": "2026", "source": first}).json()
    client.post(f"/api/clients/{cid}/versions/{newer['id']}/publish", json={})
    code = client.get(f"/api/clients/{cid}/export?format=css&project={project['id']}").text
    assert "--color-honig: #DDAA00;" in code and "--color-sommergelb: #F2C230;" in code
    assert client.get(f"/api/clients/{cid}").json()["projects"][0]["version_id"] == first
    lifted = client.patch(f"/api/clients/{cid}/projects/{project['id']}", json={"version_id": newer["id"]})
    assert lifted.json()["version_id"] == newer["id"]


# --- The export -----------------------------------------------------------------------------------------------------


def test_the_export_brings_scales_fonts_and_sizes() -> None:
    clean = brandset.clean(SET)
    css = tokens.render(clean, "css")
    assert "--color-ofenrot: #B8322A;" in css and "--color-ofenrot-500:" in css
    assert "--color-mehl-500" not in css, "neutrals bring no scale"
    assert "--font-headings: 'Fraunces', serif;" in css and "--text-body: 1.0625rem;" in css
    assert "@theme {" in tokens.render(clean, "tailwind")
    import json

    parsed = json.loads(tokens.render(clean, "json"))
    assert parsed["color"]["ofenrot"]["$value"] == "#B8322A"
    assert parsed["color"]["ofenrot"]["$extensions"]["nexbrand"]["pantone"] == "PMS 7621 C"
    assert parsed["font"]["headings"]["$value"] == ["Fraunces", "serif"]


def test_the_export_route_and_its_download_name(client: TestClient, operator: Account, space: int) -> None:
    cid = make_client(client, space)["id"]
    answer = client.get(f"/api/clients/{cid}/export?format=scss&download=true")
    assert answer.status_code == 200 and "$color-ofenrot: #B8322A;" in answer.text
    assert 'filename="baeckerei-morgenrot-draft-1.scss"' in answer.headers["content-disposition"]


# --- Rights, the bin ------------------------------------------------------------------------------------------------


def test_readers_look_writers_change_managers_delete_for_good(client: TestClient, operator: Account,
                                                              space: int) -> None:
    make_account("rita")
    make_account("wim")
    join(client, space, "rita", "read")
    join(client, space, "wim", "write")
    cid = make_client(client, space)["id"]
    vid = client.get(f"/api/clients/{cid}").json()["versions"][0]["id"]
    with new_client(make_account("nobody")) as stranger:
        assert stranger.get(f"/api/clients/{cid}").status_code == 404
        assert stranger.get("/api/clients").json() == []
    from app.db import SessionLocal
    from app.models import Account as Row

    with SessionLocal() as db:
        rita = db.query(Row).filter_by(name="rita").one()
        wim = db.query(Row).filter_by(name="wim").one()
        db.expunge_all()
    with new_client(rita) as reader:
        assert reader.get(f"/api/clients/{cid}").status_code == 200
        assert reader.get(f"/api/clients/{cid}/export").status_code == 200
        assert reader.put(f"/api/clients/{cid}/versions/{vid}", json={"label": "x"}).status_code == 403
        assert reader.delete(f"/api/clients/{cid}").status_code == 403
    with new_client(wim) as writer:
        assert writer.post(f"/api/clients/{cid}/versions/{vid}/publish", json={}).status_code == 200
        assert writer.delete(f"/api/clients/{cid}").status_code == 204
        assert writer.get("/api/clients?deleted=true").json()[0]["id"] == cid
        assert writer.delete(f"/api/clients/{cid}/purge").status_code == 403
    assert client.delete(f"/api/clients/{cid}/purge").status_code == 204
    assert client.get(f"/api/clients/{cid}").status_code == 404


def test_favourite_and_recent_are_the_accounts_own(client: TestClient, operator: Account, space: int) -> None:
    cid = make_client(client, space)["id"]
    assert client.patch(f"/api/clients/{cid}", json={"favorite": True}).json()["favorite"] is True
    assert client.post(f"/api/clients/{cid}/visit").status_code == 204
    listed = client.get("/api/clients").json()[0]
    assert listed["favorite"] is True and listed["opened_at"]
    assert listed["face"]["colors"][0] == "#B8322A"
