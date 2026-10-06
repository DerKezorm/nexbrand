"""The group of rights behind each client (``Space``): made with the client, by the account that then manages it."""

from __future__ import annotations

import logging
import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import MANAGE, Account, Membership, Space

logger = logging.getLogger("nexbrand.spaces")

#: The colours a client may have: those nexsuite also has, so a colour comes along when nexbrand connects (nexsuite
#: refuses any other). ``lib/palette.ts`` holds the same list for the interface.
COLORS = ("#60a5fa", "#38a9c4", "#4ade80", "#fbbf24", "#ff8a70", "#f472b6", "#a78bfa", "#a1a1aa")
COLOR = re.compile(r"^#[0-9a-f]{6}$")
MAX_NAME = 80


class SpaceError(Exception):
    def __init__(self, code: str, text: str, status: int = 422) -> None:
        super().__init__(text)
        self.code = code
        self.text = text
        self.status = status


def clean_name(name: str) -> str:
    text = " ".join(name.split())
    if any(unicodedata.category(char) == "Cc" and char not in "\t\n\r" for char in name):
        raise SpaceError("invalid_characters", "The text contains control characters you cannot see.")
    if not text or len(text) > MAX_NAME:
        raise SpaceError("invalid_name", "A client needs a name of 1 to 80 characters.")
    return text


def clean_color(color: str | None, fallback: str) -> str:
    if color is None:
        return fallback
    value = color.strip().lower()
    if not COLOR.match(value):
        raise SpaceError("invalid_color", "Not a colour nexbrand offers.")
    return value


def create(db: Session, account: Account | None, name: str, color: str | None = None, *, commit: bool = True) -> Space:
    """The group of rights for a new client; the account that made it manages it (none: brought by nexsuite)."""
    taken = db.scalar(select(Space.id).order_by(Space.id.desc()))
    fallback = COLORS[(taken or 0) % len(COLORS)]
    space = Space(name=clean_name(name[:MAX_NAME]), color=clean_color(color, fallback))
    db.add(space)
    db.flush()
    if account is not None:
        db.add(Membership(space_id=space.id, account_id=account.id, role=MANAGE))
    if commit:
        db.commit()
    return space
