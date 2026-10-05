"""What was decided after the check of 05.10.2026 (nexsuite/tools/pruefgang-2026-10-05/ENTSCHEIDUNGEN.md, the
numbers of LISTE.md in brackets).

* A team lead changes the team only when the operator allows it; off from the start (D3).
* The links of a blocked or deleted person stay; the operator sees how many and withdraws them all at once (A15).
* A blocked account hears that it is blocked, but only after the right password (A16).
* Connected, the sign-in page can lead to nexsuite to sign in as someone else (B11).
* An operator role that came from nexsuite only goes when disconnecting; the dialog names who loses it (B17).
* Mail goes out in the language of whoever receives it, the test mail too.
"""

from __future__ import annotations

from email.message import EmailMessage
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import Account, Review, Share, TeamMember
from app.security import Brake
from app.services import mailer, settings_service

from . import test_suite
from .conftest import PASSWORD, join, make_account, new_client
from .test_brands import SET, make_client
from .test_suite import FakeSuite, connect

fake = test_suite.fake
world = test_suite.world


def _row(name: str) -> Account:
    with SessionLocal() as db:
        row = db.query(Account).filter_by(name=name).one()
        db.expunge(row)
    return row


def _set(**values: Any) -> None:
    with SessionLocal() as db:
        settings_service.save(db, values)
        db.commit()


# --- D3: a team lead changes the team only when the operator allows it ---------------------------------------------


def test_d3_a_team_lead_changes_the_members_only_when_the_operator_allows_it(
    client: TestClient, operator: Account, world: dict
) -> None:
    cleo, team = world["cleo"], world["team"]
    assert client.get("/api/settings").json()["team_leads_edit"] is False, "off from the start"
    with new_client(world["anna"]) as anna:
        assert anna.get("/api/auth/me").json()["may_edit_led_teams"] is False
        members = anna.get("/api/directory").json()["teams"][0]["members"]
        refused = anna.patch(f"/api/teams/{team}", json={"members": [*members, cleo.id]})
        assert refused.status_code == 403 and refused.json()["detail"]["code"] == "team_leads_off"
        with SessionLocal() as db:
            assert db.get(TeamMember, (team, cleo.id)) is None
        assert client.put("/api/settings", json={"team_leads_edit": True}).json()["team_leads_edit"] is True
        assert anna.get("/api/auth/me").json()["may_edit_led_teams"] is True
        assert anna.patch(f"/api/teams/{team}", json={"members": [*members, cleo.id]}).status_code == 200
        # Still the members only: name, colour and lead stay the operator's.
        assert anna.patch(f"/api/teams/{team}", json={"name": "Mine"}).status_code == 403
    with new_client(world["ben"]) as ben:
        # Ben is in the team, but not its lead.
        refused = ben.patch(f"/api/teams/{team}", json={"members": [world["ben"].id]})
        assert refused.status_code == 403 and refused.json()["detail"]["code"] == "forbidden"
    # The operator changes every team, switch or not.
    assert client.put("/api/settings", json={"team_leads_edit": False}).status_code == 200
    assert client.patch(f"/api/teams/{team}", json={"members": [world["anna"].id]}).status_code == 200
    with new_client(world["anna"]) as anna:
        assert anna.get("/api/settings").status_code == 403, "the switch is the operator's"
        assert anna.put("/api/settings", json={"team_leads_edit": True}).status_code == 403


def test_d3_connected_the_teams_and_the_switch_are_nexsuite_s(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite
) -> None:
    connect(client, world, operator)
    team = client.get("/api/directory").json()["teams"][0]
    with SessionLocal() as db:
        settings_service.save(db, {"team_leads_edit": True})
        db.commit()
    with new_client(_row("anna")) as anna:
        assert anna.get("/api/auth/me").json()["may_edit_led_teams"] is False, "nexsuite keeps the teams"
        assert anna.patch(f"/api/teams/{team['id']}", json={"members": []}).status_code == 409
    refused = client.put("/api/settings", json={"team_leads_edit": False})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "managed_by_suite"


# --- A16: blocked, said only after the right password ---------------------------------------------------------------


def _login(browser: TestClient, name: str, password: str) -> Any:
    return browser.post("/api/auth/login", json={"name": name, "password": password})


def test_a16_a_blocked_account_hears_it_only_after_the_right_password(client: TestClient, operator: Account) -> None:
    make_account("dora")
    assert client.post(f"/api/accounts/{_row('dora').id}/block", json={"current_password": PASSWORD}).status_code == 204
    with new_client() as browser:
        wrong = _login(browser, "dora", "not the password")
        assert wrong.status_code == 401 and wrong.json()["detail"]["code"] == "wrong_credentials"
        right = _login(browser, "dora", PASSWORD)
        assert right.status_code == 403 and right.json()["detail"]["code"] == "account_blocked"
        assert browser.get("/api/auth/me").status_code == 401, "no session for a blocked account"
        # An unknown name answers like a wrong password, whatever the password.
        assert _login(browser, "nobody", PASSWORD).json()["detail"]["code"] == "wrong_credentials"


def test_a16_the_right_password_of_a_blocked_account_still_counts_for_the_brake(
    client: TestClient, operator: Account
) -> None:
    make_account("dora")
    client.post(f"/api/accounts/{_row('dora').id}/block", json={"current_password": PASSWORD})
    with new_client() as browser:
        codes = [_login(browser, "dora", PASSWORD).status_code for _ in range(Brake.FREE + 1)]
    assert codes[: Brake.FREE] == [403] * Brake.FREE and codes[-1] == 429, codes


def test_a16_the_emergency_way_says_blocked_too(client: TestClient, operator: Account, world: dict,
                                                fake: FakeSuite) -> None:
    connect(client, world, operator)
    # The person of the emergency account is deleted in nexsuite: the account is blocked here (D8).
    del fake.people["1"]
    client.post("/api/suite/sync")
    with new_client() as browser:
        assert _login(browser, "tester", "wrong").json()["detail"]["code"] == "wrong_credentials"
        answer = _login(browser, "tester", PASSWORD)
        assert answer.status_code == 403 and answer.json()["detail"]["code"] == "account_blocked"


# --- A15: the links of a blocked or deleted person ------------------------------------------------------------------


def _links_of(client: TestClient, space: int, maker: Account) -> tuple[str, str, str]:
    """A published client with a public page and an open review, both made by ``maker``."""
    _set(shares_allowed=True)
    made = make_client(client, space)
    cid, vid = made["id"], made["versions"][0]["id"]
    assert client.post(f"/api/clients/{cid}/versions/{vid}/publish", json={"label": "2026"}).status_code == 200
    draft = client.post(f"/api/clients/{cid}/versions", json={"label": "B", "data": SET}).json()["id"]
    with new_client(maker) as browser:
        share = browser.post(f"/api/clients/{cid}/shares", json={"label": "Printer"})
        review = browser.post(f"/api/clients/{cid}/reviews", json={
            "version_id": draft, "label": "2.0", "variants": [{"id": "a", "label": "Calm", "data": SET}]})
        assert share.status_code == 201 and review.status_code == 201, (share.text, review.text)
    return cid, share.json()["link"].rsplit("/", 1)[1], review.json()["link"].rsplit("/", 1)[1]


def _open_links(client: TestClient, name: str) -> int:
    return next(row["open_links"] for row in client.get("/api/accounts").json() if row["name"] == name)


def test_a15_the_links_stay_and_the_operator_withdraws_them_with_the_password(
    client: TestClient, operator: Account, space: int
) -> None:
    wim = make_account("wim")
    join(client, space, "wim", "write")
    _cid, page, review = _links_of(client, space, wim)
    assert _open_links(client, "wim") == 2
    assert _open_links(client, "tester") == 0
    assert client.post(f"/api/accounts/{wim.id}/block", json={"current_password": PASSWORD}).status_code == 204
    with new_client() as visitor:
        assert visitor.get(f"/api/public/{page}").status_code == 200, "the links stay (decided 05.10.2026)"
        assert visitor.get(f"/api/review/{review}").status_code == 200
    wrong = client.post(f"/api/accounts/{wim.id}/links/withdraw", json={"current_password": "wrong"})
    assert wrong.status_code == 401
    assert _open_links(client, "wim") == 2
    done = client.post(f"/api/accounts/{wim.id}/links/withdraw", json={"current_password": PASSWORD})
    assert done.status_code == 200 and done.json() == {"withdrawn": 2}
    with new_client() as visitor:
        assert visitor.get(f"/api/public/{page}").status_code == 404
        assert visitor.get(f"/api/review/{review}").status_code == 404
    with SessionLocal() as db:
        assert db.query(Share).count() == 0
        assert [r.status for r in db.query(Review)] == ["closed"]
    assert _open_links(client, "wim") == 0
    with new_client(make_account("mia")) as member:
        assert member.post(f"/api/accounts/{wim.id}/links/withdraw", json={}).status_code == 403


def test_a15_deleting_an_account_leaves_its_links_and_only_open_ones_count(
    client: TestClient, operator: Account, space: int
) -> None:
    wim = make_account("wim")
    join(client, space, "wim", "write")
    _cid, page, _review = _links_of(client, space, wim)
    with SessionLocal() as db:
        # A review the client decided on is no open link any more.
        db.query(Review).update({"status": "chosen"})
        db.commit()
    assert _open_links(client, "wim") == 1
    assert client.request("DELETE", f"/api/accounts/{wim.id}", json={"current_password": PASSWORD}).status_code == 204
    with new_client() as visitor:
        assert visitor.get(f"/api/public/{page}").status_code == 200


def test_a15_connected_the_links_of_a_person_blocked_in_nexsuite_are_withdrawn_here(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite
) -> None:
    _links_of(client, world["studio"], world["anna"])
    connect(client, world, operator)
    anna = _row("anna")
    fake.people["2"]["blocked"] = True
    client.post("/api/suite/sync")
    assert _open_links(client, "anna") == 2
    done = client.post(f"/api/accounts/{anna.id}/links/withdraw", json={"current_password": PASSWORD})
    assert done.status_code == 200 and done.json() == {"withdrawn": 2}


# --- B11: connected, signing in as someone else goes through nexsuite -----------------------------------------------


def test_b11_the_sign_in_page_learns_where_nexsuite_is_only_while_connected(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite
) -> None:
    with new_client() as visitor:
        assert visitor.get("/api/auth/methods").json()["suite_url"] == ""
    connect(client, world, operator)
    with new_client() as visitor:
        methods = visitor.get("/api/auth/methods").json()
        assert methods["suite"] is True and methods["suite_url"] == test_suite.SUITE


# --- B17: an operator role from nexsuite only goes with the connection ----------------------------------------------


def test_b17_an_operator_role_only_nexsuite_gave_goes_back_when_disconnecting(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite
) -> None:
    make_account("olga", "operator")
    fake.people["2"]["operator"] = True
    fake.people["70"] = {"id": "70", "name": "fritz", "display_name": "Fritz", "email": "", "operator": True,
                         "blocked": False}
    fake.people["71"] = {"id": "71", "name": "olga", "display_name": "Olga", "email": "", "operator": True,
                         "blocked": False}
    connect(client, world, operator)
    assert _row("anna").role == "operator" and _row("fritz").role == "operator"
    assert client.get("/api/suite").json()["operators_from_suite"] == ["anna", "fritz"]
    with new_client(_row("ben")) as ben:
        assert "operators_from_suite" not in ben.get("/api/suite").json(), "for the operator only"
    answer = client.post("/api/suite/disconnect", json={"current_password": PASSWORD})
    assert answer.status_code == 200, answer.text
    assert answer.json()["operators_back"] == ["anna", "fritz"]
    assert _row("anna").role == "member", "a member before connecting"
    assert _row("fritz").role == "member", "made while connected: never an operator here"
    assert _row("olga").role == "operator", "an operator before stays one"
    assert _row("tester").role == "operator"


def test_b17_the_same_with_an_emergency_code_or_when_nexsuite_lets_go(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite
) -> None:
    fake.people["2"]["operator"] = True
    connect(client, world, operator)
    from app.services import suite

    with SessionLocal() as db:
        suite.disconnect(db, tell=False)
    assert _row("anna").role == "member"


def test_b17_a_connection_from_before_the_roles_were_kept_changes_no_role(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite
) -> None:
    fake.people["2"]["operator"] = True
    connect(client, world, operator)
    with SessionLocal() as db:
        saved = dict(settings_service.get(db, "suite_saved") or {})
        saved.pop("roles", None)
        settings_service.save(db, {"suite_saved": saved})
        db.commit()
    assert client.get("/api/suite").json()["operators_from_suite"] == []
    client.post("/api/suite/disconnect", json={"current_password": PASSWORD})
    assert _row("anna").role == "operator", "nobody knows what it was before: left as it is"


# --- Mail in the language of whoever receives it --------------------------------------------------------------------


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[EmailMessage]:
    mails: list[EmailMessage] = []
    monkeypatch.setattr(mailer, "_send", lambda db, message: mails.append(message))
    return mails


def test_the_test_mail_speaks_the_language_of_whoever_receives_it(
    client: TestClient, operator: Account, sent: list[EmailMessage]
) -> None:
    dora = make_account("dora")
    with SessionLocal() as db:
        row = db.get(Account, dora.id)
        assert row is not None
        row.email, row.language = "dora@example.com", "de"
        db.get(Account, operator.id).language = "en"  # type: ignore[union-attr]
        db.commit()
    assert client.post("/api/settings/mail-test", json={"to": "DORA@example.com", "language": "en"}).status_code == 204
    assert "Testmail" in str(sent[-1]["Subject"]) and "funktioniert" in sent[-1].get_content()
    # Nobody has the address: the operator's own language, then the page's.
    assert client.post("/api/settings/mail-test", json={"to": "x@example.com", "language": "de"}).status_code == 204
    assert str(sent[-1]["Subject"]) == "nexbrand test mail"
    with SessionLocal() as db:
        db.get(Account, operator.id).language = ""  # type: ignore[union-attr]
        db.commit()
    assert client.post("/api/settings/mail-test", json={"to": "x@example.com", "language": "de"}).status_code == 204
    assert "Testmail" in str(sent[-1]["Subject"])
    assert client.post("/api/settings/mail-test", json={"to": "x@example.com"}).status_code == 204
    assert str(sent[-1]["Subject"]) == "nexbrand test mail"
