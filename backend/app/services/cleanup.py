"""What nobody needs any more, once every six hours: clients and spaces 30 days in the trash, reviews and shares that
ran out, and files nothing points at (no version, no project, no review) for a day or longer."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import delete, select

from ..db import SessionLocal
from ..models import BrandVersion, Client, Media, Review, Share, Space, utcnow
from . import brandset, media_store

logger = logging.getLogger("nexbrand.cleanup")

BIN_DAYS = 30
#: A file just uploaded is not in a version yet (the draft is saved after it); it waits a day.
ORPHAN_HOURS = 24
INTERVAL_SECONDS = 6 * 3600


def used_media(space_id: int) -> set[str]:
    """Every file a client of the space points at: in any version (drafts and the trash too) or any review."""
    used: set[str] = set()
    with SessionLocal() as db:
        clients = select(Client.id).where(Client.space_id == space_id)
        for data in db.scalars(select(BrandVersion.data).where(BrandVersion.client_id.in_(clients))):
            used |= brandset.media_of(data)
        for variants in db.scalars(select(Review.variants).where(Review.space_id == space_id)):
            for variant in variants or []:
                if isinstance(variant, dict):
                    used |= brandset.media_of(variant.get("data"))
    return used


def run_once() -> None:
    now = utcnow()
    with SessionLocal() as db:
        # A client from nexsuite goes when nexsuite says so ("clients_gone"): by the clock here it went up to a day
        # early, and a restore there then brought back an empty client (E3). Its group of rights goes with it.
        expired = db.execute(select(Client, Space).join(Space, Space.id == Client.space_id).where(
            Client.deleted_at < now - timedelta(days=BIN_DAYS), Space.external_id == "")).all()
        for client, space in expired:
            db.delete(client)
            db.delete(space)
            logger.info("Client deleted after 30 days in the trash id=%s", client.id)
        db.execute(delete(Share).where(Share.expires_at < now))
        db.execute(delete(Review).where(Review.expires_at < now - timedelta(days=BIN_DAYS)))
        db.commit()
        spaces = set(db.scalars(select(Media.space_id).distinct()))
    for space_id in spaces:
        used = used_media(space_id)
        with SessionLocal() as db:
            old = db.scalars(select(Media).where(
                Media.space_id == space_id, Media.created_at < now - timedelta(hours=ORPHAN_HOURS)
            ))
            for row in old:
                if row.id not in used:
                    media_store.path_of(row.id).unlink(missing_ok=True)
                    media_store.preview_of(row.id).unlink(missing_ok=True)
                    db.delete(row)
                    logger.info("File nobody uses removed id=%s", row.id)
            db.commit()
    # Files of spaces deleted above (their rows went with the space).
    with SessionLocal() as db:
        known = set(db.scalars(select(Media.id)))
    for path in media_store.root().iterdir():
        owner = path.name.removesuffix(".p")
        if path.is_file() and not path.name.startswith(".") and owner not in known:
            path.unlink(missing_ok=True)


async def run_forever(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=INTERVAL_SECONDS)
            return
        except TimeoutError:
            pass
        try:
            await asyncio.to_thread(run_once)
        except Exception:
            logger.exception("Cleaning up failed")
