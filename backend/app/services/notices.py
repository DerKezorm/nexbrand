"""Invitations by name and what the operator did in spaces it does not manage (``SpaceNotice``).

A manager who names an account does not make it a member: the account gets an invitation under "New" and answers it.
Unknown names are answered exactly like known ones, so the members dialog tells nobody which accounts exist.

The operator may still set rights in any space (a manager left, an account was deleted). It never happens unseen:
every member of the space, and the account concerned, gets a notice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from ..models import MANAGE, OPERATOR, Account, Membership, Space, SpaceNotice
from . import rights

INVITE = "invite"
OPERATOR_ADDED = "operator_added"
OPERATOR_ROLE = "operator_role"
OPERATOR_REMOVED = "operator_removed"
#: An invitation nobody answered goes after this long.
INVITE_DAYS = 30


class NoticeError(Exception):
    def __init__(self, code: str, status: int = 404) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass
class NoticeView:
    id: int
    kind: str
    space: str
    role: str
    #: Display names (the sign-in name when there is none): the line is read, not matched.
    actor: str
    subject: str
    created_at: datetime
    #: The notice is about the account reading it: the page says "you" instead of its name.
    mine: bool = False


def invite(db: Session, space: Space, target: Account | None, role: str, by: Account) -> None:
    """An invitation for ``target``; one more for the same space replaces the open one (with the newer right).

    ``target`` None (an unknown name) asks the same question of the database and changes nothing, so that the answer
    takes about as long either way. Only a new invitation, or a new right in it, sends a notification.
    """
    open_ = db.scalar(
        select(SpaceNotice).where(
            SpaceNotice.account_id == (target.id if target is not None else -1), SpaceNotice.space_id == space.id,
            SpaceNotice.kind == INVITE, SpaceNotice.done_at.is_(None),
        )
    )
    if target is None:
        return
    if open_ is None:
        open_ = SpaceNotice(account_id=target.id, space_id=space.id, kind=INVITE)
        db.add(open_)
    open_.space_name = space.name
    open_.role = role
    open_.actor = by.name
    open_.actor_id = by.id
    open_.created_at = datetime.now(UTC)


def tell(db: Session, space: Space, kind: str, actor: Account, subject: str, role: str = "",
         also: tuple[int, ...] = ()) -> None:
    """A notice about what the operator did, for every member of the space and for ``also`` (the account concerned)."""
    members = set(db.scalars(select(Membership.account_id).where(Membership.space_id == space.id)))
    members |= rights.team_members_of(db, space.id)
    for account_id in (members | set(also)) - {actor.id}:
        db.add(SpaceNotice(account_id=account_id, space_id=space.id, space_name=space.name, kind=kind, role=role,
                           actor=actor.name, actor_id=actor.id, subject=subject))


def oldest_open() -> datetime:
    """Notices from before this are gone: not listed, and an invitation from before cannot be accepted."""
    return datetime.now(UTC) - timedelta(days=INVITE_DAYS)


def open_for(db: Session, account_id: int) -> list[NoticeView]:
    since = oldest_open()
    rows = db.scalars(
        select(SpaceNotice)
        .where(SpaceNotice.account_id == account_id, SpaceNotice.done_at.is_(None), SpaceNotice.created_at > since)
        .order_by(SpaceNotice.created_at.desc(), SpaceNotice.id.desc())
    )
    rows = list(rows)
    own = db.get(Account, account_id)
    names = {row.subject for row in rows if row.subject} | {row.actor for row in rows if row.actor}
    people = {person.name: person for person in db.scalars(select(Account).where(Account.name.in_(names)))}
    by_id = {person.id: person for person in db.scalars(
        select(Account).where(Account.id.in_({row.actor_id for row in rows if row.actor_id is not None})))}

    def shown(name: str, person: Account | None = None) -> str:
        person = person or people.get(name)
        return (person.display_name or person.name) if person is not None else name

    return [
        NoticeView(id=row.id, kind=row.kind, space=row.space_name, role=row.role,
                   actor=shown(row.actor, by_id.get(row.actor_id) if row.actor_id is not None else None),
                   subject=shown(row.subject) if row.subject else "", created_at=row.created_at,
                   mine=own is not None and bool(row.subject) and row.subject == own.name)
        for row in rows
    ]


def _own(db: Session, account: Account, notice_id: int) -> SpaceNotice:
    row = db.get(SpaceNotice, notice_id)
    if row is None or row.account_id != account.id or row.done_at is not None:
        raise NoticeError("not_found")
    return row


def _may_invite(db: Session, inviter: Account | None, space: Space) -> bool:
    """Whether whoever sent the invitation may still invite into the space: manages it, or is the operator."""
    if inviter is None:
        return False
    if inviter.role == OPERATOR:
        return True
    return rights.at_least(rights.role_in(db, inviter, space.id), MANAGE)


def withdraw(db: Session, space_id: int, notice_id: int) -> bool:
    """A manager takes back an invitation by name not answered yet. One statement that only removes it while it is
    open: an answer at the same moment either comes first (then nothing is withdrawn) or finds nothing."""
    gone = db.execute(
        delete(SpaceNotice).where(SpaceNotice.id == notice_id, SpaceNotice.space_id == space_id,
                                  SpaceNotice.kind == INVITE, SpaceNotice.done_at.is_(None))
    ).rowcount
    db.commit()
    return bool(gone)


def answer(db: Session, account: Account, notice_id: int, *, accept: bool) -> str | None:
    """Accept or decline an invitation; the space's name when accepted. Anything else: seen.

    Taking it is one statement that only succeeds while the notice is open and the account's: a manager who withdraws
    it, or a second answer, between reading and writing finds nothing."""
    row = _own(db, account, notice_id)
    taken = db.execute(
        update(SpaceNotice)
        .where(SpaceNotice.id == notice_id, SpaceNotice.account_id == account.id, SpaceNotice.done_at.is_(None))
        .values(done_at=datetime.now(UTC))
        .execution_options(synchronize_session=False)
    ).rowcount
    if not taken:
        db.rollback()
        raise NoticeError("not_found")
    if row.kind != INVITE or not accept:
        db.commit()
        return None
    space = db.get(Space, row.space_id) if row.space_id is not None else None
    inviter = db.get(Account, row.actor_id) if row.actor_id is not None else None
    created = row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=UTC)
    # Still good only while it is not too old and its sender may still invite: a manager taken out or set down
    # could otherwise make an accomplice manager through an invitation sent before.
    too_old = created < datetime.now(UTC) - timedelta(days=INVITE_DAYS)
    if space is None or too_old or not _may_invite(db, inviter, space):
        db.commit()
        raise NoticeError("not_found")
    if db.get(Membership, (space.id, account.id)) is None:
        if not rights.owned(db, space.id) and inviter is not None and inviter.role == OPERATOR:
            # A space nobody has is the operator's; the operator who invited stays in it as manager.
            db.add(Membership(space_id=space.id, account_id=inviter.id, role=MANAGE))
        db.add(Membership(space_id=space.id, account_id=account.id, role=row.role))
    db.commit()
    return space.name
