"""The open links a person made for clients: public pages and reviews.

They stay when the person is blocked or deleted, because they serve the client. The operator sees how many are open and
withdraws them all at once.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ColumnElement, delete, func, or_, select, update
from sqlalchemy.orm import Session

from ..models import Review, Share, utcnow


def _share_open(now: datetime) -> ColumnElement[bool]:
    return or_(Share.expires_at.is_(None), Share.expires_at > now)


def _review_open(now: datetime) -> ColumnElement[bool]:
    """A review page that still opens: open, or chosen (the client still sees the choice), and not run out."""
    return Review.status.in_(("open", "chosen")) & or_(Review.expires_at.is_(None), Review.expires_at > now)


def open_counts(db: Session) -> dict[int, int]:
    """Per account id: its public pages not run out and its review pages that still open."""
    now = utcnow()
    counts: dict[int, int] = {}
    for model, still_open in ((Share, _share_open(now)), (Review, _review_open(now))):
        rows = db.execute(select(model.created_by, func.count()).where(model.created_by.is_not(None), still_open)
                          .group_by(model.created_by))
        for account_id, count in rows:
            counts[int(account_id)] = counts.get(int(account_id), 0) + int(count)
    return counts


def withdraw_all(db: Session, account_id: int) -> int:
    """Takes the account's public pages down, closes its open reviews and lets its chosen ones run out now (the choice
    stays in the history), in one transaction; how many. Each a conditional update: a choice made at the same moment
    is either closed with it or not counted, never overwritten."""
    now = utcnow()
    pages = db.execute(delete(Share).where(Share.created_by == account_id, _share_open(now)))
    still_open = or_(Review.expires_at.is_(None), Review.expires_at > now)
    closed = db.execute(update(Review).where(Review.created_by == account_id, Review.status == "open", still_open)
                        .values(status="closed"))
    ended = db.execute(update(Review).where(Review.created_by == account_id, Review.status == "chosen", still_open)
                       .values(expires_at=now))
    db.commit()
    return int(pages.rowcount or 0) + int(closed.rowcount or 0) + int(ended.rowcount or 0)
