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

from sqlalchemy import event, func, or_, select, update
from sqlalchemy.orm import Session

from ..models import (
    DRAFT,
    ORIGINS,
    PUBLISHED,
    Account,
    BrandVersion,
    Client,
    Favorite,
    Media,
    Project,
    Review,
    Space,
    Visit,
    utcnow,
)
from . import brandset, inherit

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
    """The client and its group of rights, with the files in it (their bytes go with the next clean-up). Not one
    nexsuite keeps: deleted here for good, nexsuite would bring it back as an empty client under a new id (B6)."""
    if managed(db, client):
        raise BrandError("managed_by_suite", "Clients are deleted for good in nexsuite now.", 409)
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


def _in_order(rows: list[BrandVersion]) -> list[BrandVersion]:
    published = sorted((v for v in rows if v.status == PUBLISHED),
                       key=lambda v: (v.valid_from, v.published_at or v.created_at))
    drafts = sorted((v for v in rows if v.status == DRAFT), key=lambda v: v.created_at)
    return published + drafts


def versions(db: Session, client: Client) -> list[BrandVersion]:
    """The client's own versions (not its projects'): published ones by their day, then the drafts."""
    return _in_order(list(db.scalars(select(BrandVersion).where(BrandVersion.client_id == client.id,
                                                                BrandVersion.project_id.is_(None)))))


def all_versions(db: Session, client: Client) -> list[BrandVersion]:
    """The client's and all its projects' versions (for its files)."""
    return list(db.scalars(select(BrandVersion).where(BrandVersion.client_id == client.id)))


def project_versions(db: Session, project: Project) -> list[BrandVersion]:
    return _in_order(list(db.scalars(select(BrandVersion).where(BrandVersion.project_id == project.id))))


def project_current(db: Session, project: Project) -> BrandVersion | None:
    published = [v for v in project_versions(db, project) if v.status == PUBLISHED]
    return published[-1] if published else None


def project_shown(db: Session, project: Project) -> BrandVersion | None:
    """The version a project is shown and handed out with: the current one, or else its newest draft."""
    rows = project_versions(db, project)
    return project_current(db, project) or (rows[-1] if rows else None)


def effective(db: Session, row: BrandVersion) -> dict[str, Any]:
    """The design set a version shows: the client's own as it is, a project's on the client version it stands on."""
    if row.project_id is None:
        return row.data
    base = db.get(BrandVersion, row.base_id) if row.base_id else None
    return inherit.resolve(base.data if base is not None else brandset.empty(), row.data)


def _internal_of(row: object) -> set[str]:
    if isinstance(row, BrandVersion):
        return brandset.internal_media(row.data if isinstance(row.data, dict) else None)
    if isinstance(row, Review):
        found: set[str] = set()
        for variant in row.variants or []:
            found |= brandset.internal_media(variant.get("data") if isinstance(variant, dict) else None)
        return found
    return set()


@event.listens_for(Session, "after_flush")
def _mark_kept_in_house(session: Session, _context: object) -> None:
    """Whatever version, draft, project or review direction is written with a font kept in the house marks its files
    for good (``Media.kept_in_house``): deleting that draft later does not let them out again."""
    found: set[str] = set()
    for row in [*session.new, *session.dirty]:
        found |= _internal_of(row)
    if found:
        session.connection().execute(
            update(Media).where(Media.id.in_(found), Media.kept_in_house.is_(False)).values(kept_in_house=True))


def mark_kept_in_house(db: Session) -> int:
    """At start: the marks for everything written before there were marks. How many files got one."""
    found: set[str] = set()
    for data in db.scalars(select(BrandVersion.data)):
        found |= brandset.internal_media(data if isinstance(data, dict) else None)
    for variants in db.scalars(select(Review.variants)):
        for variant in variants or []:
            found |= brandset.internal_media(variant.get("data") if isinstance(variant, dict) else None)
    if not found:
        return 0
    result = db.execute(update(Media).where(Media.id.in_(found), Media.kept_in_house.is_(False))
                        .values(kept_in_house=True))
    db.commit()
    return int(getattr(result, "rowcount", 0) or 0)


def kept_in_house(db: Session, space_id: int) -> set[str]:
    """Every file of the client that is or ever was the file of a font kept in the house, by any version, draft,
    project or review direction. Such a file never goes out over a public page, a review or a token, whatever else
    names it: an example, a logo download, an older version that called the same font free (A4)."""
    clients = select(Client.id).where(Client.space_id == space_id)
    found: set[str] = set(db.scalars(select(Media.id).where(Media.space_id == space_id, Media.kept_in_house.is_(True))))
    for data in db.scalars(select(BrandVersion.data).where(BrandVersion.client_id.in_(clients))):
        found |= brandset.internal_media(data)
    for variants in db.scalars(select(Review.variants).where(Review.client_id.in_(clients))):
        for variant in variants or []:
            found |= brandset.internal_media(variant.get("data") if isinstance(variant, dict) else None)
    return found


def for_public(db: Session, data: dict[str, Any], space_id: int) -> dict[str, Any]:
    """The design set as a page outside or a program sees it: ``brandset.for_public`` with every file the client
    keeps in the house (``kept_in_house``)."""
    return brandset.for_public(data, kept_in_house(db, space_id))


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


def _free_label(db: Session, client: Client, label: str, project: Project | None = None) -> str:
    """``label``, or with a number behind it when the client already has a version of that name: two collected
    drafts of one day, or a draft named like the published version, could not be told apart (in the list, and in
    the question before a draft is deleted)."""
    names = db.scalars(select(BrandVersion.label).where(
        BrandVersion.client_id == client.id,
        BrandVersion.project_id == project.id if project is not None else BrandVersion.project_id.is_(None)))
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
    data: Any = None, note: str = "", origin: str = "hand", author: str = "", project: Project | None = None,
    base: BrandVersion | None = None,
) -> BrandVersion:
    """A new draft: a copy of ``source``, the design set given, or an empty one. With both, the set given is the
    content and ``source`` is kept as where it came from (a redesign over MCP, a collected logo on the current
    version)."""
    count = db.scalar(select(func.count()).select_from(BrandVersion).where(BrandVersion.client_id == client.id)) or 0
    drafts = db.scalar(select(func.count()).select_from(BrandVersion).where(
        BrandVersion.client_id == client.id, BrandVersion.status == DRAFT)) or 0
    if count >= MAX_VERSIONS or drafts >= MAX_DRAFTS:
        raise BrandError("too_many_versions", "This client has as many versions as it may hold.", 409)
    content = data if data is not None else (source.data if source is not None else brandset.empty())
    if project is not None:
        # A project's version stands on a version of the client's own: the one given, the one its source stood on,
        # the one its newest version stands on, or the client's current one.
        if source is not None and source.project_id != project.id:
            raise BrandError("not_found", "Not found.", 404)
        newest = project_versions(db, project)
        base = base or (db.get(BrandVersion, source.base_id) if source is not None and source.base_id else None) \
            or (db.get(BrandVersion, newest[-1].base_id) if newest and newest[-1].base_id else None) \
            or current(db, client)
        if base is None or base.client_id != client.id or base.project_id is not None:
            raise BrandError("no_base", "A project stands on a version of its client; this client has none.", 409)
        project.version_id = base.id
    label = _free_label(db, client, _text(label, 60, "invalid_label", required=True), project)
    row = BrandVersion(id=new_id(), client_id=client.id, label=label,
                       status=DRAFT, origin=origin if origin in ORIGINS else "hand", note=_note(note, 500),
                       author=author or account.display_name or account.name, data=checked(db, client, content),
                       source_id=source.id if source is not None else None,
                       source_label=source.label if source is not None else None,
                       project_id=project.id if project is not None else None,
                       base_id=base.id if project is not None and base is not None else None)
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


def review_news(db: Session, client_id: str, review_id: int | None = None) -> int:
    """What the client did in its reviews that nobody of the agency has looked at yet: each comment, and a choice.
    A withdrawn review has nothing new."""
    from ..models import Review, ReviewComment

    comments = (select(func.count()).select_from(ReviewComment).join(Review, Review.id == ReviewComment.review_id)
                .where(Review.client_id == client_id, Review.status != "closed", ReviewComment.agency.is_(False),
                       or_(Review.seen_at.is_(None), ReviewComment.created_at > Review.seen_at)))
    chosen = (select(func.count()).select_from(Review)
              .where(Review.client_id == client_id, Review.status == "chosen",
                     or_(Review.seen_at.is_(None), Review.chosen_at > Review.seen_at)))
    if review_id is not None:
        comments = comments.where(Review.id == review_id)
        chosen = chosen.where(Review.id == review_id)
    return int(db.scalar(comments) or 0) + int(db.scalar(chosen) or 0)


def delete_draft(db: Session, account: Account, client: Client, row: BrandVersion) -> None:
    if row.status != DRAFT:
        raise BrandError("published", "A published version stays, for the history.", 409)
    if db.scalar(select(func.count()).select_from(BrandVersion).where(BrandVersion.base_id == row.id)) or \
            db.scalar(select(func.count()).select_from(Project).where(Project.version_id == row.id)):
        raise BrandError("in_use", "A project builds on this draft. Move the project first.", 409)
    db.delete(row)
    touch(client, account)
    db.commit()
    logger.info("Draft deleted client=%s version=%s label=%s by=%s", client.id, row.id, row.label, account.name)


# --- Projects ---------------------------------------------------------------------------------------------------


def create_project(
    db: Session, account: Account, client: Client, *, name: str, version_id: str, note: str = "",
    own: Any = None, data: Any = None,
) -> Project:
    """A project on a version of the client's, with a first draft that takes everything from it (or the set given,
    in the shape of ``services/inherit.py``); ``own``: colours of its own on top, as projects had them before."""
    count = db.scalar(select(func.count()).select_from(Project).where(Project.client_id == client.id)) or 0
    if count >= MAX_PROJECTS:
        raise BrandError("too_many_projects", "This client has as many projects as it may hold.", 409)
    version = version_for(db, client, version_id)
    if version.project_id is not None:
        raise BrandError("not_found", "Not found.", 404)
    row = Project(id=new_id(), client_id=client.id, name=_text(name, 120, "invalid_name", required=True),
                  version_id=version.id, note=_note(note, 500), own=[])
    db.add(row)
    db.flush()
    colors = _own(own)
    first = data if data is not None else ({"inherit": {"colors": "extend"}, "colors": colors} if colors else {})
    create_version(db, account, client, label="1.0", data=first, project=row, base=version)
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
    note: str | None = None,
) -> Project:
    """Its name and note. What it looks like changes in its versions; standing on a newer client version is a new
    draft (``create_version`` with ``base``)."""
    if name is not None:
        row.name = _text(name, 120, "invalid_name", required=True)
    if note is not None:
        row.note = _note(note, 500)
    row.updated_at = utcnow()
    touch(client, account)
    db.commit()
    return row


def delete_project(db: Session, account: Account, client: Client, row: Project) -> None:
    """Gone at once, with its versions (the client's stay)."""
    for version in project_versions(db, row):
        db.delete(version)
    db.delete(row)
    touch(client, account)
    db.commit()


def adopt_projects(db: Session) -> int:
    """Projects from before 05.10.2026 (a pointer to a client version, a few colours of their own) become a first
    published version that takes everything from that client version and adds those colours. Run at start."""
    moved = 0
    for project in db.scalars(select(Project)).all():
        if db.scalar(select(func.count()).select_from(BrandVersion).where(BrandVersion.project_id == project.id)):
            continue
        base = db.get(BrandVersion, project.version_id)
        if base is None:
            continue
        colors = project.own or []
        data = {"inherit": {"colors": "extend"}, "colors": colors} if colors else {}
        db.add(BrandVersion(id=new_id(), client_id=project.client_id, project_id=project.id, base_id=base.id,
                            label="1.0", status=PUBLISHED, origin="hand", note="", author="",
                            data=brandset.clean(data), valid_from=project.created_at.date().isoformat(),
                            created_at=project.created_at, updated_at=project.updated_at,
                            published_at=project.created_at, published_by="nexbrand"))
        moved += 1
    if moved:
        db.commit()
        logger.info("Projects given versions of their own count=%s", moved)
    return moved
