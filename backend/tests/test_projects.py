"""Projects with a design set of their own: versions on a client version, part by part inherited, added or own."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import Account, BrandVersion, Project
from app.services import apitokens, brands, brandset, inherit

from .test_api import _program, _token
from .test_brands import SET, make_client
from .test_public import _open_pages

CASES = Path(__file__).parent / "data" / "inherit_cases.json"
BASE = brandset.clean({**SET, "rules": [{"kind": "do", "text": "Kurz."}],
                       "dark": {"ground": "Kruste", "surface": "Kruste", "text": "Mehl", "muted": "Mehl",
                                "primary": "Honig", "on_primary": "Kruste"}})
OWN_CASES: list[dict[str, Any]] = [
    {},
    {"inherit": {"colors": "extend"}, "colors": [{"name": "honig", "hex": "#DDAA00", "role": "accent"},
                                                 {"name": "Sommergelb", "hex": "#F2C230", "role": "accent"}]},
    {"inherit": {"colors": "own", "fonts": "own", "rules": "extend", "dark": "own"},
     "colors": [{"name": "Nacht", "hex": "#101010", "role": "neutral"}], "fonts": [],
     "rules": [{"kind": "dont", "text": "Nie rot."}]},
    {"inherit": {"scale": "extend"}, "scale": [{"name": "Body", "use": "body", "size": 18, "weight": 400,
                                                "font": "Fraunces", "line_height": 1.5}]},
]


def test_the_inherit_cases_file_is_what_the_server_computes() -> None:
    computed = {"base": BASE, "cases": [{"own": own, "resolved": inherit.resolve(BASE, own),
                                         "origin": inherit.origin(BASE, own)} for own in OWN_CASES]}
    if os.environ.get("UPDATE_COLOR_CASES"):
        CASES.write_bytes((json.dumps(computed, indent=1, ensure_ascii=False) + "\n").encode())
    assert json.loads(CASES.read_text(encoding="utf-8")) == computed


def test_extend_replaces_by_name_and_adds_the_rest() -> None:
    resolved = inherit.resolve(BASE, OWN_CASES[1])
    assert [c["name"] for c in resolved["colors"]] == ["Ofenrot", "honig", "Mehl", "Kruste", "Weiß", "Sommergelb"]
    assert resolved["fonts"] == BASE["fonts"] and resolved["dark"] == BASE["dark"]
    assert inherit.origin(BASE, OWN_CASES[1])["colors"] == ["client", "project", "client", "client", "client",
                                                            "project"]


def test_own_takes_nothing_from_the_client_and_rules_add_up() -> None:
    resolved = inherit.resolve(BASE, OWN_CASES[2])
    assert [c["name"] for c in resolved["colors"]] == ["Nacht"] and resolved["fonts"] == []
    assert [r["text"] for r in resolved["rules"]] == ["Kurz.", "Nie rot."]
    assert "dark" not in resolved


@pytest.mark.parametrize(("data", "where"), [
    ({"inherit": {"glow": "own"}}, "inherit.glow"),
    ({"inherit": {"colors": "some"}}, "inherit.colors"),
    ({"inherit": "own"}, "inherit"),
])
def test_a_wrong_part_or_mode_is_refused(data: dict[str, Any], where: str) -> None:
    with pytest.raises(brandset.SetError) as caught:
        brandset.clean(data)
    assert str(caught.value).startswith(where + ":")


def test_only_what_is_not_inherited_is_written_down() -> None:
    assert "inherit" not in brandset.clean({"inherit": {"colors": "inherit"}})
    assert brandset.clean({"inherit": {"colors": "own", "fonts": "inherit"}})["inherit"] == {"colors": "own"}


def _project(client: TestClient, space: int, **extra: Any) -> tuple[str, str, dict[str, Any]]:
    made = make_client(client, space)
    cid, first = made["id"], made["versions"][0]["id"]
    client.post(f"/api/clients/{cid}/versions/{first}/publish", json={"label": "2022", "valid_from": "2022-01-01"})
    project = client.post(f"/api/clients/{cid}/projects", json={"name": "Summer", "version_id": first, **extra})
    assert project.status_code == 201, project.text
    return cid, first, project.json()


def test_a_new_project_has_a_draft_that_takes_everything(client: TestClient, operator: Account, space: int) -> None:
    cid, first, project = _project(client, space)
    assert project["current"] is None and project["drafts"] == 1 and project["base_id"] == first
    draft = project["versions"][0]
    assert draft["project_id"] == project["id"] and draft["base_id"] == first and draft["data"].get("inherit") is None
    whole = client.get(f"/api/clients/{cid}").json()
    assert draft["resolved"]["colors"] == whole["versions"][0]["data"]["colors"]
    # The client's own list stays the client's.
    assert [v["label"] for v in whole["versions"]] == ["2022"]
    assert whole["projects"][0]["face"]["colors"] == [c["hex"] for c in whole["versions"][0]["data"]["colors"]]


def test_own_colours_come_on_top_and_go_into_the_export(client: TestClient, operator: Account, space: int) -> None:
    cid, _, project = _project(client, space, own=OWN_CASES[1]["colors"])
    code = client.get(f"/api/clients/{cid}/export?format=css&project={project['id']}").text
    assert "--color-honig: #DDAA00;" in code and "--color-sommergelb: #F2C230;" in code and "--color-mehl:" in code


def test_a_project_is_lifted_by_a_new_draft_on_the_newer_version(client: TestClient, operator: Account,
                                                                  space: int) -> None:
    cid, first, project = _project(client, space)
    vid = project["versions"][0]["id"]
    assert client.post(f"/api/clients/{cid}/versions/{vid}/publish", json={}).status_code == 200
    newer = client.post(f"/api/clients/{cid}/versions", json={"label": "2026", "source": first}).json()
    client.post(f"/api/clients/{cid}/versions/{newer['id']}/publish", json={})
    listed = client.get(f"/api/clients/{cid}").json()["projects"][0]
    assert listed["current"] == "1.0" and listed["base_label"] == "2022" and listed["behind"] is True
    lifted = client.post(f"/api/clients/{cid}/versions", json={"label": "1.1", "source": vid,
                                                                "project_id": project["id"], "base_id": newer["id"]})
    assert lifted.status_code == 201 and lifted.json()["base_id"] == newer["id"]
    whole = client.get(f"/api/clients/{cid}/projects/{project['id']}").json()
    assert [v["label"] for v in whole["versions"]] == ["1.0", "1.1"] and whole["version_id"] == newer["id"]
    assert client.delete(f"/api/clients/{cid}/versions/{lifted.json()['id']}").status_code == 204


def test_a_client_draft_a_project_stands_on_stays(client: TestClient, operator: Account, space: int) -> None:
    made = make_client(client, space)
    cid, draft = made["id"], made["versions"][0]["id"]
    assert client.post(f"/api/clients/{cid}/projects", json={"name": "P", "version_id": draft}).status_code == 201
    answer = client.delete(f"/api/clients/{cid}/versions/{draft}")
    assert answer.status_code == 409 and answer.json()["detail"]["code"] == "in_use"


def test_a_project_version_is_not_made_on_another_project(client: TestClient, operator: Account, space: int) -> None:
    cid, first, project = _project(client, space)
    other = client.post(f"/api/clients/{cid}/projects", json={"name": "Other", "version_id": first}).json()
    answer = client.post(f"/api/clients/{cid}/versions", json={"label": "x", "source": project["versions"][0]["id"],
                                                                "project_id": other["id"]})
    assert answer.status_code == 404
    as_client = client.post(f"/api/clients/{cid}/versions", json={"label": "x", "source": project["versions"][0]["id"]})
    assert as_client.status_code == 404


def test_deleting_a_project_takes_its_versions(client: TestClient, operator: Account, space: int) -> None:
    cid, _, project = _project(client, space)
    assert client.delete(f"/api/clients/{cid}/projects/{project['id']}").status_code == 204
    with SessionLocal() as db:
        assert db.query(BrandVersion).filter(BrandVersion.project_id == project["id"]).count() == 0


def test_a_project_from_before_gets_a_first_version(client: TestClient, operator: Account, space: int) -> None:
    made = make_client(client, space)
    cid, first = made["id"], made["versions"][0]["id"]
    with SessionLocal() as db:
        db.add(Project(id="oldproject01", client_id=cid, name="Old", version_id=first,
                       own=[{"name": "Extra", "hex": "#123456", "role": "accent", "pantone": "", "cmyk": "",
                             "note": ""}]))
        db.commit()
        assert brands.adopt_projects(db) == 1 and brands.adopt_projects(db) == 0
    version = client.get(f"/api/clients/{cid}/projects/oldproject01").json()["versions"][0]
    assert version["status"] == "published" and version["base_id"] == first
    assert version["data"]["inherit"] == {"colors": "extend"} and version["resolved"]["colors"][-1]["name"] == "Extra"


def test_a_project_page_and_the_api_show_the_project(client: TestClient, operator: Account, space: int) -> None:
    cid, _, project = _project(client, space, own=OWN_CASES[1]["colors"])
    vid = project["versions"][0]["id"]
    client.post(f"/api/clients/{cid}/versions/{vid}/publish", json={})
    _open_pages()
    share = client.post(f"/api/clients/{cid}/shares", json={"project_id": project["id"], "days": 5})
    assert share.status_code == 201, share.text
    token = share.json()["link"].rsplit("/", 1)[1]
    page = client.get(f"/api/public/{token}").json()
    assert page["project"] == "Summer" and page["design"]["colors"][-1]["name"] == "Sommergelb"
    apitokens.forget()
    assert client.put("/api/settings", json={"api_tokens_allowed": True}).status_code == 200
    auth = _token(client)
    with _program() as program:
        brand = program.get(f"/api/v1/clients/{cid}?project=Summer", headers=auth).json()
    apitokens.forget()
    assert brand["project"]["name"] == "Summer" and brand["current"] is True
    assert [c["name"] for c in brand["design"]["colors"]][-1] == "Sommergelb"
