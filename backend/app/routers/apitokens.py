"""API tokens through the interface: an account's own (My account, Connections) and every token for the operator.

Only with a session: a token never makes, lists or deletes tokens (``require_account`` reads the session cookie).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Path
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..deps import Account, DbSession, OperatorAccount
from ..errors import error, invalid_characters
from ..models import Account as AccountRow
from ..models import ApiToken, Client, utcnow
from ..services import apitokens, names, rights
from ..services.apitokens import TokenError

logger = logging.getLogger("nexbrand.api")

router = APIRouter(prefix="/api", tags=["api tokens"])


class TokenOut(BaseModel):
    id: int
    name: str
    level: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    #: The operator blocked it: it answers like none, for good.
    blocked: bool = False
    #: The clients the token may see (id and name), of those the account may read now; None: all of them.
    clients: list[dict[str, str]] | None = None


class TokensOut(BaseModel):
    allowed: bool
    tokens: list[TokenOut]


#: How long a new token holds when nothing else is said (F26, decided 05.10.2026).
DEFAULT_DAYS = 90


class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    #: ``read``, or ``draft``: also proposes versions as drafts (MCP, ``/api/v1``).
    level: str = Field(default="read", max_length=8)
    #: Ids of clients the token sees. Needed unless ``all_clients`` (F26: a new token is narrow from the start).
    clients: list[str] | None = Field(default=None, max_length=1000)
    #: Every client the account may read, now and later, instead of ``clients``; asked for on purpose.
    all_clients: bool = False
    #: 30, 90 or 365; ``null`` on purpose: never runs out; left out: 90 (F26).
    days: int | None = DEFAULT_DAYS


class MadeOut(BaseModel):
    token: TokenOut
    #: Shown once, never again.
    secret: str


def _out(db: Any, account: Any, row: ApiToken) -> TokenOut:
    named = None
    if row.spaces is not None:
        # Only clients the account may still read: one it lost since tells nothing (and the token does not see it).
        readable = rights.readable_ids(db, account)
        wanted = [space_id for space_id in row.spaces if space_id in readable]
        rows = db.scalars(select(Client).where(Client.space_id.in_(wanted), Client.deleted_at.is_(None))
                          .order_by(Client.name)) if wanted else []
        named = [{"id": client.id, "name": client.name} for client in rows]
    return TokenOut(id=row.id, name=row.name, level=row.level, prefix=row.prefix, created_at=row.created_at,
                    last_used_at=row.last_used_at, expires_at=row.expires_at, blocked=row.blocked_at is not None,
                    clients=named)


@router.get("/api-tokens", response_model=TokensOut, summary="The own API tokens")
def own_tokens(account: Account, db: DbSession) -> TokensOut:
    rows = db.scalars(select(ApiToken).where(ApiToken.account_id == account.id).order_by(ApiToken.id)).all()
    return TokensOut(allowed=apitokens.allowed(db), tokens=[_out(db, account, row) for row in rows])


@router.post("/api-tokens", response_model=MadeOut, status_code=201, summary="Make an API token; shown once")
def make_token(body: TokenIn, account: Account, db: DbSession) -> MadeOut:
    if not apitokens.allowed(db):
        raise error("api_off", "The operator has not switched API tokens on.", 403)
    groups = None
    if body.all_clients and body.clients is not None:
        raise error("invalid_input", "Choose clients, or all of them, not both.", 422)
    if not body.all_clients and not body.clients:
        raise error("choose_clients", "Choose the clients the token may see, or all of them on purpose.", 422)
    if body.clients is not None:
        # A client is seen through its group of rights; one that does not exist is refused like one not readable.
        found = {c.id: c.space_id for c in db.scalars(select(Client).where(Client.id.in_(body.clients),
                                                                           Client.deleted_at.is_(None)))}
        if len(found) != len(set(body.clients)):
            raise error("invalid_input", "Choose clients you may read.", 422)
        groups = list(found.values())
    try:
        name = names.title(body.name, 100)
    except ValueError as exc:
        raise invalid_characters() from exc
    try:
        row, secret = apitokens.make(db, account, name, body.level, groups, body.days)
    except TokenError as exc:
        raise error(exc.code, exc.text, exc.status) from exc
    return MadeOut(token=_out(db, account, row), secret=secret)


@router.delete("/api-tokens/{token_id}", status_code=204, summary="Delete an own API token")
def delete_token(token_id: Annotated[int, Path(ge=1)], account: Account, db: DbSession) -> None:
    row = db.get(ApiToken, token_id)
    if row is None or row.account_id != account.id:
        raise error("not_found", "Not found.", 404)
    db.delete(row)
    db.commit()
    logger.info("API token deleted token_id=%s", token_id)


# --- The operator ----------------------------------------------------------------------------------------------------


class AnyTokenOut(BaseModel):
    id: int
    account: str
    name: str
    level: str
    prefix: str
    #: How many clients it is limited to; None: all its account may read.
    clients: int | None = None
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    blocked: bool = False


@router.get("/admin/api-tokens", response_model=list[AnyTokenOut], summary="Every API token (operator)")
def every_token(_operator: OperatorAccount, db: DbSession) -> list[AnyTokenOut]:
    names = dict(db.execute(select(AccountRow.id, AccountRow.name)).all())
    rows = db.scalars(select(ApiToken).order_by(ApiToken.account_id, ApiToken.id)).all()
    return [AnyTokenOut(id=row.id, account=names.get(row.account_id, ""), name=row.name, level=row.level,
                        prefix=row.prefix, clients=None if row.spaces is None else len(row.spaces),
                        created_at=row.created_at, last_used_at=row.last_used_at, expires_at=row.expires_at,
                        blocked=row.blocked_at is not None) for row in rows]


@router.post("/admin/api-tokens/{token_id}/block", response_model=AnyTokenOut,
             summary="Block a token for good (operator); its account sees it blocked")
def block_token(token_id: Annotated[int, Path(ge=1)], _operator: OperatorAccount, db: DbSession) -> AnyTokenOut:
    row = db.get(ApiToken, token_id)
    if row is None:
        raise error("not_found", "Not found.", 404)
    if row.blocked_at is None:
        row.blocked_at = utcnow()
        db.commit()
        logger.info("API token blocked by the operator token_id=%s", token_id)
    owner = db.get(AccountRow, row.account_id)
    return AnyTokenOut(id=row.id, account=owner.name if owner else "", name=row.name, level=row.level,
                       prefix=row.prefix, clients=None if row.spaces is None else len(row.spaces),
                       created_at=row.created_at, last_used_at=row.last_used_at, expires_at=row.expires_at,
                       blocked=True)
