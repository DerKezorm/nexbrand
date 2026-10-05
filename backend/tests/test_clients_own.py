"""Clients stand on their own: each has its own group of rights, made and deleted with it; who may make one; data from
before (several clients in one space) is regrouped at the start."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import SessionLocal
from app.models import ApiToken, BrandVersion, Client, Media, Membership, Space, TeamGrant
from app.services import media_store, regroup

from .conftest import PASSWORD, client_of, join, make_account, new_client, new_group
from .test_brands import SET, SVG, make_client, upload


def test_a_client_brings_its_own_group_and_its_maker_manages_it(client: TestClient, operator) -> None:
    anna = make_account("anna")
    with new_client(anna) as browser:
        made = browser.post("/api/clients", json={"name": "Example Bakery", "color": "#4ade80"})
        assert made.status_code == 201, made.text
        body = made.json()
        assert body["role"] == "manage" and body["color"] == "#4ade80" and body["managed"] is False
        assert len(body["versions"]) == 1, "a first draft unless asked for none"
        groups = browser.get("/api/spaces").json()
        assert [(g["client"], g["role"]) for g in groups] == [(body["id"], "manage")]
        bare = browser.post("/api/clients", json={"name": "No design yet", "label": ""}).json()
        assert bare["versions"] == []
    with new_client(make_account("ben")) as other:
        assert other.get(f"/api/clients/{body['id']}").status_code == 404, "nobody else sees it"


def test_rights_are_given_per_client(client: TestClient, operator, space: int) -> None:
    first = client_of(client, space)
    second = client_of(client, new_group(client, "Other"))
    mia = make_account("mia")
    join(client, space, "mia", "read")
    with new_client(mia) as browser:
        assert [c["id"] for c in browser.get("/api/clients").json()] == [first], "a right opens that client only"
        assert browser.get(f"/api/clients/{second}").status_code == 404


def test_the_operator_decides_whether_members_make_clients(client: TestClient, operator) -> None:
    anna = make_account("anna")
    assert client.put("/api/settings", json={"members_create_clients": False}).status_code == 200
    with new_client(anna) as browser:
        refused = browser.post("/api/clients", json={"name": "Example"})
        assert refused.status_code == 403
    assert client.post("/api/clients", json={"name": "Example"}).status_code == 201, "the operator always may"
    client.put("/api/settings", json={"members_create_clients": True})
    with new_client(anna) as browser:
        assert browser.post("/api/clients", json={"name": "Example"}).status_code == 201


def test_deleting_for_good_takes_the_group_along(client: TestClient, operator, space: int) -> None:
    cid = make_client(client, space)["id"]
    assert client.delete(f"/api/clients/{cid}").status_code == 204
    assert client.request("DELETE", f"/api/clients/{cid}/purge", json={"current_password": PASSWORD}).status_code == 204
    with SessionLocal() as db:
        assert db.get(Space, space) is None and db.query(Membership).filter_by(space_id=space).count() == 0


def test_a_token_limited_to_clients_sees_only_those(client: TestClient, operator, space: int) -> None:
    from app.services import apitokens

    client.put("/api/settings", json={"api_tokens_allowed": True})
    mine = make_client(client, space)["id"]
    other = client.post("/api/clients", json={"name": "Other"}).json()["id"]
    made = client.post("/api/api-tokens", json={"name": "ci", "clients": [mine]})
    assert made.status_code == 201, made.text
    assert made.json()["token"]["clients"] == [{"id": mine, "name": "Bäckerei Morgenrot"}]
    assert client.post("/api/api-tokens", json={"name": "x", "clients": ["no-such-one"]}).status_code == 422
    assert client.post("/api/api-tokens", json={"name": "x", "clients": [mine, "no-such-one"]}).status_code == 422
    from app.main import app

    with TestClient(app, base_url="http://testserver") as program:
        headers = {"Authorization": f"Bearer {made.json()['secret']}"}
        assert [c["id"] for c in program.get("/api/v1/clients", headers=headers).json()] == [mine]
        assert program.get(f"/api/v1/clients/{other}", headers=headers).status_code == 404
        assert program.get("/api/v1/me", headers=headers).json()["clients"] == 1
    apitokens.forget()


def test_clients_that_shared_a_space_get_a_group_each_and_keep_their_files(client: TestClient, operator,
                                                                           space: int) -> None:
    shared = upload(client, space, "logo.svg", SVG)
    own = upload(client, space, "mark.svg", SVG + b" ")
    logo = {"id": "main", "name": "Logo", "fg": "#000000", "ground": "#FFFFFF"}
    first = make_client(client, space, {**SET, "logos": [{**logo, "media": shared}]})["id"]
    anna = make_account("anna")
    join(client, space, "anna", "write")
    team = client.post("/api/teams", json={"name": "Design", "members": [anna.id]}).json()
    client.put(f"/api/spaces/{space}/teams/{team['id']}", json={"role": "read"})
    with SessionLocal() as db:  # as before 04.10.2026: a plain index, a second client in the same space, a token
        db.execute(text("DROP INDEX ix_clients_space_id"))
        db.execute(text("CREATE INDEX ix_clients_space_id ON clients (space_id)"))
        db.add(Client(id="second-client", space_id=space, name="Second"))
        db.flush()
        db.add(BrandVersion(id="second-v1", client_id="second-client", label="1", status="draft",
                            data={**SET, "logos": [{**logo, "media": shared}, {**logo, "id": "m", "media": own}]}))
        db.add(ApiToken(account_id=operator.id, name="old", level="read", token_hash="x" * 64, prefix="nxb_old",
                        spaces=[space]))
        db.commit()
        assert regroup.run(db) == 1
        unique = {row["name"]: row["unique"] for row in db.execute(text("PRAGMA index_list('clients')")).mappings()}
        assert unique["ix_clients_space_id"] == 1, "the database refuses a second client in a group from now on"
    with SessionLocal() as db:
        moved = db.get(Client, "second-client")
        assert moved is not None and moved.space_id != space
        assert db.get(Client, first).space_id == space, "the oldest keeps the group"  # type: ignore[union-attr]
        assert {(m.account_id, m.role) for m in db.query(Membership).filter_by(space_id=moved.space_id)} == {
            (operator.id, "manage"), (anna.id, "write")}
        assert db.query(TeamGrant).filter_by(space_id=moved.space_id).one().role == "read"
        data = db.get(BrandVersion, "second-v1").data  # type: ignore[union-attr]
        copy = data["logos"][0]["media"]
        assert copy != shared and db.get(Media, copy).space_id == moved.space_id, "a shared file is copied"
        assert media_store.path_of(copy).read_bytes() == media_store.path_of(shared).read_bytes()
        assert data["logos"][1]["media"] == own and db.get(Media, own).space_id == moved.space_id, "its own moves"
        assert db.get(Media, shared).space_id == space, "the first keeps the original"
        token = db.query(ApiToken).filter_by(name="old").one()
        assert set(token.spaces) == {space, moved.space_id}, "the token keeps seeing both"
        assert regroup.run(db) == 0, "once done, nothing left to do"
    with new_client(anna) as browser:
        assert browser.get("/api/clients/second-client").json()["role"] == "write"


def test_an_empty_space_from_before_goes_one_with_files_stays(client: TestClient, operator) -> None:
    with SessionLocal() as db:
        empty, kept = Space(name="Personal"), Space(name="Files")
        db.add_all([empty, kept])
        db.flush()
        db.add(Media(id="kept-file-0001", space_id=kept.id, name="a.svg", kind="svg", mime="image/svg+xml", size=1,
                     sha256="0" * 64))
        db.commit()
        regroup.run(db)
        assert db.get(Space, empty.id) is None
        assert db.get(Space, kept.id) is not None


def test_the_client_colours_are_nexsuites_here_and_in_the_interface() -> None:
    import re
    from pathlib import Path

    from app.services import spaces, suite

    palette = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "palette.ts"
    shown = re.search(r"CLIENT_COLORS = \[([^\]]*)\]", palette.read_text(encoding="utf-8"))
    assert shown is not None
    assert set(spaces.COLORS) == set(suite.SUITE_COLORS), "a colour nexsuite refuses would not come along"
    assert set(re.findall(r"#[0-9a-f]{6}", shown.group(1))) == set(spaces.COLORS)


def test_a_group_from_before_takes_its_clients_name(client: TestClient, operator, space: int) -> None:
    with SessionLocal() as db:
        db.get(Space, space).name = "Personal"  # type: ignore[union-attr]
        db.commit()
        regroup.run(db)
        assert db.get(Space, space).name == "Home", "the access lists name the client"  # type: ignore[union-attr]


def test_a_client_keeps_its_addresses(client: TestClient, operator, space: int) -> None:
    cid = client_of(client, space)
    links = [{"kind": "website", "url": "https://www.example.com/", "label": "Site"},
             {"kind": "repo", "url": "https://github.com/example/site"},
             {"kind": "website", "url": "https://www.example.com"}]
    changed = client.patch(f"/api/clients/{cid}", json={"links": links})
    assert changed.status_code == 200, changed.text
    assert changed.json()["links"] == [
        {"kind": "website", "url": "https://www.example.com/", "label": "Site"},
        {"kind": "repo", "url": "https://github.com/example/site", "label": ""}], "a double goes"
    for bad in ([{"kind": "ftp", "url": "https://example.com"}], [{"kind": "website", "url": "javascript:alert(1)"}],
                [{"kind": "website", "url": f"https://example.com/{n}"} for n in range(11)]):
        answer = client.patch(f"/api/clients/{cid}", json={"links": bad})
        assert answer.status_code == 422, bad
    assert client.get(f"/api/clients/{cid}").json()["links"][0]["label"] == "Site", "a refusal changes nothing"


def test_addresses_are_nexbrands_also_for_a_client_nexsuite_keeps(client: TestClient, operator, space: int,
                                                                  monkeypatch) -> None:
    from app.services import brands

    monkeypatch.setattr(brands, "managed", lambda db, row: True)
    cid = client_of(client, space)
    assert client.patch(f"/api/clients/{cid}", json={"name": "Other"}).status_code == 409
    kept = client.patch(f"/api/clients/{cid}", json={"links": [{"kind": "website", "url": "https://example.com"}]})
    assert kept.status_code == 200 and kept.json()["links"][0]["url"] == "https://example.com"


def test_reading_a_client_does_not_give_the_right_to_change_its_addresses(client: TestClient, operator,
                                                                         space: int) -> None:
    mia = make_account("mia")
    join(client, space, "mia", "read")
    with new_client(mia) as browser:
        answer = browser.patch(f"/api/clients/{client_of(client, space)}",
                               json={"links": [{"kind": "website", "url": "https://example.com"}]})
        assert answer.status_code == 403
