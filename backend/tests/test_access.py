"""Who has access to a client, invitations by name and by link, and what the sign-in answers (Prüfgang 05.10.2026,
block 3: D4, D5, F4, F22, G4 and the invitation mail)."""

from __future__ import annotations

from datetime import timedelta
from email.message import EmailMessage
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import Account, Invite, Membership, SpaceNotice, utcnow
from app.services import mailer, notices

from . import test_suite
from .conftest import PASSWORD, join, make_account, new_client, new_group
from .test_suite import FakeSuite, connect

fake = test_suite.fake
world = test_suite.world


def _team(client: TestClient, name: str, people: list[Account]) -> int:
    answer = client.post("/api/teams", json={"name": name, "members": [p.id for p in people], "lead": people[0].id})
    assert answer.status_code in (200, 201), answer.text
    return int(answer.json()["id"])


# --- D4: everybody with access sees who has it, with the teams ------------------------------------------------------


def test_readers_and_writers_see_who_has_access_with_the_teams_but_no_invitations(
    client: TestClient, operator: Account
) -> None:
    anna, ben, cleo = make_account("anna"), make_account("ben"), make_account("cleo")
    space = new_group(client, "Studio")
    join(client, space, "anna", "read")
    join(client, space, "ben", "write")
    team = _team(client, "Design", [ben, cleo])
    assert client.put(f"/api/spaces/{space}/teams/{team}", json={"role": "read"}).status_code == 200
    client.post(f"/api/spaces/{space}/invites", json={"role": "read", "email": "new@example.com"})
    make_account("dora")
    assert client.put(f"/api/spaces/{space}/members/dora", json={"role": "read"}).status_code == 202

    own = client.get(f"/api/spaces/{space}/members").json()
    assert [t["name"] for t in own["teams"]] == ["Design"] and own["teams"][0]["people"] == 2
    # tester, anna, ben and cleo (through the team); ben counts once.
    assert own["count"] == 4
    assert len(own["invites"]) == 1 and [a["name"] for a in own["asked"]] == ["dora"]
    for person in (anna, ben):
        with new_client(person) as browser:
            seen = browser.get(f"/api/spaces/{space}/members")
            assert seen.status_code == 200, seen.text
            body = seen.json()
            assert {m["name"] for m in body["members"]} == {"tester", "anna", "ben"}
            assert [t["name"] for t in body["teams"]] == ["Design"] and body["count"] == 4
            assert body["invites"] == [] and body["asked"] == []
            assert browser.put(f"/api/spaces/{space}/members/cleo", json={"role": "read"}).status_code == 403
    # Somebody without access learns nothing, as before.
    with new_client(make_account("erik")) as stranger:
        assert stranger.get(f"/api/spaces/{space}/members").status_code == 404


def test_connected_the_teams_of_a_client_nexsuite_keeps_are_listed(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite
) -> None:
    connect(client, world, operator)
    body = client.get(f"/api/spaces/{world['studio']}/members").json()
    assert body["managed"] is True
    assert [t["name"] for t in body["teams"]] == ["Design"] and body["teams"][0]["role"] == "read"


# --- D5: invitations by name are seen and withdrawn; one link per address -------------------------------------------


def _open_invite(name: str) -> SpaceNotice:
    with SessionLocal() as db:
        person = db.query(Account).filter_by(name=name).one()
        row = db.query(SpaceNotice).filter_by(account_id=person.id, kind="invite", done_at=None).one()
        db.expunge(row)
    return row


def test_a_manager_withdraws_an_invitation_by_name_and_it_cannot_be_accepted_after(
    client: TestClient, operator: Account
) -> None:
    anna = make_account("anna")
    make_account("ben")
    space = new_group(client, "Studio")
    join(client, space, "ben", "read")
    assert client.put(f"/api/spaces/{space}/members/anna", json={"role": "write"}).status_code == 202
    asked = client.get(f"/api/spaces/{space}/members").json()["asked"]
    assert [(a["name"], a["role"]) for a in asked] == [("anna", "write")]
    with new_client(make_account("ben2")) as nobody:
        assert nobody.delete(f"/api/spaces/{space}/asked/{asked[0]['id']}").status_code == 404
    with SessionLocal() as db:
        ben = db.query(Account).filter_by(name="ben").one()
    with new_client(ben) as reader:
        assert reader.delete(f"/api/spaces/{space}/asked/{asked[0]['id']}").status_code == 403
    assert client.delete(f"/api/spaces/{space}/asked/{asked[0]['id']}").status_code == 204
    assert client.get(f"/api/spaces/{space}/members").json()["asked"] == []
    with new_client(anna) as browser:
        assert browser.get("/api/notices").json() == []
        assert browser.post(f"/api/notices/{asked[0]['id']}/accept").status_code == 404
    with SessionLocal() as db:
        assert db.get(Membership, (space, anna.id)) is None
    assert client.delete(f"/api/spaces/{space}/asked/{asked[0]['id']}").status_code == 404


def test_accepting_and_withdrawing_at_the_same_moment_never_both_happen(
    client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The withdrawal lands between the answer's reading and writing: the answer finds nothing (before: a 500, the
    stale row could not be written)."""
    anna = make_account("anna")
    space = new_group(client, "Studio")
    assert client.put(f"/api/spaces/{space}/members/anna", json={"role": "manage"}).status_code == 202
    notice = _open_invite("anna")
    real = notices._own

    def read_then_withdrawn(db: Any, account: Account, notice_id: int) -> SpaceNotice:
        row = real(db, account, notice_id)
        with SessionLocal() as other:
            assert notices.withdraw(other, space, notice_id)
        return row

    monkeypatch.setattr(notices, "_own", read_then_withdrawn)
    with new_client(anna) as browser:
        answer = browser.post(f"/api/notices/{notice.id}/accept")
    assert answer.status_code == 404
    with SessionLocal() as db:
        assert db.get(Membership, (space, anna.id)) is None


def test_withdrawing_after_the_answer_finds_nothing_and_the_right_stays(client: TestClient, operator: Account,
                                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    anna = make_account("anna")
    space = new_group(client, "Studio")
    assert client.put(f"/api/spaces/{space}/members/anna", json={"role": "read"}).status_code == 202
    notice = _open_invite("anna")
    with new_client(anna) as browser:
        assert browser.post(f"/api/notices/{notice.id}/accept").status_code == 200
    assert client.delete(f"/api/spaces/{space}/asked/{notice.id}").status_code == 404
    with SessionLocal() as db:
        assert db.get(Membership, (space, anna.id)) is not None


def test_a_second_invitation_to_the_same_address_replaces_the_first(client: TestClient, operator: Account,
                                                                     space: int) -> None:
    first = client.post(f"/api/spaces/{space}/invites", json={"role": "read", "days": 7, "email": "x@example.com"})
    second = client.post(f"/api/spaces/{space}/invites", json={"role": "manage", "days": 7, "email": "X@example.com"})
    assert first.status_code == 201 and second.status_code == 201
    with SessionLocal() as db:
        assert db.query(Invite).filter_by(space_id=space).count() == 1
    stranger = TestClient(client.app, headers={"X-Nexbrand-Client": "tab-stranger0"})
    old = first.json()["link"].rsplit("/", 1)[1]
    assert stranger.get(f"/api/invite/{old}").json()["detail"]["code"] == "invite_invalid"
    assert stranger.get(f"/api/invite/{second.json()['link'].rsplit('/', 1)[1]}").status_code == 200
    # Into nexbrand without a client the same: one per address, and another place keeps its own.
    elsewhere = new_group(client, "Other")
    client.post("/api/invites", json={"email": "x@example.com"})
    client.post("/api/invites", json={"email": "x@example.com"})
    client.post(f"/api/spaces/{elsewhere}/invites", json={"role": "read", "email": "x@example.com"})
    with SessionLocal() as db:
        assert db.query(Invite).filter(Invite.space_id.is_(None)).count() == 1
        assert db.query(Invite).count() == 3


# --- G4: a link that does not hold says why -------------------------------------------------------------------------


def test_a_link_that_ran_out_says_so_and_a_withdrawn_one_says_it_is_not_valid(client: TestClient,
                                                                              operator: Account) -> None:
    made = client.post("/api/invites", json={}).json()
    token = made["link"].rsplit("/", 1)[1]
    stranger = TestClient(client.app, headers={"X-Nexbrand-Client": "tab-stranger0"})
    with SessionLocal() as db:
        row = db.get(Invite, made["id"])
        assert row is not None
        row.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
    gone = stranger.get(f"/api/invite/{token}")
    assert gone.status_code == 404 and gone.json()["detail"]["code"] == "invite_expired"
    accepted = stranger.post(f"/api/invite/{token}", json={"name": "dora", "password": PASSWORD})
    assert accepted.status_code == 404
    other = client.post("/api/invites", json={}).json()
    assert client.delete(f"/api/invites/{other['id']}").status_code == 204
    withdrawn = stranger.get(f"/api/invite/{other['link'].rsplit('/', 1)[1]}")
    assert withdrawn.status_code == 404 and withdrawn.json()["detail"]["code"] == "invite_invalid"


# --- F4 and F22: the answer of an accepted invitation -------------------------------------------------------------


def test_accepting_an_invitation_answers_with_what_the_account_may_do(client: TestClient, operator: Account) -> None:
    token = client.post("/api/invites", json={}).json()["link"].rsplit("/", 1)[1]
    stranger = TestClient(client.app, headers={"X-Nexbrand-Client": "tab-stranger0"})
    bad = stranger.post(f"/api/invite/{token}", json={"name": "Kim Gross", "password": PASSWORD})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "invalid_account_name"
    made = stranger.post(f"/api/invite/{token}", json={"name": "kim", "password": PASSWORD})
    assert made.status_code == 200
    body = made.json()
    assert body["may_create_clients"] is True and body["suite"] == stranger.get("/api/auth/me").json()["suite"]
    assert body == stranger.get("/api/auth/me").json()


# --- The invitation mail: nexbrand's own words, in the language of whoever gets it ----------------------------------


@pytest.fixture
def sent(client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch) -> list[EmailMessage]:
    mails: list[EmailMessage] = []
    monkeypatch.setattr(mailer, "_send", lambda db, message: mails.append(message))
    assert client.put("/api/settings", json={"smtp_host": "mail.example.com", "smtp_from": "brand@example.com",
                                             "public_url": "https://brand.example.com"}).status_code == 200
    return mails


def test_the_invitation_mail_speaks_of_clients_in_the_inviters_language(client: TestClient, operator: Account,
                                                                        sent: list[EmailMessage]) -> None:
    space = new_group(client, "Bäckerei Morgenrot")
    assert client.put("/api/me/language", json={"language": "de"}).status_code in (200, 204)
    made = client.post(f"/api/spaces/{space}/invites",
                       json={"role": "read", "email": "neu@example.com", "send": True, "days": 7})
    assert made.status_code == 201 and made.json()["sent"] is True
    text = sent[-1].get_content()
    assert sent[-1]["Subject"] == "tester lädt dich zu nexbrand ein"
    assert "zum Kunden „Bäckerei Morgenrot“" in text and made.json()["link"] in text
    until = utcnow() + timedelta(days=7)
    assert until.strftime("%d.%m.%Y") in text or (until - timedelta(days=1)).strftime("%d.%m.%Y") in text
    assert "notes" not in text and "space" not in text


def test_the_invitation_mail_follows_the_receivers_own_language_first(client: TestClient, operator: Account,
                                                                      sent: list[EmailMessage]) -> None:
    known = make_account("lena")
    with SessionLocal() as db:
        row = db.get(Account, known.id)
        assert row is not None
        row.email, row.language = "lena@example.com", "en"
        db.commit()
    client.put("/api/me/language", json={"language": "de"})
    assert client.post("/api/invites", json={"email": "Lena@example.com", "send": True}).status_code == 201
    assert sent[-1]["Subject"] == "tester invites you to nexbrand"
    assert "invites you to nexbrand. nexbrand keeps the corporate design" in sent[-1].get_content()
    # Neither account says a language: the one the page was in, then English.
    client.put("/api/me/language", json={"language": ""})
    client.post("/api/invites", json={"email": "a@example.com", "send": True, "language": "de-AT"})
    assert sent[-1]["Subject"] == "tester lädt dich zu nexbrand ein"
    client.post("/api/invites", json={"email": "b@example.com", "send": True, "language": "fr"})
    assert sent[-1]["Subject"] == "tester invites you to nexbrand"


# --- A5: behind a proxy nobody named, a stranger's guesses do not keep the known browsers out ------------------------


def _browser(host: str = "172.18.0.2") -> TestClient:
    from app.main import app

    return TestClient(app, base_url="http://testserver", headers={"X-Nexbrand-Client": "tab-proxy00001"},
                      client=(host, 50000))


def _spray(count: int = 31) -> list[int]:
    stranger = _browser()
    return [stranger.post("/api/auth/login", json={"name": f"guess{n}", "password": "summer2026"},
                          headers={"X-Forwarded-For": f"198.51.100.{n}"}).status_code for n in range(count)]


def test_the_emergency_account_gets_in_from_its_browser_while_a_stranger_guesses(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite
) -> None:
    from app.security import DEVICE_COOKIE, brake, device_token

    connect(client, world, operator)
    own = _browser()
    assert own.post("/api/auth/login", json={"name": "tester", "password": PASSWORD}).status_code == 200
    assert own.cookies.get(DEVICE_COOKIE)
    own.post("/api/auth/logout")
    assert 429 in _spray()
    # The emergency account, from the browser it signed in with before: in.
    assert own.post("/api/auth/login", json={"name": "tester", "password": PASSWORD},
                    headers={"X-Forwarded-For": "203.0.113.9"}).status_code == 200
    # Without that browser, with a made-up cookie or with one given to another name: the sender waits.
    assert _browser().post("/api/auth/login", json={"name": "tester", "password": PASSWORD}).status_code == 429
    forged = _browser()
    forged.cookies.set(DEVICE_COOKIE, f"{operator.id}.abc." + "0f" * 16, path="/api/auth")
    assert forged.post("/api/auth/login", json={"name": "tester", "password": PASSWORD}).status_code == 429
    other = _browser()
    with SessionLocal() as db:
        anna = db.get(Account, world["anna"].id)
        assert anna is not None
        other.cookies.set(DEVICE_COOKIE, device_token(db, anna), path="/api/auth")
    assert other.post("/api/auth/login", json={"name": "tester", "password": PASSWORD}).status_code == 429
    brake.forget()


def test_the_operator_hears_of_a_proxy_nobody_named(client: TestClient, operator: Account,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    from app import deps
    from app.config import get_settings

    monkeypatch.setattr(deps, "_warned_unknown_proxy", False)
    assert client.get("/api/settings").json()["proxy_unknown"] is False
    assert client.get("/api/settings", headers={"X-Real-IP": "198.51.100.4"}).json()["proxy_unknown"] is True
    # Remembered for the next visit without the header, and gone once the proxy is named.
    assert client.get("/api/settings").json()["proxy_unknown"] is True
    monkeypatch.setattr(get_settings(), "trusted_proxies", "172.16.0.0/12")
    assert client.get("/api/settings", headers={"X-Forwarded-For": "198.51.100.4"}).json()["proxy_unknown"] is False


# --- D5: a failed mail keeps the invitation it was to replace; old invitations by name drop off ----------------------


def test_a_replacement_whose_mail_fails_keeps_the_invitation_before(client: TestClient, operator: Account,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    space = new_group(client, "Studio")
    first = client.post(f"/api/spaces/{space}/invites", json={"role": "read", "email": "x@example.com"})
    assert first.status_code == 201
    assert client.put("/api/settings", json={"smtp_host": "mail.example.com", "smtp_from": "brand@example.com",
                                             "public_url": "https://brand.example.com"}).status_code == 200

    def refuse(db: Any, message: EmailMessage) -> None:
        raise mailer.MailError("mail_failed", "The mail server did not take the mail.")

    monkeypatch.setattr(mailer, "_send", refuse)
    failed = client.post(f"/api/spaces/{space}/invites", json={"role": "write", "email": "x@example.com", "send": True})
    assert failed.status_code == 502
    with SessionLocal() as db:
        assert [row.space_role for row in db.query(Invite).filter_by(space_id=space)] == ["read"]
    stranger = TestClient(client.app, headers={"X-Nexbrand-Client": "tab-stranger0"})
    assert stranger.get(f"/api/invite/{first.json()['link'].rsplit('/', 1)[1]}").status_code == 200


def test_invitations_by_name_too_old_to_accept_are_not_listed(client: TestClient, operator: Account) -> None:
    make_account("anna")
    space = new_group(client, "Studio")
    assert client.put(f"/api/spaces/{space}/members/anna", json={"role": "read"}).status_code == 202
    assert len(client.get(f"/api/spaces/{space}/members").json()["asked"]) == 1
    with SessionLocal() as db:
        row = db.query(SpaceNotice).filter_by(space_id=space, kind="invite").one()
        row.created_at = utcnow() - timedelta(days=notices.INVITE_DAYS, minutes=1)
        db.commit()
    assert client.get(f"/api/spaces/{space}/members").json()["asked"] == []


def test_the_number_on_access_is_the_people_the_dialog_counts(client: TestClient, operator: Account) -> None:
    anna, ben, cleo = make_account("anna"), make_account("ben"), make_account("cleo")
    space = new_group(client, "Studio")
    join(client, space, "anna", "read")
    team = _team(client, "Design", [anna, ben, cleo])
    client.put(f"/api/spaces/{space}/teams/{team}", json={"role": "read"})
    listed = next(s for s in client.get("/api/spaces").json() if s["id"] == space)
    # tester and anna by name, ben and cleo through the team (anna counts once): four, not three entries.
    assert listed["people"] == client.get(f"/api/spaces/{space}/members").json()["count"] == 4


# --- The device cookie holds only for the account and the state it was given for --------------------------------------

NEW_PASSWORD = "another long password"


def _known(name: str, password: str = PASSWORD) -> TestClient:
    """A browser that signed in as ``name`` (and so holds its device cookie), signed out again."""
    from app.security import DEVICE_COOKIE, brake

    brake.forget()
    browser = _browser()
    assert browser.post("/api/auth/login", json={"name": name, "password": password}).status_code == 200
    assert browser.cookies.get(DEVICE_COOKIE)
    browser.post("/api/auth/logout")
    return browser


def _sign_in(browser: TestClient, name: str) -> None:
    from app.security import brake

    brake.forget()
    assert browser.post("/api/auth/login", json={"name": name, "password": PASSWORD}).status_code == 200


def _passes(browser: TestClient, name: str, password: str = PASSWORD) -> int:
    """After a stranger's guesses from the same address: in (200), or waiting like everybody (429)."""
    from app.security import brake

    brake.forget()
    assert 429 in _spray()
    return browser.post("/api/auth/login", json={"name": name, "password": password}).status_code


def test_a_device_cookie_from_before_a_new_password_counts_no_more(client: TestClient, operator: Account) -> None:
    make_account("anna")
    old = _known("anna")
    assert _passes(old, "anna") == 200
    old.post("/api/auth/logout")
    changer = _browser()
    _sign_in(changer, "anna")
    assert changer.put("/api/auth/password", json={"current": PASSWORD, "new": NEW_PASSWORD}).status_code == 204
    changer.post("/api/auth/logout")
    assert _passes(old, "anna", NEW_PASSWORD) == 429
    # The browser that changed it stays known.
    assert _passes(changer, "anna", NEW_PASSWORD) == 200


def test_a_device_cookie_from_before_a_new_password_does_not_open_the_lock(client: TestClient,
                                                                           operator: Account) -> None:
    from app.services.accounts import MAX_FAILURES

    make_account("anna")
    old = _known("anna")
    changer = _browser()
    _sign_in(changer, "anna")
    changer.put("/api/auth/password", json={"current": PASSWORD, "new": NEW_PASSWORD})
    with SessionLocal() as db:
        row = db.query(Account).filter_by(name="anna").one()
        row.failed_logins, row.locked_until = MAX_FAILURES, utcnow() + timedelta(minutes=10)
        db.commit()
    assert old.post("/api/auth/login", json={"name": "anna", "password": NEW_PASSWORD}).status_code == 401


def test_a_new_account_under_the_id_of_a_deleted_one_knows_none_of_its_browsers(client: TestClient,
                                                                                operator: Account) -> None:
    gone = make_account("zoe")
    browser = _known("zoe")
    deleted = client.request("DELETE", f"/api/accounts/{gone.id}", json={"current_password": PASSWORD})
    assert deleted.status_code == 204
    after = make_account("zora")
    assert after.id == gone.id, "SQLite gives the id of the deleted last account again"
    assert _passes(browser, "zora") == 429


def test_blocking_unblocking_and_signing_out_everywhere_forget_the_browsers(client: TestClient,
                                                                           operator: Account) -> None:
    anna = make_account("anna")
    browser = _known("anna")
    for path in ("block", "unblock"):
        assert client.post(f"/api/accounts/{anna.id}/{path}", json={"current_password": PASSWORD}).status_code == 204
    assert _passes(browser, "anna") == 429
    browser = _known("anna")
    assert client.post(f"/api/accounts/{anna.id}/sign-out").status_code == 204
    assert _passes(browser, "anna") == 429
    # Signing out the others from one browser: the others are forgotten, this one stays known.
    other, keeper = _known("anna"), _browser()
    _sign_in(keeper, "anna")
    assert keeper.post("/api/auth/logout-all").status_code == 204
    keeper.post("/api/auth/logout")
    assert _passes(other, "anna") == 429
    assert _passes(keeper, "anna") == 200


def test_any_way_a_password_or_block_changes_forgets_the_browsers(client: TestClient, operator: Account) -> None:
    """Also where no session is ended on the way (a block from nexsuite, a password set by a service)."""
    from app.security import hash_password

    make_account("anna")
    for change in ("password", "block"):
        browser = _known("anna")
        with SessionLocal() as db:
            row = db.query(Account).filter_by(name="anna").one()
            if change == "password":
                row.password_hash = hash_password(PASSWORD)
            else:
                row.blocked_at = utcnow()
                db.commit()
                row.blocked_at = None
            db.commit()
        assert _passes(browser, "anna") == 429, change
