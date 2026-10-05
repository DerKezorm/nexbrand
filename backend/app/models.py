"""The data model.

Everything lives in SQLite, except the files of brands (logos, fonts, examples): those lie as plain files in the
media folder (``services/media_store.py``), named by their id.

A client lives in a space and has a design set in versions. A version's content is one JSON document (``data``),
checked by ``services/brandset.py`` on every write, never trusted as it came.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    return datetime.now(UTC)


class UtcDateTime(TypeDecorator[datetime]):
    """SQLite forgets the time zone. Stored as UTC, read back as UTC with the zone attached."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    pass


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=True)


OPERATOR = "operator"
MEMBER = "member"
ROLES = (OPERATOR, MEMBER)

SIGN_IN_PASSWORD = "password"
SIGN_IN_OIDC = "oidc"

#: Rights in a space, each one including the ones before it: reading; writing (clients, drafts, projects, files,
#: publishing a version, the bin); managing (inviting, giving rights, public pages and reviews, renaming or deleting
#: the space).
READ = "read"
WRITE = "write"
MANAGE = "manage"
SPACE_ROLES = (READ, WRITE, MANAGE)


class Space(Base):
    """The group of rights behind one client: its members and teams with read, write or manage. Nobody sees it as a
    place of its own; every client has exactly one (``Client.space_id``), made and deleted with it. Kept as a table of
    its own because invitations, notices, team grants and the files of a client hang on it, as in the family."""

    __tablename__ = "spaces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    color: Mapped[str] = mapped_column(String(16), default="#2f7bff")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    #: The space's id in nexsuite while nexbrand is connected to it; its rights come from there then.
    external_id: Mapped[str] = mapped_column(String(40), default="")
    #: Set when a manager deleted the space; it lies in the bin with its clients for 30 days.
    deleted_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class Account(Base):
    """A person. The first account is the operator; the others come by invitation or through OIDC."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: Lower case, the name people sign in with. What people see is the display name, when there is one.
    name: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(80), default="")
    #: The version whose "What's new" the account has read or put away.
    whats_new_seen: Mapped[str] = mapped_column(String(32), default="")
    role: Mapped[str] = mapped_column(String(16), default=MEMBER)
    sign_in: Mapped[str] = mapped_column(String(16), default=SIGN_IN_PASSWORD)
    #: Argon2id. Empty for accounts that sign in through OIDC only.
    password_hash: Mapped[str] = mapped_column(String(255), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    oidc_subject: Mapped[str] = mapped_column(String(255), default="")
    #: The interface language chosen in the account menu; empty: the browser's.
    language: Mapped[str] = mapped_column(String(16), default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: Set when nexsuite blocked the person (or does not know it any more): no sign-in, sessions end at once.
    blocked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: The second factor (``services/totp.py``): the seed encrypted with the server secret, empty while off; the
    #: recovery codes as a JSON list of SHA-256 hashes; the time step of the last code taken (no replay).
    totp_secret_enc: Mapped[str] = mapped_column(Text, default="")
    totp_recovery: Mapped[str] = mapped_column(Text, default="")
    totp_last_step: Mapped[int] = mapped_column(Integer, default=0)
    #: The profile picture (``services/avatars.py``): a square WebP drawn anew, loaded only when asked for.
    avatar: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, deferred=True)
    avatar_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: The account's own preferences (start page and the like); only what it chose.
    preferences: Mapped[Any] = mapped_column(JSON, nullable=True)
    #: The account's own AI service (``services/ai.py``): address, model, the key encrypted, and its own switch.
    ai_url: Mapped[str] = mapped_column(String(500), default="")
    ai_model: Mapped[str] = mapped_column(String(200), default="")
    ai_key_enc: Mapped[str] = mapped_column(Text, default="")
    ai_active: Mapped[bool] = mapped_column(Boolean, default=False)
    #: What the device cookies of this account are signed with (``security.device_token``): random per account, so
    #: an account made later under the id of a deleted one knows none of its browsers, and drawn anew on a new
    #: password, a block or unblock and "sign out everywhere", so no browser from before counts as known any more.
    #: Empty (accounts from before it existed): no device is known until the next sign-in.
    device_key: Mapped[str] = mapped_column(String(64), default="")
    #: The moment nexsuite last said this person signed out everywhere (as nexsuite sent it), once it was applied
    #: here: the browsers known before are forgotten once per new moment, not with every sync.
    suite_signed_out: Mapped[str] = mapped_column(String(64), default="")
    #: The person in nexsuite this account belonged to before the last disconnect (B8): connecting again to the same
    #: nexsuite suggests that person first, so an account nexsuite once brought is not made a second time.
    suite_person: Mapped[str] = mapped_column(String(64), default="")
    #: The sign-in link of its own (a provider such as authentik) of an account left out when connecting, set aside
    #: while connected and given back on disconnecting: in ``oidc_subject`` it could pass for a person of nexsuite
    #: whose id looks the same, and take that person's sign-in and rights (Prüfgang 05.10.2026, from nextasks).
    own_subject: Mapped[str] = mapped_column(String(255), default="")
    #: Not stored. Set on the account an API token acts as when the token may see only some spaces.
    key_spaces: ClassVar[frozenset[int] | None] = None
    #: Not stored. True on the account a token acts as: a program never has the operator's powers over other
    #: people's spaces, even when its account is the operator's.
    via_key: ClassVar[bool] = False




def new_device_key() -> str:
    return secrets.token_urlsafe(24)


@event.listens_for(Account, "before_insert")
def _first_device_key(_mapper: Any, _connection: Any, target: Account) -> None:
    if not target.device_key:
        target.device_key = new_device_key()


@event.listens_for(Account.password_hash, "set")
@event.listens_for(Account.blocked_at, "set")
def _forget_devices(target: Account, value: Any, old: Any, _initiator: Any) -> None:
    """A new password, a block or an unblock: the browsers known before are not known any more (whatever the way
    it happens: here, by the operator, or from nexsuite)."""
    if value != old:
        target.device_key = new_device_key()

class AuthSession(Base):
    """A browser session. Only the hash of the token is stored; the token itself lives in the cookie."""

    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
    last_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(255), default="")


class Membership(Base):
    """An account's right in a space. A space without any member belongs to the operator."""

    __tablename__ = "memberships"

    space_id: Mapped[int] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True, index=True)
    role: Mapped[str] = mapped_column(String(16), default=READ)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


TEAM_LOCAL = "local"
TEAM_ADMIN = "admin"
TEAM_SOURCES = (TEAM_LOCAL, TEAM_ADMIN)


class Team(Base):
    """People who work together (planning, design, the shop floor …). A team is not a space: a space says who may see
    what, a team says who works together. A space can give a team a right, and then everybody in the team has it.

    ``source`` says who keeps the members: nexbrand itself, or later the family's admin app (``external_id`` is its
    id then). Only the source changes when that day comes, never the id. The same in every app of the family."""

    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    color: Mapped[str] = mapped_column(String(16), default="#2f7bff")
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    source: Mapped[str] = mapped_column(String(16), default=TEAM_LOCAL)
    #: The admin app's id for ``admin``.
    external_id: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class TeamMember(Base):
    __tablename__ = "team_members"

    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class TeamGrant(Base):
    """A team's right in a space: everybody in the team has it, next to any right of their own (the higher counts)."""

    __tablename__ = "team_grants"

    space_id: Mapped[int] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True, index=True)
    role: Mapped[str] = mapped_column(String(16), default=READ)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class Invite(Base):
    """A link that lets somebody in: into nexbrand (a new account) and, when it names a space, into that space with a
    right. Only the hash of the token is stored; used once, then gone."""

    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    space_id: Mapped[int | None] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), nullable=True)
    #: The right in the space; empty for an invitation into nexbrand only.
    space_role: Mapped[str] = mapped_column(String(16), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)


class SpaceNotice(Base):
    """Something about a space an account should know or answer: an invitation by name (accepted or declined; nobody
    becomes a member without saying yes), or a change the operator made in a space it does not manage."""

    __tablename__ = "space_notices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    space_id: Mapped[int | None] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), nullable=True)
    space_name: Mapped[str] = mapped_column(String(255), default="")
    #: ``invite``, or what the operator did: ``operator_added``, ``operator_role``, ``operator_removed``.
    kind: Mapped[str] = mapped_column(String(24))
    role: Mapped[str] = mapped_column(String(16), default="")
    actor: Mapped[str] = mapped_column(String(64), default="")
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    subject: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    done_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class Client(Base):
    """A client of the agency. Who sees it is decided by its own group of rights (``space_id``, one per client). A
    client has a design set with versions (``BrandVersion``, none yet for a client nexsuite brought) and projects that
    build on one of them."""

    __tablename__ = "clients"

    #: Short and random, so addresses do not reveal how many clients there are.
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    space_id: Mapped[int] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    sector: Mapped[str] = mapped_column(String(120), default="")
    contact: Mapped[str] = mapped_column(String(255), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    #: The client's addresses, for collecting with a click: ``[{"kind": "website"|"repo", "url", "label"}]``. nexbrand's
    #: own, like the note: also for a client nexsuite keeps. None: none yet.
    links: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    #: Who changed it last, as a name (kept when the account goes).
    updated_by: Mapped[str] = mapped_column(String(64), default="")
    deleted_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


DRAFT = "draft"
PUBLISHED = "published"
VERSION_STATES = (DRAFT, PUBLISHED)
#: Where a version came from: made by hand, collected from sources, proposed over MCP, chosen by the client in a
#: review.
ORIGINS = ("hand", "collect", "mcp", "review")


class BrandVersion(Base):
    """One version of a client's design set: colours, fonts, logos, type sizes, rules, examples (``data``, as
    ``services/brandset.py`` checked it). A draft changes; a published version never does again. The newest published
    one is the current one."""

    __tablename__ = "brand_versions"

    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(16), default=DRAFT)
    #: The day from which a published version holds (ISO date), chosen when publishing; empty for drafts.
    valid_from: Mapped[str] = mapped_column(String(10), default="")
    origin: Mapped[str] = mapped_column(String(16), default="hand")
    #: Who made it, as shown: a name, a token's name, "the client".
    author: Mapped[str] = mapped_column(String(120), default="")
    note: Mapped[str] = mapped_column(String(500), default="")
    data: Mapped[Any] = mapped_column(JSON)
    #: A version of a project (``services/inherit.py``); None: of the client's own design set. Not a foreign key:
    #: projects point at versions already (``Project.version_id``), and a circle of keys cannot be created in order.
    #: ``brands.delete_project`` takes the versions along; the client's cascade does when the client goes.
    project_id: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    #: For a project's version: the client's version it stands on. Not a foreign key: deleting a draft somebody
    #: stands on is refused in ``services/brands.py``.
    base_id: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    #: The version this one was made from, and its name then (kept when that one is deleted). None: started from a
    #: design set given, or empty, or made before 05.10.2026.
    source_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    source_label: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    published_by: Mapped[str] = mapped_column(String(120), default="")


class Project(Base):
    """A client's project (an app, a product, a campaign) with a design set of its own: versions like the client's,
    each standing on a version of the client's and taking each part from it, adding to it, or having it its own
    (``services/inherit.py``). It stays on that version until somebody lifts it, so a reprint looks like the first
    print. ``version_id`` follows the client version its newest version stands on; ``own`` is from before
    05.10.2026 (moved into a first version at start, ``services/regroup.py``)."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    #: Deleting a draft a project builds on is refused in ``services/brands.py``; the cascade is for the client going.
    version_id: Mapped[str] = mapped_column(ForeignKey("brand_versions.id", ondelete="CASCADE"), index=True)
    own: Mapped[Any] = mapped_column(JSON, nullable=True)
    note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class Media(Base):
    """A file of a brand: a logo, a font, an example. The bytes lie in the media folder under the id; the space's
    rights apply. Versions point at files by id; a file nothing points at any more goes after a day
    (``services/cleanup.py``)."""

    __tablename__ = "media"
    __table_args__ = (Index("media_space_hash", "space_id", "sha256"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    space_id: Mapped[int] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    #: What the content is, found from the bytes, never from the name.
    kind: Mapped[str] = mapped_column(String(16))
    mime: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    pages: Mapped[int] = mapped_column(Integer, default=0)
    #: Named once as the file of a font kept in the house (by any version, draft, project or review direction): never
    #: out over a public way again, even when nothing names it so any more. Freed only by uploading it anew.
    kept_in_house: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class Favorite(Base):
    """A client an account starred."""

    __tablename__ = "favorites"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class Visit(Base):
    """When an account last opened a client, for "Recent"."""

    __tablename__ = "visits"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True)
    opened_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class Share(Base):
    """A public read-only page of a client's design set, for a printer or a photographer: anybody with the link
    looks, nobody changes anything. Fonts kept "internal" show only by name; the checks never show."""

    __tablename__ = "shares"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: The secret part of the address. Kept, so the link can be copied again; it only ever opens this one client.
    token: Mapped[str] = mapped_column(String(64), unique=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    space_id: Mapped[int] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    #: A fixed published version; empty: always the current one (of the project, with ``project_id``).
    version_id: Mapped[str | None] = mapped_column(ForeignKey("brand_versions.id", ondelete="CASCADE"), nullable=True)
    #: A page of one project; empty: of the client's own design set.
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    label: Mapped[str] = mapped_column(String(120), default="")
    views: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: Argon2id; empty: no password.
    password_hash: Mapped[str] = mapped_column(String(255), default="")


class Review(Base):
    """A draft put before the client: one or more directions on a sample page, comments, and the client's choice,
    which becomes the next published version. Anybody with the link takes part; nobody needs an account."""

    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    space_id: Mapped[int] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    #: The draft the choice is written into.
    version_id: Mapped[str] = mapped_column(ForeignKey("brand_versions.id", ondelete="CASCADE"), index=True)
    #: The directions, each a whole design set (``services/brandset.py``) with an id, a label and a short reason.
    variants: Mapped[Any] = mapped_column(JSON)
    #: ``open``, ``chosen`` (the client chose, the draft became a version) or ``closed`` (withdrawn).
    status: Mapped[str] = mapped_column(String(16), default="open")
    chosen: Mapped[str] = mapped_column(String(16), default="")
    chosen_by: Mapped[str] = mapped_column(String(80), default="")
    chosen_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: Who the agency is, as the client sees it on the page.
    sender: Mapped[str] = mapped_column(String(120), default="")
    #: What the draft is called once the client chose ("1.0").
    label: Mapped[str] = mapped_column(String(60), default="")
    #: A few words from the agency at the top of the page.
    message: Mapped[str] = mapped_column(String(1000), default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: When somebody of the agency last looked at it: what the client did after that is new (``brands.review_news``).
    seen_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class ReviewComment(Base):
    __tablename__ = "review_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"), index=True)
    variant: Mapped[str] = mapped_column(String(16))
    #: The example of the direction it is about (a media id of its ``samples``); None: the direction as a whole.
    sample: Mapped[str | None] = mapped_column(String(40), nullable=True)
    author: Mapped[str] = mapped_column(String(80))
    text: Mapped[str] = mapped_column(String(2000))
    #: True for a comment from the agency's side, written in nexbrand.
    agency: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class AiEvent(Base):
    """What went out to an account's AI service, word for word, encrypted: the proof of what left the house. Kept
    14 days (``services/ai.py``), cleared at once on request; a failure is in it too, a request refused before
    sending is not."""

    __tablename__ = "ai_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, index=True)
    model: Mapped[str] = mapped_column(String(200), default="")
    task: Mapped[str] = mapped_column(String(32), default="")
    #: The request body as sent (JSON), encrypted with the server secret under a context of its own.
    body_enc: Mapped[str] = mapped_column(Text, default="")
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(String(64), default="")


class ApiToken(Base):
    """A token an account made for programs (``/api/v1``). Only the SHA-256 is stored."""

    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    #: ``read`` or ``write``.
    level: Mapped[str] = mapped_column(String(8))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    prefix: Mapped[str] = mapped_column(String(16))
    #: The ids of the spaces the token may see, of those its account may read; empty (None): all of them.
    spaces: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    blocked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    warned_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


__all__ = [
    "DRAFT",
    "MANAGE",
    "MEMBER",
    "OPERATOR",
    "ORIGINS",
    "PUBLISHED",
    "READ",
    "ROLES",
    "SIGN_IN_OIDC",
    "SIGN_IN_PASSWORD",
    "SPACE_ROLES",
    "TEAM_ADMIN",
    "TEAM_LOCAL",
    "TEAM_SOURCES",
    "VERSION_STATES",
    "WRITE",
    "Account",
    "AiEvent",
    "ApiToken",
    "AuthSession",
    "Base",
    "BrandVersion",
    "Client",
    "Favorite",
    "Invite",
    "Media",
    "Membership",
    "Project",
    "Review",
    "ReviewComment",
    "Setting",
    "Share",
    "Space",
    "SpaceNotice",
    "Team",
    "TeamGrant",
    "TeamMember",
    "Visit",
    "utcnow",
]
