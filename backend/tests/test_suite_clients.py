"""Clients and people while connected (Prüfgang 05.10.2026, block 4): deleting for good, connecting again, choices
that hold, direct links through the sign-in, a person made a moment ago, names, invitations from before, and the
browsers nexbrand knows.

nexsuite is played by ``FakeSuite`` from ``test_suite``; the provider for the sign-in by ``FakeProvider`` from
``test_oidc``. Nothing here waits for a clock.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import Account, Client, Space
from app.security import encrypt_secret
from app.services import oidc, settings_service, suite

from . import test_oidc, test_suite
from .conftest import PASSWORD, client_of, make_account, new_client, new_group, sign_in
from .test_oidc import CLIENT_ID, CLIENT_SECRET, ISSUER, FakeProvider, come_back, configure, fresh_browser
from .test_suite import SUITE, FakeSuite, _row, _setting, connect

# The fixtures of the suite and sign-in tests, under the names pytest looks for.
fake = test_suite.fake
world = test_suite.world
provider = test_oidc.provider


def _purge(browser: TestClient, cid: str, password: str | None = PASSWORD) -> Any:
    body = {"current_password": password} if password is not None else None
    return browser.request("DELETE", f"/api/clients/{cid}/purge", json=body)


# --- B6: deleting for good ------------------------------------------------------------------------------------------


def test_b6_a_client_nexsuite_keeps_is_not_deleted_for_good_here(client: TestClient, operator: Account, world: dict,
                                                                 fake: FakeSuite) -> None:
    connect(client, world, operator)
    ideen = client_of(client, world["ideen"])
    fake.ticked.discard("10")
    fake.clients_bin = [{"id": "10", "deleted_at": "2026-10-04T10:00:00+00:00"}]
    client.post("/api/suite/sync")
    assert ideen in [c["id"] for c in client.get("/api/clients?deleted=true").json()]
    refused = _purge(client, ideen)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "managed_by_suite"
    # Without a password neither: the refusal comes before it, there is nothing to confirm.
    assert _purge(client, ideen, None).status_code == 409
    with SessionLocal() as db:
        assert db.get(Client, ideen) is not None and db.get(Space, world["ideen"]) is not None


def test_b6_deleting_for_good_asks_for_the_password(client: TestClient, operator: Account) -> None:
    cid = client_of(client, new_group(client, "Example Bakery"))
    assert client.delete(f"/api/clients/{cid}").status_code == 204
    missing = _purge(client, cid, None)
    assert missing.status_code == 401 and missing.json()["detail"]["code"] == "wrong_password"
    assert _purge(client, cid, "not the password").status_code == 401
    with SessionLocal() as db:
        assert db.get(Client, cid) is not None
    assert _purge(client, cid).status_code == 204
    with SessionLocal() as db:
        assert db.get(Client, cid) is None


def test_b6_a_manager_who_is_no_operator_gives_the_password_too(client: TestClient, operator: Account) -> None:
    anna = make_account("anna")
    with new_client(anna) as browser:
        cid = client_of(browser, new_group(browser, "Annas"))
        assert browser.delete(f"/api/clients/{cid}").status_code == 204
        assert _purge(browser, cid, "wrong one").status_code == 401
        assert _purge(browser, cid).status_code == 204


# --- B8, B9, B23, B24: connecting -----------------------------------------------------------------------------------


def _start(client: TestClient) -> dict[str, Any]:
    answer = client.post("/api/suite/start", json={"url": SUITE, "code": "GOOD-CODE-1234"})
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_b8_connecting_again_keeps_the_blocked_blocked_and_finds_the_own_person(
        client: TestClient, operator: Account, world: dict, fake: FakeSuite) -> None:
    connect(client, world, operator)  # cleo is left out, and blocked
    # Another app brought a person "cleo" to nexsuite: the sync makes her an account here, beside the blocked one.
    fake.people["60"] = {"id": "60", "name": "cleo", "display_name": "Cleo Example", "email": "", "operator": False,
                         "blocked": False}
    # anna is deleted in nexsuite: blocked here.
    del fake.people["2"]
    client.post("/api/suite/sync")
    assert _row("cleo2").oidc_subject == "60" and _row("anna").blocked_at is not None
    assert client.post("/api/suite/disconnect", json={"current_password": PASSWORD}).status_code == 200
    fake.connected = False
    people_before = set(fake.people)
    found = _start(client)
    rows = {a["name"]: a for a in found["accounts"]}
    assert (rows["cleo"]["suggest"], rows["cleo"]["blocked"]) == ("skip", True), "left out before, left out again"
    assert (rows["anna"]["suggest"], rows["anna"]["blocked"], rows["anna"]["gone"]) == ("skip", True, True)
    assert (rows["cleo2"]["suggest"], rows["cleo2"]["from_suite"]) == ("60", True), "its own person, not a new one"
    assert rows["tester"]["suggest"] == "1" and rows["tester"]["blocked"] is False
    choices = {a["id"]: a["suggest"] for a in found["accounts"]}
    done = client.post("/api/suite/finish", json={"accounts": choices, "clients": {}})
    assert done.status_code == 200, done.text
    assert set(fake.people) == people_before, "nobody made twice in nexsuite"
    assert _row("cleo").blocked_at is not None and _row("anna").blocked_at is not None
    assert _row("cleo2").oidc_subject == "60" and _row("cleo2").blocked_at is None


def test_b8_another_nexsuite_does_not_count_the_persons_from_before(client: TestClient, operator: Account,
                                                                    world: dict, fake: FakeSuite) -> None:
    connect(client, world, operator)
    assert client.post("/api/suite/disconnect", json={"current_password": PASSWORD}).status_code == 200
    with SessionLocal() as db:
        settings_service.save(db, {"suite_former_url": "https://other.example.com"})
        db.commit()
    fake.connected = False
    fake.people["2"]["email"], fake.people["2"]["name"] = "", "someone"
    rows = {a["name"]: a for a in _start(client)["accounts"]}
    assert rows["anna"]["suggest"] == "new" and rows["anna"]["from_suite"] is False


def test_b9_a_person_client_or_team_nexsuite_does_not_have_is_refused(client: TestClient, operator: Account,
                                                                      world: dict, fake: FakeSuite) -> None:
    found = _start(client)
    choices = {a["id"]: a["suggest"] for a in found["accounts"]}
    choices[world["cleo"].id] = "skip"
    unknown = dict(choices)
    unknown[world["ben"].id] = "99999"
    refused = client.post("/api/suite/finish", json={"accounts": unknown, "clients": {}})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "person_unknown"
    fake.people["4"] = {"id": "4", "name": "blocky", "display_name": "", "email": "", "operator": False,
                        "blocked": True}
    unknown[world["ben"].id] = "4"
    blocked = client.post("/api/suite/finish", json={"accounts": unknown, "clients": {}})
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "person_unknown"
    studio = client_of(client, world["studio"])
    wrong_client = client.post("/api/suite/finish", json={"accounts": choices, "clients": {studio: "777"}})
    assert wrong_client.status_code == 409 and wrong_client.json()["detail"]["code"] == "client_unknown"
    wrong_team = client.post("/api/suite/finish", json={"accounts": choices, "clients": {},
                                                        "teams": {world["team"]: "888"}})
    assert wrong_team.status_code == 409 and wrong_team.json()["detail"]["code"] == "team_unknown"
    assert _setting("suite_state") == "connecting"
    assert _row("ben").blocked_at is None and _row("ben").oidc_subject == ""
    assert [path for method, path in fake.calls if method == "POST" and path != "/pair"] == [], "nothing made there"


def test_b23_the_choices_so_far_are_kept_until_connected(client: TestClient, operator: Account, world: dict,
                                                         fake: FakeSuite) -> None:
    assert client.put("/api/suite/choices", json={"accounts": {}, "step": 2}).status_code == 409, "nothing under way"
    found = _start(client)
    assert found["chosen"] is None
    chosen = {"accounts": {str(world["cleo"].id): "skip", str(world["ben"].id): "new"},
              "clients": {client_of(client, world["studio"]): "new"}, "teams": {str(world["team"]): "new"}, "step": 3}
    assert client.put("/api/suite/choices", json=chosen).status_code == 204
    assert client.get("/api/suite/proposal").json()["chosen"] == chosen
    with new_client(world["anna"]) as anna:
        assert anna.put("/api/suite/choices", json=chosen).status_code == 403
    assert client.put("/api/suite/choices", json={**chosen, "step": 7}).status_code == 422
    choices = {a["id"]: a["suggest"] for a in found["accounts"]}
    choices[world["cleo"].id] = "skip"
    assert client.post("/api/suite/finish", json={"accounts": choices, "clients": {}}).status_code == 200
    assert _setting("suite_pending") is None
    assert client.put("/api/suite/choices", json=chosen).status_code == 409


@pytest.mark.parametrize("answer", [
    suite.SuiteError("tab_missing", "Refused.", 409),  # another nex-app at that address
    suite.SuiteError("suite_failed", "nexsuite refused.", 409),  # nexsuite under a path it does not have
    {"ok": True},  # something that answers, but not as nexsuite
])
def test_b24_an_address_that_is_not_nexsuite_is_named_as_such(client: TestClient, operator: Account,
                                                              monkeypatch: pytest.MonkeyPatch, answer: Any) -> None:
    def other_app(method: str, url: str, *, token: str = "", body: Any = None) -> Any:
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(suite, "request", other_app)
    refused = client.post("/api/suite/start", json={"url": "https://tasks.example.com", "code": "GOOD-CODE-1234"})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "not_suite"
    assert _setting("suite_state") == ""


def test_b24_nexsuites_own_refusal_is_passed_on(client: TestClient, operator: Account, fake: FakeSuite) -> None:
    wrong = client.post("/api/suite/start", json={"url": SUITE, "code": "BAD-CODE"})
    assert wrong.status_code == 409 and wrong.json()["detail"]["code"] == "pair_code_invalid"


# --- B10, B20: the sign-in ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(("asked", "landing"), [
    ("/c/abc123XYZ_-?tab=reviews&v=x1", "/c/abc123XYZ_-?tab=reviews&v=x1"),
    ("/settings?tab=teams", "/settings?tab=teams"),
    ("/", None),
    ("//evil.example.com/x", None),
    ("/\\evil.example.com", None),
    ("https://evil.example.com/", None),
    ("/api/auth/me", None),
    ("/api", None),
    ("/c/a b", None),
    ("/c/ä", None),
    ("c/relative", None),
    ("/" + "a" * 600, None),
])
def test_b10_only_a_page_of_nexbrands_own_is_a_landing(asked: str, landing: str | None) -> None:
    assert oidc.safe_next(asked) == landing


def _sign_in(browser: TestClient, provider: FakeProvider, next_path: str | None, **claims: Any) -> Any:
    query = f"?next={quote(next_path, safe='')}" if next_path is not None else ""
    started = browser.get(f"/api/oidc/start{query}", follow_redirects=False)
    assert started.status_code == 302, started.text
    values = dict(part.split("=", 1) for part in started.headers["location"].split("?", 1)[1].split("&"))
    provider.challenge = values["code_challenge"]
    provider.claims = {"nonce": values["nonce"], **claims}
    return come_back(browser, values["state"])


def test_b10_a_direct_link_survives_the_sign_in_through_the_provider(client: TestClient, operator: Account,
                                                                     provider: FakeProvider) -> None:
    configure(client, auto_create=True)
    browser = fresh_browser(client)
    back = _sign_in(browser, provider, "/c/abc123XYZ?tab=reviews")
    assert back.status_code == 303 and back.headers["location"] == "/c/abc123XYZ?tab=reviews"
    assert browser.get("/api/auth/me").status_code == 200
    other = _sign_in(fresh_browser(client), provider, "//evil.example.com")
    assert other.headers["location"] == "/", "never another host"
    plain = _sign_in(fresh_browser(client), provider, None)
    assert plain.headers["location"] == "/"


def test_b10_a_refusal_keeps_the_page_for_the_next_try(client: TestClient, operator: Account,
                                                       provider: FakeProvider) -> None:
    configure(client, auto_create=False)
    refused = _sign_in(fresh_browser(client), provider, "/c/abc123XYZ", sub="nobody", email="no@example.com")
    assert refused.headers["location"] == "/login?error=oidc_no_account&next=%2Fc%2Fabc123XYZ"


def _suite_signs_in(client: TestClient) -> None:
    """The provider of the tests stands in for nexsuite's sign-in (the connection set nexsuite's own)."""
    with SessionLocal() as db:
        settings_service.save(db, {"oidc_issuer": ISSUER, "oidc_client_id": CLIENT_ID,
                                   "oidc_client_secret_enc": encrypt_secret(CLIENT_SECRET)})
        db.commit()


def test_b20_a_person_made_in_nexsuite_a_moment_ago_gets_in_at_once(
        client: TestClient, operator: Account, world: dict, fake: FakeSuite, provider: FakeProvider) -> None:
    connect(client, world, operator)
    _suite_signs_in(client)
    fake.people["61"] = {"id": "61", "name": "dora", "display_name": "Dora", "email": "dora@example.com",
                         "operator": False, "blocked": False}
    browser = fresh_browser(client)
    back = _sign_in(browser, provider, "/c/abc123XYZ", sub="61", email="dora@example.com", preferred_username="dora")
    assert back.status_code == 303 and back.headers["location"] == "/c/abc123XYZ"
    assert browser.get("/api/auth/me").json()["name"] == "dora"
    assert _row("dora").oidc_subject == "61"
    # Somebody nexsuite does not list: refused with the reason for a connected app, no invitation offered.
    stranger = _sign_in(fresh_browser(client), provider, None, sub="999", email="x@example.com")
    assert stranger.headers["location"] == "/login?error=suite_no_account"


# --- B21, B22, B26, G3 ------------------------------------------------------------------------------------------


def test_b21_a_new_person_gets_the_name_a_deleted_one_had(client: TestClient, operator: Account, world: dict,
                                                          fake: FakeSuite) -> None:
    connect(client, world, operator)
    studio = client_of(client, world["studio"])
    with SessionLocal() as db:
        db.get(Client, studio).updated_by = "anna"  # type: ignore[union-attr]
        db.commit()
    old = world["anna"].id
    del fake.people["2"]
    fake.people["70"] = {"id": "70", "name": "anna", "display_name": "Anna New", "email": "", "operator": False,
                         "blocked": False}
    client.post("/api/suite/sync")
    new = _row("anna")
    assert new.oidc_subject == "70" and new.id != old, "named as in nexsuite"
    with SessionLocal() as db:
        before = db.get(Account, old)
        assert before is not None and before.name == "anna2" and before.blocked_at is not None
        assert db.get(Client, studio).updated_by == "anna2", "what the deleted one did stays hers"  # type: ignore[union-attr]
    # The emergency account keeps its name whatever happens: it is its way in.
    del fake.people["1"]
    fake.people["71"] = {"id": "71", "name": "tester", "display_name": "", "email": "", "operator": False,
                         "blocked": False}
    client.post("/api/suite/sync")
    assert _row("tester").id == operator.id and _row("tester2").oidc_subject == "71"


def test_b22_who_makes_clients_is_not_changed_here_while_connected(client: TestClient, operator: Account,
                                                                   world: dict, fake: FakeSuite) -> None:
    assert client.put("/api/settings", json={"members_create_clients": False}).status_code == 200
    connect(client, world, operator)
    refused = client.put("/api/settings", json={"members_create_clients": True})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "managed_by_suite"
    assert _setting("members_create_clients") is False


def test_b26_an_invitation_from_before_says_at_once_that_it_does_not_hold(client: TestClient, operator: Account,
                                                                          world: dict, fake: FakeSuite) -> None:
    link = client.post(f"/api/spaces/{world['studio']}/invites", json={"role": "write", "days": 7}).json()["link"]
    token = link.rsplit("/", 1)[1]
    with SessionLocal() as db:
        db.get(Account, operator.id).display_name = "Robin Example"  # type: ignore[union-attr]
        db.commit()
    with new_client() as stranger:
        alone = stranger.get(f"/api/invite/{token}").json()
        assert (alone["space"], alone["role"], alone["by"]) == ("Studio", "write", "Robin Example")
        connect(client, world, operator)
        answer = stranger.get(f"/api/invite/{token}")
        assert answer.status_code == 404 and answer.json()["detail"]["code"] == "invite_suite"
        assert "Studio" not in answer.text


def test_g3_the_page_knows_where_nexsuite_opens_while_connected(client: TestClient, operator: Account, world: dict,
                                                                fake: FakeSuite) -> None:
    assert client.get("/api/auth/me").json()["suite_url"] == ""
    connect(client, world, operator)
    with new_client(world["anna"]) as anna:
        assert anna.get("/api/auth/me").json()["suite_url"] == SUITE


def test_g8_every_client_says_whether_nexsuite_keeps_its_rights(client: TestClient, operator: Account, world: dict,
                                                                fake: FakeSuite) -> None:
    assert {s["name"]: s["managed"] for s in client.get("/api/admin/spaces").json()} == {"Studio": False,
                                                                                          "ideen": False}
    connect(client, world, operator)
    assert all(s["managed"] for s in client.get("/api/admin/spaces").json())


# --- Block 3, continued: the browsers nexbrand knows -----------------------------------------------------------------


def _keys() -> dict[str, str]:
    with SessionLocal() as db:
        return {row.name: row.device_key for row in db.query(Account)}


def test_signing_out_everywhere_in_nexsuite_forgets_the_browsers_once(client: TestClient, operator: Account,
                                                                      world: dict, fake: FakeSuite) -> None:
    connect(client, world, operator)
    before = _keys()
    client.post("/api/suite/sync")
    assert _keys() == before, "a sync that changes nothing draws no new key"
    fake.people["2"]["signed_out"] = "2026-10-05T10:00:00+00:00"
    client.post("/api/suite/sync")
    after = _keys()
    assert after["anna"] != before["anna"], "signed out everywhere in nexsuite: the browsers known before are not"
    assert {k: v for k, v in after.items() if k != "anna"} == {k: v for k, v in before.items() if k != "anna"}
    client.post("/api/suite/sync")
    assert _keys() == after, "the same moment again is no new sign-out"
    fake.people["2"]["signed_out"] = "2026-10-05T11:00:00+00:00"
    client.post("/api/suite/sync")
    assert _keys()["anna"] != after["anna"]


def test_the_same_password_or_block_set_again_keeps_the_browsers(client: TestClient, operator: Account) -> None:
    anna = make_account("anna")
    with SessionLocal() as db:
        row = db.get(Account, anna.id)
        assert row is not None
        key = row.device_key
        row.password_hash = row.password_hash
        row.blocked_at = row.blocked_at
        db.commit()
        assert db.get(Account, anna.id).device_key == key  # type: ignore[union-attr]
    with new_client() as browser:
        sign_in(browser, anna)
        assert browser.get("/api/auth/me").status_code == 200
