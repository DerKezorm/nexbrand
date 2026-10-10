"""Clients and people while connected (Prüfgang 05.10.2026, block 4): deleting for good, connecting again, choices
that hold, direct links through the sign-in, a person made a moment ago, names, invitations from before, and the
browsers nexbrand knows.

nexsuite is played by ``FakeSuite`` from ``test_suite``; its sign-in by the fake provider of the shared contract tests
(``tests/oidc_helpers.py``), standing in for nexsuite's entry of the provider list. Nothing here waits for a clock.
The page a sign-in started from (B10) is tested in ``test_oidc_app.py``.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import Account, Client, Membership, OidcProvider, Space
from app.security import encrypt_secret
from app.services import settings_service, suite
from app.vendor.nexoidc import secret_context

from . import oidc_helpers, test_suite
from .conftest import PASSWORD, client_of, make_account, new_client, new_group, sign_in
from .oidc_helpers import FakeProvider, add_provider, come_back, error_in, fresh_browser, location
from .test_suite import SUITE, FakeSuite, _own_links, _person, _row, _setting, connect, own_link, own_provider


@pytest.fixture(autouse=True)
def _no_catch_up_held() -> None:
    """The brake on fetching the directory for strangers remembers them per process: each test starts clean."""
    suite._catch_up.clear()

# The fixtures of the suite and sign-in tests, under the names pytest looks for.
fake = test_suite.fake
world = test_suite.world
provider = oidc_helpers.provider


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
    assert _person("cleo2") == "60" and _row("anna").blocked_at is not None
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
    assert _person("cleo2") == "60" and _row("cleo2").blocked_at is None


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
    assert _row("ben").blocked_at is None and _person("ben") == ""
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


def test_b24_a_code_too_short_once_trimmed_is_a_wrong_code_not_another_app(client: TestClient, operator: Account,
                                                                           fake: FakeSuite) -> None:
    for code in ("abc ", "   abc   ", " ab  "):
        short = client.post("/api/suite/start", json={"url": SUITE, "code": code})
        assert short.status_code == 409 and short.json()["detail"]["code"] == "pair_code_invalid", code
    assert fake.calls == [], "nexsuite is not even asked"
    assert _setting("suite_state") == ""


# --- B20: the sign-in ------------------------------------------------------------------------------------------------


def _suite_signs_in(provider: FakeProvider) -> None:
    """The fake provider stands in for nexsuite's sign-in: nexsuite's entry of the list takes its issuer and client
    (the coupling made it with nexsuite's own)."""
    with SessionLocal() as db:
        row = db.query(OidcProvider).filter_by(managed="nexsuite").one()
        row.issuer, row.client_id = provider.issuer.rstrip("/"), provider.client_id
        row.client_secret_enc = encrypt_secret(provider.client_secret, secret_context(row.id))
        db.commit()


def _sign_in(browser: TestClient, provider: FakeProvider, page: str | None = None, **person: Any) -> Any:
    """``person`` signs in through nexsuite's button (the entry ``oidc``); the answer of the return."""
    provider.person = person
    started = browser.get("/api/oidc/oidc/start", params={"next": page} if page else {})
    return come_back(browser, provider, location(started))


def test_b20_a_person_made_in_nexsuite_a_moment_ago_gets_in_at_once(
        client: TestClient, operator: Account, world: dict, fake: FakeSuite, provider: FakeProvider) -> None:
    connect(client, world, operator)
    _suite_signs_in(provider)
    fake.people["61"] = {"id": "61", "name": "dora", "display_name": "Dora", "email": "dora@example.com",
                         "operator": False, "blocked": False}
    browser = fresh_browser()
    back = _sign_in(browser, provider, "/c/abc123XYZ", sub="61", email="dora@example.com", preferred_username="dora")
    assert back.status_code == 303 and location(back) == "/c/abc123XYZ"
    assert browser.get("/api/auth/me").json()["name"] == "dora"
    assert _person("dora") == "61"
    # Somebody nexsuite does not list: refused with the reason for a connected app, no invitation offered.
    stranger = _sign_in(fresh_browser(), provider, sub="999", email="x@example.com")
    assert location(stranger) == "/login?error=suite_no_account"


def test_b20_the_directory_is_fetched_off_the_server_loop_and_at_most_every_half_minute(
        client: TestClient, operator: Account, world: dict, fake: FakeSuite, provider: FakeProvider,
        monkeypatch: pytest.MonkeyPatch) -> None:
    import threading

    connect(client, world, operator)
    _suite_signs_in(provider)
    now = [1000.0]
    monkeypatch.setattr(suite, "_clock", lambda: now[0])
    threads: list[str] = []
    real = suite.catch_up

    def watched(subject: str) -> bool:
        threads.append(threading.current_thread().name)
        return real(subject)

    monkeypatch.setattr(suite, "catch_up", watched)

    def fetched() -> int:
        return sum(1 for method, path in fake.calls if method == "GET" and path == "/directory")

    before = fetched()
    for _ in range(3):
        refused = _sign_in(fresh_browser(), provider, sub="999", email="x@example.com")
        assert error_in(refused) == "suite_no_account"
    assert fetched() == before + 1, "the same stranger fetches the directory once in half a minute"
    assert threads and all(name.startswith("AnyIO worker thread") for name in threads), threads
    now[0] += suite.CATCH_UP_SECONDS + 1
    _sign_in(fresh_browser(), provider, sub="999", email="x@example.com")
    assert fetched() == before + 2, "and once more after it"
    # Another person is not held back by the stranger; a person known here fetches nothing.
    fake.people["62"] = {"id": "62", "name": "eli", "display_name": "", "email": "", "operator": False,
                         "blocked": False}
    back = _sign_in(fresh_browser(), provider, sub="62", email="eli@example.com")
    assert location(back) == "/" and _person("eli") == "62"
    known = fetched()
    assert location(_sign_in(fresh_browser(), provider, sub="62")) == "/" and fetched() == known


# --- B21, B22, B26, G3 ------------------------------------------------------------------------------------------


def _everything_by_name(client: TestClient, world: dict, fake: FakeSuite, shown: str) -> dict[str, Any]:
    """anna does everything nexbrand keeps by a name instead of an id: a draft and a published version, a review with
    an agency comment, a licence note, a notice, the last change of a client, a line in the log. A customer of the
    same name comments too."""
    from app.models import SpaceNotice
    from app.services import logs

    from .test_brands import SET

    fake.people["2"]["display_name"] = shown
    client.post("/api/suite/sync")
    with SessionLocal() as db:
        settings_service.save(db, {"shares_allowed": True})
        db.commit()
    cid = client_of(client, world["studio"])
    said = shown or "anna"
    data = {**SET, "fonts": [{"family": "Inter", "license": "free",
                              "license_note": f"Files taken from the client's website; licence confirmed by {said} "
                                              f"on 05/10/2026."}]}
    with new_client(world["anna"]) as anna:
        draft = anna.post(f"/api/clients/{cid}/versions", json={"label": "2.0", "data": data})
        assert draft.status_code == 201, draft.text
        published = anna.post(f"/api/clients/{cid}/versions", json={"label": "1.0", "data": SET}).json()["id"]
        assert anna.post(f"/api/clients/{cid}/versions/{published}/publish", json={}).status_code == 200
        review = anna.post(f"/api/clients/{cid}/reviews", json={
            "version_id": draft.json()["id"], "label": "2.0", "sender": said,
            "variants": [{"id": "a", "label": "Calm", "data": data}]})
        assert review.status_code == 201, review.text
        rid, token = review.json()["id"], review.json()["link"].rsplit("/", 1)[1]
        assert anna.post(f"/api/clients/{cid}/reviews/{rid}/comments",
                         json={"variant": "a", "text": "From us"}).status_code == 201
    with new_client() as customer:
        assert customer.post(f"/api/review/{token}/comments",
                             json={"variant": "a", "text": "Nice", "author": "anna"}).status_code == 201
    with SessionLocal() as db:
        db.get(Client, cid).updated_by = "anna"  # type: ignore[union-attr]
        notice = SpaceNotice(account_id=world["ben"].id, space_id=world["studio"], kind="invite", actor="anna",
                             actor_id=world["anna"].id, subject="anna")
        db.add(notice)
        db.commit()
        notice_id = notice.id
    with logs.log_file().open("ab") as file:
        file.write(b"2026-10-05 10:00:00 INFO     nexbrand.clients [r1 u:anna] | Version published by=anna "
                   b"name=annabel to=anna@example.com\r\n")
    return {"cid": cid, "rid": rid, "draft": draft.json()["id"], "published": published, "notice": notice_id}


def _names_now(made: dict[str, Any]) -> dict[str, Any]:
    from app.models import BrandVersion, Review, ReviewComment, SpaceNotice
    from app.services import logs

    with SessionLocal() as db:
        draft = db.get(BrandVersion, made["draft"])
        published = db.get(BrandVersion, made["published"])
        review = db.get(Review, made["rid"])
        assert draft is not None and published is not None and review is not None
        notice = db.get(SpaceNotice, made["notice"])
        assert notice is not None
        comments = {c.agency: c.author for c in db.query(ReviewComment).filter_by(review_id=review.id)}
        line = [x for x in logs.log_file().read_bytes().split(b"\r\n") if b"Version published" in x][-1].decode()
        return {"author": draft.author, "published_by": published.published_by, "sender": review.sender,
                "agency_comment": comments[True], "customer_comment": comments[False],
                "note": draft.data["fonts"][0]["license_note"],
                "review_note": review.variants[0]["data"]["fonts"][0]["license_note"],
                "updated_by": db.get(Client, made["cid"]).updated_by,  # type: ignore[union-attr]
                "actor": notice.actor, "subject": notice.subject, "log": line}


def test_b21_everything_the_deleted_one_did_stays_hers(client: TestClient, operator: Account, world: dict,
                                                       fake: FakeSuite) -> None:
    connect(client, world, operator)
    made = _everything_by_name(client, world, fake, "")
    del fake.people["2"]
    fake.people["70"] = {"id": "70", "name": "anna", "display_name": "", "email": "", "operator": False,
                         "blocked": False}
    client.post("/api/suite/sync")
    now = _names_now(made)
    assert now.pop("customer_comment") == "anna", "what a customer typed is theirs"
    log = now.pop("log")
    assert "u:anna2]" in log and "by=anna2 " in log and "name=annabel" in log and "to=anna@example.com" in log
    assert now.pop("note") == now.pop("review_note") == ("Files taken from the client's website; licence confirmed "
                                                         "by anna2 on 05/10/2026.")
    assert now == dict.fromkeys(now, "anna2"), now


def test_b21_a_display_name_follows_only_when_the_new_person_shows_the_same(
        client: TestClient, operator: Account, world: dict, fake: FakeSuite) -> None:
    connect(client, world, operator)
    made = _everything_by_name(client, world, fake, "Anna Berg")
    del fake.people["2"]
    fake.people["70"] = {"id": "70", "name": "anna", "display_name": "Anna Berg", "email": "", "operator": False,
                         "blocked": False}
    client.post("/api/suite/sync")
    now = _names_now(made)
    for key in ("author", "published_by", "sender", "agency_comment"):
        assert now[key] == "Anna Berg (anna2)", key
    assert now["note"].endswith("confirmed by Anna Berg (anna2) on 05/10/2026.")
    assert now["updated_by"] == now["actor"] == now["subject"] == "anna2"


def test_b21_a_display_name_of_its_own_stays(client: TestClient, operator: Account, world: dict,
                                              fake: FakeSuite) -> None:
    connect(client, world, operator)
    made = _everything_by_name(client, world, fake, "Anna Berg")
    del fake.people["2"]
    fake.people["70"] = {"id": "70", "name": "anna", "display_name": "Anna New", "email": "", "operator": False,
                         "blocked": False}
    client.post("/api/suite/sync")
    now = _names_now(made)
    assert now["author"] == now["sender"] == now["agency_comment"] == "Anna Berg"
    assert now["updated_by"] == "anna2"


def test_b21_b8_an_account_left_out_keeps_its_name_and_its_own_link(client: TestClient, operator: Account,
                                                                    world: dict, fake: FakeSuite) -> None:
    # The checker's r2 and r3: cleo signs in through authentik on her own and is left out when connecting.
    own_link("cleo", "ak-cleo-uuid", own_provider())
    connect(client, world, operator)
    fake.people["60"] = {"id": "60", "name": "cleo", "display_name": "", "email": "", "operator": False,
                         "blocked": False}
    client.post("/api/suite/sync")
    assert (_row("cleo").id, _person("cleo"), _row("cleo").suite_person) == (
        world["cleo"].id, "", ""), "nexsuite never had her: not renamed"
    assert _own_links("cleo") == [("oidc-own", "ak-cleo-uuid", False)], "her own link waits aside while connected"
    assert _person("cleo2") == "60"
    assert client.post("/api/suite/disconnect", json={"current_password": PASSWORD}).status_code == 200
    assert _own_links("cleo") == [("oidc", "ak-cleo-uuid", True)], "her own link is back"
    assert _person("cleo2") == "" and _row("cleo2").suite_person == "60"
    fake.connected = False
    rows = {a["name"]: a for a in _start(client)["accounts"]}
    assert (rows["cleo"]["from_suite"], rows["cleo"]["gone"], rows["cleo"]["suggest"]) == (False, False, "skip")
    assert (rows["cleo2"]["from_suite"], rows["cleo2"]["suggest"]) == (True, "60")


def _left_out_with_a_number(client: TestClient, world: dict, operator: Account) -> None:
    """cleo signs in through another provider whose subject is "2", the id anna has in nexsuite, and is left out when
    connecting. Links belong to their provider: hers stays with authentik's entry, aside while connected."""
    own_link("cleo", "2", own_provider())
    connect(client, world, operator)


def test_a_left_out_account_never_takes_the_sign_in_of_a_person_with_the_same_id(
        client: TestClient, operator: Account, world: dict, fake: FakeSuite, provider: FakeProvider) -> None:
    # (A) from the nextasks checker: the blocked cleo was found first, anna got "account_blocked".
    _left_out_with_a_number(client, world, operator)
    _suite_signs_in(provider)
    browser = fresh_browser()
    back = _sign_in(browser, provider, sub="2", email="anna@example.com")
    assert location(back) == "/", location(back)
    assert browser.get("/api/auth/me").json()["name"] == "anna"


def test_a_left_out_account_never_takes_what_a_person_with_the_same_id_has(
        client: TestClient, operator: Account, world: dict, fake: FakeSuite) -> None:
    # (B) from the nextasks checker: the sync took the last account with subject "2", unblocked cleo and gave her
    # anna's address, name, person, teams and rights.
    _left_out_with_a_number(client, world, operator)
    assert client.post("/api/suite/sync").status_code in (200, 204)
    cleo, anna = _row("cleo"), _row("anna")
    assert cleo.blocked_at is not None, "left out stays blocked"
    assert cleo.suite_person == "" and cleo.email != "anna@example.com" and cleo.display_name != "Anna Berg"
    assert anna.suite_person == "2" and anna.blocked_at is None and anna.display_name == "Anna Berg"
    with SessionLocal() as db:
        from app.models import Membership, TeamMember

        assert not db.query(TeamMember).filter_by(account_id=cleo.id).count()
        assert not db.query(Membership).filter_by(account_id=cleo.id).count()
    assert client.post("/api/suite/disconnect", json={"current_password": PASSWORD}).status_code == 200
    assert _own_links("cleo") == [("oidc", "2", True)], "her own link is hers again after disconnecting"


def test_a_left_out_account_is_not_taken_for_a_new_person_with_its_number(
        client: TestClient, operator: Account, world: dict, fake: FakeSuite, provider: FakeProvider) -> None:
    # (B) where nobody here knows the person yet: cleo's own subject "77" is the id of a person nexsuite makes later.
    # The person gets an account of its own; cleo stays as she was.
    own_link("cleo", "77", own_provider())
    connect(client, world, operator)
    fake.people["77"] = {"id": "77", "name": "dora", "display_name": "Dora", "email": "dora@example.com",
                         "operator": False, "blocked": False}
    assert client.post("/api/suite/sync").status_code in (200, 204)
    cleo = _row("cleo")
    assert cleo.blocked_at is not None and cleo.suite_person == "" and cleo.email != "dora@example.com"
    assert _row("dora").suite_person == "77" and _row("dora").id != cleo.id
    # (A) the same way round: dora's account is younger than cleo's, and dora signs in as dora, not as blocked cleo.
    _suite_signs_in(provider)
    browser = fresh_browser()
    back = _sign_in(browser, provider, sub="77", email="dora@example.com")
    assert location(back) == "/", location(back)
    assert browser.get("/api/auth/me").json()["name"] == "dora"


def test_no_account_links_itself_to_a_provider_while_connected(
        client: TestClient, operator: Account, world: dict, fake: FakeSuite, provider: FakeProvider) -> None:
    # From nextasks: the emergency account linked to a subject of its own would be nobody's to the next sync, and
    # locked out. Started before connecting and coming back after, nothing is linked either.
    add_provider(client, provider, slug="sso")
    started = client.post("/api/oidc/sso/link", json={"password": PASSWORD})
    assert started.status_code == 200, started.text
    connect(client, world, operator)
    refused = client.post("/api/oidc/oidc/link", json={"password": PASSWORD})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "managed_by_suite"
    refused = client.post("/api/oidc/sso/link", json={"password": PASSWORD})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "managed_by_suite"
    provider.person = {"sub": "ak-own-uuid"}
    back = come_back(client, provider, started.json()["url"])
    assert location(back).startswith("/account?error="), "nothing linked, back on the account page"
    assert _person("tester") == "1", "still its person in nexsuite"
    assert _own_links("tester") == [], "and no foreign subject beside it"
    assert client.post("/api/suite/sync").status_code in (200, 204)
    assert _row("tester").blocked_at is None, "the emergency account still gets in"


def test_a_person_blocked_in_nexsuite_keeps_its_account(
        client: TestClient, operator: Account, world: dict, fake: FakeSuite) -> None:
    # erik is blocked in nexsuite; the next syncs must not make "erik2" with erik's person, and unblocked in nexsuite,
    # erik works with his rights and history again.
    connect(client, world, operator)
    fake.people["3"]["blocked"] = True
    assert client.post("/api/suite/sync").status_code in (200, 204)
    erik = _row("erik")
    assert erik.blocked_at is not None and _person("erik") == "3"
    for _ in range(2):
        assert client.post("/api/suite/sync").status_code in (200, 204)
    with SessionLocal() as db:
        assert db.query(Account).filter(Account.name == "erik2").count() == 0
    assert _person("erik") == "3" and _row("erik").suite_person == "3"
    fake.people["3"]["blocked"] = False
    assert client.post("/api/suite/sync").status_code in (200, 204)
    assert _row("erik").id == erik.id and _row("erik").blocked_at is None


def test_a_person_renamed_in_nexsuite_keeps_its_blocked_account(
        client: TestClient, operator: Account, world: dict, fake: FakeSuite) -> None:
    # erik blocked in nexsuite, his display name changed there meanwhile: no erik2.
    connect(client, world, operator)
    fake.people["3"]["blocked"] = True
    assert client.post("/api/suite/sync").status_code in (200, 204)
    erik = _row("erik")
    fake.people["3"]["display_name"] = "Erik New"
    for _ in range(2):
        assert client.post("/api/suite/sync").status_code in (200, 204)
    with SessionLocal() as db:
        assert db.query(Account).filter(Account.name == "erik2").count() == 0
    assert _row("erik").id == erik.id and _person("erik") == "3" and _row("erik").suite_person == "3"


def test_b8_a_connection_from_before_this_was_kept_is_known_too(client: TestClient, operator: Account, world: dict,
                                                                fake: FakeSuite) -> None:
    connect(client, world, operator)
    with SessionLocal() as db:  # the mark lost: the link at nexsuite's entry still says who is who
        db.query(Account).update({"suite_person": ""})
        db.commit()
    assert client.post("/api/suite/disconnect", json={"current_password": PASSWORD}).status_code == 200
    assert (_person("anna"), _row("anna").suite_person) == ("", "2")


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
    assert _person("anna") == "70" and new.id != old, "named as in nexsuite"
    with SessionLocal() as db:
        before = db.get(Account, old)
        assert before is not None and before.name == "anna2" and before.blocked_at is not None
        assert db.get(Client, studio).updated_by == "anna2", "what the deleted one did stays hers"  # type: ignore[union-attr]
    # The emergency account keeps its name whatever happens: it is its way in.
    del fake.people["1"]
    fake.people["71"] = {"id": "71", "name": "tester", "display_name": "", "email": "", "operator": False,
                         "blocked": False}
    client.post("/api/suite/sync")
    assert _row("tester").id == operator.id and _person("tester2") == "71"


def test_b21_r7_a_person_that_came_with_a_sync_is_renamed_when_deleted_there(
        client: TestClient, operator: Account, world: dict, fake: FakeSuite) -> None:
    # The checker's r7: dora comes with a sync, not when connecting; nexsuite deletes her and makes a new dora.
    connect(client, world, operator)
    fake.people["50"] = {"id": "50", "name": "dora", "display_name": "", "email": "", "operator": False,
                         "blocked": False}
    client.post("/api/suite/sync")
    old = _row("dora").id
    del fake.people["50"]
    fake.people["51"] = {"id": "51", "name": "dora", "display_name": "", "email": "", "operator": False,
                         "blocked": False}
    client.post("/api/suite/sync")
    with SessionLocal() as db:
        before = db.get(Account, old)
        assert before is not None and before.name == "dora2", "the account of the deleted one moves aside"
    assert _person("dora") == "51" and _row("dora").id != old


def test_b21_the_log_renames_people_only(client: TestClient, operator: Account) -> None:
    """Only a person's key follows a rename (``u:``, ``by=``, ``name=`` …): a font family, a label or a team of the
    same name stays."""
    from app.services import logs

    line = (b"2026-10-05 10:00:00 INFO     nexbrand.x [r1 u:anna] | Font files taken family=anna label=anna team=anna "
            b"by=anna name=anna account=anna person=anna from=anna to=anna xby=anna\r\n")
    with logs.log_file().open("ab") as file:
        file.write(line)
    logs.rename_actor("anna", "anna2")
    found = [x for x in logs.log_file().read_bytes().split(b"\r\n") if b"Font files taken" in x][-1].decode()
    assert "u:anna2]" in found
    for key in ("by", "name", "account", "person"):
        assert f" {key}=anna2" in found, key
    for key in ("family", "label", "team", "from", "to", "xby"):
        assert f" {key}=anna " in found or found.endswith(f" {key}=anna"), key


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


# --- B18: a client nexsuite no longer gives nexbrand ------------------------------------------------------------------


def _shown(browser: TestClient, cid: str) -> dict[str, Any]:
    return next(c for c in browser.get("/api/clients").json() if c["id"] == cid)


def test_b18_a_client_nexsuite_lets_go_is_marked_and_the_operator_may_put_it_away(
        client: TestClient, operator: Account, world: dict, fake: FakeSuite) -> None:
    connect(client, world, operator)
    ideen = client_of(client, world["ideen"])
    assert _shown(client, ideen)["dropped"] is False
    fake.ticked.discard("10")
    client.post("/api/suite/sync")
    shown = _shown(client, ideen)
    assert shown["dropped"] is True
    assert client.delete(f"/api/clients/{ideen}").status_code == 204
    assert ideen in [c["id"] for c in client.get("/api/clients?deleted=true").json()]
    assert client.post(f"/api/clients/{ideen}/restore").status_code == 200
    assert client.delete(f"/api/clients/{ideen}").status_code == 204
    assert _purge(client, ideen).status_code == 204, "nexsuite says nothing about it any more: deleted here for good"
    with SessionLocal() as db:
        assert db.get(Client, ideen) is None


def test_b18_given_again_it_is_nexsuites_again(client: TestClient, operator: Account, world: dict,
                                               fake: FakeSuite) -> None:
    connect(client, world, operator)
    ideen = client_of(client, world["ideen"])
    fake.ticked.discard("10")
    client.post("/api/suite/sync")
    fake.ticked.add("10")
    client.post("/api/suite/sync")
    shown = _shown(client, ideen)
    assert shown["dropped"] is False and shown["managed"] is True
    refused = client.delete(f"/api/clients/{ideen}")
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "managed_by_suite"


def test_b18_one_in_nexsuites_bin_is_not_let_go(client: TestClient, operator: Account, world: dict,
                                                fake: FakeSuite) -> None:
    connect(client, world, operator)
    ideen = client_of(client, world["ideen"])
    fake.ticked.discard("10")
    fake.clients_bin = [{"id": "10", "deleted_at": "2026-10-04T10:00:00+00:00"}]
    client.post("/api/suite/sync")
    shown = next(c for c in client.get("/api/clients?deleted=true").json() if c["id"] == ideen)
    assert shown["dropped"] is False and shown["managed"] is True, "it comes back or goes for good in nexsuite"


def test_b18_let_go_first_and_binned_in_nexsuite_after_it_is_nexsuites_again(
        client: TestClient, operator: Account, world: dict, fake: FakeSuite) -> None:
    connect(client, world, operator)
    ideen = client_of(client, world["ideen"])
    fake.ticked.discard("10")
    client.post("/api/suite/sync")
    assert _shown(client, ideen)["dropped"] is True
    fake.clients_bin = [{"id": "10", "deleted_at": "2026-10-04T10:00:00+00:00"}]
    client.post("/api/suite/sync")
    shown = next(c for c in client.get("/api/clients?deleted=true").json() if c["id"] == ideen)
    assert shown["dropped"] is False, "nexsuite's bin decides now, not the operator here"
    refused = client.post(f"/api/clients/{ideen}/restore")
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "managed_by_suite"


def test_b18_only_the_operator_in_the_interface_puts_it_away(client: TestClient, operator: Account, world: dict,
                                                             fake: FakeSuite) -> None:
    connect(client, world, operator)
    ideen = client_of(client, world["ideen"])
    fake.ticked.discard("10")
    client.post("/api/suite/sync")
    with SessionLocal() as db:
        space = db.get(Space, world["ideen"])
        assert space is not None and space.suite_dropped_at is not None
        db.add(Membership(space_id=space.id, account_id=world["anna"].id, role="manage"))
        db.commit()
    with new_client(world["anna"]) as browser:
        refused = browser.delete(f"/api/clients/{ideen}")
        assert refused.status_code == 409 and refused.json()["detail"]["code"] == "managed_by_suite"


def test_b18_disconnecting_forgets_the_mark(client: TestClient, operator: Account, world: dict,
                                            fake: FakeSuite) -> None:
    connect(client, world, operator)
    fake.ticked.discard("10")
    client.post("/api/suite/sync")
    with SessionLocal() as db:
        suite.disconnect(db, tell=False)
        db.commit()
    with SessionLocal() as db:
        space = db.get(Space, world["ideen"])
        assert space is not None and space.suite_dropped_at is None and space.external_id == ""


def test_b18_put_away_it_goes_by_the_clock_here(client: TestClient, operator: Account, world: dict,
                                                fake: FakeSuite) -> None:
    from datetime import timedelta

    from app.models import utcnow
    from app.services import cleanup

    connect(client, world, operator)
    ideen = client_of(client, world["ideen"])
    studio = client_of(client, world["studio"])
    fake.ticked.discard("10")
    client.post("/api/suite/sync")
    assert client.delete(f"/api/clients/{ideen}").status_code == 204
    with SessionLocal() as db:
        for cid in (ideen, studio):
            db.get(Client, cid).deleted_at = utcnow() - timedelta(days=40)  # type: ignore[union-attr]
        db.commit()
    cleanup.run_once()
    with SessionLocal() as db:
        assert db.get(Client, ideen) is None, "nexsuite says nothing about it: the clock here counts"
        assert db.get(Client, studio) is not None, "one nexsuite still gives waits for nexsuite"
