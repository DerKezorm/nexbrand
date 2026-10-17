"""Handling and the small things around it.

* An account locked for a while after wrong passwords keeps its API tokens; a block still ends them.
* A new password that is the old one is refused and ends no other session.
* Names and titles refuse every control character, DEL and C1 too; names from the directory service lose them.
* A test mail without a mail server is a setting, not a failure outside: 409, no error in the log.
* Nothing of nexbrand belongs in a search engine.
* Whether collecting from outside is allowed is known before anybody tries.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import Account, Client, Share, Team, utcnow
from app.services import apitokens

from . import test_suite
from .conftest import PASSWORD, make_account, new_client
from .test_brands import make_client
from .test_suite import FakeSuite, connect

fake = test_suite.fake
world = test_suite.world

NEW_PASSWORD = "another long password 42"
#: One of each kind: C0 (unit separator, which Python's split takes for a blank), DEL, C1 (next line, also a blank to
#: split, and a plain C1 one).
CONTROLS = ["\x1f", "\x7f", "\x85", "\x9b"]


@pytest.fixture
def tokens_on(client: TestClient, operator: Account) -> Iterator[None]:
    apitokens.forget()
    assert client.put("/api/settings", json={"api_tokens_allowed": True}).status_code == 200
    yield
    apitokens.forget()


def _program() -> TestClient:
    from app.main import app

    return TestClient(app, base_url="http://testserver")


# --- API tokens and the lock after wrong passwords --------------------------------------------------------------


def test_a_lock_after_wrong_passwords_keeps_the_tokens_a_block_ends_them(
    client: TestClient, operator: Account, space: int, tokens_on: None
) -> None:
    anna = make_account("anna")
    with new_client(anna) as browser:
        made = browser.post("/api/api-tokens", json={"name": "Build", "level": "read", "all_clients": True,
                                                     "days": None})
        assert made.status_code == 201, made.text
        auth = {"Authorization": f"Bearer {made.json()['secret']}"}
    with _program() as program:
        assert program.get("/api/v1/clients", headers=auth).status_code == 200
        with SessionLocal() as db:
            row = db.get(Account, anna.id)
            assert row is not None
            # As ten wrong guesses by a stranger leave it.
            row.locked_until = utcnow() + timedelta(minutes=15)
            db.commit()
        assert program.get("/api/v1/clients", headers=auth).status_code == 200, "a stranger's guesses cut no program off"
        assert client.post(f"/api/accounts/{anna.id}/block", json={"current_password": PASSWORD}).status_code == 204
        refused = program.get("/api/v1/clients", headers=auth)
        assert refused.status_code == 401 and refused.json()["detail"]["code"] == "token_invalid"


# --- An unchanged password -----------------------------------------------------------------------------------------


def test_an_unchanged_password_is_refused_and_ends_no_session(client: TestClient, operator: Account) -> None:
    with new_client(operator) as other:
        answer = client.put("/api/auth/password", json={"current": PASSWORD, "new": PASSWORD})
        assert answer.status_code == 422 and answer.json()["detail"]["code"] == "password_unchanged"
        assert other.get("/api/auth/me").status_code == 200, "the other session goes on"
        assert client.put("/api/auth/password", json={"current": PASSWORD, "new": NEW_PASSWORD}).status_code == 204
        assert other.get("/api/auth/me").status_code == 401


# --- Control characters ----------------------------------------------------------------------------------------------


def _refused(answer: Any) -> bool:
    return answer.status_code == 422 and answer.json()["detail"]["code"] == "invalid_characters"


@pytest.mark.parametrize("sign", CONTROLS)
def test_names_and_titles_refuse_every_control_character(client: TestClient, operator: Account, space: int,
                                                          tokens_on: None, sign: str) -> None:
    assert client.put("/api/settings", json={"shares_allowed": True}).status_code == 200
    made = make_client(client, space)
    cid = made["id"]
    version = made["versions"][0]
    bad = f"Acme{sign}Studio"
    # A client, its project, a version, a team, a token, a public page and a review: every name and title.
    assert _refused(client.post("/api/clients", json={"name": bad, "label": ""}))
    assert _refused(client.patch(f"/api/clients/{cid}", json={"name": bad}))
    assert _refused(client.patch(f"/api/clients/{cid}", json={"sector": bad}))
    assert _refused(client.post(f"/api/clients/{cid}/projects", json={"name": bad, "version_id": version["id"]}))
    assert _refused(client.put(f"/api/clients/{cid}/versions/{version['id']}", json={"label": bad}))
    assert _refused(client.post("/api/teams", json={"name": bad}))
    assert _refused(client.post("/api/api-tokens", json={"name": bad, "all_clients": True}))
    direction = {"id": "a", "label": "A", "data": version["data"]}
    assert _refused(client.post(f"/api/clients/{cid}/reviews", json={"version_id": version["id"], "label": bad,
                                                                    "variants": [direction]}))
    assert _refused(client.post(f"/api/clients/{cid}/reviews", json={
        "version_id": version["id"], "label": "2.0", "variants": [{**direction, "label": bad}]}))
    with SessionLocal() as db:
        assert not any(sign in (row.name or "") for row in db.query(Client)), "nothing kept"
        assert not any(sign in (row.name or "") for row in db.query(Team))
    # Line breaks and tabs typed into a name are no reason to refuse it: they become one blank, as before.
    assert client.patch(f"/api/clients/{cid}", json={"name": "Acme\tStudio\n"}).json()["name"] == "Acme Studio"


def test_a_public_page_and_a_note_refuse_control_characters_too(client: TestClient, operator: Account,
                                                                 space: int) -> None:
    made = make_client(client, space)
    cid = made["id"]
    version = client.get(f"/api/clients/{cid}").json()["versions"][0]["id"]
    assert client.post(f"/api/clients/{cid}/versions/{version}/publish", json={}).status_code == 200
    assert client.put("/api/settings", json={"shares_allowed": True}).status_code == 200
    assert _refused(client.post(f"/api/clients/{cid}/shares", json={"label": "Press\x7fkit"}))
    share = client.post(f"/api/clients/{cid}/shares", json={"label": "Press kit"})
    assert share.status_code == 201, share.text
    assert _refused(client.patch(f"/api/shares/{share.json()['id']}", json={"label": "Press\x85kit"}))
    with SessionLocal() as db:
        assert [row.label for row in db.query(Share)] == ["Press kit"]
    # A note keeps its lines, never a control character.
    assert _refused(client.patch(f"/api/clients/{cid}", json={"note": "first line\nsecond\x9b"}))
    assert client.patch(f"/api/clients/{cid}", json={"note": "first line\nsecond"}).status_code == 200


def test_names_from_nexsuite_lose_their_control_characters(client: TestClient, operator: Account, world: dict,
                                                           fake: FakeSuite) -> None:
    connect(client, world, operator)
    fake.people["2"]["display_name"] = "Anna\x85Berg\x7f\u200b"
    fake.teams["70"] = {"id": "70", "name": "Gra\x9bfik\x1f", "color": "#2f7bff", "lead": None, "members": ["1"]}
    fake.clients["10"]["name"] = "Ide\x7fen\x85Werk"
    fake.clients["10"]["sector"] = "Bak\x9bery"
    assert client.post("/api/suite/sync").status_code == 200
    with SessionLocal() as db:
        anna = db.query(Account).filter_by(name="anna").one()
        assert anna.display_name == "Anna Berg", "as a display name typed here: no control, no format character"
        assert db.query(Team).filter_by(external_id="70").one().name == "Grafik"
        names = {row.name for row in db.query(Client)}
        assert "Ideen Werk" in names and not any(any(sign in name for sign in CONTROLS) for name in names)
        assert {row.sector for row in db.query(Client)} >= {"Bakery"}


# --- Test mail without a mail server ------------------------------------------------------------------------------


def test_a_test_mail_without_a_mail_server_is_409_and_no_error(
    client: TestClient, operator: Account, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        answer = client.post("/api/settings/mail-test", json={"to": "dora@example.com"})
    assert answer.status_code == 409 and answer.json()["detail"]["code"] == "mail_off"
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]
    # An invitation by mail the same: the link was to go by mail only, so none is kept.
    assert client.put("/api/settings", json={"public_url": "https://brand.example.com"}).status_code == 200
    invite = client.post("/api/invites", json={"email": "dora@example.com", "send": True})
    assert invite.status_code == 409 and invite.json()["detail"]["code"] == "mail_off"
    assert client.get("/api/invites").json() == []


# --- Search engines and the switch for collecting --------------------------------------------------------------


def test_no_page_of_nexbrand_is_for_a_search_engine(client: TestClient) -> None:
    for path in ("/api/health", "/api/auth/methods", "/api/public/nothing-here"):
        assert client.get(path).headers.get("x-robots-tag") == "noindex, nofollow", path


def test_the_switch_for_collecting_is_known_before_anybody_tries(client: TestClient, operator: Account) -> None:
    assert client.get("/api/auth/me").json()["collect_allowed"] is False
    assert client.put("/api/settings", json={"collect_allowed": True}).status_code == 200
    with new_client(make_account("anna")) as anna:
        assert anna.get("/api/auth/me").json()["collect_allowed"] is True


# --- Connecting: what the directory service answers -------------------------------------------------------------


@pytest.mark.parametrize("code", ["app_still_connected", "app_not_reachable"])
def test_a_pairing_nexsuite_refuses_for_an_older_connection_says_why(client: TestClient, operator: Account,
                                                                     fake: FakeSuite, code: str) -> None:
    fake.pair_refused = code
    answer = client.post("/api/suite/start", json={"url": test_suite.SUITE + "/", "code": "GOOD-CODE-1234"})
    # Not "no the directory service at this address": it is one, and it names what to do.
    assert answer.status_code == 409 and answer.json()["detail"]["code"] == code


def test_a_display_name_goes_to_a_matched_person_without_one(client: TestClient, operator: Account, world: dict,
                                                             fake: FakeSuite) -> None:
    with SessionLocal() as db:
        anna = db.get(Account, world["anna"].id)
        assert anna is not None
        anna.display_name = "Anna Example"
        db.commit()
    fake.people["2"]["display_name"] = ""
    connect(client, world, operator)
    assert ("POST", "/people/2/name") in fake.calls
    assert fake.people["2"]["display_name"] == "Anna Example"
    assert ("POST", "/people/1/name") not in fake.calls, "a person with a display name keeps it"
    with SessionLocal() as db:
        assert db.query(Account).filter_by(name="anna").one().display_name == "Anna Example"


def test_a_refused_display_name_does_not_stop_connecting(client: TestClient, operator: Account, world: dict,
                                                         fake: FakeSuite) -> None:
    with SessionLocal() as db:
        anna = db.get(Account, world["anna"].id)
        assert anna is not None
        anna.display_name = "Anna Example"
        db.commit()
    fake.people["2"]["display_name"] = ""
    fake.name_refused = True
    connect(client, world, operator)
    assert ("POST", "/people/2/name") in fake.calls
    assert client.get("/api/suite").json()["state"] == "connected"
