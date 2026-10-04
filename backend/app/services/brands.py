"""Clients, the versions of their design sets, and their projects.

**Versions.** A client's design set lives in versions. A draft changes as often as anybody likes; publishing freezes
it for good, with the day it holds from (``valid_from``, today unless somebody records an older version afterwards).
The current version is the published one with the latest day; "as of" a day is the one that held then. A version
somebody works on next starts as a copy of another, so history is never written over.

**Projects** build on one version and keep it: a newer version changes nothing in a project until somebody lifts it
on purpose. A project's own colours replace a colour of its version by name, or come on top.
"""

from __future__ import annotations

import logging
import re
import secrets
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    DRAFT,
    ORIGINS,
    PUBLISHED,
    Account,
    BrandVersion,
    Client,
    Favorite,
    Project,
    Space,
    Visit,
    utcnow,
)
from . import brandset

logger = logging.getLogger("nexbrand.brands")

#: A client may hold this many versions in all, and this many drafts at once: an AI in a loop must not fill the
#: database.
MAX_VERSIONS = 300
MAX_DRAFTS = 30
MAX_PROJECTS = 300


class BrandError(Exception):
    def __init__(self, code: str, text: str, status: int = 422, **values: Any) -> None:
        super().__init__(text)
        self.code = code
        self.text = text
        self.status = status
        self.values = values


def new_id() -> str:
    return secrets.token_urlsafe(9)


def _text(value: str | None, most: int, code: str, *, required: bool = False) -> str:
    text = " ".join((value or "").split())
    if any(ord(char) < 32 for char in text) or len(text) > most or (required and not text):
        raise BrandError(code, "This value is not valid.")
    return text


def _note(value: str | None, most: int) -> str:
    text = (value or "").strip()
    if len(text) > most or any(ord(char) < 32 and char not in "\n\t" for char in text):
        raise BrandError("invalid_note", "This note is too long.")
    return text


def checked(db: Session, client: Client, data: Any) -> dict[str, Any]:
    try:
        return brandset.clean(data, db, client.space_id)
    except brandset.SetError as exc:
        raise BrandError("invalid_set", exc.text, where=exc.where) from exc


def day(value: str | None) -> str:
    if not value:
        # The day where the server stands (TZ), not in Greenwich: "published today" in the evening is today.
        return datetime.now(UTC).astimezone().date().isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise BrandError("invalid_date", "Not a date.") from exc


# --- Clients ----------------------------------------------------------------------------------------------------


def may_create(db: Session, account: Account) -> bool:
    """Who makes clients here: the operator always, members while the operator lets them (on until switched off)."""
    from ..models import OPERATOR
    from . import settings_service

    return account.role == OPERATOR or bool(settings_service.get(db, "members_create_clients"))


def create_client(
    db: Session, account: Account, name: str, *, sector: str = "", contact: str = "", note: str = "",
    color: str | None = None, label: str | None = "1", data: Any = None, origin: str = "hand", author: str = "",
) -> tuple[Client, BrandVersion | None]:
    """A client with its own group of rights (the account manages it) and, unless ``label`` is None, a first version as
    a draft (empty, or the design set given)."""
    from . import spaces, suite

    if suite.connected(db):
        raise BrandError("managed_by_suite", "Clients are made in nexsuite now.", 409)
    if not may_create(db, account):
        raise BrandError("forbidden", "The operator has not allowed members to make clients.", 403)
    clean = _text(name, 120, "invalid_name", required=True)
    try:
        space = spaces.create(db, account, clean, color, commit=False)
    except spaces.SpaceError as exc:
        raise BrandError(exc.code, exc.text, exc.status) from exc
    client = Client(id=new_id(), space_id=space.id, name=clean,
                    sector=_text(sector, 120, "invalid_sector"), contact=_text(contact, 255, "invalid_contact"),
                    note=_note(note, 4000), created_by=account.id, updated_by=account.name)
    db.add(client)
    db.flush()
    version = None
    if label is not None:
        version = BrandVersion(id=new_id(), client_id=client.id, label=_text(label, 60, "invalid_label", required=True),
                               status=DRAFT, origin=origin if origin in ORIGINS else "hand",
                               author=author or account.display_name or account.name,
                               data=checked(db, client, data if data is not None else brandset.empty()))
        db.add(version)
    db.commit()
    logger.info("Client created id=%s by=%s", client.id, account.name)
    return client, version


def managed(db: Session, client: Client) -> bool:
    """Whether nexsuite keeps this client (its name, sector, contact, colour and who may see it)."""
    from . import suite

    space = db.get(Space, client.space_id)
    return bool(space is not None and space.external_id and suite.connected(db))


LINK_KINDS = ("website", "repo")
MAX_LINKS = 10


def clean_links(value: Any) -> list[dict[str, str]]:
    """A client's addresses: at most ten, each a website or a repository at an http(s) address; doubles go."""
    if not isinstance(value, list) or len(value) > MAX_LINKS:
        raise BrandError("invalid_links", "At most ten addresses.", 422)
    out: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict) or item.get("kind") not in LINK_KINDS:
            raise BrandError("invalid_links", "An address is a website or a repository.", 422)
        url = str(item.get("url") or "").strip()
        if len(url) > 500 or not re.match(r"^https?://[^\s/?#@]+(/[^\s]*)?$", url):
            raise BrandError("invalid_links", "An address starts with http:// or https://.", 422)
        label = " ".join(str(item.get("label") or "").split())[:60]
        if all(seen["url"].rstrip("/") != url.rstrip("/") for seen in out):
            out.append({"kind": str(item["kind"]), "url": url, "label": label})
    return out


def change_client(db: Session, account: Account, client: Client, **fields: Any) -> Client:
    from . import spaces

    kept = {key for key in ("name", "sector", "contact", "color") if fields.get(key) is not None}
    if kept and managed(db, client):
        raise BrandError("managed_by_suite", "This is kept in nexsuite now.", 409)
    space = db.get(Space, client.space_id)
    if fields.get("name") is not None:
        client.name = _text(fields["name"], 120, "invalid_name", required=True)
        if space is not None:
            space.name = spaces.clean_name(client.name[:spaces.MAX_NAME])
    if fields.get("color") is not None and space is not None:
        try:
            space.color = spaces.clean_color(fields["color"], space.color)
        except spaces.SpaceError as exc:
            raise BrandError(exc.code, exc.text, exc.status) from exc
    if fields.get("sector") is not None:
        client.sector = _text(fields["sector"], 120, "invalid_sector")
    if fields.get("contact") is not None:
        client.contact = _text(fields["contact"], 255, "invalid_contact")
    if fields.get("note") is not None:
        client.note = _note(fields["note"], 4000)
    if fields.get("links") is not None:
        client.links = clean_links(fields["links"])
    touch(client, account)
    db.commit()
    return client


def touch(client: Client, account: Account) -> None:
    client.updated_at = utcnow()
    client.updated_by = account.name


def trash(db: Session, client: Client) -> None:
    if managed(db, client):
        raise BrandError("managed_by_suite", "Clients are deleted in nexsuite now.", 409)
    client.deleted_at = utcnow()
    db.commit()
    logger.info("Client moved to the bin id=%s", client.id)


def restore(db: Session, client: Client) -> None:
    if managed(db, client):
        raise BrandError("managed_by_suite", "Clients are restored in nexsuite now.", 409)
    client.deleted_at = None
    db.commit()
    logger.info("Client restored id=%s", client.id)


def purge(db: Session, client: Client) -> None:
    """The client and its group of rights, with the files in it (their bytes go with the next clean-up)."""
    space = db.get(Space, client.space_id)
    db.delete(client)
    if space is not None:
        db.delete(space)
    db.commit()
    logger.info("Client deleted for good id=%s", client.id)


def set_favorite(db: Session, account: Account, client: Client, on: bool) -> None:
    row = db.get(Favorite, (account.id, client.id))
    if on and row is None:
        db.add(Favorite(account_id=account.id, client_id=client.id))
    if not on and row is not None:
        db.delete(row)
    db.commit()


def visit(db: Session, account: Account, client: Client) -> None:
    row = db.get(Visit, (account.id, client.id))
    if row is None:
        db.add(Visit(account_id=account.id, client_id=client.id))
    else:
        row.opened_at = utcnow()
    db.commit()


# --- Versions ---------------------------------------------------------------------------------------------------


def versions(db: Session, client: Client) -> list[BrandVersion]:
    """Published ones by their day, then the drafts by when they were made."""
    rows = list(db.scalars(select(BrandVersion).where(BrandVersion.client_id == client.id)))
    published = sorted((v for v in rows if v.status == PUBLISHED),
                       key=lambda v: (v.valid_from, v.published_at or v.created_at))
    drafts = sorted((v for v in rows if v.status == DRAFT), key=lambda v: v.created_at)
    return published + drafts


def current(db: Session, client: Client) -> BrandVersion | None:
    published = [v for v in versions(db, client) if v.status == PUBLISHED]
    return published[-1] if published else None


def valid_on(db: Session, client: Client, when: str) -> BrandVersion | None:
    """The version that held on a day: the last published one whose day is not after it."""
    when = day(when)
    held = [v for v in versions(db, client) if v.status == PUBLISHED and v.valid_from <= when]
    return held[-1] if held else None


def version_for(db: Session, client: Client, version_id: str) -> BrandVersion:
    row = db.get(BrandVersion, version_id)
    if row is None or row.client_id != client.id:
        raise BrandError("not_found", "Not found.", 404)
    return row


def _free_label(db: Session, client: Client, label: str) -> str:
    """``label``, or with a number behind it when the client already has a version of that name: two collected
    drafts of one day, or a draft named like the published version, could not be told apart (in the list, and in
    the question before a draft is deleted)."""
    names = db.scalars(select(BrandVersion.label).where(BrandVersion.client_id == client.id))
    taken = {name.casefold() for name in names}
    if label.casefold() not in taken:
        return label
    for number in range(2, MAX_VERSIONS + 2):
        tail = f" ({number})"
        candidate = label[:60 - len(tail)] + tail
        if candidate.casefold() not in taken:
            return candidate
    return label


def create_version(
    db: Session, account: Account, client: Client, *, label: str, source: BrandVersion | None = None,
    data: Any = None, note: str = "", origin: str = "hand", author: str = "",
) -> BrandVersion:
    """A new draft: a copy of ``source``, the design set given, or an empty one."""
    count = db.scalar(select(func.count()).select_from(BrandVersion).where(BrandVersion.client_id == client.id)) or 0
    drafts = db.scalar(select(func.count()).select_from(BrandVersion).where(
        BrandVersion.client_id == client.id, BrandVersion.status == DRAFT)) or 0
    if count >= MAX_VERSIONS or drafts >= MAX_DRAFTS:
        raise BrandError("too_many_versions", "This client has as many versions as it may hold.", 409)
    content = data if data is not None else (source.data if source is not None else brandset.empty())
    label = _free_label(db, client, _text(label, 60, "invalid_label", required=True))
    row = BrandVersion(id=new_id(), client_id=client.id, label=label,
                       status=DRAFT, origin=origin if origin in ORIGINS else "hand", note=_note(note, 500),
                       author=author or account.display_name or account.name, data=checked(db, client, content))
    db.add(row)
    touch(client, account)
    db.commit()
    logger.info("Draft made client=%s version=%s origin=%s by=%s", client.id, row.id, row.origin, account.name)
    return row


def change_draft(
    db: Session, account: Account, client: Client, row: BrandVersion, *, label: str | None = None,
    note: str | None = None, data: Any = None,
) -> BrandVersion:
    if row.status != DRAFT:
        raise BrandError("published", "A published version never changes. Make a new draft from it.", 409)
    if label is not None:
        row.label = _text(label, 60, "invalid_label", required=True)
    if note is not None:
        row.note = _note(note, 500)
    if data is not None:
        row.data = checked(db, client, data)
    row.updated_at = utcnow()
    touch(client, account)
    db.commit()
    return row


def publish(
    db: Session, account: Account, client: Client, row: BrandVersion, *, valid_from: str | None = None,
    label: str | None = None, by: str = "",
) -> BrandVersion:
    if row.status != DRAFT:
        raise BrandError("published", "This version is published already.", 409)
    if label is not None:
        row.label = _text(label, 60, "invalid_label", required=True)
    # Checked once more: a file named in it may have gone since it was saved.
    row.data = checked(db, client, row.data)
    row.status = PUBLISHED
    row.valid_from = day(valid_from)
    row.published_at = utcnow()
    row.published_by = by or account.display_name or account.name
    touch(client, account)
    db.commit()
    logger.info("Version published client=%s version=%s from=%s by=%s", client.id, row.id, row.valid_from,
                account.name)
    return row


def delete_draft(db: Session, account: Account, client: Client, row: BrandVersion) -> None:
    if row.status != DRAFT:
        raise BrandError("published", "A published version stays, for the history.", 409)
    if db.scalar(select(func.count()).select_from(Project).where(Project.version_id == row.id)):
        raise BrandError("in_use", "A project builds on this draft. Move the project first.", 409)
    db.delete(row)
    touch(client, account)
    db.commit()
    logger.info("Draft deleted client=%s version=%s label=%s by=%s", client.id, row.id, row.label, account.name)


# --- Projects ---------------------------------------------------------------------------------------------------


def create_project(
    db: Session, account: Account, client: Client, *, name: str, version_id: str, note: str = "",
    own: Any = None,
) -> Project:
    count = db.scalar(select(func.count()).select_from(Project).where(Project.client_id == client.id)) or 0
    if count >= MAX_PROJECTS:
        raise BrandError("too_many_projects", "This client has as many projects as it may hold.", 409)
    version = version_for(db, client, version_id)
    row = Project(id=new_id(), client_id=client.id, name=_text(name, 120, "invalid_name", required=True),
                  version_id=version.id, note=_note(note, 500), own=_own(own))
    db.add(row)
    touch(client, account)
    db.commit()
    logger.info("Project made client=%s project=%s by=%s", client.id, row.id, account.name)
    return row


def _own(value: Any) -> list[dict[str, Any]]:
    try:
        return brandset.clean_colors(value, "own")
    except brandset.SetError as exc:
        raise BrandError("invalid_set", exc.text, where=exc.where) from exc


def project_for(db: Session, client: Client, project_id: str) -> Project:
    row = db.get(Project, project_id)
    if row is None or row.client_id != client.id:
        raise BrandError("not_found", "Not found.", 404)
    return row


def change_project(
    db: Session, account: Account, client: Client, row: Project, *, name: str | None = None,
    note: str | None = None, version_id: str | None = None, own: Any = None,
) -> Project:
    if name is not None:
        row.name = _text(name, 120, "invalid_name", required=True)
    if note is not None:
        row.note = _note(note, 500)
    if version_id is not None:
        row.version_id = version_for(db, client, version_id).id
    if own is not None:
        row.own = _own(own)
    row.updated_at = utcnow()
    touch(client, account)
    db.commit()
    return row


def delete_project(db: Session, account: Account, client: Client, row: Project) -> None:
    """Gone at once: a project holds only its name, a pointer and a few colours, nothing to restore."""
    db.delete(row)
    touch(client, account)
    db.commit()


def project_colors(version: BrandVersion, project: Project) -> list[dict[str, Any]]:
    """The version's colours with the project's own: replacing by name, or added. ``from`` says which is which."""
    own = {color["name"].casefold(): color for color in project.own or []}
    out = []
    for color in version.data.get("colors", []):
        replaced = own.pop(color["name"].casefold(), None)
        out.append({**(replaced or color), "from": "replaced" if replaced else "inherited"})
    out.extend({**color, "from": "own"} for color in own.values())
    return out
