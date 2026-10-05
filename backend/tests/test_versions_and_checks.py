"""Versions, checks and export (Prüfgang 05.10.2026, block 5): a version that holds from a later day, colours written
as CSS writes them, uploads of the wrong kind, comparing two versions in full, ratios shown as they are graded, the
type scale in the code, names that are unique, and the defaults of a new API token.

Nothing here reads the clock: ``brands.today`` is set to a fixed day.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.models import Account
from app.services import apitokens, brands

from . import test_suite
from .conftest import make_account, new_client
from .test_api import _program, _rpc
from .test_brands import SET, make_client

TODAY = "2026-10-05"

# The fixtures of the suite tests, under the names pytest looks for.
fake = test_suite.fake
world = test_suite.world


@pytest.fixture(autouse=True)
def _fixed_day(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(brands, "today", lambda: TODAY, raising=False)


@pytest.fixture
def tokens_on(client: TestClient, operator: Account) -> Iterator[None]:
    apitokens.forget()
    assert client.put("/api/settings", json={"api_tokens_allowed": True}).status_code == 200
    yield
    apitokens.forget()


def _token(client: TestClient, level: str = "read") -> dict[str, str]:
    answer = client.post("/api/api-tokens", json={"name": "Editor", "level": level, "all_clients": True,
                                                  "days": None})
    assert answer.status_code == 201, answer.text
    return {"Authorization": f"Bearer {answer.json()['secret']}"}


def _publish(client: TestClient, cid: str, vid: str, label: str, day: str) -> None:
    answer = client.post(f"/api/clients/{cid}/versions/{vid}/publish", json={"label": label, "valid_from": day})
    assert answer.status_code == 200, answer.text


def _two_versions(client: TestClient, space: int) -> dict[str, str]:
    """1.0 holds since January, 2.0 is published to hold from 2030; a project stands on 1.0."""
    made = make_client(client, space, project="Website")
    cid, first = made["id"], made["versions"][0]["id"]
    _publish(client, cid, first, "1.0", "2026-01-19")
    second = client.post(f"/api/clients/{cid}/versions", json={
        "label": "2.0", "source": first,
        "data": {**SET, "colors": [{"name": "Ofenrot", "hex": "#1F5FBF", "role": "primary"}]}}).json()["id"]
    _publish(client, cid, second, "2.0", "2030-01-01")
    pid = client.get(f"/api/clients/{cid}").json()["projects"][0]["id"]
    return {"cid": cid, "first": first, "second": second, "pid": pid}


# --- F2: a version that holds from a later day ---------------------------------------------------------------------


def test_f2_a_version_from_a_later_day_holds_only_from_that_day(client: TestClient, space: int,
                                                                 tokens_on: None) -> None:
    made = _two_versions(client, space)
    cid = made["cid"]
    whole = client.get(f"/api/clients/{cid}").json()
    assert whole["current"] == "1.0" and whole["current_id"] == made["first"]
    assert [c["current"] for c in client.get("/api/clients").json() if c["id"] == cid] == ["1.0"]
    project = whole["projects"][0]
    assert project["behind"] is False, "standing on the version that holds today is not behind"
    export = client.get(f"/api/clients/{cid}/export?format=css").text
    assert "1.0" in export.splitlines()[0] and "#B8322A" in export
    auth = _token(client)
    with _program() as program:
        listed = program.get("/api/v1/clients", headers=auth).json()
        assert listed[0]["current_version"] == "1.0"
        brand = program.get(f"/api/v1/clients/{cid}", headers=auth).json()
        assert brand["version"]["label"] == "1.0" and brand["current"] is True
        later = program.get(f"/api/v1/clients/{cid}?at=2030-02-01", headers=auth).json()
        assert later["version"]["label"] == "2.0" and later["current"] is False
        assert "#B8322A" in program.get(f"/api/v1/clients/{cid}/code", headers=auth).text
        audited = program.post(f"/api/v1/clients/{cid}/audit", headers=auth, json={"colors": ["#B8322A"]}).json()
        assert audited["version"]["label"] == "1.0" and audited["colors"][0]["verdict"] == "same"
        code = _rpc(program, auth, "tools/call", {"name": "get_code", "arguments": {"client": cid, "format": "css"}})
        assert "#B8322A" in code["content"][0]["text"]


def test_f2_on_its_day_the_later_version_holds(client: TestClient, space: int, monkeypatch: pytest.MonkeyPatch) -> None:
    made = _two_versions(client, space)
    monkeypatch.setattr(brands, "today", lambda: "2030-01-01")
    whole = client.get(f"/api/clients/{made['cid']}").json()
    assert whole["current"] == "2.0" and whole["current_id"] == made["second"]
    assert whole["projects"][0]["behind"] is True


def test_f2_a_project_version_from_a_later_day_holds_only_from_that_day(client: TestClient, space: int) -> None:
    made = _two_versions(client, space)
    cid, pid = made["cid"], made["pid"]
    first = client.get(f"/api/clients/{cid}/projects/{pid}").json()["versions"][0]["id"]
    _publish(client, cid, first, "1.0", "2026-02-01")
    later = client.post(f"/api/clients/{cid}/versions", json={"label": "2.0", "project_id": pid,
                                                               "source": first})
    assert later.status_code == 201, later.text
    _publish(client, cid, later.json()["id"], "2.0", "2031-01-01")
    project = client.get(f"/api/clients/{cid}/projects/{pid}").json()
    assert project["current"] == "1.0" and project["current_id"] == first


# --- F3, F17: colours as style sheets write them, ratios as they are graded ------------------------------------------


def test_f3_audit_and_contrast_read_colours_as_style_sheets_write_them(client: TestClient, space: int,
                                                                         tokens_on: None) -> None:
    made = _two_versions(client, space)
    auth = _token(client)
    written = ["rgb(184, 50, 42)", "rgb(184 50 42 / 50%)", "B8322A", "#b8322a80", "hsl(3deg 63% 44%)", "red"]
    with _program() as program:
        found = program.post(f"/api/v1/clients/{made['cid']}/audit", headers=auth,
                             json={"colors": written}).json()["colors"]
        assert [c["verdict"] for c in found] == ["same", "same", "same", "same", "same", "unreadable"]
        assert {c["value"] for c in found[:4]} == {"#B8322A"}
        mcp = _rpc(program, auth, "tools/call", {"name": "audit", "arguments": {"client": made["cid"],
                                                                                "colors": written}})
        assert [c["verdict"] for c in mcp["structuredContent"]["colors"]] == [c["verdict"] for c in found]
        sheet = program.post(f"/api/v1/clients/{made['cid']}/audit", headers=auth, json={
            "css": ".a { color: hsl(0, 0%, 100%); background: hsl(36deg 80% 57%) }"}).json()
        assert sheet["css"]["pairs"][0]["fg"] == "#FFFFFF" and sheet["css"]["pairs"][0]["bg"] == "#E9A33A"
        short = program.get("/api/v1/contrast", headers=auth, params={"fg": "000", "bg": "rgb(255, 255, 255)"})
        assert short.status_code == 200 and short.json()["ratio"] == 21.0
        wrong = program.get("/api/v1/contrast", headers=auth, params={"fg": "red", "bg": "#fff"})
        assert wrong.status_code == 422 and wrong.json()["detail"]["where"] == "fg"
        tool = _rpc(program, auth, "tools/call", {"name": "check_contrast", "arguments": {
            "foreground": "hsl(0 0% 0%)", "background": "fff"}})
        assert tool["isError"] is False and tool["structuredContent"]["ratio"] == 21.0


def test_f17_a_ratio_just_under_a_threshold_is_not_shown_on_it(client: TestClient, tokens_on: None) -> None:
    auth = _token(client)
    with _program() as program:
        answer = program.get("/api/v1/contrast", headers=auth, params={"fg": "#00848a", "bg": "#ffffff"}).json()
        tool = _rpc(program, auth, "tools/call", {"name": "check_contrast", "arguments": {
            "foreground": "#00848a", "background": "#ffffff"}})["structuredContent"]
    assert answer["ratio"] == tool["ratio"] == 4.49 and answer["text"] == "AA large"


# --- F18: the type scale in the code -------------------------------------------------------------------------------


def test_f18_the_code_carries_weight_and_line_height_of_each_step(client: TestClient, space: int,
                                                                   tokens_on: None) -> None:
    import json

    made = _two_versions(client, space)
    cid = made["cid"]
    css = client.get(f"/api/clients/{cid}/export?format=css").text
    assert "--text-body: 1.0625rem;" in css and "--text-body--line-height: 1.6;" in css
    assert "--text-body--font-weight: 400;" in css
    assert "--text-body--line-height: 1.6;" in client.get(f"/api/clients/{cid}/export?format=tailwind").text
    scss = client.get(f"/api/clients/{cid}/export?format=scss").text
    assert "$text-body-line-height: 1.6;" in scss and "$text-body-font-weight: 400;" in scss
    tokens = json.loads(client.get(f"/api/clients/{cid}/export?format=json").text)
    assert tokens["text"]["body"] == {"$type": "dimension", "$value": "1.0625rem"}, "the sizes keep their shape"
    assert tokens["lineHeight"]["body"]["$value"] == 1.6 and tokens["fontWeight"]["body"]["$value"] == 400
    auth = _token(client)
    with _program() as program:
        assert "--text-body--font-weight: 400;" in program.get(f"/api/v1/clients/{cid}/code", headers=auth).text


# --- F9: an upload of the wrong kind -------------------------------------------------------------------------------


def test_f9_a_logo_or_font_of_the_wrong_kind_is_refused_and_not_kept(client: TestClient, space: int) -> None:
    from sqlalchemy import func, select

    from app.db import SessionLocal
    from app.models import Media

    from .test_brands import SVG, WOFF2

    def count() -> int:
        with SessionLocal() as db:
            return int(db.scalar(select(func.count()).select_from(Media)) or 0)

    html = b"<!doctype html><html><body>not a picture</body></html>" + bytes(40)
    before = count()
    logo = client.post(f"/api/media?space={space}&name=fake.png&expect=picture", content=html)
    assert logo.status_code == 422 and logo.json()["detail"]["code"] == "not_a_picture"
    font = client.post(f"/api/media?space={space}&name=notafont.ttf&expect=font", content=b"just some words, no font")
    assert font.status_code == 422 and font.json()["detail"]["code"] == "not_a_font"
    assert client.post(f"/api/media?space={space}&name=logo.svg&expect=font", content=SVG).status_code == 422
    assert count() == before, "nothing refused stays behind"
    assert client.post(f"/api/media?space={space}&name=logo.svg&expect=picture", content=SVG).status_code == 201
    assert client.post(f"/api/media?space={space}&name=a.woff2&expect=font", content=WOFF2).status_code == 201
    # Without an expectation (an example, a further logo format) any file is taken, as before.
    assert client.post(f"/api/media?space={space}&name=brief.txt", content=b"words").status_code == 201


# --- F26: a new token is narrow from the start ---------------------------------------------------------------------


def test_f26_a_new_token_asks_for_its_clients_and_runs_out_after_90_days(client: TestClient, space: int,
                                                                          tokens_on: None) -> None:
    from datetime import timedelta

    from app.models import utcnow

    cid = _two_versions(client, space)["cid"]
    refused = client.post("/api/api-tokens", json={"name": "ci"})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "choose_clients"
    assert client.post("/api/api-tokens", json={"name": "ci", "clients": []}).status_code == 422
    both = client.post("/api/api-tokens", json={"name": "ci", "clients": [cid], "all_clients": True})
    assert both.status_code == 422
    made = client.post("/api/api-tokens", json={"name": "ci", "clients": [cid]})
    assert made.status_code == 201, made.text
    token = made.json()["token"]
    assert token["clients"] == [{"id": cid, "name": "Bäckerei Morgenrot"}] and token["level"] == "read"
    left = token_end(token) - utcnow()
    assert timedelta(days=89) < left <= timedelta(days=90)
    # "All" and "never" are still there, on purpose.
    wide = client.post("/api/api-tokens", json={"name": "wide", "all_clients": True, "days": None}).json()["token"]
    assert wide["clients"] is None and wide["expires_at"] is None


def token_end(token: dict[str, Any]) -> Any:
    from datetime import UTC, datetime

    end = datetime.fromisoformat(token["expires_at"])
    return end if end.tzinfo else end.replace(tzinfo=UTC)


# --- F15: names that tell things apart ------------------------------------------------------------------------------


def _code(answer: Any) -> str:
    return str(answer.json()["detail"]["code"])


def test_f15_client_names_are_unique_on_every_way(client: TestClient, operator: Account, tokens_on: None) -> None:
    first = client.post("/api/clients", json={"name": "Acme", "label": ""})
    assert first.status_code == 201
    for name in ("Acme", "  acme ", "ACME", "Ac me".replace(" ", "")):
        twin = client.post("/api/clients", json={"name": name, "label": ""})
        assert twin.status_code == 409 and _code(twin) == "client_name_taken", name
    other = client.post("/api/clients", json={"name": "Other", "label": ""}).json()
    renamed = client.patch(f"/api/clients/{other['id']}", json={"name": " acme"})
    assert renamed.status_code == 409 and _code(renamed) == "client_name_taken"
    assert client.patch(f"/api/clients/{first.json()['id']}", json={"name": "ACME"}).status_code == 200, \
        "its own name in other capitals"
    assert client.delete(f"/api/clients/{first.json()['id']}").status_code == 204
    binned = client.post("/api/clients", json={"name": "acme", "label": ""})
    assert binned.status_code == 409 and _code(binned) == "client_name_in_bin"
    # A member with the right to make clients meets the same rule.
    member = make_account("mila")
    with new_client(member) as browser:
        assert _code(browser.post("/api/clients", json={"name": "Other", "label": ""})) == "client_name_taken"


def test_f15_project_names_are_unique_within_their_client(client: TestClient, space: int, tokens_on: None) -> None:
    made = _two_versions(client, space)
    cid = made["cid"]
    twin = client.post(f"/api/clients/{cid}/projects", json={"name": " website ", "version_id": made["first"]})
    assert twin.status_code == 409 and _code(twin) == "project_name_taken"
    app = client.post(f"/api/clients/{cid}/projects", json={"name": "App", "version_id": made["first"]}).json()
    renamed = client.patch(f"/api/clients/{cid}/projects/{app['id']}", json={"name": "WEBSITE"})
    assert renamed.status_code == 409 and _code(renamed) == "project_name_taken"
    # Another client may have a project of that name.
    second = client.post("/api/clients", json={"name": "Second", "label": "1.0", "project": "Website"})
    assert second.status_code == 201, second.text
    auth = _token(client)
    with _program() as program:
        # By name, as an AI knows them: one client, one project of that name (it was 404 or the first of two).
        found = program.get("/api/v1/clients/bäckerei morgenrot?project=website", headers=auth).json()
        assert found["client"]["id"] == cid and found["project"]["id"] == made["pid"]


def test_f15_team_names_are_unique(client: TestClient, operator: Account) -> None:
    assert client.post("/api/teams", json={"name": "Design"}).status_code == 201
    twin = client.post("/api/teams", json={"name": " design "})
    assert twin.status_code == 409 and _code(twin) == "team_name_taken"
    other = client.post("/api/teams", json={"name": "Print"}).json()
    renamed = client.patch(f"/api/teams/{other['id']}", json={"name": "DESIGN"})
    assert renamed.status_code == 409 and _code(renamed) == "team_name_taken"
    assert client.patch(f"/api/teams/{other['id']}", json={"name": "print"}).status_code == 200


def test_f15_doubles_from_before_get_a_number_at_start(client: TestClient, operator: Account) -> None:
    from app.db import SessionLocal, init_db
    from app.models import Client, Project, Space, Team

    made = client.post("/api/clients", json={"name": "Acme", "label": "1.0", "project": "Web"}).json()
    with SessionLocal() as db:
        for name in ("acme", " ACME"):
            space = Space(name=name)
            db.add(space)
            db.flush()
            db.add(Client(id=brands.new_id(), space_id=space.id, name=name, updated_by="tester"))
        db.add(Project(id=brands.new_id(), client_id=made["id"], name="web", version_id=made["versions"][0]["id"],
                       note="", own=[]))
        db.add_all([Team(name="Design"), Team(name="design")])
        db.commit()
    init_db()
    with SessionLocal() as db:
        assert sorted(db.scalars(Client.__table__.select().with_only_columns(Client.name))) == sorted(
            ["Acme", "acme (2)", "ACME (3)"])
        assert db.get(Client, made["id"]).name == "Acme", "the oldest keeps its name"  # type: ignore[union-attr]
        assert sorted(p.name for p in db.query(Project).filter_by(client_id=made["id"])) == ["Web", "web (2)"]
        assert sorted(t.name for t in db.query(Team)) == ["Design", "design (2)"]
        spaces = {s.name for s in db.query(Space)}
        assert {"acme (2)", "ACME (3)"} <= spaces


def test_f15_what_nexsuite_brings_never_fails_on_a_name(client: TestClient, operator: Account, world: dict,
                                                        fake: test_suite.FakeSuite) -> None:
    """Two clients and two teams of one name in nexsuite: both come, the second with a number here, and the sync goes
    through, the next one too without a further number."""
    from app.db import SessionLocal
    from app.models import Client, Team

    test_suite.connect(client, world, operator)
    fake.clients["11"] = {**fake.clients["10"], "id": "11", "name": " IDEEN "}
    fake.ticked.add("11")
    fake.teams["80"] = {"id": "80", "name": "Print", "color": "#123456", "lead": None, "members": []}
    fake.teams["81"] = {"id": "81", "name": "print", "color": "#123456", "lead": None, "members": []}
    for _ in range(2):
        assert client.post("/api/suite/sync").status_code in (200, 204)
        with SessionLocal() as db:
            clients = sorted(c.name for c in db.query(Client))
            teams = sorted(t.name for t in db.query(Team))
        assert clients.count("Ideen") == 1 and "IDEEN (2)" in clients, clients
        assert teams.count("Print") == 1 and "print (2)" in teams, teams


def test_f15_two_at_once_make_one_client(client: TestClient, operator: Account,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """Two requests with the same new name at the same moment (a double click, two people): the first holds the name
    from its look until its commit, the second waits and is refused. Played out step by step: the first stops right
    after its look until the second has had every chance to look too."""
    import threading

    from app.db import SessionLocal
    from app.models import Account as AccountRow
    from app.models import Client
    from app.services import names

    looked = {"first": threading.Event(), "second": threading.Event()}
    go = threading.Event()
    real = names.check_client

    def watched(db: Any, name: str, own_id: str | None = None) -> None:
        real(db, name, own_id)
        who = threading.current_thread().name
        looked[who].set()
        if who == "first":
            go.wait(5)

    monkeypatch.setattr(names, "check_client", watched)
    results: dict[str, str] = {}

    def make(who: str) -> None:
        with SessionLocal() as db:
            account = db.get(AccountRow, operator.id)
            assert account is not None
            try:
                brands.create_client(db, account, "Twin Example", label=None)
                results[who] = "made"
            except brands.BrandError as exc:
                results[who] = exc.code

    first = threading.Thread(target=make, args=("first",), name="first")
    first.start()
    assert looked["first"].wait(5)
    second = threading.Thread(target=make, args=("second",), name="second")
    second.start()
    # Without the lock the second looks now and finds the name free; with it, it waits for the first.
    looked["second"].wait(1)
    go.set()
    first.join(10)
    second.join(10)
    with SessionLocal() as db:
        made = [c for c in db.query(Client) if c.name == "Twin Example"]
    assert len(made) == 1, results
    assert sorted(results.values()) == ["client_name_taken", "made"], results


def test_f15_one_name_however_it_is_written(client: TestClient, operator: Account) -> None:
    import unicodedata

    composed = unicodedata.normalize("NFC", "Café Lumière")
    decomposed = unicodedata.normalize("NFD", "Café Lumière")
    assert composed != decomposed
    assert client.post("/api/clients", json={"name": composed, "label": ""}).status_code == 201
    twin = client.post("/api/clients", json={"name": decomposed, "label": ""})
    assert twin.status_code == 409 and _code(twin) == "client_name_taken"
    assert client.post("/api/clients", json={"name": "Acme", "label": ""}).status_code == 201
    for hidden in ("Ac\u200bme", "\u2060Acme", "Ac\u00adme", "\uff21\uff43\uff4d\uff45", "Acme  "):
        answer = client.post("/api/clients", json={"name": hidden, "label": ""})
        assert answer.status_code == 409 and _code(answer) == "client_name_taken", ascii(hidden)
    assert client.post("/api/teams", json={"name": "Design"}).status_code == 201
    assert client.post("/api/teams", json={"name": "De\u200bsign"}).status_code == 409


def test_f15_a_number_from_nexsuite_is_logged_once(client: TestClient, operator: Account, world: dict,
                                                   fake: test_suite.FakeSuite,
                                                   caplog: pytest.LogCaptureFixture) -> None:
    import logging

    test_suite.connect(client, world, operator)
    fake.clients["11"] = {**fake.clients["10"], "id": "11", "name": "IDEEN"}
    fake.ticked.add("11")
    with caplog.at_level(logging.WARNING, logger="nexbrand.names"):
        for _ in range(3):
            assert client.post("/api/suite/sync").status_code in (200, 204)
    said = [r for r in caplog.records if "given a number" in r.getMessage()]
    assert len(said) == 1, [r.getMessage() for r in said]


def test_f9_every_picture_the_server_takes_as_a_logo_is_one_a_browser_shows(
        client: TestClient, space: int, monkeypatch: pytest.MonkeyPatch) -> None:
    """BMP is a logo; a HEIC is one as the WebP it becomes; a HEIC that cannot become one is refused and not kept."""
    import io

    from sqlalchemy import func, select

    from app.db import SessionLocal
    from app.models import Media
    from app.services import media, media_store

    from .test_media import picture

    def as_bytes(fmt: str) -> bytes:
        out = io.BytesIO()
        picture().save(out, format=fmt)
        return out.getvalue()

    bmp = client.post(f"/api/media?space={space}&name=logo.bmp&expect=picture", content=as_bytes("BMP"))
    assert bmp.status_code == 201 and bmp.json()["kind"] == "bmp"
    assert "bmp" in media_store.PICTURES and media_store.PICTURES <= set(media_store.SHOWN)
    heic = client.post(f"/api/media?space={space}&name=logo.heic&expect=picture", content=as_bytes("HEIF"))
    assert heic.status_code == 201 and heic.json()["kind"] == "webp"
    monkeypatch.setattr(media, "to_webp", lambda *_: False)
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(Media))
    other = picture()
    other.putpixel((0, 0), (1, 2, 3))
    out = io.BytesIO()
    other.save(out, format="HEIF")
    refused = client.post(f"/api/media?space={space}&name=other.heic&expect=picture", content=out.getvalue())
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "not_a_picture"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Media)) == before


def test_f2_before_any_version_holds_the_coming_one_is_given_as_not_current(client: TestClient, space: int,
                                                                             tokens_on: None) -> None:
    made = make_client(client, space, project="Website")
    cid, first = made["id"], made["versions"][0]["id"]
    _publish(client, cid, first, "1.0", "2030-01-01")
    pid = client.get(f"/api/clients/{cid}").json()["projects"][0]["id"]
    own = client.get(f"/api/clients/{cid}/projects/{pid}").json()["versions"][0]["id"]
    _publish(client, cid, own, "1.0", "2031-01-01")
    # A draft after it: the project still answers with its coming version, as the client does.
    assert client.post(f"/api/clients/{cid}/versions", json={"label": "1.1", "project_id": pid,
                                                             "source": own}).status_code == 201
    auth = _token(client)
    with _program() as program:
        assert program.get("/api/v1/clients", headers=auth).json()[0]["current_version"] is None
        brand = program.get(f"/api/v1/clients/{cid}", headers=auth).json()
        assert brand["version"]["label"] == "1.0" and brand["current"] is False
        project = program.get(f"/api/v1/clients/{cid}?project=Website", headers=auth).json()
        assert project["version"]["id"] == own and project["current"] is False
