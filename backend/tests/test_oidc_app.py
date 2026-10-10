"""nexbrand's own side of sign-in through providers, around the shared contract tests (``tests/nexoidc``): the
migration from the single provider of 0.1 (also of an instance coupled to nexsuite), the buttons of the sign-in page,
the operator's account list, the code step after a provider that is not trusted with the second factor, invitations
into a client, the address a provider knows, the page a sign-in started from (B10), the coupling, and the log.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import MANAGE, OPERATOR, SIGN_IN_OIDC, WRITE, Account, Membership, OidcLink, OidcProvider, Space
from app.routers.auth import PENDING_COOKIE
from app.security import SESSION_COOKIE, encrypt_secret, hash_password
from app.services import accounts, backups, landing, logs, oidc_store, settings_service, suite, totp
from app.vendor import nexoidc
from app.vendor.nexoidc import coupling

from . import oidc_helpers
from .conftest import PASSWORD, make_account, sign_in
from .oidc_helpers import (
    FakeProvider,
    add_provider,
    come_back,
    error_in,
    fakes,
    fresh_browser,
    link,
    location,
    sign_in_via_oidc,
)

#: The fake provider of the shared contract tests, as a fixture.
provider = oidc_helpers.provider

AUTHENTIK_ISSUER = "https://sso.example.com/application/o/nexbrand/"


def _legacy(fake: FakeProvider, *, label: str, issuer: str | None = None, auto_create: bool = False,
            subjects: dict[str, str] | None = None) -> None:
    """nexbrand 0.1 as it kept its one provider: in the settings, the subject at the account."""
    with SessionLocal() as db:
        settings_service.save(db, {
            "oidc_issuer": issuer or fake.issuer,
            "oidc_client_id": fake.client_id,
            "oidc_client_secret_enc": encrypt_secret(fake.client_secret),
            "oidc_provider_name": label,
            "oidc_auto_create": auto_create,
            oidc_store.MIGRATED: False,
        })
        for name, subject in (subjects or {}).items():
            row = accounts.by_name(db, name)
            assert row is not None
            row.oidc_subject = subject
        db.commit()


def _entries() -> list[OidcProvider]:
    with SessionLocal() as db:
        rows = list(db.scalars(select(OidcProvider).order_by(OidcProvider.id)))
        for row in rows:
            db.expunge(row)
        return rows


def _links() -> list[tuple[str, str, str]]:
    """(provider slug, subject, account name) of every link."""
    with SessionLocal() as db:
        return sorted(
            (db.get(OidcProvider, row.provider_id).slug, row.subject, db.get(Account, row.account_id).name)  # type: ignore[union-attr]
            for row in db.scalars(select(OidcLink))
        )


def accounts_row(name: str) -> Account:
    with SessionLocal() as db:
        row = accounts.by_name(db, name)
        assert row is not None
        db.expunge(row)
        return row


# --- The migration --------------------------------------------------------------------------------------------------


def test_the_migration_makes_a_backup_first_and_keeps_name_auto_create_and_every_link(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    make_account("anna")
    make_account("ben")
    _legacy(provider, label="Company", auto_create=True, subjects={"anna": "anna-1", "ben": "ben-1"})
    before = len(backups.entries())
    entry = oidc_store.migrate_settings()
    assert entry is not None and len(backups.entries()) == before + 1
    assert backups.entries()[0].kind == backups.UPDATE
    [row] = _entries()
    assert (row.slug, row.label, row.auto_create, row.trusts_second_factor, row.managed, row.enabled) == (
        "oidc", "Company", True, True, "", True)
    with SessionLocal() as db:
        links = sorted((link.subject, link.issuer) for link in db.scalars(select(OidcLink)))
    assert links == [("anna-1", provider.issuer.rstrip("/")), ("ben-1", provider.issuer.rstrip("/"))]
    # The secret came over, sealed for the entry now (its own context).
    with SessionLocal() as db:
        assert oidc_store.SqlStore(db).provider_by_slug("oidc").client_secret == provider.client_secret  # type: ignore[union-attr]
        assert row.client_secret_enc and provider.client_secret not in row.client_secret_enc
    # A second start does nothing, no second backup either.
    assert oidc_store.migrate_settings() is None and len(backups.entries()) == before + 1
    # The old address still signs anna in.
    provider.person = {"sub": "anna-1", "preferred_username": "anna"}
    browser = fresh_browser()
    target = location(browser.get("/api/oidc/oidc/start"))
    assert "%2Fapi%2Foidc%2Fcallback" in target
    assert location(browser.get("/api/oidc/callback", params=provider.authorize(target))) == "/"
    assert browser.get("/api/auth/me").json()["name"] == "anna"


def test_removing_every_entry_after_the_migration_brings_the_old_provider_back_never(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    _legacy(provider, label="Company")
    entry = oidc_store.migrate_settings(backup=False)
    assert entry is not None
    assert client.delete(f"/api/oidc/admin/providers/{entry.id}").status_code == 200
    assert oidc_store.migrate_settings(backup=False) is None and _entries() == []


def test_the_button_of_0_1_becomes_an_entry_the_button_looks_after_and_keeps_its_address(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    _legacy(provider, label="authentik", issuer=AUTHENTIK_ISSUER)
    oidc_store.migrate_settings(backup=False)
    [row] = _entries()
    assert (row.slug, row.managed, row.issuer, row.redirect_path) == (
        "oidc", "authentik", AUTHENTIK_ISSUER.rstrip("/"), "")
    view = client.get("/api/oidc/admin/providers").json()[0]
    assert view["redirect_uri"] == "http://testserver/api/oidc/callback"
    # A provider named so by hand, with another issuer, is the operator's own.
    with SessionLocal() as db:
        db.query(OidcProvider).delete()
        db.commit()
    _legacy(provider, label="authentik")
    oidc_store.migrate_settings(backup=False)
    assert _entries()[0].managed == ""
    with SessionLocal() as db:
        db.query(OidcProvider).delete()
        db.commit()
    _legacy(provider, label="Company", issuer=AUTHENTIK_ISSUER)
    oidc_store.migrate_settings(backup=False)
    assert _entries()[0].managed == ""


def test_without_a_provider_in_the_settings_nothing_is_made(client: TestClient, operator: Account) -> None:
    assert oidc_store.migrate_settings(backup=False) is None and _entries() == []
    with SessionLocal() as db:
        assert settings_service.get(db, oidc_store.MIGRATED) is True


def _coupled_before_the_list(suite_fake: FakeProvider, own: FakeProvider) -> None:
    """nexbrand 0.1 connected to nexsuite: nexsuite's client in the settings, the own provider kept for the way back
    in ``suite_saved``, each account's person in ``oidc_subject``, the own link of one left out in ``own_subject``."""
    for name in ("anna", "cleo", "erik", "fritz"):
        make_account(name)
    with SessionLocal() as db:
        settings_service.save(db, {
            "suite_state": "connected",
            "suite_url": "https://suite.example.com",
            "oidc_issuer": suite_fake.issuer,
            "oidc_client_id": suite_fake.client_id,
            "oidc_client_secret_enc": encrypt_secret(suite_fake.client_secret),
            "oidc_provider_name": "nexsuite",
            "password_login": False,
            "suite_saved": {"oidc_issuer": own.issuer, "oidc_client_id": own.client_id,
                            "oidc_client_secret_enc": encrypt_secret(own.client_secret),
                            "oidc_provider_name": "authentik", "oidc_auto_create": False, "password_login": True,
                            "roles": {}},
            oidc_store.MIGRATED: False,
        })
        rows = {row.name: row for row in db.scalars(select(Account))}
        rows["tester"].oidc_subject, rows["tester"].suite_person = "1", "1"
        rows["anna"].oidc_subject, rows["anna"].suite_person = "2", "2"
        # Left out when connecting: blocked, its own authentik link set aside.
        rows["cleo"].own_subject, rows["cleo"].blocked_at = "ak-cleo", suite.utcnow()
        # Connected before ``suite_person`` was kept: a subject on an account nexsuite never knew (blocked).
        rows["erik"].oidc_subject, rows["erik"].blocked_at = "ak-erik", suite.utcnow()
        # The same person twice (a mess from before c485f67): the account marked for it keeps it.
        rows["fritz"].oidc_subject = "2"
        # A person nexsuite brought: no password, its address from the directory.
        db.add(Account(name="neu", role="member", sign_in=SIGN_IN_OIDC, oidc_subject="4", suite_person="4",
                       email="neu@example.com"))
        db.commit()


def test_a_coupled_instance_moves_to_the_list_with_nexsuite_as_its_provider_and_gets_its_own_back(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    network = provider.network  # type: ignore[attr-defined]
    suite_fake = network.add(fakes.FakeProvider("https://suite.example.com"))
    own = provider
    _coupled_before_the_list(suite_fake, own)
    entry = oidc_store.migrate_settings(backup=False)
    assert entry is not None and entry.managed == "nexsuite"
    listed = {row.slug: row for row in _entries()}
    assert set(listed) == {"oidc", "oidc-own"}
    assert (listed["oidc"].label, listed["oidc"].enabled, listed["oidc"].trusts_second_factor) == ("nexsuite", True,
                                                                                                 True)
    assert (listed["oidc-own"].label, listed["oidc-own"].enabled, listed["oidc-own"].managed) == (
        "authentik", False, "")
    assert listed["oidc-own"].redirect_path == "/api/oidc/callback", "parked, it keeps the address authentik knows"
    # fritz held anna's person too (a connection from before c485f67): the account marked for it keeps it, fritz
    # loses it and is blocked, as the sync before the list did. A subject of nexsuite's never becomes a link at an own
    # entry (erik's from before ``suite_person`` was kept neither): only cleo's own link, issued by her own provider.
    assert _links() == [("oidc", "1", "tester"), ("oidc", "2", "anna"), ("oidc", "4", "neu"),
                        ("oidc-own", "ak-cleo", "cleo")]
    with SessionLocal() as db:
        persons = set(db.scalars(select(Account.oidc_subject).where(Account.oidc_subject != "")))
    assert not [link for link in _links() if link[0] != "oidc" and link[1] in persons], "nexsuite's ids stay its own"
    assert accounts_row("fritz").blocked_at is not None and accounts_row("anna").blocked_at is None
    assert accounts_row("tester").blocked_at is None
    with SessionLocal() as db:
        kept = settings_service.get(db, oidc_store.COUPLING)
        assert kept["provider_id"] == entry.id and settings_service.get(db, oidc_store.MIGRATED) is True
    assert oidc_store.migrate_settings(backup=False) is None, "once"
    # nexsuite's people sign in at the address nexsuite was told, the own provider waits.
    suite_fake.person = {"sub": "2", "preferred_username": "anna"}
    browser = fresh_browser()
    target = location(browser.get("/api/oidc/oidc/start"))
    assert "%2Fapi%2Foidc%2Fcallback" in target
    assert location(come_back(browser, suite_fake, target)) == "/"
    assert browser.get("/api/auth/me").json()["name"] == "anna"
    assert error_in(fresh_browser().get("/api/oidc/oidc-own/start")) == "oidc_not_configured"
    # The address of nexsuite's people is the directory's, never the token's, also for one through it only.
    suite_fake.person = {"sub": "4", "email": "neu.token@example.com"}
    browser = fresh_browser()
    assert location(come_back(browser, suite_fake, location(browser.get("/api/oidc/oidc/start")))) == "/"
    assert browser.get("/api/auth/me").json()["name"] == "neu"
    assert accounts_row("neu").email == "neu@example.com"
    # Disconnecting: nexsuite's entry goes with its links, the own entry is ``oidc`` again with cleo's link.
    with SessionLocal() as db:
        suite.disconnect(db, tell=False)
    listed = {row.slug: row for row in _entries()}
    assert set(listed) == {"oidc"} and listed["oidc"].label == "authentik" and listed["oidc"].enabled
    assert _links() == [("oidc", "ak-cleo", "cleo")]
    assert accounts_row("neu").email == "neu@example.com", "what nexsuite gave stays after disconnecting"
    with SessionLocal() as db:
        db.get(Account, accounts_row("cleo").id).blocked_at = None  # type: ignore[union-attr]
        db.commit()
    own.person = {"sub": "ak-cleo"}
    browser = fresh_browser()
    target = location(browser.get("/api/oidc/oidc/start"))
    assert location(browser.get("/api/oidc/callback", params=own.authorize(target))) == "/"
    assert browser.get("/api/auth/me").json()["name"] == "cleo"
    assert accounts_row("anna").suite_person == "2", "kept for connecting again"


# --- The buttons and the operator's list ---------------------------------------------------------------------------


def test_the_sign_in_page_learns_the_active_providers_in_their_order_and_nothing_else(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    first = add_provider(client, provider, slug="sso", label="SSO")
    second = add_provider(client, provider, slug="work", label="Work")
    methods = fresh_browser().get("/api/auth/methods").json()
    assert methods["password"] is True
    assert methods["providers"] == [{"slug": "sso", "label": "SSO"}, {"slug": "work", "label": "Work"}]
    client.put("/api/oidc/admin/providers/order", json={"ids": [second["id"], first["id"]]})
    body = {key: first[key] for key in ("label", "issuer", "client_id", "scopes", "auto_create",
                                         "trusts_second_factor")}
    assert client.put(f"/api/oidc/admin/providers/{first['id']}", json={**body, "enabled": False}).status_code == 200
    assert fresh_browser().get("/api/oidc/providers").json() == [{"slug": "work", "label": "Work"}]
    assert fresh_browser().get("/api/auth/methods").json()["providers"] == [{"slug": "work", "label": "Work"}]
    assert provider.client_secret not in str(client.get("/api/oidc/admin/providers").json())


def test_password_sign_in_can_go_off_only_with_an_active_provider_and_members_then_come_through_it(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    refused = client.put("/api/settings", json={"password_login": False})
    assert refused.json()["detail"]["code"] == "provider_first"
    entry = add_provider(client, provider, enabled=False)
    refused = client.put("/api/settings", json={"password_login": False})
    assert refused.json()["detail"]["code"] == "provider_first", "a provider that is off lets nobody in"
    body = {key: entry[key] for key in ("label", "issuer", "client_id", "scopes", "auto_create",
                                         "trusts_second_factor")}
    client.put(f"/api/oidc/admin/providers/{entry['id']}", json={**body, "enabled": True})
    assert client.put("/api/settings", json={"password_login": False}).status_code == 200
    make_account("anna")
    anna = fresh_browser()
    assert anna.post("/api/auth/login", json={"name": "anna", "password": PASSWORD}).status_code == 403
    # The operator keeps the password.
    assert fresh_browser().post("/api/auth/login", json={"name": "tester", "password": PASSWORD}).status_code == 200
    member = fresh_browser()
    sign_in(member, accounts_row("anna"))
    assert location(link(member, provider, PASSWORD, sub="anna-1")) == "/account?linked=sso"
    browser = fresh_browser()
    assert location(sign_in_via_oidc(browser, provider, sub="anna-1")) == "/"
    assert browser.get("/api/auth/me").json()["name"] == "anna"


def test_the_account_list_shows_each_accounts_providers_and_the_operator_unlinks_with_the_own_password(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    entry = add_provider(client, provider, label="SSO")
    make_account("anna")
    member = fresh_browser()
    sign_in(member, accounts_row("anna"))
    link(member, provider, PASSWORD, sub="anna-1")
    listed = {row["name"]: row for row in client.get("/api/accounts").json()}
    assert listed["anna"]["providers"] == [{"id": entry["id"], "slug": "sso", "label": "SSO", "managed": ""}]
    assert listed["tester"]["providers"] == []
    anna_id = listed["anna"]["id"]
    address = f"/api/oidc/admin/accounts/{anna_id}/links/{entry['id']}"
    wrong = client.request("DELETE", address, json={"current_password": "not it"})
    assert wrong.status_code == 401
    assert _links() == [("sso", "anna-1", "anna")]
    assert client.request("DELETE", address, json={"current_password": PASSWORD}).status_code == 204
    assert {row["name"]: row for row in client.get("/api/accounts").json()}["anna"]["providers"] == []
    # Never unseen: anna finds it under "New", with the provider's name and who did it.
    told = [(item["kind"], item["actor"], item["space"], item["mine"]) for item in member.get("/api/notices").json()]
    assert told == [("operator_unlinked", "tester", "SSO", True)]
    gone = client.request("DELETE", address, json={"current_password": PASSWORD})
    assert gone.status_code == 404


def test_the_operator_cannot_take_the_last_link_of_an_account_without_a_password(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    entry = add_provider(client, provider, auto_create=True)
    sign_in_via_oidc(fresh_browser(), provider, sub="clara-1", preferred_username="clara")
    clara = accounts_row("clara")
    assert clara.sign_in == SIGN_IN_OIDC
    refused = client.request("DELETE", f"/api/oidc/admin/accounts/{clara.id}/links/{entry['id']}",
                             json={"current_password": PASSWORD})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "oidc_only_account"


def test_an_account_without_a_password_cannot_start_a_link(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    add_provider(client, provider, auto_create=True)
    browser = fresh_browser()
    sign_in_via_oidc(browser, provider, sub="clara-1", preferred_username="clara")
    refused = browser.post("/api/oidc/sso/link", json={"password": "anything at all"})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "oidc_only_account"


def test_a_blocked_account_does_not_come_in_through_its_provider(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    add_provider(client, provider)
    make_account("anna")
    member = fresh_browser()
    sign_in(member, accounts_row("anna"))
    link(member, provider, PASSWORD, sub="anna-1")
    with SessionLocal() as db:
        db.get(Account, accounts_row("anna").id).blocked_at = suite.utcnow()  # type: ignore[union-attr]
        db.commit()
    browser = fresh_browser()
    assert error_in(sign_in_via_oidc(browser, provider, sub="anna-1")) == "account_blocked"
    assert browser.get("/api/auth/me").status_code == 401


# --- The address a provider knows ------------------------------------------------------------------------------------


def test_an_account_through_the_provider_only_follows_its_address_but_never_takes_anothers(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    add_provider(client, provider, auto_create=True)
    sign_in_via_oidc(fresh_browser(), provider, sub="clara-1", preferred_username="clara",
                     email="clara@example.com")
    assert accounts_row("clara").email == "clara@example.com"
    sign_in_via_oidc(fresh_browser(), provider, sub="clara-1", preferred_username="clara",
                     email="clara.new@example.com")
    assert accounts_row("clara").email == "clara.new@example.com", "it follows the provider"
    with SessionLocal() as db:
        db.get(Account, operator.id).email = "boss@example.com"  # type: ignore[union-attr]
        db.commit()
    sign_in_via_oidc(fresh_browser(), provider, sub="clara-1", preferred_username="clara",
                     email="BOSS@example.com")
    assert accounts_row("clara").email == "clara.new@example.com", "never an address another account has"


def test_an_account_with_a_password_is_offered_the_address_and_it_goes_with_the_last_link(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    add_provider(client, provider, slug="sso", label="SSO")
    work = provider.network.add(fakes.FakeProvider("https://work.example.com"))  # type: ignore[attr-defined]
    add_provider(client, work, slug="work", label="Work")
    make_account("anna")
    member = fresh_browser()
    sign_in(member, accounts_row("anna"))
    link(member, provider, PASSWORD, sub="anna-1", email="anna@example.com")
    assert accounts_row("anna").email == "", "only offered, never given"
    mine = member.get("/api/oidc/me").json()
    assert mine == [{"slug": "sso", "label": "SSO", "linked": True, "address": "anna@example.com"},
                    {"slug": "work", "label": "Work", "linked": False, "address": None}]
    assert member.post("/api/oidc/work/address").status_code == 404, "no link there"
    taken = member.post("/api/oidc/sso/address")
    assert taken.status_code == 200 and accounts_row("anna").email == "anna@example.com"
    assert member.get("/api/oidc/me").json()[0]["address"] is None, "nothing to offer any more"
    link(member, work, PASSWORD, slug="work", sub="anna-w", email="anna@work.example.com")
    assert member.delete("/api/oidc/sso/link").status_code == 204
    assert accounts_row("anna").email == "anna@example.com", "it stays while another link holds"
    assert member.delete("/api/oidc/work/link").status_code == 204
    assert accounts_row("anna").email == "", "the provider's address goes with the last link"


def test_an_offered_address_another_account_has_is_not_taken(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    add_provider(client, provider)
    make_account("anna")
    with SessionLocal() as db:
        db.get(Account, operator.id).email = "anna@example.com"  # type: ignore[union-attr]
        db.commit()
    member = fresh_browser()
    sign_in(member, accounts_row("anna"))
    link(member, provider, PASSWORD, sub="anna-1", email="anna@example.com")
    refused = member.post("/api/oidc/sso/address")
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "email_taken"
    assert accounts_row("anna").email == ""


# --- The second factor after a provider that is not trusted with it --------------------------------------------------


def test_the_code_step_of_the_sign_in_page_finishes_a_sign_in_through_an_untrusted_provider(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    add_provider(client, provider, trusts_second_factor=False)
    seed = totp.generate_seed()
    with SessionLocal() as db:
        db.add(Account(name="anna", role="member", password_hash=hash_password(PASSWORD),
                       totp_secret_enc=totp.seal_seed(seed)))
        db.commit()
    member = fresh_browser()
    member.post("/api/auth/login", json={"name": "anna", "password": PASSWORD})
    member.post("/api/auth/login/totp", json={"code": totp.code_at(seed, time.time())})
    assert location(link(member, provider, PASSWORD, sub="anna-1")) == "/account?linked=sso"
    browser = fresh_browser()
    started = browser.get("/api/oidc/sso/start", params={"next": "/c/abc123XYZ"})
    back = come_back(browser, provider, location(started))
    assert location(back) == "/login?step=code&next=%2Fc%2Fabc123XYZ", "the page asked for waits with the code"
    assert browser.get("/api/auth/me").status_code == 401
    assert browser.cookies.get(PENDING_COOKIE)
    wrong = browser.post("/api/auth/login/totp", json={"code": "000000"})
    assert wrong.status_code == 401
    done = browser.post("/api/auth/login/totp", json={"code": totp.code_at(seed, time.time() + 30)})
    assert done.status_code == 200 and browser.get("/api/auth/me").json()["name"] == "anna"


# --- Invitations into a client ---------------------------------------------------------------------------------------


def test_an_invitation_through_the_provider_brings_the_right_in_its_client_and_the_inviter_stays_manager(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    add_provider(client, provider)
    with SessionLocal() as db:
        space = Space(name="Team")
        db.add(space)
        db.flush()
        inviter = db.get(Account, operator.id)
        assert inviter is not None
        _invite, token = accounts.create_invite(db, inviter, space_id=space.id, space_role=WRITE, days=7)
        space_id = space.id
    browser = fresh_browser()
    back = sign_in_via_oidc(browser, provider, invite=token, sub="dora-1", preferred_username="dora")
    assert location(back) == "/" and browser.get("/api/auth/me").json()["name"] == "dora"
    with SessionLocal() as db:
        roles = {db.get(Account, row.account_id).name: row.role  # type: ignore[union-attr]
                 for row in db.scalars(select(Membership).where(Membership.space_id == space_id))}
    assert roles == {"dora": WRITE, "tester": "manage"}
    # Used up: the next one with the same link does not even get to the provider.
    again = fresh_browser().get("/api/oidc/sso/start", params={"invite": token})
    assert error_in(again) == "invite_invalid"


def test_a_new_account_through_a_provider_gets_a_clean_unique_name(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    add_provider(client, provider, auto_create=True)
    make_account("max", OPERATOR)
    sign_in_via_oidc(fresh_browser(), provider, sub="m-1", preferred_username="Max@example.com")
    sign_in_via_oidc(fresh_browser(), provider, sub="m-2", preferred_username="", name="", email="")
    with SessionLocal() as db:
        names = set(db.scalars(select(Account.name)))
    assert {"max-2", "user"} <= names


@pytest.mark.parametrize("raw", ["a" * 80 + "-2", "Ä Ö", "x", "--", "max.mustermann"])
def test_names_from_a_provider_follow_the_rules_of_nexbrand(raw: str) -> None:
    cleaned = oidc_store.clean_name(raw)
    assert cleaned == "" or accounts.NAME_PATTERN.match(cleaned)
    assert len(cleaned) <= 64
    if raw.endswith("-2"):
        assert cleaned.endswith("-2")


# --- B10: the page a sign-in started from ----------------------------------------------------------------------------


@pytest.mark.parametrize(("asked", "landing_page"), [
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
    # The API in any spelling a browser or the server reads as the API (correction round).
    ("/%61pi/auth/me", None),
    ("/API/auth/me", None),
    ("/Api", None),
    ("/c/../api/auth/me", None),
    ("/./api/x", None),
    ("/./api/auth/me", None),
    ("/x/%2e%2e/api/suite", None),
    ("/x/%2E%2E/api/suite", None),
    ("/%252F%252Fevil.example.com", None),
    ("/%2F%2Fevil.example.com", None),
    ("/%5Cevil.example.com", None),
    ("/apiary", "/apiary"),
])
def test_b10_only_a_page_of_nexbrands_own_is_a_landing(asked: str, landing_page: str | None) -> None:
    assert landing.safe_next(asked) == landing_page
    assert landing.read(landing.pack(asked)) == landing_page


def _sign_in_from(browser: TestClient, fake: FakeProvider, page: str | None, **person: Any) -> Any:
    if person:
        fake.person = {"sub": "person-1", **person}
    query = f"?next={quote(page, safe='')}" if page is not None else ""
    started = browser.get(f"/api/oidc/sso/start{query}")
    assert started.status_code == 303, started.text
    return come_back(browser, fake, location(started))


def test_b10_a_direct_link_survives_the_sign_in_through_the_provider(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    add_provider(client, provider, auto_create=True)
    browser = fresh_browser()
    back = _sign_in_from(browser, provider, "/c/abc123XYZ?tab=reviews")
    assert location(back) == "/c/abc123XYZ?tab=reviews"
    assert browser.get("/api/auth/me").status_code == 200
    assert not browser.cookies.get(landing.COOKIE), "the page is used once"
    assert location(_sign_in_from(fresh_browser(), provider, "//evil.example.com")) == "/", "never another host"
    assert location(_sign_in_from(fresh_browser(), provider, None)) == "/"


def test_b10_a_next_too_long_is_dropped_not_refused(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    add_provider(client, provider, auto_create=True)
    assert location(_sign_in_from(fresh_browser(), provider, "/c/" + "a" * 2000)) == "/"
    assert location(_sign_in_from(fresh_browser(), provider, "/%61pi/auth/me")) == "/"


def test_b10_a_refusal_keeps_the_page_for_the_next_try(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    add_provider(client, provider, auto_create=False)
    refused = _sign_in_from(fresh_browser(), provider, "/c/abc123XYZ", sub="nobody", email="no@example.com")
    assert location(refused) == "/login?error=oidc_no_account&next=%2Fc%2Fabc123XYZ"


def test_b10_a_page_cookie_nexbrand_did_not_sign_counts_for_nothing(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    add_provider(client, provider, auto_create=True)
    browser = fresh_browser()
    target = location(browser.get("/api/oidc/sso/start"))
    planted = landing.pack("/c/abc123XYZ")
    assert planted is not None
    encoded, _signature = planted.split(".")
    browser.cookies.set(landing.COOKIE, f"{encoded}.forged", path="/api/oidc")
    assert location(come_back(browser, provider, target)) == "/"


# --- Two instances on one host ---------------------------------------------------------------------------------------


def test_two_instances_on_one_host_keep_their_attempt_cookies_apart(
    client: TestClient, operator: Account, provider: FakeProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_provider(client, provider)
    names = []
    try:
        for suffix in ("", "_allein"):
            monkeypatch.setattr(get_settings(), "cookie_suffix", suffix)
            oidc_store.configure()
            started = fresh_browser().get("/api/oidc/sso/start")
            names.append(started.headers["set-cookie"].split("=", 1)[0])
    finally:
        monkeypatch.undo()
        oidc_store.configure()
    assert names == ["nexbrand_oidc", "nexbrand_oidc_allein"]
    assert nexoidc.current().cookie_name == "nexbrand_oidc" + get_settings().cookie_name_suffix()


# --- While coupled to nexsuite ---------------------------------------------------------------------------------------


def test_while_coupled_nobody_links_or_unlinks_and_an_old_invitation_is_no_way_in(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    add_provider(client, provider)
    make_account("anna")
    member = fresh_browser()
    sign_in(member, accounts_row("anna"))
    link(member, provider, PASSWORD, sub="anna-1")
    suite_fake = provider.network.add(fakes.FakeProvider("https://suite.example.com"))  # type: ignore[attr-defined]
    with SessionLocal() as db:
        _invite, token = accounts.create_invite(db, db.get(Account, operator.id), space_id=None, space_role="",
                                                days=7)
        joined = coupling.couple(oidc_store.couple_store(db), issuer=suite_fake.issuer, client_id=suite_fake.client_id,
                                 client_secret=suite_fake.client_secret, label="nexsuite",
                                 people=[(accounts_row("anna").id, "2")])
        settings_service.save(db, {"suite_state": "connected", oidc_store.COUPLING: joined.as_dict()})
    refused = member.post("/api/oidc/oidc/link", json={"password": PASSWORD})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "managed_by_suite"
    assert member.delete("/api/oidc/sso/link").json()["detail"]["code"] == "managed_by_suite"
    anna = accounts_row("anna").id
    entry = next(row for row in _entries() if row.slug == "sso")
    gone = client.request("DELETE", f"/api/oidc/admin/accounts/{anna}/links/{entry.id}",
                          json={"current_password": PASSWORD})
    assert gone.status_code == 409 and gone.json()["detail"]["code"] == "managed_by_suite"
    assert error_in(fresh_browser().get("/api/oidc/oidc/start", params={"invite": token})) == "invite_invalid"
    # Somebody nexsuite does not give nexbrand is told so, not to ask for an invitation.
    suite_fake.person = {"sub": "999"}
    assert error_in(sign_in_via_oidc(fresh_browser(), suite_fake, slug="oidc")) == "suite_no_account"
    assert ("sso", "anna-1", "anna") in _links(), "anna's own link waits with its provider"


# --- The log ------------------------------------------------------------------------------------------------------


def test_no_secret_and_no_invitation_leaves_a_trace_in_the_log(
    client: TestClient, operator: Account, provider: FakeProvider, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        add_provider(client, provider, auto_create=True)
        browser = fresh_browser()
        target = location(browser.get("/api/oidc/sso/start"))
        params = provider.authorize(target)
        browser.get("/api/oidc/sso/callback", params=params)
    session = browser.cookies.get(SESSION_COOKIE)
    assert session
    for secret in (provider.client_secret, params["state"], params["code"], session):
        assert secret not in caplog.text
    assert "OIDC sign in started at provider sso" in caplog.text
    for line in ("GET /api/oidc/sso/start?invite=AbCdEfGhIjKlMnOp12 -> 303",
                 "GET /api/oidc/sso/callback?code=abc123def&state=zzz999 -> 303"):
        for kept_out in ("AbCdEfGhIjKlMnOp12", "abc123def", "zzz999"):
            assert kept_out not in logs.redact(line)


def test_the_button_pressed_again_after_the_migration_keeps_the_old_address_the_entry_and_its_links(
    client: TestClient, operator: Account
) -> None:
    """Blueprint 01 "Umstieg" 3: the entry ``oidc`` keeps ``/api/oidc/callback`` when the operator presses the
    authentik button again; the provider is its own (found by its client id), so no link is dropped."""
    network = fakes.Network()
    ak = network.add(fakes.FakeAuthentik())
    made = ak.add_provider("nexbrand", "http://testserver/api/oidc/callback", slug="nexbrand")
    issuer = f"{ak.base}/application/o/nexbrand/"
    signer = ak.sign_in_with(issuer, made["client_id"], made["client_secret"])
    nexoidc.use_transport(network.transport())
    try:
        make_account("anna")
        _legacy(signer, label="authentik", issuer=issuer, subjects={"anna": "anna-1"})
        oidc_store.migrate_settings(backup=False)
        result = client.post("/api/oidc/authentik/setup", json={"url": ak.base, "token": ak.token}).json()
        assert result["ok"] and result["links_dropped"] == 0, result
        [row] = _entries()
        assert (row.slug, row.managed, row.redirect_path) == ("oidc", "authentik", "")
        assert len(ak.providers) == 1
        assert ak.providers[0]["redirect_uris"][0]["url"] == "http://testserver/api/oidc/callback"
        signer.person = {"sub": "anna-1"}
        browser = fresh_browser()
        target = location(browser.get("/api/oidc/oidc/start"))
        back = browser.get("/api/oidc/callback", params=signer.authorize(target))
        assert location(back) == "/" and browser.get("/api/auth/me").json()["name"] == "anna"
    finally:
        nexoidc.use_transport(None)



# --- Module 1.0.8: the button asks before another issuer takes the links ---------------------------------------------


def test_another_issuer_for_the_entry_oidc_is_asked_first_and_only_the_confirmation_drops_the_links(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    issuer = "https://auth.example.com/application/o/nexbrand/"
    make_account("anna")
    _legacy(FakeProvider(issuer), label="authentik", issuer=issuer, subjects={"anna": "anna-1"})
    assert oidc_store.migrate_settings(backup=False) is not None
    other = provider.network.add(fakes.FakeAuthentik(base="https://auth2.example.com"))  # type: ignore[attr-defined]
    asked = client.post("/api/oidc/authentik/setup", json={"url": other.base, "token": other.token})
    assert asked.status_code == 200 and asked.json()["ok"] is False, asked.text
    assert [(step["key"], step["reason"]) for step in asked.json()["steps"]] == [("reached", "issuer_change")]
    assert asked.json()["count"] == 1 and asked.json()["links_dropped"] == 0
    assert len(_links()) == 1 and not other.providers, "the question changes nothing, nothing made in authentik"
    # Said no with the explicit false: the same.
    no = client.post("/api/oidc/authentik/setup", json={"url": other.base, "token": other.token,
                                                         "confirm_issuer_change": False})
    assert no.json()["steps"][0]["reason"] == "issuer_change" and len(_links()) == 1
    yes = client.post("/api/oidc/authentik/setup", json={"url": other.base, "token": other.token,
                                                          "confirm_issuer_change": True})
    assert yes.status_code == 200 and yes.json()["ok"], yes.text
    assert yes.json()["links_dropped"] == 1 and _links() == []


def test_while_coupled_the_button_stays_shut_whatever_the_confirmation_says(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    suite_fake = provider.network.add(fakes.FakeProvider("https://suite.example.com"))  # type: ignore[attr-defined]
    other = provider.network.add(fakes.FakeAuthentik(base="https://auth2.example.com"))  # type: ignore[attr-defined]
    with SessionLocal() as db:
        joined = coupling.couple(oidc_store.couple_store(db), issuer=suite_fake.issuer, client_id=suite_fake.client_id,
                                 client_secret=suite_fake.client_secret, label="nexsuite",
                                 people=[(operator.id, "1")])
        settings_service.save(db, {"suite_state": "connected", oidc_store.COUPLING: joined.as_dict()})
    before = _links()
    for confirm in (False, True):
        answer = client.post("/api/oidc/authentik/setup", json={"url": other.base, "token": other.token,
                                                                 "confirm_issuer_change": confirm})
        assert answer.status_code == 200 and answer.json()["ok"] is False, answer.text
        assert [(step["key"], step["reason"]) for step in answer.json()["steps"]] == [("reached", "coupled")]
    assert _links() == before and not other.providers and not other.calls


# --- Module 1.0.8: an invitation at a known link --------------------------------------------------------------------


def test_a_known_person_coming_through_an_invitation_gets_its_rights_on_top_and_never_fewer(
    client: TestClient, operator: Account, provider: FakeProvider
) -> None:
    add_provider(client, provider, slug="authentik", label="authentik")
    with SessionLocal() as db:
        space = Space(name="Team")
        db.add(space)
        db.commit()
        space_id = space.id
    for name in ("anna", "ben"):
        make_account(name)
        member = fresh_browser()
        sign_in(member, accounts_row(name))
        link(member, provider, PASSWORD, slug="authentik", sub=f"{name}-1")

    def role(name: str) -> str | None:
        with SessionLocal() as db:
            return db.scalar(select(Membership.role).where(Membership.space_id == space_id,
                                                          Membership.account_id == accounts_row(name).id))

    def invite(email: str = "") -> str:
        with SessionLocal() as db:
            boss = accounts.by_name(db, "tester")
            assert boss is not None
            return accounts.create_invite(db, boss, space_id=space_id, space_role=WRITE, days=7, email=email)[1]

    # anna has no right in the space: the invitation gives her write access and is used up; her own address stays.
    assert role("anna") is None
    token = invite("someone-else@example.com")
    browser = fresh_browser()
    assert location(sign_in_via_oidc(browser, provider, slug="authentik", invite=token, sub="anna-1")) == "/"
    assert browser.get("/api/auth/me").json()["name"] == "anna"
    assert role("anna") == WRITE and accounts_row("anna").email != "someone-else@example.com"
    with SessionLocal() as db:
        assert accounts.find_invite(db, token) is None, "used up"
    # ben manages the space already: the invitation gives nothing less.
    with SessionLocal() as db:
        db.add(Membership(space_id=space_id, account_id=accounts_row("ben").id, role=MANAGE))
        db.commit()
    sign_in_via_oidc(fresh_browser(), provider, slug="authentik", invite=invite(), sub="ben-1")
    assert role("ben") == MANAGE
    # An invitation used between the start and the return does not keep a known person out.
    gone = invite()
    again = fresh_browser()
    provider.person = {"sub": "anna-1"}
    target = location(again.get("/api/oidc/authentik/start", params={"invite": gone}))
    with SessionLocal() as db:
        found = accounts.find_invite(db, gone)
        assert found is not None and accounts.consume(db, found)
        db.commit()
    assert location(come_back(again, provider, target)) == "/"
    assert again.get("/api/auth/me").json()["name"] == "anna"
