"""One group of rights per client, for data from before clients stood on their own (04.10.2026).

Until then a space held several clients and its members saw all of them. Now every client has its own group
(``Client.space_id``, unique). At every start, once nothing is left to do a single query:

* a space with several clients keeps the oldest; every other client gets a group of its own with the same members and
  team rights, and takes its shares, reviews and files along. A file another client of the old space also uses is
  copied (new id, its bytes copied, the client's design sets point at the copy), so neither loses it;
* API tokens limited to the old space see the new groups too, so a token keeps seeing what it saw;
* a space without any client and without files goes; one with files stays (nobody sees it, the clean-up keeps them);
* every group carries its client's name (a space kept its old name, "Personal" say, and the access lists showed it);
* the index on ``clients.space_id`` becomes unique, so the database itself refuses a second client in a group (an old
  database kept the plain index of the same name; ``create_all`` does not change an index that exists).
"""

from __future__ import annotations

import json
import logging
import secrets
import shutil
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..models import ApiToken, BrandVersion, Client, Media, Membership, Review, Share, Space, TeamGrant
from . import brandset, media_store

logger = logging.getLogger("nexbrand.regroup")


def _uses(db: Session, client: Client) -> set[str]:
    found: set[str] = set()
    for data in db.scalars(select(BrandVersion.data).where(BrandVersion.client_id == client.id)):
        found |= brandset.media_of(data)
    for variants in db.scalars(select(Review.variants).where(Review.client_id == client.id)):
        for variant in variants or []:
            if isinstance(variant, dict):
                found |= brandset.media_of(variant.get("data"))
    return found


def _renamed(value: Any, ids: dict[str, str]) -> Any:
    """The same JSON with every file id in ``ids`` replaced (ids are random and never part of other words)."""
    text = json.dumps(value)
    for old, new in ids.items():
        text = text.replace(json.dumps(old), json.dumps(new))
    return json.loads(text)


def _copy_media(row: Media, space_id: int) -> str:
    new_id = secrets.token_urlsafe(12)
    for source, target in ((media_store.path_of(row.id), media_store.path_of(new_id)),
                           (media_store.preview_of(row.id), media_store.preview_of(new_id))):
        if source.is_file():
            shutil.copyfile(source, target)
    return new_id


def run(db: Session) -> int:
    """Gives every client its own group; returns how many clients moved."""
    crowded = db.execute(select(Client.space_id).group_by(Client.space_id).having(func.count() > 1)).scalars().all()
    empty = db.scalars(select(Space.id).where(~Space.id.in_(select(Client.space_id)),
                                              ~Space.id.in_(select(Media.space_id)))).all()
    if not crowded and not empty:
        _names(db)
        _unique_index(db)
        return 0
    moved = 0
    for space_id in crowded:
        space = db.get(Space, space_id)
        assert space is not None
        clients = db.scalars(select(Client).where(Client.space_id == space_id).order_by(Client.created_at)).all()
        for client in clients[1:]:
            group = Space(name=client.name[:80], color=space.color, external_id="", deleted_at=space.deleted_at)
            db.add(group)
            db.flush()
            for member in db.scalars(select(Membership).where(Membership.space_id == space_id)):
                db.add(Membership(space_id=group.id, account_id=member.account_id, role=member.role))
            for grant in db.scalars(select(TeamGrant).where(TeamGrant.space_id == space_id)):
                db.add(TeamGrant(space_id=group.id, team_id=grant.team_id, role=grant.role))
            others: set[str] = set()
            for other in clients:
                if other.id != client.id and other.space_id == space_id:
                    others |= _uses(db, other)
            copies: dict[str, str] = {}
            for media_id in _uses(db, client):
                row = db.get(Media, media_id)
                if row is None or row.space_id != space_id:
                    continue
                if media_id in others:
                    new_id = _copy_media(row, group.id)
                    db.add(Media(id=new_id, space_id=group.id, owner_id=row.owner_id, name=row.name, kind=row.kind,
                                 mime=row.mime, size=row.size, sha256=row.sha256, width=row.width, height=row.height,
                                 pages=row.pages, created_at=row.created_at))
                    copies[media_id] = new_id
                else:
                    row.space_id = group.id
            if copies:
                for version in db.scalars(select(BrandVersion).where(BrandVersion.client_id == client.id)):
                    version.data = _renamed(version.data, copies)
                for review in db.scalars(select(Review).where(Review.client_id == client.id)):
                    review.variants = _renamed(review.variants, copies)
            for share in db.scalars(select(Share).where(Share.client_id == client.id)):
                share.space_id = group.id
            for review in db.scalars(select(Review).where(Review.client_id == client.id)):
                review.space_id = group.id
            for token in db.scalars(select(ApiToken).where(ApiToken.spaces.is_not(None))):
                if space_id in (token.spaces or []):
                    token.spaces = sorted({*token.spaces, group.id})
            client.space_id = group.id
            db.flush()
            moved += 1
    for space_id in empty:
        space = db.get(Space, space_id)
        if space is not None:
            db.delete(space)
    db.commit()
    logger.info("Every client has its own group of rights now: %s moved, %s empty spaces gone", moved, len(empty))
    _names(db)
    _unique_index(db)
    return moved


def _names(db: Session) -> None:
    rows = db.execute(select(Client, Space).join(Space, Space.id == Client.space_id)).all()
    renamed = 0
    for client, space in rows:
        wanted = " ".join(client.name.split())[:80] or "?"
        if space.name != wanted:
            space.name = wanted
            renamed += 1
    if renamed:
        db.commit()
        logger.info("Groups of rights named after their clients: %s", renamed)


def _unique_index(db: Session) -> None:
    rows = db.execute(text("PRAGMA index_list('clients')")).mappings().all()
    plain = [row for row in rows if row["name"] == "ix_clients_space_id" and not row["unique"]]
    if plain:
        db.execute(text("DROP INDEX ix_clients_space_id"))
        db.execute(text("CREATE UNIQUE INDEX ix_clients_space_id ON clients (space_id)"))
        db.commit()
        logger.info("The index on clients.space_id is unique now")
