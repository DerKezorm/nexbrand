"""What the night check of 04.10.2026 found in nexbrand, each as it should be now (the numbers are those of the
list in nexsuite/tools/pruefgang-2026-10-04/LISTE.md). The second part holds what the check of 05.10.2026 found
missing of them in nexbrand (its numbers in brackets, from nexsuite/tools/pruefgang-2026-10-05/LISTE.md)."""

from __future__ import annotations

import hashlib
import time
from datetime import timedelta
from typing import Any, Self

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import Account, Space, utcnow
from app.services import cleanup, settings_service, suite

from . import test_suite, test_totp
from .conftest import PASSWORD, client_of, join, make_account, new_client, new_group, sign_in
from .test_suite import SUITE, FakeSuite, _signed, connect

# The fixtures of the suite tests, under the names pytest looks for.
fake = test_suite.fake
world = test_suite.world
clock = test_totp.clock


def _client(client: TestClient, space: int, name: str = "Plan") -> str:
    """The client of the group ``space``, under ``name``."""
    cid = client_of(client, space)
    assert client.patch(f"/api/clients/{cid}", json={"name": name}).status_code == 200
    return cid


def test_a8_a_public_page_of_a_client_in_the_bin_is_gone(client: TestClient, operator: Account, space: int) -> None:
    from .test_brands import make_client

    with SessionLocal() as db:
        settings_service.save(db, {"shares_allowed": True})
        db.commit()
    made = make_client(client, space)["id"]
    version = client.get(f"/api/clients/{made}").json()["versions"][0]["id"]
    client.post(f"/api/clients/{made}/versions/{version}/publish", json={})
    token = client.post(f"/api/clients/{made}/shares", json={"days": 7}).json()["link"].rsplit("/", 1)[1]
    with new_client() as visitor:
        assert visitor.get(f"/api/public/{token}").status_code == 200
        assert client.delete(f"/api/clients/{made}").status_code == 204
        assert visitor.get(f"/api/public/{token}").status_code == 404


def test_a9_connected_what_nexsuite_keeps_stays_shut(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite
) -> None:
    invite = client.post(f"/api/spaces/{world['studio']}/invites", json={"role": "manage", "days": 7})
    token = invite.json()["link"].rsplit("/", 1)[1]
    connect(client, world, operator)
    for answer in (
        client.put("/api/settings", json={"public_url": "https://other.example.com"}),
        client.delete("/api/oidc/link"),
        client.post("/api/backups/nexbrand-2026-10-04-120000.zip/restore", json={"password": PASSWORD}),
    ):
        assert answer.status_code == 409 and answer.json()["detail"]["code"] == "managed_by_suite", answer.text
    with new_client(world["ben"]) as ben:
        joined = ben.post(f"/api/invite/{token}/join")
        assert joined.status_code == 409 and joined.json()["detail"]["code"] == "managed_by_suite"


def test_a13_a_refusal_is_no_reason_to_leave(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite, monkeypatch: Any
) -> None:
    connect(client, world, operator)

    def refused(*_args: Any, **_kwargs: Any) -> Any:
        raise suite.SuiteError("suite_failed", "nexsuite refused.", 409)

    monkeypatch.setattr(suite, "request", refused)
    with SessionLocal() as db:
        assert suite.sync(db) is False
        assert settings_service.get(db, "suite_state") == "connected"


def test_a13_the_code_decides(monkeypatch: Any) -> None:
    import httpx

    class Client:
        def __init__(self, *_: Any, **__: Any) -> None:
            pass

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def request(self, *_: Any, **__: Any) -> httpx.Response:
            return httpx.Response(401, json={"detail": {"code": Client.code}})

    monkeypatch.setattr(suite.httpx, "Client", Client)
    for code, expected in (("app_unknown", "suite_refused"), ("sign_in_first", "suite_failed")):
        Client.code = code
        try:
            suite.request("GET", SUITE + "/api/connect/v1/directory", token="nxs_x")
        except suite.SuiteError as exc:
            assert exc.code == expected, code
        else:
            raise AssertionError("no error")


def test_a14_a_space_without_a_right_answers_as_if_there_were_none(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite
) -> None:
    connect(client, world, operator)
    with new_client(world["ben"]) as ben:
        for answer in (
            ben.patch(f"/api/spaces/{world['ideen']}", json={"name": "x"}),
            ben.delete(f"/api/spaces/{world['ideen']}"),
        ):
            assert answer.status_code == 404, answer.text


def test_d9_for_good_takes_the_right_to_manage(client: TestClient, operator: Account, space: int) -> None:
    made = _client(client, space)
    make_account("wim")
    join(client, space, "wim", "write")
    with new_client() as wim:
        sign_in(wim, Account(id=_id("wim"), name="wim"))
        assert wim.delete(f"/api/clients/{made}").status_code == 204, "into the bin, as before"
        assert wim.delete(f"/api/clients/{made}/purge").status_code in (403, 404)
    assert client.request("DELETE", f"/api/clients/{made}/purge", json={"current_password": PASSWORD}).status_code == 204


def _id(name: str) -> int:
    with SessionLocal() as db:
        return db.query(Account).filter_by(name=name).one().id


def test_d4_the_operator_sees_and_brings_back_every_client_in_the_bin(client: TestClient, operator: Account) -> None:
    anna = make_account("anna")
    with new_client(anna) as browser:
        own = client_of(browser, new_group(browser, "Annas"))
        assert browser.delete(f"/api/clients/{own}").status_code == 204
    assert [c["id"] for c in client.get("/api/clients?deleted=true").json()] == [own]
    assert client.post(f"/api/clients/{own}/restore").status_code == 200


def test_e3_a_client_from_nexsuite_waits_for_nexsuite_not_for_the_clock(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite
) -> None:
    from app.models import Client

    connect(client, world, operator)
    ideen = client_of(client, world["ideen"])
    with SessionLocal() as db:
        assert db.get(Space, world["ideen"]).external_id  # type: ignore[union-attr]
        db.get(Client, ideen).deleted_at = utcnow() - timedelta(days=40)  # type: ignore[union-attr]
        local = Space(name="Alt")
        db.add(local)
        db.flush()
        db.add(Client(id="local-client", space_id=local.id, name="Alt", deleted_at=utcnow() - timedelta(days=40)))
        db.commit()
        local_id = local.id
    cleanup.run_once()
    with SessionLocal() as db:
        assert db.get(Client, ideen) is not None, "nexsuite says when it is gone"
        assert db.get(Client, "local-client") is None and db.get(Space, local_id) is None, "with its group"


def test_d6_a_blocked_person_is_no_colleague_to_pick(client: TestClient, operator: Account) -> None:
    gone = make_account("gone")
    make_account("mia")
    with SessionLocal() as db:
        db.get(Account, gone.id).blocked_at = utcnow()  # type: ignore[union-attr]
        db.commit()
    with new_client() as mia:
        sign_in(mia, Account(id=_id("mia"), name="mia"))
        assert "gone" not in [p["name"] for p in mia.get("/api/directory").json()["people"]]
    seen = {p["name"]: p for p in client.get("/api/directory").json()["people"]}
    assert seen["gone"]["blocked"] is True, "the operator still sees it, marked"


def test_f5_the_operator_blocks_an_account_alone_too(client: TestClient, operator: Account, space: int) -> None:
    rita = make_account("rita")
    assert client.post(f"/api/accounts/{rita.id}/block", json={"current_password": "wrong"}).status_code == 401
    assert client.post(f"/api/accounts/{operator.id}/block", json={"current_password": PASSWORD}).status_code == 409
    assert client.post(f"/api/accounts/{rita.id}/block", json={"current_password": PASSWORD}).status_code == 204
    with new_client() as stranger:
        # The right password hears that the account is blocked (A16, decided 05.10.2026).
        assert stranger.post("/api/auth/login", json={"name": "rita", "password": PASSWORD}).status_code == 403
    assert client.post(f"/api/accounts/{rita.id}/unblock", json={"current_password": PASSWORD}).status_code == 204
    with SessionLocal() as db:
        assert db.get(Account, rita.id).blocked_at is None  # type: ignore[union-attr]


# --- What the check of 05.10.2026 found missing -----------------------------------------------------------------------


def test_connected_only_the_emergency_account_carries_a_backup_away(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite
) -> None:
    """(A1) The archive holds the emergency account's password hash and second factor with the key: an operator
    coming through nexsuite, never asked for a password here, must not get it (the way A5 closed for passwords)."""
    from app.services import backups

    name = backups.create().name
    connect(client, world, operator)
    fake.people["2"]["operator"] = True
    client.post("/api/suite/sync")
    with new_client() as anna:
        sign_in(anna, world["anna"])
        for answer in (anna.post(f"/api/backups/{name}/download", json={"password": ""}),
                       anna.request("DELETE", f"/api/backups/{name}", json={"password": ""})):
            assert answer.status_code == 403 and answer.json()["detail"]["code"] == "backups_emergency_only", answer.text
    assert client.post(f"/api/backups/{name}/download", json={"password": "wrong"}).status_code == 401
    assert client.post(f"/api/backups/{name}/download", json={"password": PASSWORD}).status_code == 200


def test_d8_the_emergency_account_goes_with_the_person_and_comes_back_on_disconnecting(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite
) -> None:
    """(B1) Deleted in nexsuite, the emergency account is shut as when blocked there; disconnecting lets it in."""
    connect(client, world, operator)
    del fake.people["1"]  # the operator's person deleted in nexsuite
    with SessionLocal() as db:
        suite.sync(db)
    with new_client() as browser:
        refused = browser.post("/api/auth/login", json={"name": "tester", "password": PASSWORD})
        assert refused.status_code == 403 and refused.json()["detail"]["code"] == "account_blocked"
    with SessionLocal() as db:
        _without, blocked, _back = suite.disconnect(db, tell=False)
    assert "tester" not in blocked
    with new_client() as browser:
        assert browser.post("/api/auth/login", json={"name": "tester", "password": PASSWORD}).status_code == 200


def test_d8_blocked_in_nexsuite_the_emergency_account_is_free_again_once_disconnected(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite
) -> None:
    """(B1) Blocked there, then nexsuite disconnects the app: the emergency account is the way in again."""
    connect(client, world, operator)
    fake.people["1"]["blocked"] = True
    with SessionLocal() as db:
        suite.sync(db)
        assert db.get(Account, operator.id).blocked_at is not None  # type: ignore[union-attr]
    body, head = _signed(fake.token, {"revision": 9, "kind": "disconnected"})
    with TestClient(client.app, base_url="http://testserver") as program:
        assert program.post("/api/suite/event", content=body, headers=head).status_code == 204
    with new_client() as browser:
        assert browser.post("/api/auth/login", json={"name": "tester", "password": PASSWORD}).status_code == 200


def test_b2_abort_gives_up_only_a_connection_that_did_not_finish(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite
) -> None:
    connect(client, world, operator)
    other = make_account("second", "operator")
    for who in (client, new_client(other)):
        refused = who.post("/api/suite/abort")
        assert refused.status_code == 409 and refused.json()["detail"]["code"] == "already_connected", refused.text
    with SessionLocal() as db:
        assert suite.connected(db)
    assert ("POST", "/leave") not in fake.calls
    assert client.post("/api/teams", json={"name": "Still kept there"}).status_code == 409


def test_b2_abort_still_gives_up_a_connection_half_way(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite
) -> None:
    assert client.post("/api/suite/start", json={"url": SUITE + "/", "code": "GOOD-CODE-1234"}).status_code == 200
    assert client.post("/api/suite/abort").status_code == 204
    with SessionLocal() as db:
        assert suite.state(db) == ""
    assert ("POST", "/leave") in fake.calls


def test_a11_the_plain_way_needs_nexsuite_and_the_emergency_report_waits_for_it(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite
) -> None:
    """(B3, B4) Out of reach, the plain way is refused; the emergency code's report waits and goes later."""
    fake.emergency = [hashlib.sha256(b"WXYZ23456789").hexdigest()]
    connect(client, world, operator)
    fake.down = True
    refused = client.post("/api/suite/disconnect", json={"current_password": PASSWORD})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "suite_unreachable_disconnect"
    with SessionLocal() as db:
        assert settings_service.get(db, "suite_state") == "connected"
    right = client.post("/api/suite/emergency", json={"current_password": PASSWORD, "code": "WXYZ-2345-6789"})
    assert right.status_code == 200, right.text
    assert fake.reports == []
    fake.down = False
    suite.run_forever_sync()  # the round of the background loop, connected or not
    with SessionLocal() as db:
        assert settings_service.get(db, "suite_owed") is None
    assert fake.reports == [{"kind": "emergency_disconnect", "who": "tester"}], "told once nexsuite is back"


def test_a11_when_nexsuite_forgot_the_app_the_plain_way_works(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite
) -> None:
    connect(client, world, operator)
    fake.known = False
    assert client.post("/api/suite/disconnect", json={"current_password": PASSWORD}).status_code == 200
    with SessionLocal() as db:
        assert settings_service.get(db, "suite_state") == ""


class AtOnce:
    """A thread that runs at once, so a test sees what it did."""

    def __init__(self, target: Any = None, **_: Any) -> None:
        self.target = target

    def start(self) -> None:
        self.target()


def test_a11_an_emergency_sign_in_is_reported(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite, monkeypatch: Any
) -> None:
    import threading

    connect(client, world, operator)
    monkeypatch.setattr(threading, "Thread", AtOnce)
    with new_client() as browser:
        assert browser.post("/api/auth/login", json={"name": "tester", "password": PASSWORD}).status_code == 200
    assert fake.reports == [{"kind": "emergency_sign_in", "who": "tester"}]


def test_a11_the_emergency_sign_in_counts_after_the_second_factor(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite, clock: Any, monkeypatch: Any
) -> None:
    """(B5) The password alone is no sign-in yet: nexsuite hears of it after the second factor."""
    import threading

    secret, _codes = test_totp.enrol(client)
    connect(client, world, operator)
    monkeypatch.setattr(threading, "Thread", AtOnce)
    with new_client() as browser:
        test_totp.password_step(browser)
        assert fake.reports == [], "the password alone is no sign-in yet"
        assert test_totp.code_step(browser, test_totp.fresh_code(secret, clock)).status_code == 200
    assert fake.reports == [{"kind": "emergency_sign_in", "who": "tester"}]


def test_b7_a_matched_address_goes_along(client: TestClient, operator: Account, world: dict, fake: FakeSuite) -> None:
    """(B13) erik here has an address, erik in nexsuite none: it goes there instead of getting lost here."""
    with SessionLocal() as db:
        erik = db.query(Account).filter_by(name="erik").one()
        erik.email = "erik@example.com"
        db.commit()
    connect(client, world, operator)
    assert fake.people["3"]["email"] == "erik@example.com", "matched by name, the address from here goes along"
    assert fake.people["2"]["email"] == "anna@example.com"
    with SessionLocal() as db:
        assert db.query(Account).filter_by(name="erik").one().email == "erik@example.com"


def test_a10_a_notice_is_taken_once_and_a_strange_signature_is_refused(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite
) -> None:
    connect(client, world, operator)
    with TestClient(client.app, base_url="http://testserver") as program:
        body, head = _signed(fake.token, {"revision": 8, "kind": "changed"})
        assert program.post("/api/suite/event", content=body, headers=head).status_code == 204
        assert program.post("/api/suite/event", content=body, headers=head).status_code == 401, "the same notice twice"
        body, head = _signed(fake.token, {"revision": 9, "kind": "changed"})
        head["X-Nexsuite-Signature"] = "\u00e4".encode() * 64  # type: ignore[assignment]
        assert program.post("/api/suite/event", content=body, headers=head).status_code == 401
        body, head = _signed(fake.token, {"revision": 10, "kind": "changed"}, stamp=int(time.time()) + 3600)
        assert program.post("/api/suite/event", content=body, headers=head).status_code == 401, "from the future"
