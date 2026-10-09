"""Connecting to nexsuite that fails at its last step, or whose answer gets lost (nexcanvas review of ba44488, 4f54522,
e709c94): nothing here changes before nexsuite confirms ``/finish``, giving up leaves nothing half connected, a
finish nexsuite took finishes with the next try, and the choices that went out with it hold.

nexsuite is played by ``FakeSuite`` from ``test_suite``.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import OPERATOR, Account, Space, Team
from app.services import settings_service, suite

from . import test_suite
from .conftest import PASSWORD, client_of, make_account, new_client
from .test_suite import SUITE, FakeSuite, _row, _setting, connect

fake = test_suite.fake
world = test_suite.world


def _code(answer: Any) -> str:
    return str(answer.json()["detail"]["code"])


def _snapshot() -> tuple[dict[str, tuple[Any, ...]], dict[int, tuple[str, str]], dict[int, str]]:
    """What connecting changes here: each account's subjects, mark, block and way in; teams; the clients' groups."""
    with SessionLocal() as db:
        return ({row.name: (row.oidc_subject, row.own_subject, row.suite_person, row.blocked_at is None,
                            row.sign_in) for row in db.query(Account)},
                {team.id: (team.source, team.external_id) for team in db.query(Team)},
                {space.id: space.external_id for space in db.query(Space)})


def _choices(client: TestClient, world: dict) -> dict[str, Any]:
    answer = client.post("/api/suite/start", json={"url": SUITE, "code": "GOOD-CODE-1234"})
    assert answer.status_code == 200, answer.text
    found = answer.json()
    accounts = {a["id"]: a["suggest"] for a in found["accounts"]}
    accounts[world["cleo"].id] = "skip"
    return {"accounts": accounts, "clients": {c["id"]: c["suggest"] for c in found["clients"]}}


def _again(client: TestClient) -> dict[str, dict[str, Any]]:
    """Connecting again to the same nexsuite: the rows of the accounts by name."""
    started = client.post("/api/suite/start", json={"url": SUITE, "code": "GOOD-CODE-1234"})
    assert started.status_code == 200, started.text
    return {a["name"]: a for a in started.json()["accounts"]}


def _lose_finish_once(fake: FakeSuite, monkeypatch: pytest.MonkeyPatch) -> None:
    """nexsuite takes /finish, the answer never comes back (once)."""
    real = fake.handle
    lost = {"once": True}

    def losing(method: str, url: str, **kwargs: Any) -> Any:
        answer = real(method, url, **kwargs)
        if url.endswith("/api/connect/v1/finish") and lost.pop("once", False):
            raise suite.SuiteError("suite_unreachable", "nexsuite cannot be reached.")
        return answer

    monkeypatch.setattr(suite, "request", losing)


def _connected_here(world: dict) -> None:
    assert _setting("suite_state") == "connected" and _setting("suite_pending") is None
    assert _row("anna").oidc_subject == "2" and _row("cleo").blocked_at is not None
    with SessionLocal() as db:
        team = db.get(Team, world["team"])
        studio = db.get(Space, world["studio"])
        ideen = db.get(Space, world["ideen"])
        assert team is not None and team.source == "admin" and team.external_id
        assert studio is not None and studio.external_id
        assert ideen is not None and ideen.external_id == "10"


# --- nothing here before nexsuite confirms ----------------------------------------------------------------------------


def test_finish_failing_at_its_last_step_changes_nothing_here_and_abort_leaves_it_so(
        client: TestClient, operator: Account, world: dict, fake: FakeSuite) -> None:
    with SessionLocal() as db:  # cleo signed in through authentik before
        db.get(Account, world["cleo"].id).oidc_subject = "authentik-hash-of-cleo"  # type: ignore[union-attr]
        db.commit()
    before = _snapshot()
    chosen = _choices(client, world)
    fake.fail_on = "/finish"
    answer = client.post("/api/suite/finish", json=chosen)
    assert answer.status_code in (409, 502) and _code(answer) == "suite_unreachable", answer.text
    assert _setting("suite_state") == "connecting"
    assert _snapshot() == before, "nothing here changes before nexsuite has the connection, the clients neither"
    assert client.post("/api/suite/abort").status_code == 204
    assert _setting("suite_state") == ""
    assert _snapshot() == before, "given up, everything is as before connecting"
    cleo = _row("cleo")
    assert (cleo.oidc_subject, cleo.own_subject, cleo.blocked_at) == ("authentik-hash-of-cleo", "", None)


def test_finish_again_after_a_failed_last_step_connects_once(client: TestClient, operator: Account, world: dict,
                                                           fake: FakeSuite) -> None:
    chosen = _choices(client, world)
    fake.fail_on = "/finish"
    assert client.post("/api/suite/finish", json=chosen).status_code in (409, 502)
    people, teams, clients = len(fake.people), len(fake.teams), len(fake.clients)
    done = client.post("/api/suite/finish", json=chosen)
    assert done.status_code == 200, done.text
    _connected_here(world)
    assert (len(fake.people), len(fake.teams), len(fake.clients)) == (people, teams, clients), \
        "what was made before is used, not made again"
    assert len([c for c in fake.clients.values() if c["name"] == "Studio"]) == 1


def test_abort_in_another_tab_waits_for_a_finish_under_way(client: TestClient, operator: Account, world: dict,
                                                           fake: FakeSuite, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tab 1 connects and nexsuite is slow to confirm; tab 2 gives up meanwhile. The give-up waits for the finish and
    then finds the connection done (409), instead of forgetting it half way."""
    chosen = _choices(client, world)
    reached, go = threading.Event(), threading.Event()
    real = fake.handle

    def slow(method: str, url: str, **kwargs: Any) -> Any:
        if url.endswith("/api/connect/v1/finish"):
            reached.set()
            assert go.wait(10)
        return real(method, url, **kwargs)

    monkeypatch.setattr(suite, "request", slow)
    results: dict[str, int] = {}

    def finishing() -> None:
        results["finish"] = client.post("/api/suite/finish", json=chosen).status_code

    def aborting() -> None:
        results["abort"] = client.post("/api/suite/abort").status_code

    first = threading.Thread(target=finishing)
    first.start()
    assert reached.wait(10), "the finish reaches nexsuite"
    second = threading.Thread(target=aborting)
    second.start()
    second.join(0.5)
    go.set()
    first.join(20)
    second.join(20)
    assert results == {"finish": 200, "abort": 409}
    assert _setting("suite_state") == "connected" and _setting("suite_url") == SUITE and _setting("suite_token_enc")
    assert ("POST", "/leave") not in fake.calls


# --- a /finish nexsuite took, the answer lost ---------------------------------------------------------------------


def test_finish_whose_answer_got_lost_finishes_with_the_next_try(client: TestClient, operator: Account, world: dict,
                                                                fake: FakeSuite, monkeypatch: pytest.MonkeyPatch) -> None:
    """nexsuite took /finish, the answer never came. The next try sends only /finish again; nexsuite's
    already_connected (asked with this app's token) is the confirmation."""
    chosen = _choices(client, world)
    _lose_finish_once(fake, monkeypatch)
    failed = client.post("/api/suite/finish", json=chosen)
    assert failed.status_code in (409, 502) and _code(failed) == "suite_unreachable"
    assert fake.connected and _setting("suite_state") == "connecting"
    people, teams, clients = len(fake.people), len(fake.teams), len(fake.clients)
    calls = len(fake.calls)
    done = client.post("/api/suite/finish", json=chosen)
    assert done.status_code == 200, done.text
    _connected_here(world)
    again = [call for call in fake.calls[calls:] if call[0] == "POST" and call[1] != "/finish"]
    assert again == [], "nothing but /finish is sent again"
    assert (len(fake.people), len(fake.teams), len(fake.clients)) == (people, teams, clients)


def test_finish_whose_local_commit_failed_finishes_with_the_next_try(client: TestClient, operator: Account,
                                                                   world: dict, fake: FakeSuite,
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    """nexsuite confirmed /finish, then writing it here failed (a full disk, a lock): nothing here changed, and the
    next try writes it."""
    chosen = _choices(client, world)
    real = settings_service.save
    broken = {"once": True}

    def failing(db: Any, changes: dict[str, Any]) -> None:
        if changes.get("suite_state") == "connected" and broken.pop("once", False):
            raise RuntimeError("the disk is full")
        real(db, changes)

    monkeypatch.setattr(settings_service, "save", failing)
    with TestClient(client.app, base_url="http://testserver", headers=dict(client.headers),
                    raise_server_exceptions=False, cookies=client.cookies) as same:
        assert same.post("/api/suite/finish", json=chosen).status_code == 500
    assert fake.connected and _setting("suite_state") == "connecting"
    assert _row("anna").oidc_subject == "" and _row("cleo").blocked_at is None, "nothing written here"
    with SessionLocal() as db:
        assert db.get(Space, world["studio"]).external_id == ""  # type: ignore[union-attr]
    done = client.post("/api/suite/finish", json=chosen)
    assert done.status_code == 200, done.text
    _connected_here(world)


def test_finish_sent_and_given_up_tells_nexsuite_to_forget(client: TestClient, operator: Account, world: dict,
                                                           fake: FakeSuite, monkeypatch: pytest.MonkeyPatch) -> None:
    chosen = _choices(client, world)
    real = fake.handle

    def losing(method: str, url: str, **kwargs: Any) -> Any:
        answer = real(method, url, **kwargs)
        if url.endswith("/api/connect/v1/finish"):
            raise suite.SuiteError("suite_unreachable", "nexsuite cannot be reached.")
        return answer

    monkeypatch.setattr(suite, "request", losing)
    assert client.post("/api/suite/finish", json=chosen).status_code in (409, 502)
    assert client.post("/api/suite/abort").status_code == 204
    assert ("POST", "/leave") in fake.calls and not fake.connected
    assert _setting("suite_state") == "" and _row("anna").oidc_subject == ""
    with SessionLocal() as db:
        assert db.get(Space, world["studio"]).external_id == ""  # type: ignore[union-attr]


def test_the_proposal_says_when_something_was_made_in_nexsuite_already(client: TestClient, operator: Account,
                                                                       world: dict, fake: FakeSuite) -> None:
    chosen = _choices(client, world)
    assert client.get("/api/suite/proposal").json()["made"] == 0
    fake.fail_on = "/clients"
    assert client.post("/api/suite/finish", json=chosen).status_code in (409, 502)
    assert client.get("/api/suite/proposal").json()["made"] == 2, "ben as a person and the team Design"


# --- once /finish went out, its choices hold ----------------------------------------------------------------------


def test_after_finish_went_out_other_choices_are_refused_not_ignored(client: TestClient, operator: Account,
                                                                     world: dict, fake: FakeSuite,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """The answer to /finish got lost; the operator then tries to set anna to "leave out", or to change a team. Keeping
    that is refused (the assistant shows the choices of then, locked); finishing sends /finish again and applies the
    choices of then, whatever comes along with it."""
    chosen = _choices(client, world)
    _lose_finish_once(fake, monkeypatch)
    assert client.post("/api/suite/finish", json=chosen).status_code in (409, 502)
    assert client.get("/api/suite/proposal").json()["sent"] is True
    other = {**chosen, "accounts": {**chosen["accounts"], world["anna"].id: "skip"}}
    kept = client.put("/api/suite/choices", json={**other, "teams": {}, "step": 2})
    assert kept.status_code == 409 and _code(kept) == "connection_sent"
    team_only = client.put("/api/suite/choices", json={**chosen, "teams": {str(world["team"]): "70"}, "step": 3})
    assert team_only.status_code == 409 and _code(team_only) == "connection_sent"
    assert _setting("suite_state") == "connecting" and _row("anna").oidc_subject == ""
    done = client.post("/api/suite/finish", json=other)
    assert done.status_code == 200, done.text
    assert _row("anna").oidc_subject == "2" and _row("anna").blocked_at is None, "the choices of then"


def _sent_and_lost(client: TestClient, world: dict, fake: FakeSuite, monkeypatch: pytest.MonkeyPatch) -> dict:
    chosen = _choices(client, world)
    _lose_finish_once(fake, monkeypatch)
    assert client.post("/api/suite/finish", json=chosen).status_code in (409, 502)
    assert fake.connected
    return chosen


def test_after_reloading_the_assistant_shows_what_was_sent_and_finishes_with_it(
        client: TestClient, operator: Account, world: dict, fake: FakeSuite,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """nexsuite has the connection, so it offers no client any more. The proposal still names the choices that went
    out, with the names of their targets, and finishing with them works."""
    chosen = _sent_and_lost(client, world, fake, monkeypatch)
    ideen = client_of(client, world["ideen"])
    found = client.get("/api/suite/proposal").json()
    assert found["sent"] is True
    assert found["chosen"]["clients"][ideen] == "10"
    assert {"id": "10", "name": "Ideen", "color": "#f472b6"} in found["candidates"], "the target by its name"
    assert found["chosen"]["accounts"] == {str(k): v for k, v in chosen["accounts"].items()}
    assert {person["id"] for person in found["people"]} >= {"1", "2", "3"}
    assert {row["id"] for row in found["clients"]} == set(chosen["clients"])
    body = {key: found["chosen"][key] for key in ("accounts", "clients", "teams")}
    done = client.post("/api/suite/finish", json=body)
    assert done.status_code == 200, done.text
    with SessionLocal() as db:
        assert db.get(Space, world["ideen"]).external_id == "10"  # type: ignore[union-attr]


def test_an_account_made_after_sending_is_not_in_the_list_and_stops_nothing(
        client: TestClient, operator: Account, world: dict, fake: FakeSuite,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """An account made here after /finish went out is not among the choices, and a finish that brings it along still
    finishes; nothing is made for it in nexsuite."""
    chosen = _sent_and_lost(client, world, fake, monkeypatch)
    late = make_account("spaet")
    found = client.get("/api/suite/proposal").json()
    assert "spaet" not in {row["name"] for row in found["accounts"]}
    people = len(fake.people)
    body = {**chosen, "accounts": {**chosen["accounts"], late.id: "new"}}
    done = client.post("/api/suite/finish", json=body)
    assert done.status_code == 200, done.text
    assert len(fake.people) == people
    assert _row("spaet").oidc_subject == ""


def test_giving_up_after_finish_went_out_says_when_nexsuite_may_still_list_the_app(
        client: TestClient, operator: Account, world: dict, fake: FakeSuite,
        monkeypatch: pytest.MonkeyPatch) -> None:
    chosen = _choices(client, world)
    _lose_finish_once(fake, monkeypatch)
    assert client.post("/api/suite/finish", json=chosen).status_code in (409, 502)
    fake.down = True
    answer = client.post("/api/suite/abort")
    assert answer.status_code == 200 and answer.json() == {"kept_in_suite": True}
    assert _setting("suite_state") == ""


def test_giving_up_before_finish_went_out_says_nothing_more(client: TestClient, operator: Account, world: dict,
                                                            fake: FakeSuite) -> None:
    _choices(client, world)
    fake.down = True
    assert client.post("/api/suite/abort").status_code == 204
    fake.down = False
    _choices(client, world)
    assert client.post("/api/suite/abort").status_code == 204


# --- what the plan has no place for ----------------------------------------------------------------------------------


@pytest.mark.parametrize("way", ["at once", "after a lost answer"])
@pytest.mark.parametrize("role", [OPERATOR, "member"])
def test_an_account_without_a_place_in_the_plan_is_blocked_like_one_left_out(
        client: TestClient, operator: Account, world: dict, fake: FakeSuite, monkeypatch: pytest.MonkeyPatch,
        role: str, way: str) -> None:
    """Made between pairing and finishing, or after /finish went out: no person in nexsuite, so no way in while
    connected; never a password sign-in of its own beside nexsuite."""
    chosen = _choices(client, world)
    if way == "after a lost answer":
        _lose_finish_once(fake, monkeypatch)
        assert client.post("/api/suite/finish", json=chosen).status_code in (409, 502)
    make_account("neuchef", role)
    done = client.post("/api/suite/finish", json=chosen)
    assert done.status_code == 200, done.text
    late = _row("neuchef")
    assert late.blocked_at is not None and late.oidc_subject == "" and late.suite_person == ""
    with new_client() as browser:
        refused = browser.post("/api/auth/login", json={"name": "neuchef", "password": PASSWORD})
        assert refused.status_code != 200
    assert _row("tester").blocked_at is None, "never the emergency account"


def test_a_left_out_account_deleted_between_the_tries_stops_nothing(
        client: TestClient, operator: Account, world: dict, fake: FakeSuite,
        monkeypatch: pytest.MonkeyPatch) -> None:
    chosen = _sent_and_lost(client, world, fake, monkeypatch)
    with SessionLocal() as db:
        cleo = db.get(Account, world["cleo"].id)
        assert cleo is not None
        db.delete(cleo)
        db.commit()
    done = client.post("/api/suite/finish", json=chosen)
    assert done.status_code == 200, done.text
    assert _setting("suite_state") == "connected"


def test_after_sending_a_chosen_person_deleted_in_nexsuite_still_shows_by_its_name(
        client: TestClient, operator: Account, world: dict, fake: FakeSuite,
        monkeypatch: pytest.MonkeyPatch) -> None:
    _sent_and_lost(client, world, fake, monkeypatch)
    del fake.people["2"]
    del fake.people["3"]
    found = client.get("/api/suite/proposal").json()
    people = {person["id"]: person["name"] for person in found["people"]}
    assert people.get("2") == "anna" and people.get("3") == "erik", "the targets of then, by name"
    assert found["chosen"]["step"] == 3, "the assistant opens at the last step"


# --- settling a connection from before: a deleted person's id is no link of its own --------------------------------


def test_settled_a_person_deleted_before_the_update_leaves_no_link_behind(
        client: TestClient, operator: Account, world: dict, fake: FakeSuite) -> None:
    """Connected before ``suite_person`` was kept, anna's person was deleted in nexsuite and her account blocked. Her
    subject was nexsuite's, not a link of her own: after a disconnect she has no link and signs in with her password
    again, and connecting again says that her person is gone."""
    connect(client, world, operator)
    del fake.people["2"]
    assert client.post("/api/suite/sync").status_code == 200
    with SessionLocal() as db:  # as connected before the mark was kept
        db.query(Account).update({"suite_person": ""})
        db.commit()
    assert client.post("/api/suite/sync").status_code == 200
    anna = _row("anna")
    assert anna.own_subject == "" and anna.blocked_at is not None
    assert client.post("/api/suite/disconnect", json={"current_password": PASSWORD}).status_code == 200
    anna = _row("anna")
    assert (anna.oidc_subject, anna.own_subject, anna.sign_in) == ("", "", "password")
    rows = _again(client)
    assert rows["anna"]["gone"] is True and rows["anna"]["suggest"] == "skip"


def test_settled_an_oidc_account_without_a_password_keeps_its_own_link(client: TestClient, operator: Account,
                                                                     world: dict, fake: FakeSuite) -> None:
    """Connected before the mark was kept: dora came through authentik (no password of her own) and was left out,
    keeping her link. Her subject is no person of nexsuite's: she keeps it apart and gets it back on disconnecting."""
    from app.services import accounts

    with SessionLocal() as db:
        dora_id = accounts.create_oidc(db, "dora", "authentik-hash-of-dora", "dora@example.com").id
    chosen = _choices(client, world)
    chosen["accounts"][dora_id] = "skip"
    assert client.post("/api/suite/finish", json=chosen).status_code == 200
    with SessionLocal() as db:  # as connected before the own link was set aside
        dora = db.get(Account, dora_id)
        assert dora is not None and dora.blocked_at is not None
        dora.oidc_subject, dora.own_subject = "authentik-hash-of-dora", ""
        db.commit()
    assert client.post("/api/suite/sync").status_code == 200
    dora = _row("dora")
    assert (dora.oidc_subject, dora.suite_person, dora.own_subject) == ("", "", "authentik-hash-of-dora")
    assert client.post("/api/suite/disconnect", json={"current_password": PASSWORD}).status_code == 200
    dora = _row("dora")
    assert (dora.oidc_subject, dora.suite_person, dora.sign_in) == ("authentik-hash-of-dora", "", "oidc")
    rows = _again(client)
    assert rows["dora"]["from_suite"] is False and rows["dora"]["gone"] is False
