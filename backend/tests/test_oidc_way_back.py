"""The way back for one version: what 0.1.1 reads (the settings ``oidc_*`` and the columns ``oidc_subject``,
``own_subject``) always names exactly one issuer and holds nothing the list took away, otherwise it is empty.

Starting 0.1.1 again on a database of this version must neither let a stranger of the own provider in as somebody's
account, nor bring back a provider the operator removed, nor a link an account or the operator unlinked."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text

from app.db import SessionLocal, engine
from app.models import Account, OidcLink, OidcProvider
from app.security import decrypt_secret
from app.services import oidc_store, settings_service, suite

from . import oidc_helpers, test_suite
from .conftest import PASSWORD, make_account, sign_in
from .oidc_helpers import FakeProvider, fakes, fresh_browser, link
from .test_oidc_app import _legacy, _links, accounts_row
from .test_suite import SUITE, FakeSuite, _person, connect

provider = oidc_helpers.provider
fake = test_suite.fake
world = test_suite.world

EMPTY = {"oidc_issuer": "", "oidc_client_id": "", "oidc_client_secret": "", "oidc_provider_name": "",
         "oidc_auto_create": False}


def _old_settings(values: dict[str, Any] | None = None) -> dict[str, Any]:
    """The old settings as 0.1.1 reads them, the secret opened as 0.1.1 opens it (no context)."""
    if values is None:
        with SessionLocal() as db:
            values = settings_service.get_all(db)
    return {"oidc_issuer": values.get("oidc_issuer") or "", "oidc_client_id": values.get("oidc_client_id") or "",
            "oidc_client_secret": decrypt_secret(str(values.get("oidc_client_secret_enc") or "")),
            "oidc_provider_name": values.get("oidc_provider_name") or "",
            "oidc_auto_create": bool(values.get("oidc_auto_create"))}


def _columns() -> dict[str, tuple[str, str]]:
    """Per account: ``oidc_subject`` and ``own_subject``."""
    with SessionLocal() as db:
        return {row.name: (row.oidc_subject, row.own_subject) for row in db.scalars(select(Account))}


def _migrated(idp: FakeProvider, **subjects: str) -> int:
    """0.1.1 with one provider (``Company``) and these links, moved to the list; the id of the entry ``oidc``."""
    for name in subjects:
        if name != "tester":
            make_account(name)
    _legacy(idp, label="Company", subjects=subjects)
    entry = oidc_store.migrate_settings(backup=False)
    assert entry is not None and entry.slug == "oidc"
    return entry.id


def _own(idp: FakeProvider) -> dict[str, Any]:
    return {"oidc_issuer": idp.issuer, "oidc_client_id": idp.client_id, "oidc_client_secret": idp.client_secret,
            "oidc_provider_name": "Company", "oidc_auto_create": False}


# --- B2: removed, another issuer, unlinked --------------------------------------------------------------------------


def test_the_migration_keeps_the_old_settings_and_subjects_as_they_were(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    _migrated(provider, anna="anna-1", ben="ben-1")
    assert _old_settings() == _own(provider)
    assert _columns()["anna"] == ("anna-1", "") and _columns()["ben"] == ("ben-1", "")


def test_removing_the_entry_oidc_empties_the_old_settings_and_every_subject(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    entry = _migrated(provider, anna="anna-1", ben="ben-1")
    assert client.delete(f"/api/oidc/admin/providers/{entry}").status_code == 200
    assert _old_settings() == EMPTY
    assert {subjects for subjects in _columns().values()} == {("", "")}


def _save(client: TestClient, entry: int, **changes: Any) -> Any:
    [row] = [row for row in client.get("/api/oidc/admin/providers").json() if row["id"] == entry]
    body = {"label": row["label"], "issuer": row["issuer"], "client_id": row["client_id"], "client_secret": "",
            "scopes": row["scopes"], "enabled": row["enabled"], "auto_create": row["auto_create"],
            "trusts_second_factor": row["trusts_second_factor"], **changes}
    answer = client.put(f"/api/oidc/admin/providers/{entry}", json=body)
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_another_issuer_for_the_entry_oidc_empties_the_old_settings_and_every_subject_for_good(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    entry = _migrated(provider, anna="anna-1", ben="ben-1")
    other = provider.network.add(fakes.FakeProvider("https://other.example.com"))  # type: ignore[attr-defined]
    _save(client, entry, issuer=other.issuer, client_id=other.client_id, client_secret=other.client_secret)
    assert _old_settings() == EMPTY
    assert {subjects for subjects in _columns().values()} == {("", "")}
    # A new link at the other issuer never lands in the old column: 0.1.1 knows no provider any more.
    make_account("cleo")
    member = fresh_browser()
    sign_in(member, accounts_row("cleo"))
    link(member, other, PASSWORD, slug="oidc", sub="cleo-1")
    assert _links() == [("oidc", "cleo-1", "cleo")]
    assert _columns()["cleo"] == ("", "") and _old_settings() == EMPTY


def test_the_same_issuer_with_a_new_client_is_followed_and_a_switched_off_entry_empties_it(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    entry = _migrated(provider, anna="anna-1")
    _save(client, entry, client_id="renewed-client", client_secret="renewed-" + provider.client_secret[:6],
          auto_create=True)
    assert _old_settings() == {**_own(provider), "oidc_client_id": "renewed-client",
                               "oidc_client_secret": "renewed-" + provider.client_secret[:6],
                               "oidc_auto_create": True}
    assert _columns()["anna"] == ("anna-1", "")
    # "New people" off again: 0.1.1 makes nobody new through it either.
    _save(client, entry, auto_create=False)
    assert _old_settings()["oidc_auto_create"] is False and _old_settings()["oidc_issuer"] == provider.issuer
    # Switched off: 0.1.1 lets nobody in through it, new or known (it has no "off", only no provider).
    _save(client, entry, auto_create=True)
    _save(client, entry, enabled=False)
    assert _old_settings() == EMPTY and _columns()["anna"] == ("", "")
    _save(client, entry, enabled=True)
    assert _old_settings() == EMPTY, "switched off once, 0.1.1 gets it back never"


def test_unlinking_takes_the_subject_from_the_old_column_and_a_new_link_comes_into_it(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    entry = _migrated(provider, anna="anna-1", ben="ben-1")
    # anna unlinks herself, the operator unlinks ben.
    member = fresh_browser()
    sign_in(member, accounts_row("anna"))
    assert member.delete("/api/oidc/oidc/link").status_code == 204
    ben = accounts_row("ben").id
    answer = client.request("DELETE", f"/api/oidc/admin/accounts/{ben}/links/{entry}",
                            json={"current_password": PASSWORD})
    assert answer.status_code == 204
    assert _columns()["anna"] == ("", "") and _columns()["ben"] == ("", "")
    assert _old_settings() == _own(provider), "the provider itself stays"
    # anna links another identity of the same provider: 0.1.1 knows that one, not the old.
    link(member, provider, PASSWORD, slug="oidc", sub="anna-2")
    assert _columns()["anna"] == ("anna-2", "")


# --- B1: coupling and uncoupling --------------------------------------------------------------------------------


def test_coupling_writes_the_old_settings_as_0_1_1_did_and_uncoupling_gives_the_own_back(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite, provider: FakeProvider
) -> None:
    _legacy(provider, label="Company", subjects={"anna": "ak-anna", "cleo": "ak-cleo"})
    assert oidc_store.migrate_settings(backup=False) is not None
    connect(client, world, operator)
    with SessionLocal() as db:
        values = settings_service.get_all(db)
    # nexsuite is the provider 0.1.1 finds, its persons are the accounts' subjects ...
    assert _old_settings(values) == {"oidc_issuer": SUITE, "oidc_client_id": "nxs-client",
                                     "oidc_client_secret": "the-client-secret", "oidc_provider_name": "nexsuite",
                                     "oidc_auto_create": False}
    columns = _columns()
    for name in ("tester", "anna", "ben", "erik"):
        assert columns[name][0] == _person(name) != "", name
        assert accounts_row(name).suite_person == _person(name)
    # ... the own provider waits beside it, with the own links (cleo left out, anna's own identity).
    assert _old_settings(values["suite_saved"]) == _own(provider)
    assert columns["cleo"] == ("", "ak-cleo") and columns["anna"][1] == "ak-anna"
    assert {own for name, (_, own) in columns.items() if name not in ("anna", "cleo")} == {""}
    # A sync keeps it so; a person made in nexsuite comes into the old column too.
    fake.people["60"] = {"id": "60", "name": "fritz", "display_name": "Fritz", "email": "fritz@example.com",
                         "operator": False, "blocked": False}
    assert client.post("/api/suite/sync").status_code in (200, 204)
    assert _columns()["fritz"] == ("60", "")
    assert client.post("/api/suite/disconnect", json={"current_password": PASSWORD}).status_code == 200
    with SessionLocal() as db:
        values = settings_service.get_all(db)
    assert _old_settings(values) == _own(provider)
    assert not {key for key in values["suite_saved"] or {} if key.startswith("oidc_")}
    assert _columns() == {"tester": ("", ""), "anna": ("ak-anna", ""), "ben": ("", ""), "cleo": ("ak-cleo", ""),
                          "erik": ("", ""), "fritz": ("", "")}


def test_coupling_without_an_own_provider_leaves_nothing_to_give_back(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite
) -> None:
    connect(client, world, operator)
    with SessionLocal() as db:
        values = settings_service.get_all(db)
    assert values["oidc_issuer"] == SUITE and _old_settings(values["suite_saved"]) == EMPTY
    assert client.post("/api/suite/disconnect", json={"current_password": PASSWORD}).status_code == 200
    assert _old_settings() == EMPTY
    assert {subjects for subjects in _columns().values()} == {("", "")}


# --- B4: the old order of 0.1.1, the sign-in name included -------------------------------------------------------


def _as_0_1_1_left_it(change: Any) -> None:
    """The coupled state written above is 0.1.1's own: the list goes, the migration has to come again."""
    with SessionLocal() as db:
        db.execute(delete(OidcLink))
        db.execute(delete(OidcProvider))
        settings_service.save(db, {oidc_store.MIGRATED: False, oidc_store.COUPLING: None}, commit=False)
        change(db, {row.name: row for row in db.scalars(select(Account))})
        db.commit()


def test_migrated_the_persons_sign_in_name_wins_even_blocked_and_younger(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite
) -> None:
    # As test_the_persons_sign_in_name_wins_even_blocked_and_younger of 0.1.1, before its sync: nobody marked, ben
    # (older, not blocked) and erik (blocked) both hold "3". Person 3's sign-in name is erik's.
    connect(client, world, operator)

    def change(db: Any, rows: dict[str, Account]) -> None:
        rows["ben"].oidc_subject, rows["ben"].blocked_at = "3", None
        rows["erik"].blocked_at = suite.utcnow()
        for row in rows.values():
            row.suite_person = ""

    _as_0_1_1_left_it(change)
    assert accounts_row("ben").id < accounts_row("erik").id
    assert oidc_store.migrate_settings(backup=False) is not None
    # Without the name nothing decides: "3" waits, no link, both as 0.1.1 left them (the way back too).
    assert [subject for _, subject, _ in _links()].count("3") == 0
    assert _columns()["ben"][0] == "3" and _columns()["erik"][0] == "3"
    assert accounts_row("ben").blocked_at is None
    assert client.post("/api/suite/sync").status_code in (200, 204)
    erik, ben = accounts_row("erik"), accounts_row("ben")
    assert _person("erik") == "3" and erik.suite_person == "3" and erik.blocked_at is None
    assert _person("ben") == "" and ben.oidc_subject == "" and ben.blocked_at is not None
    with SessionLocal() as db:
        assert db.scalar(select(Account.id).where(Account.name == "erik2")) is None
        assert settings_service.get(db, oidc_store.WAITING) is None
    assert _columns()["erik"] == ("3", "")


def test_migrated_the_operators_choice_when_connecting_goes_before_the_name(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite
) -> None:
    # As test_the_operators_choice_when_connecting_goes_before_the_name of 0.1.1: person 2 ("anna") was given to
    # the account ben; the account anna, left out (blocked, unmarked), holds "2" too. ben stays the person's.
    connect(client, world, operator)

    def change(db: Any, rows: dict[str, Account]) -> None:
        rows["anna"].oidc_subject, rows["anna"].suite_person, rows["anna"].blocked_at = "2", "", suite.utcnow()
        rows["ben"].oidc_subject, rows["ben"].suite_person = "2", "2"

    _as_0_1_1_left_it(change)
    assert oidc_store.migrate_settings(backup=False) is not None
    assert _person("ben") == "2" and _person("anna") == ""
    assert accounts_row("anna").blocked_at is not None and _columns()["anna"][0] == ""
    with SessionLocal() as db:
        assert settings_service.get(db, oidc_store.WAITING) is None


def test_a_waiting_subject_nobody_may_claim_goes_from_the_old_column_too(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite
) -> None:
    # cleo, left out (blocked, unmarked), holds a subject nexsuite has no person for: as 0.1.1's sync, nobody claims
    # it, and it never turns into a link; she stays blocked.
    connect(client, world, operator)

    def change(db: Any, rows: dict[str, Account]) -> None:
        rows["cleo"].oidc_subject = "77"

    _as_0_1_1_left_it(change)
    assert oidc_store.migrate_settings(backup=False) is not None
    assert _columns()["cleo"] == ("77", ""), "waits as 0.1.1 left it"
    assert client.post("/api/suite/sync").status_code in (200, 204)
    assert _columns()["cleo"] == ("", "") and accounts_row("cleo").blocked_at is not None
    assert "77" not in [subject for _, subject, _ in _links()]


def test_the_emergency_account_is_never_blocked_for_losing_a_waiting_person(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite
) -> None:
    # The operator (the emergency account) and anna, both unmarked, wait for person 2; the sync gives it to anna by
    # her sign-in name. The emergency account loses the subject but stays the way in.
    connect(client, world, operator)

    def change(db: Any, rows: dict[str, Account]) -> None:
        rows["tester"].oidc_subject = "2"
        for row in rows.values():
            row.suite_person = ""

    _as_0_1_1_left_it(change)
    assert oidc_store.migrate_settings(backup=False) is not None
    with SessionLocal() as db:
        assert settings_service.get(db, "suite_emergency_account") == operator.id
        assert sorted(settings_service.get(db, oidc_store.WAITING)["2"]) == sorted([operator.id, world["anna"].id])
    assert client.post("/api/suite/sync").status_code in (200, 204)
    assert _person("anna") == "2"
    assert accounts_row("tester").oidc_subject != "2" and accounts_row("tester").blocked_at is None


def test_the_emergency_account_is_never_blocked_for_losing_a_person_in_the_migration(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite
) -> None:
    # anna is marked for person 2, the operator holds "2" too: the migration gives it to anna at once; the
    # emergency account loses it without being blocked.
    connect(client, world, operator)

    def change(db: Any, rows: dict[str, Account]) -> None:
        rows["tester"].oidc_subject, rows["tester"].suite_person = "2", ""

    _as_0_1_1_left_it(change)
    assert oidc_store.migrate_settings(backup=False) is not None
    assert _person("anna") == "2" and _person("tester") == ""
    assert accounts_row("tester").blocked_at is None


def test_waiting_persons_get_no_link_when_disconnected_before_a_sync(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite
) -> None:
    connect(client, world, operator)

    def change(db: Any, rows: dict[str, Account]) -> None:
        rows["ben"].oidc_subject = "3"
        for row in rows.values():
            row.suite_person = ""

    _as_0_1_1_left_it(change)
    assert oidc_store.migrate_settings(backup=False) is not None
    assert client.post("/api/suite/disconnect", json={"current_password": PASSWORD}).status_code == 200
    assert _links() == [] and _columns()["ben"] == ("", "") and _columns()["erik"] == ("", "")
    with SessionLocal() as db:
        assert settings_service.get(db, oidc_store.WAITING) is None


# --- B5: 0.1.1 makes accounts on a database this version made ------------------------------------------------------


def test_an_account_made_without_the_new_column_gets_its_default(client: TestClient, operator: Account) -> None:
    # 0.1.1 names every column it knows and none it does not: the insert below is its insert.
    with engine.begin() as connection:
        known = [row[1] for row in connection.execute(text("PRAGMA table_info(accounts)"))
                 if row[1] not in ("id", "name", "email_from_provider")]
        listed = ", ".join(f'"{name}"' for name in known)  # names of the table itself, nothing from outside
        statement = f'INSERT INTO accounts ("name", {listed}) SELECT :name, {listed} FROM accounts WHERE id = :id'  # noqa: S608
        connection.execute(text(statement), {"name": "old-made", "id": operator.id})
    assert accounts_row("old-made").email_from_provider is False
