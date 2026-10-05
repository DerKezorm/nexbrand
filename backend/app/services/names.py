"""Names that tell things apart (F15, decided 05.10.2026): no two clients of one name, no two projects of one name in
a client, no two teams of one name. Names are compared without capitals, without spaces at the ends or doubled
inside, without invisible signs and in one Unicode form (``key``: "Acme", " acme ", "ACME" and "Acme" with a
zero-width space inside are one name).

A client in the bin counts too: brought back, it would stand beside its double. Whoever names one gets a clear
refusal (``client_name_taken``, ``client_name_in_bin``, ``project_name_taken``, ``team_name_taken``).

Clients and teams nexsuite brings never fail on it: one whose name is taken here gets a number behind it, here only,
and the log says so (``unique``). Doubles from before the rule get their number at start (``number_doubles``).
"""

from __future__ import annotations

import logging
import threading
import unicodedata
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Client, Project, Space, Team

logger = logging.getLogger("nexbrand.names")

#: Held from the look for a name until the commit that takes it: two clicks at once make no double.
lock = threading.RLock()


class NameTaken(Exception):
    def __init__(self, code: str, text: str) -> None:
        super().__init__(text)
        self.code = code
        self.text = text
        self.status = 409


def key(name: str) -> str:
    """A name as compared: NFKC (an "é" typed as one sign or as "e" and an accent is one name), without invisible
    signs (a zero-width space, a soft hyphen), spaces folded to one inside and gone at the ends, without capitals."""
    text = unicodedata.normalize("NFKC", str(name or ""))
    text = "".join(char for char in text if unicodedata.category(char) != "Cf")
    return " ".join(text.split()).casefold()


def free(name: str, taken: Iterable[str], most: int) -> str:
    """``name``, or with `` (2)``, `` (3)`` … behind it when it is taken; never longer than ``most``."""
    keys = {key(item) for item in taken}
    name = " ".join(str(name or "").split())
    if key(name) not in keys:
        return name
    for number in range(2, 10_000):
        tail = f" ({number})"
        candidate = name[:most - len(tail)].rstrip() + tail
        if key(candidate) not in keys:
            return candidate
    return name


def check_client(db: Session, name: str, own_id: str | None = None) -> None:
    wanted = key(name)
    for row in db.scalars(select(Client).where(Client.id != (own_id or ""))):
        if key(row.name) == wanted:
            if row.deleted_at is not None:
                raise NameTaken("client_name_in_bin", "A client of this name is in the bin. Restore it, or choose "
                                "another name.")
            raise NameTaken("client_name_taken", "There is a client of this name already. Choose another name.")


def check_project(db: Session, client_id: str, name: str, own_id: str | None = None) -> None:
    wanted = key(name)
    for row in db.scalars(select(Project).where(Project.client_id == client_id, Project.id != (own_id or ""))):
        if key(row.name) == wanted:
            raise NameTaken("project_name_taken", "This client has a project of this name already. Choose another "
                            "name.")


def check_team(db: Session, name: str, own_id: int | None = None) -> None:
    wanted = key(name)
    for row in db.scalars(select(Team).where(Team.id != (own_id or 0))):
        if key(row.name) == wanted:
            raise NameTaken("team_name_taken", "There is a team of this name already. Choose another name.")


def unique(db: Session, kind: str, name: str, others: Iterable[str], most: int, source: Any = "",
           before: str = "") -> str:
    """For what nexsuite brings: its name, or with a number when another here has it. Never refused; logged once,
    when the number is new (``before``: the name it has here now), not with every sync."""
    found = free(name, others, most)
    if found != name and found != before:
        logger.warning("Name taken here, given a number kind=%s id=%s", kind, source)
    return found


def number_doubles(db: Session) -> int:
    """At start: clients, projects (within their client) and teams that share a name from before the rule; the oldest
    keeps it, the others get a number. How many were renamed."""
    renamed = 0

    def run(rows: list[Any], most: int, kind: str) -> None:
        nonlocal renamed
        seen: list[str] = []
        for row in rows:
            if key(row.name) in {key(item) for item in seen}:
                new = free(row.name, seen + [r.name for r in rows], most)
                logger.warning("Double name given a number kind=%s id=%s", kind, row.id)
                row.name = new
                if kind == "client":
                    space = db.get(Space, row.space_id)
                    if space is not None:
                        space.name = new[:80]
                renamed += 1
            seen.append(row.name)

    run(list(db.scalars(select(Client).order_by(Client.created_at, Client.id))), 120, "client")
    for client_id in db.scalars(select(Project.client_id).distinct()):
        run(list(db.scalars(select(Project).where(Project.client_id == client_id)
                            .order_by(Project.created_at, Project.id))), 120, "project")
    run(list(db.scalars(select(Team).order_by(Team.id))), 80, "team")
    if renamed:
        db.commit()
    return renamed
