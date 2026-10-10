"""nexbrand's side of the shared sign-in module ``vendor/nexoidc``: the ``Store`` over its tables, the start-up
configuration, and the migration from the single provider of the settings to the list.

The module (the shared blueprint "Anmeldung mit OIDC und authentik") runs the protocol, decides who an identity is
and keeps the provider list; it never sees a database. What is nexbrand's own lives here: accounts and their names,
the rights an invitation brings into a client, the address an account takes from its provider, the encryption of
the client secrets with the server secret, and the coupling to nexsuite as nexbrand keeps it (``services/suite.py``).

A ``SqlStore`` works inside one SQLAlchemy session, one request. The module commits when an outcome is settled and
rolls back when it refuses after a write (a consumed invitation comes back that way). ``OneTransaction`` is the same
store whose commits only flush: the coupling and the migration write their part through it, and nexbrand commits
once, together with its own settings.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .. import __version__
from ..config import get_settings
from ..db import SessionLocal
from ..models import (
    MEMBER,
    SIGN_IN_OIDC,
    SIGN_IN_PASSWORD,
    Account,
    OidcLink,
    OidcProvider,
    utcnow,
)
from ..models import Invite as InviteRow
from ..security import decrypt_secret, encrypt_secret
from ..vendor import nexoidc
from ..vendor.nexoidc import (
    MANAGED_NEXSUITE,
    AccountState,
    Invite,
    Link,
    Provider,
    ProviderValues,
    coupling,
    migrate,
    secret_context,
)
from . import accounts, settings_service

logger = logging.getLogger("nexbrand.oidc")

APP_NAME = "nexbrand"
#: Where nexbrand's sign-in and account pages are, as the module sends the browser there.
LOGIN_PAGE = "/login"
ACCOUNT_PAGE = "/account"
HOME = "/"
#: Longest account name (``accounts.NAME_PATTERN``).
NAME_MAX = 64
_NUMBERED = re.compile(r"^(.*?)(-\d+)$")
#: The setting that keeps the coupling to nexsuite (``coupling.Coupling.as_dict``) until nexbrand uncouples.
COUPLING = "suite_coupling"


def _public_url() -> str:
    with SessionLocal() as db:
        return settings_service.public_url(db)


def _server_secret() -> str:
    return get_settings().resolved_secret_key()


def configure() -> None:
    """Tell the module who it runs in; called once at start-up (and by the tests)."""
    nexoidc.configure(
        nexoidc.AppConfig(
            app_name=APP_NAME,
            server_secret=_server_secret,
            public_url=_public_url,
            login_page=LOGIN_PAGE,
            account_page=ACCOUNT_PAGE,
            home=HOME,
            # Two instances on one host (the test stands :8540 and :8541) keep their attempt cookies apart.
            cookie_suffix=get_settings().cookie_name_suffix(),
        )
    )


def clean_name(raw: str) -> str:
    """An account name from what the provider suggests: lower case, nexbrand's characters, at most 64; a number at
    the end (``max-2``) survives the cut. Empty when nothing usable is left."""
    cleaned = re.sub(r"[^a-z0-9._-]", "-", raw.strip().lower()).strip("-._")
    if len(cleaned) > NAME_MAX:
        numbered = _NUMBERED.match(cleaned)
        suffix = numbered.group(2) if numbered else ""
        stem = numbered.group(1) if numbered else cleaned
        cleaned = stem[: NAME_MAX - len(suffix)].rstrip("-._") + suffix
    return cleaned if accounts.NAME_PATTERN.match(cleaned) else ""


def has_links(db: Session, account_id: int) -> bool:
    return db.scalar(select(OidcLink.id).where(OidcLink.account_id == account_id).limit(1)) is not None


def follows_provider(account: Account) -> bool:
    """An account that signs in through a provider only: its address is the provider's and follows it. Every other
    account is only offered the provider's address (My account), never given it (blueprint 01)."""
    return account.sign_in == SIGN_IN_OIDC and not account.password_hash


def address_taken(db: Session, email: str, own_id: int) -> bool:
    """Whether another account has this address already: nexbrand never gives one address to two accounts."""
    return (
        db.scalar(
            select(Account.id).where(func.lower(Account.email) == email.strip().lower(), Account.id != own_id).limit(1)
        )
        is not None
    )


def take_address(db: Session, account: Account, email: str | None) -> bool:
    """The provider's address becomes the account's (marked as from the provider, so it goes with the last link).
    False when there is none, it is no address, or another account has it."""
    clean = (email or "").strip()[:255]
    if not clean or not accounts.EMAIL_PATTERN.match(clean) or address_taken(db, clean, account.id):
        return False
    account.email = clean
    account.email_from_provider = True
    return True


class SqlStore:
    """``nexoidc.Store`` over ``oidc_providers`` and ``oidc_links``, inside one session."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Providers -------------------------------------------------------------------------------------------------

    def _provider(self, row: OidcProvider | None) -> Provider | None:
        if row is None:
            return None
        return Provider(
            id=row.id,
            slug=row.slug,
            label=row.label,
            issuer=row.issuer,
            client_id=row.client_id,
            client_secret=decrypt_secret(row.client_secret_enc, secret_context(row.id)),
            scopes=row.scopes,
            enabled=row.enabled,
            auto_create=row.auto_create,
            trusts_second_factor=row.trusts_second_factor,
            managed=row.managed,
            position=row.position,
            redirect_path=row.redirect_path,
            created_at=row.created_at,
        )

    def list_providers(self) -> list[Provider]:
        rows = self.db.scalars(select(OidcProvider).order_by(OidcProvider.position, OidcProvider.id))
        return [provider for provider in (self._provider(row) for row in rows) if provider is not None]

    def get_provider(self, provider_id: int) -> Provider | None:
        return self._provider(self.db.get(OidcProvider, provider_id))

    def provider_by_slug(self, slug: str) -> Provider | None:
        return self._provider(self.db.scalar(select(OidcProvider).where(OidcProvider.slug == slug)))

    @staticmethod
    def _apply(row: OidcProvider, values: ProviderValues) -> None:
        row.slug, row.label, row.issuer, row.client_id = values.slug, values.label, values.issuer, values.client_id
        row.scopes, row.enabled, row.auto_create = values.scopes, values.enabled, values.auto_create
        row.trusts_second_factor, row.managed, row.position = (
            values.trusts_second_factor,
            values.managed,
            values.position,
        )
        row.redirect_path = values.redirect_path

    def insert_provider(self, values: ProviderValues) -> Provider:
        row = OidcProvider()
        self._apply(row, values)
        self.db.add(row)
        self.db.flush()
        row.client_secret_enc = encrypt_secret(values.client_secret or "", secret_context(row.id))
        self.db.flush()
        provider = self._provider(row)
        assert provider is not None
        return provider

    def update_provider(self, provider_id: int, values: ProviderValues) -> Provider:
        row = self.db.get(OidcProvider, provider_id)
        assert row is not None
        self._apply(row, values)
        if values.client_secret is not None:
            row.client_secret_enc = encrypt_secret(values.client_secret, secret_context(row.id))
        self.db.flush()
        provider = self._provider(row)
        assert provider is not None
        return provider

    def delete_provider(self, provider_id: int) -> None:
        # Foreign keys are on (db.py), the links would go anyway; said here so that nothing depends on a pragma.
        self.drop_links(provider_id)
        self.db.execute(delete(OidcProvider).where(OidcProvider.id == provider_id))

    def _managed(self, provider_id: int) -> str:
        return str(self.db.scalar(select(OidcProvider.managed).where(OidcProvider.id == provider_id)) or "")

    # --- Links -----------------------------------------------------------------------------------------------------

    @staticmethod
    def _link(row: OidcLink) -> Link:
        return Link(row.provider_id, row.subject, row.account_id, row.issuer, row.email, row.created_at,
                    row.last_used_at)

    def find_link(self, provider_id: int, subject: str) -> Link | None:
        row = self.db.scalar(select(OidcLink).where(OidcLink.provider_id == provider_id, OidcLink.subject == subject))
        return self._link(row) if row else None

    def links_of_provider(self, provider_id: int) -> list[Link]:
        rows = self.db.scalars(select(OidcLink).where(OidcLink.provider_id == provider_id).order_by(OidcLink.id))
        return [self._link(row) for row in rows]

    def links_of_account(self, account_id: int) -> list[Link]:
        rows = self.db.scalars(select(OidcLink).where(OidcLink.account_id == account_id).order_by(OidcLink.id))
        return [self._link(row) for row in rows]

    def add_link(self, link: Link) -> None:
        self.db.add(OidcLink(provider_id=link.provider_id, subject=link.subject, account_id=link.account_id,
                             issuer=link.issuer, email=link.email))
        self.db.flush()
        self._address(link.provider_id, link.account_id, link.email)

    def remove_link(self, provider_id: int, account_id: int) -> bool:
        result = self.db.execute(
            delete(OidcLink).where(OidcLink.provider_id == provider_id, OidcLink.account_id == account_id)
        )
        removed = bool(result.rowcount)  # type: ignore[attr-defined]
        if removed:
            self._forget_provider_address(account_id)
        return removed

    def drop_links(self, provider_id: int) -> int:
        holders = set(self.db.scalars(select(OidcLink.account_id).where(OidcLink.provider_id == provider_id)))
        result = self.db.execute(delete(OidcLink).where(OidcLink.provider_id == provider_id))
        for account_id in holders:
            self._forget_provider_address(account_id)
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    def _forget_provider_address(self, account_id: int) -> None:
        """No link left for the account: an address that came from a provider goes too; one of its own (from the
        invitation, from nexsuite, set by hand) stays, and so does every address while another link holds."""
        if has_links(self.db, account_id):
            return
        account = self.db.get(Account, account_id)
        if account is not None and account.email_from_provider:
            account.email = ""
            account.email_from_provider = False

    def touch_link(self, provider_id: int, subject: str, email: str | None) -> None:
        self.db.execute(
            update(OidcLink)
            .where(OidcLink.provider_id == provider_id, OidcLink.subject == subject)
            .values(last_used_at=utcnow(), email=email)
        )
        account_id = self.db.scalar(
            select(OidcLink.account_id).where(OidcLink.provider_id == provider_id, OidcLink.subject == subject)
        )
        if account_id is not None:
            self._address(provider_id, account_id, email)

    def _address(self, provider_id: int, account_id: int, email: str | None) -> None:
        """What the provider says about the address: an account through the provider only follows it, every other one
        is offered it on its account page. While coupled the address of nexsuite's people is the directory's
        (``services/suite.py``), never the token's."""
        if not email or self._managed(provider_id) == MANAGED_NEXSUITE:
            return
        account = self.db.get(Account, account_id)
        if account is not None and follows_provider(account):
            take_address(self.db, account, email)

    # --- Accounts --------------------------------------------------------------------------------------------------

    def account_state(self, account_id: int) -> AccountState | None:
        row = self.db.get(Account, account_id)
        if row is None:
            return None
        return AccountState(
            id=row.id,
            name=row.name,
            blocked=row.blocked_at is not None,
            # An account nexsuite signs in keeps its password for a disconnect, but cannot use it while connected.
            has_password=row.sign_in == SIGN_IN_PASSWORD and bool(row.password_hash),
            has_second_factor=bool(row.totp_secret_enc),
        )

    def clean_name(self, raw: str) -> str:
        return clean_name(raw)

    def name_taken(self, name: str) -> bool:
        return accounts.by_name(self.db, name) is not None

    def create_account(self, name: str, *, invite: Invite | None, email: str | None) -> int:
        row = Account(name=name, role=MEMBER, sign_in=SIGN_IN_OIDC, whats_new_seen=__version__)
        self.db.add(row)
        self.db.flush()
        take_address(self.db, row, email)
        if invite is not None and isinstance(invite.rights, InviteRow):
            accounts.redeem(self.db, invite.rights, row, consumed=True, commit=False)
        logger.info("Account created name=%s role=%s sign_in=oidc", row.name, MEMBER)
        return row.id

    # --- Invitations -----------------------------------------------------------------------------------------------

    def find_invite(self, key: str) -> Invite | None:
        from . import suite

        if suite.connected(self.db):
            # Connected, accounts come from nexsuite: an old invitation is no way in (C9).
            return None
        row = accounts.find_invite(self.db, key)
        return Invite(key=key, id=row.id, rights=row) if row is not None else None

    def consume_invite(self, invite: Invite) -> bool:
        row = invite.rights
        return isinstance(row, InviteRow) and accounts.consume(self.db, row)

    # --- Transaction -----------------------------------------------------------------------------------------------

    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()


class OneTransaction(SqlStore):
    """The store for the coupling and the migration: the module's commits only flush, and nexbrand commits once,
    together with the settings that say what happened (connected, the coupling kept for the way back)."""

    def commit(self) -> None:
        self.db.flush()


def coupled_entry(db: Session) -> Provider | None:
    """The entry of nexsuite while nexbrand is coupled to it, else None."""
    row = db.scalar(select(OidcProvider).where(OidcProvider.managed == MANAGED_NEXSUITE).limit(1))
    return SqlStore(db)._provider(row)


# --- The migration from the single provider of the settings (blueprint 01 "Umstieg", 06 "Wanderung") --------------

#: The settings of the single provider before the list. They stay readable for one version (the way back), then go.
LEGACY_KEYS = ("oidc_issuer", "oidc_client_id", "oidc_client_secret_enc", "oidc_provider_name", "oidc_auto_create")
#: Set once the settings were looked at: an operator who later removes every entry must not get the old provider
#: back at the next start.
MIGRATED = "oidc_list_migrated"
#: nexbrand asked no code after the provider before the list: the migrated entries keep that (blueprint 06).
TRUSTED_BEFORE = True


def _legacy(values: dict[str, object]) -> migrate.Legacy:
    label = str(values.get("oidc_provider_name") or "")
    return migrate.Legacy(
        issuer=str(values.get("oidc_issuer") or ""),
        client_id=str(values.get("oidc_client_id") or ""),
        # Sealed without a context before the list; the entry seals it anew under its own (``secret_context``).
        client_secret=decrypt_secret(str(values.get("oidc_client_secret_enc") or "")),
        label=label,
        auto_create=bool(values.get("oidc_auto_create")),
        # The authentik button of nexbrand 0.1 named the provider "authentik"; the form never did by itself.
        set_up_by_button=label == "authentik",
    )


def legacy_plan(db: Session) -> migrate.Plan | None:
    """The entry ``oidc`` and its links the old settings become; None when no provider was set up."""
    subjects = [
        (account_id, subject)
        for account_id, subject in db.execute(
            select(Account.id, Account.oidc_subject).where(Account.oidc_subject != "").order_by(Account.id)
        )
    ]
    return migrate.plan(_legacy(settings_service.get_all(db)), subjects, trusts_second_factor=TRUSTED_BEFORE)


def _coupled_at_migration(db: Session) -> bool:
    from . import suite

    return suite.connected(db) and bool(settings_service.get(db, "oidc_issuer"))


def coupled_pairs(db: Session) -> tuple[list[tuple[int, str]], list[tuple[int, str]], list[int]]:
    """For an instance connected to nexsuite before the list: which account is which person (``oidc_subject`` of the
    accounts nexsuite knew), the own links set aside since connecting (``own_subject``, issued by the own provider),
    and the accounts that lose a person to another.

    ``oidc_subject`` of a connected instance is nexsuite's, never the own provider's: it becomes a link at nexsuite's
    entry or nothing, never a link at an own entry (a subject only holds with its issuer; an authentik user with the
    same ``sub`` would otherwise come in as that account). Per subject one account: the one marked for that very
    person (``suite_person``, the operator's choice when connecting and every sync since), then one not blocked, then
    the oldest; the others lose it and are blocked, as the sync before the list blocked an account that did not keep a
    subject (``_settle_subjects``). An account nexsuite never knew (blocked, unmarked) gets no link from it."""
    rows = list(db.scalars(select(Account).order_by(Account.id)))

    def claims(row: Account) -> bool:
        return bool(row.oidc_subject) and (
            row.suite_person == row.oidc_subject or (not row.suite_person and row.blocked_at is None)
        )

    people: list[tuple[int, str]] = []
    taken: set[str] = set()
    losers: list[int] = []
    for row in sorted((row for row in rows if claims(row)),
                      key=lambda row: (row.suite_person != row.oidc_subject, row.blocked_at is not None, row.id)):
        if row.oidc_subject in taken:
            losers.append(row.id)
            continue
        taken.add(row.oidc_subject)
        people.append((row.id, row.oidc_subject))
    own = [(row.id, row.own_subject) for row in rows if row.own_subject]
    return people, own, losers


def migration_due(db: Session) -> bool:
    if settings_service.get(db, MIGRATED) or db.scalar(select(func.count()).select_from(OidcProvider)):
        return False
    return _coupled_at_migration(db) or legacy_plan(db) is not None


def _migrate_coupled(db: Session) -> Provider | None:
    """Connected to nexsuite at the moment: the own provider from before the connection (kept for the way back in
    ``suite_saved``) becomes the entry ``oidc`` with the own links, set aside at once (it waits as ``oidc-own``);
    nexsuite becomes the coupled entry with the accounts' persons. One transaction with the settings."""
    values = settings_service.get_all(db)
    saved = values.get("suite_saved") if isinstance(values.get("suite_saved"), dict) else {}
    own = _legacy({key: saved.get(key) for key in LEGACY_KEYS}) if isinstance(saved, dict) else None
    people, own_subjects, losers = coupled_pairs(db)
    keeper = int(values.get("suite_emergency_account") or 0)
    for account_id in losers:
        row = db.get(Account, account_id)
        if row is not None and row.id != keeper and row.blocked_at is None:
            row.blocked_at = utcnow()
    store = OneTransaction(db)
    joined = migrate.apply_coupled(
        store,
        nexsuite=_legacy(values),
        own=own,
        people=people,
        own_subjects=own_subjects,
        trusts_second_factor=TRUSTED_BEFORE,
        label=str(values.get("oidc_provider_name") or "") or "nexsuite",
    )
    if joined is None:
        db.rollback()
        return None
    settings_service.save(db, {COUPLING: joined.as_dict(), MIGRATED: True}, commit=False)
    db.commit()
    logger.warning("OIDC: the coupled instance moved to the provider list, %d persons, %d own links",
                   len(people), len(own_subjects))
    return store.get_provider(joined.provider_id)


def migrate_settings(*, backup: bool = True) -> Provider | None:
    """Once, at the first start with the list: the provider of the settings becomes the entry ``oidc`` with a link
    per stored subject; ``/api/oidc/callback`` keeps signing in. Connected to nexsuite, nexsuite becomes the coupled
    entry and the own provider waits aside. A backup goes first (the way back). Nothing happens when there was no
    provider or the list has entries already."""
    with SessionLocal() as db:
        if not migration_due(db):
            if not settings_service.get(db, MIGRATED):
                settings_service.save(db, {MIGRATED: True})
            return None
    if backup:
        from . import backups

        backups.create(kind=backups.UPDATE, note="before the sign-in provider list")
    with SessionLocal() as db:
        if not migration_due(db):
            return None
        if _coupled_at_migration(db):
            return _migrate_coupled(db)
        entry = migrate.apply(SqlStore(db), legacy_plan(db))
        settings_service.save(db, {MIGRATED: True})
        return entry


def couple_store(db: Session) -> OneTransaction:
    """The store the coupling writes through (``services/suite.py``)."""
    return OneTransaction(db)


__all__ = [
    "COUPLING",
    "MIGRATED",
    "OneTransaction",
    "SqlStore",
    "clean_name",
    "configure",
    "coupled_entry",
    "coupling",
    "follows_provider",
    "migrate_settings",
    "take_address",
]
