"""The open links a person made for clients: public pages and reviews.

They stay when the person is blocked or deleted, because they serve the client (Prüfgang 05.10.2026 A15, as
decided). The operator sees how many are open and withdraws them all at once.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ColumnElement, delete, func, or_, select, update
from sqlalchemy.orm import Session

from ..models import Review, Share, utcnow


def _share_open(now: datetime) -> ColumnElement[bool]:
    return or_(Share.expires_at.is_(None), Share.expires_at > now)


def _review_open(now: datetime) -> ColumnElement[bool]:
    return (Review.status == "open") & or_(Review.expires_at.is_(None), Review.expires_at > now)


def open_counts(db: Session) -> dict[int, int]:
    """Per account id: its public pages not run out and its reviews still open."""
    now = utcnow()
    counts: dict[int, int] = {}
    for model, still_open in ((Share, _share_open(now)), (Review, _review_open(now))):
        rows = db.execute(select(model.created_by, func.count()).where(model.created_by.is_not(None), still_open)
                          .group_by(model.created_by))
        for account_id, count in rows:
            counts[int(account_id)] = counts.get(int(account_id), 0) + int(count)
    return counts


def withdraw_all(db: Session, account_id: int) -> int:
    """Takes the account's public pages down and closes its open reviews, in one transaction; how many."""
    now = utcnow()
    pages = db.execute(delete(Share).where(Share.created_by == account_id, _share_open(now)))
    reviews = db.execute(update(Review).where(Review.created_by == account_id, _review_open(now))
                         .values(status="closed"))
    db.commit()
    return int(pages.rowcount or 0) + int(reviews.rowcount or 0)
