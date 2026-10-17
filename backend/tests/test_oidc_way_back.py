"""The way back for one version: what 0.1.1 reads (the settings ``oidc_*`` and the columns ``oidc_subject``,
``own_subject``) always names exactly one issuer and holds nothing the list took away, otherwise it is empty.

Starting 0.1.1 again on a database of this version must neither let a stranger of the own provider in as somebody's
account, nor bring back a provider the operator removed, nor a link an account or the operator unlinked."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text

from app.db import SessionLocal, engine
from app.models import Account, OidcLink, OidcProvider
from app.security import decrypt_secret, encrypt_secret
from app.services import oidc_store, settings_service, suite
from app.vendor.nexoidc import migrate

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

def _off(idp: FakeProvider) -> dict[str, Any]:
    """An entry that is off for 0.1.1 (switched off, or without the second factor of its own): no client, no secret,
    no new people; the issuer and the name wait."""
    return {"oidc_issuer": idp.issuer, "oidc_client_id": "", "oidc_client_secret": "",
            "oidc_provider_name": "Company", "oidc_auto_create": False}


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


# --- removed, another issuer, unlinked --------------------------------------------------------------------------


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
    # Switched off: 0.1.1 lets nobody in through it, new or known (it has no "off", only no provider: no client).
    _save(client, entry, auto_create=True)
    _save(client, entry, enabled=False)
    assert _old_settings() == _off(provider), "no client, no new people; issuer and name wait"
    assert _columns()["anna"] == ("anna-1", ""), "the known person waits too, and cannot come in without a client"
    # Switched on again, everything is there again (rule of 10.10.2026, both directions of the switch).
    _save(client, entry, enabled=True)
    assert _old_settings() == {**_own(provider), "oidc_client_id": "renewed-client",
                               "oidc_client_secret": "renewed-" + provider.client_secret[:6],
                               "oidc_auto_create": True}
    assert _columns()["anna"] == ("anna-1", "")


def test_a_provider_that_does_not_check_the_second_factor_is_off_for_0_1_1_and_comes_back_with_the_switch(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    """0.1.1 knows no such switch and would ask no code after the provider, so for it the entry is off, the same
    way as a switched-off entry, at once in both directions (rule of 10.10.2026)."""
    entry = _migrated(provider, anna="anna-1")
    _save(client, entry, auto_create=True)
    on = _old_settings()
    assert on == {**_own(provider), "oidc_auto_create": True}
    _save(client, entry, trusts_second_factor=False)
    assert _old_settings() == _off(provider) and _columns()["anna"] == ("anna-1", "")
    # A link made or taken meanwhile still follows the list while the entry waits.
    make_account("ben")
    member = fresh_browser()
    sign_in(member, accounts_row("ben"))
    link(member, provider, PASSWORD, slug="oidc", sub="ben-1")
    assert _columns()["ben"] == ("ben-1", "") and _old_settings() == _off(provider)
    _save(client, entry, trusts_second_factor=True)
    assert _old_settings() == on
    # Off by either reason is off; the entry is back only when both allow it.
    _save(client, entry, trusts_second_factor=False, enabled=False)
    assert _old_settings() == _off(provider)
    _save(client, entry, trusts_second_factor=True)
    assert _old_settings() == _off(provider), "still switched off itself"
    _save(client, entry, enabled=True)
    assert _old_settings() == on
    _save(client, entry, enabled=False)
    _save(client, entry, trusts_second_factor=False)
    _save(client, entry, enabled=True)
    assert _old_settings() == _off(provider), "still without the second factor of its own"
    # Another issuer while it waits is another provider: empty for good, as ever.
    other = provider.network.add(fakes.FakeProvider("https://other.example.com"))  # type: ignore[attr-defined]
    _save(client, entry, trusts_second_factor=True, issuer=other.issuer, client_id=other.client_id,
          client_secret=other.client_secret)
    assert _old_settings() == EMPTY and {subjects for subjects in _columns().values()} == {("", "")}


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


# --- coupling and uncoupling --------------------------------------------------------------------------------


def test_coupling_writes_the_old_settings_as_0_1_1_did_and_uncoupling_gives_the_own_back(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite, provider: FakeProvider
) -> None:
    _legacy(provider, label="Company", subjects={"anna": "ak-anna", "cleo": "ak-cleo"})
    assert oidc_store.migrate_settings(backup=False) is not None
    connect(client, world, operator)
    with SessionLocal() as db:
        values = settings_service.get_all(db)
    # The directory service is the provider 0.1.1 finds, its persons are the accounts' subjects ...
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
    # A sync keeps it so; a person made in the directory service comes into the old column too.
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


def test_an_own_entry_without_the_second_factor_waits_off_beside_nexsuite_and_off_after_disconnecting(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite, provider: FakeProvider
) -> None:
    _legacy(provider, label="Company", subjects={"anna": "ak-anna"})
    own = oidc_store.migrate_settings(backup=False)
    assert own is not None
    entry = own.id
    _save(client, entry, trusts_second_factor=False)
    assert _old_settings() == _off(provider)
    connect(client, world, operator)
    with SessionLocal() as db:
        values = settings_service.get_all(db)
    assert _old_settings(values["suite_saved"]) == _off(provider), "waits aside, off for the version before"
    assert _columns()["anna"][1] == "ak-anna", "its link waits aside"
    assert client.post("/api/suite/disconnect", json={"current_password": PASSWORD}).status_code == 200
    assert _old_settings() == _off(provider) and _columns()["anna"] == ("ak-anna", "")
    _save(client, entry, trusts_second_factor=True)
    assert _old_settings() == _own(provider)


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


# --- the old order of 0.1.1, the sign-in name included -------------------------------------------------------


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
    # cleo, left out (blocked, unmarked), holds a subject the directory service has no person for: as 0.1.1's sync, nobody claims
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


# --- 0.1.1 makes accounts on a database this version made ------------------------------------------------------


def test_an_account_made_without_the_new_column_gets_its_default(client: TestClient, operator: Account) -> None:
    # 0.1.1 names every column it knows and none it does not: the insert below is its insert.
    with engine.begin() as connection:
        known = [row[1] for row in connection.execute(text("PRAGMA table_info(accounts)"))
                 if row[1] not in ("id", "name", "email_from_provider")]
        listed = ", ".join(f'"{name}"' for name in known)  # names of the table itself, nothing from outside
        statement = f'INSERT INTO accounts ("name", {listed}) SELECT :name, {listed} FROM accounts WHERE id = :id'  # noqa: S608
        connection.execute(text(statement), {"name": "old-made", "id": operator.id})
    assert accounts_row("old-made").email_from_provider is False


# --- Up again after the way back (module 1.0.9): what 0.1.1 changed is taken over, coupled nothing ------------------


def _as_0_1_1_changed(idp: FakeProvider | None, **subjects: str) -> None:
    """0.1.1 at work between two starts: its settings (empty without ``idp``) and the subjects named."""
    with SessionLocal() as db:
        settings_service.save(db, {
            "oidc_issuer": idp.issuer if idp else "", "oidc_client_id": idp.client_id if idp else "",
            "oidc_client_secret_enc": encrypt_secret(idp.client_secret) if idp else "",
            "oidc_provider_name": "Changed" if idp else "", "oidc_auto_create": False}, commit=False)
        for name, subject in subjects.items():
            accounts_row_in(db, name).oidc_subject = subject
        db.commit()


def accounts_row_in(db: Any, name: str) -> Account:
    row = db.scalar(select(Account).where(Account.name == name))
    assert row is not None
    return row


def _list_state() -> tuple[list[tuple[str, str, str, bool]], list[tuple[str, str, str]]]:
    """Every entry (slug, issuer, label, enabled) and every link (slug, subject, account), nothing else."""
    with SessionLocal() as db:
        entries = [(row.slug, row.issuer, row.label, row.enabled)
                   for row in db.scalars(select(OidcProvider).order_by(OidcProvider.id))]
    return entries, _links()


def test_a_start_coupled_takes_over_nothing_and_writes_the_way_back_again(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite, provider: FakeProvider,
    caplog: pytest.LogCaptureFixture
) -> None:
    _legacy(provider, label="Company", subjects={"anna": "ak-anna", "cleo": "ak-cleo"})
    assert oidc_store.migrate_settings(backup=False) is not None
    connect(client, world, operator)
    before, coupled_old = _list_state(), _old_settings()
    assert coupled_old["oidc_issuer"] == SUITE
    other = provider.network.add(fakes.FakeProvider("https://other.example.com"))  # type: ignore[attr-defined]
    # 0.1.1 started on the coupled database and changed what it could: the provider, a person, an own identity.
    _as_0_1_1_changed(other, anna="elsewhere")
    with SessionLocal() as db:
        accounts_row_in(db, "cleo").own_subject = "changed-own"
        db.commit()
    with caplog.at_level("WARNING"):
        assert oidc_store.migrate_settings(backup=False) is None
    assert _list_state() == before, "neither entries nor links changed"
    assert "while coupled; nothing taken over" in caplog.text and "took over what" not in caplog.text
    # The way back is written again from the list, and the next start is quiet.
    assert _old_settings() == coupled_old and _columns()["anna"][0] == _person("anna")
    caplog.clear()
    with caplog.at_level("WARNING"):
        oidc_store.migrate_settings(backup=False)
    assert _list_state() == before and "OIDC:" not in caplog.text


def test_a_start_that_changed_nothing_changes_nothing_and_says_nothing(
    client: TestClient, operator: Account, provider: FakeProvider, caplog: pytest.LogCaptureFixture
) -> None:
    _migrated(provider, anna="anna-1")
    with SessionLocal() as db:
        stamp = settings_service.get(db, oidc_store.FINGERPRINT)
        assert stamp
    before, old = _list_state(), _old_settings()
    caplog.clear()
    for _ in range(2):
        with caplog.at_level("WARNING"):
            oidc_store.migrate_settings(backup=False)
    assert _list_state() == before and _old_settings() == old and "OIDC:" not in caplog.text
    with SessionLocal() as db:
        assert settings_service.get(db, oidc_store.FINGERPRINT) == stamp


def test_the_fingerprint_follows_every_change_the_way_back_makes(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    entry = _migrated(provider, anna="anna-1")
    with SessionLocal() as db:
        first = settings_service.get(db, oidc_store.FINGERPRINT)
    _save(client, entry, enabled=False)
    with SessionLocal() as db:
        off = settings_service.get(db, oidc_store.FINGERPRINT)
        legacy, subjects = oidc_store.read_legacy(db)
        assert off == migrate.fingerprint(legacy, subjects) != first
    # What the mirror wrote itself (an entry that is off) is no change of 0.1.1 at the next start.
    before = _list_state()
    oidc_store.migrate_settings(backup=False)
    assert _list_state() == before


def test_a_session_made_without_the_new_column_gets_its_default(client: TestClient, operator: Account) -> None:
    # 0.1.1 names every column of auth_sessions it knows and none it does not.
    with engine.begin() as connection:
        known = [row[1] for row in connection.execute(text("PRAGMA table_info(auth_sessions)"))
                 if row[1] not in ("id", "token_hash", "second_factor_by_provider")]
        listed = ", ".join(f'"{name}"' for name in known)  # names of the table itself, nothing from outside
        statement = (f'INSERT INTO auth_sessions ("token_hash", {listed}) '  # noqa: S608
                     f'SELECT :hash, {listed} FROM auth_sessions LIMIT 1')
        assert connection.execute(text("SELECT count(*) FROM auth_sessions")).scalar() == 1
        connection.execute(text(statement), {"hash": "0" * 64})
        assert connection.execute(
            text('SELECT second_factor_by_provider FROM auth_sessions WHERE token_hash = :hash'), {"hash": "0" * 64}
        ).scalar() == 0


# --- Module 1.0.10 and 1.0.11: one rule, the anchor, the issuer as 0.1.1 wrote it ------------------------------------


def _quiet_start(caplog: pytest.LogCaptureFixture) -> None:
    """A start that must change nothing and say nothing."""
    before, old, columns = _list_state(), _old_settings(), _columns()
    caplog.clear()
    with caplog.at_level("WARNING"):
        oidc_store.migrate_settings(backup=False)
    assert (_list_state(), _old_settings(), _columns()) == (before, old, columns) and "OIDC:" not in caplog.text


def test_a_first_start_without_a_provider_stores_the_fingerprint_and_takes_over_one_set_up_later(
    client: TestClient, operator: Account, provider: FakeProvider, caplog: pytest.LogCaptureFixture
) -> None:
    """Prüfer nexbrand, Befund 1: without the fingerprint of "no provider" the next start took a provider that 0.1.1
    set up in between for no change and wrote the old settings empty."""
    make_account("anna")
    # The test's own start (the fixture's lifespan was one already) is the first one: nothing looked at yet.
    with SessionLocal() as db:
        settings_service.save(db, {oidc_store.MIGRATED: False, oidc_store.FINGERPRINT: "", oidc_store.ANCHOR: ""})
    assert oidc_store.migrate_settings(backup=False) is None
    with SessionLocal() as db:
        legacy, subjects = oidc_store.read_legacy(db)
        stamp = settings_service.get(db, oidc_store.FINGERPRINT)
        assert stamp and stamp == migrate.fingerprint(legacy, subjects), "the fingerprint of no provider"
        assert settings_service.get(db, oidc_store.ANCHOR) == migrate.CLOSED
    # 0.1.1 started on this database: its operator set a provider up and linked anna.
    _as_0_1_1_changed(provider, anna="anna-1")
    with caplog.at_level("WARNING"):
        assert oidc_store.migrate_settings(backup=False) is None
    entries, links = _list_state()
    assert [(slug, issuer) for slug, issuer, _label, _on in entries] == [("oidc", provider.issuer)]
    assert links == [("oidc", "anna-1", "anna")]
    assert _old_settings()["oidc_client_id"] == provider.client_id and _columns()["anna"] == ("anna-1", "")
    _quiet_start(caplog)


def test_off_and_the_provider_removed_in_0_1_1_removes_the_entry_at_the_next_start(
    client: TestClient, operator: Account, provider: FakeProvider, caplog: pytest.LogCaptureFixture
) -> None:
    """Prüfer nexbrand, Befund 2: the issuer stays standing while the entry is off (rule 2), so "remove the provider"
    in 0.1.1 is a change the next start sees; it removes the entry with its links, like removing does anywhere."""
    entry = _migrated(provider, anna="anna-1")
    _save(client, entry, enabled=False)
    assert _old_settings() == _off(provider)
    # 0.1.1: "Remove the provider" clears its settings (the subjects of the accounts stay in their column).
    _as_0_1_1_changed(None)
    with caplog.at_level("WARNING"):
        oidc_store.migrate_settings(backup=False)
    assert _list_state() == ([], [])
    assert _old_settings() == EMPTY and _columns()["anna"] == ("", "")
    with SessionLocal() as db:
        assert settings_service.get(db, oidc_store.ANCHOR) == migrate.CLOSED
    _quiet_start(caplog)


def test_deleting_an_account_writes_the_way_back_and_the_fingerprint_too(
    client: TestClient, operator: Account, provider: FakeProvider, caplog: pytest.LogCaptureFixture
) -> None:
    """Without it the next start took the missing subject for a change of 0.1.1, made a backup for nothing and logged
    it (the contract test "every commit" asks for the same through the adapter)."""
    _migrated(provider, anna="anna-1", ben="ben-1")
    gone = client.request("DELETE", f"/api/accounts/{accounts_row('anna').id}", json={"current_password": PASSWORD})
    assert gone.status_code == 204, gone.text
    assert _columns().get("anna") is None and _columns()["ben"] == ("ben-1", "")
    with SessionLocal() as db:
        legacy, subjects = oidc_store.read_legacy(db)
        assert settings_service.get(db, oidc_store.FINGERPRINT) == migrate.fingerprint(legacy, subjects)
    assert _links() == [("oidc", "ben-1", "ben")]
    _quiet_start(caplog)


def test_the_issuer_stays_as_0_1_1_wrote_it_through_the_whole_round(
    client: TestClient, operator: Account, provider: FakeProvider, caplog: pytest.LogCaptureFixture
) -> None:
    """Module 1.0.11: authentik hands out the issuer with a slash and six older versions compare it letter by letter
    when a provider is saved; the way back writes the text they knew, never a form without the slash."""
    written = provider.issuer.rstrip("/") + "/"
    for name in ("anna",):
        make_account(name)
    _legacy(provider, label="Company", issuer=written, subjects={"anna": "anna-1"})
    entry = oidc_store.migrate_settings(backup=False)
    assert entry is not None and not entry.issuer.endswith("/"), "the entry holds the form without the slash"
    assert _old_settings()["oidc_issuer"] == written
    _save(client, entry.id, enabled=False)
    assert _old_settings()["oidc_issuer"] == written and _old_settings()["oidc_client_id"] == ""
    _save(client, entry.id, enabled=True)
    assert _old_settings() == {**_own(provider), "oidc_issuer": written}
    _quiet_start(caplog)
    _save(client, entry.id, label="Renamed")
    assert _old_settings()["oidc_issuer"] == written and _columns()["anna"] == ("anna-1", "")
    _quiet_start(caplog)
    # 0.1.1 sets the same provider up again with a new client, its issuer written with the slash as its button does.
    with SessionLocal() as db:
        settings_service.save(db, {"oidc_issuer": written, "oidc_client_id": "renewed-client"})
    oidc_store.migrate_settings(backup=False)
    assert _links() == [("oidc", "anna-1", "anna")], "no link was thrown away"
    assert _old_settings()["oidc_issuer"] == written and _old_settings()["oidc_client_id"] == "renewed-client"
    _quiet_start(caplog)


def test_a_start_backs_up_only_when_0_1_1_changed_something(
    client: TestClient, operator: Account, provider: FakeProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import backups

    made: list[str] = []
    monkeypatch.setattr(backups, "create", lambda **kwargs: made.append(str(kwargs.get("note"))))
    _migrated(provider, anna="anna-1")
    oidc_store.migrate_settings(backup=True)
    assert made == [], "nothing changed since the way back was written: no backup for nothing"
    _as_0_1_1_changed(provider, anna="")
    oidc_store.migrate_settings(backup=True)
    assert len(made) == 1 and "0.1.1" in made[0]


def test_a_start_coupled_makes_no_backup_for_what_it_does_not_take_over(
    client: TestClient, operator: Account, world: dict, fake: FakeSuite, provider: FakeProvider,
    monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import backups

    _legacy(provider, label="Company", subjects={"anna": "ak-anna"})
    assert oidc_store.migrate_settings(backup=False) is not None
    connect(client, world, operator)
    made: list[str] = []
    monkeypatch.setattr(backups, "create", lambda **kwargs: made.append(str(kwargs.get("note"))))
    other = provider.network.add(fakes.FakeProvider("https://other.example.com"))  # type: ignore[attr-defined]
    # 0.1.1 changed the old settings and a subject on the coupled database: nothing is taken over, so nothing is backed up.
    _as_0_1_1_changed(other, anna="elsewhere")
    assert oidc_store.migrate_settings(backup=True) is None
    assert made == [], "a backup for nothing"


def test_a_provider_made_without_the_new_column_gets_its_default(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    # The list before module 1.0.10 (a build of this version from before) names every column it knows and none it does
    # not: the insert below is its insert.
    _migrated(provider, anna="anna-1")
    with engine.begin() as connection:
        known = [row[1] for row in connection.execute(text("PRAGMA table_info(oidc_providers)"))
                 if row[1] not in ("id", "slug", "registered_redirect")]
        listed = ", ".join(f'"{name}"' for name in known)  # names of the table itself, nothing from outside
        statement = (f'INSERT INTO oidc_providers ("slug", {listed}) '  # noqa: S608
                     f'SELECT :slug, {listed} FROM oidc_providers LIMIT 1')
        connection.execute(text(statement), {"slug": "made-before"})
    with SessionLocal() as db:
        row = db.scalar(select(OidcProvider).where(OidcProvider.slug == "made-before"))
        assert row is not None and row.registered_redirect == ""
