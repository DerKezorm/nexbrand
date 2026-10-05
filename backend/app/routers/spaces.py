"""The group of rights behind each client: who is in it, with which right, and the rights of teams (the dialog
"Who has access" of a client). Made, renamed and deleted only with its client (``routers/clients.py``).

Members and invitations are in ``routers/members.py``.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter
from fastapi import Path as PathParam
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..deps import Account, DbSession
from ..errors import error
from ..models import MANAGE, SPACE_ROLES, Client, Membership, Space, Team, TeamGrant
from ..models import Account as AccountRow
from ..services import rights, spaces, suite

logger = logging.getLogger("nexbrand.spaces")

router = APIRouter(prefix="/api/spaces", tags=["spaces"])

SpaceId = Annotated[int, PathParam(ge=1)]


class TeamRight(BaseModel):
    role: str = Field(pattern="^(read|write|manage)$")


def _fail(exc: spaces.SpaceError | rights.RightsError) -> Exception:
    return error(exc.code, exc.text, exc.status)


def _view(db: DbSession, account: AccountRow, space: Space) -> dict[str, Any]:
    rows = db.execute(
        select(Membership, AccountRow)
        .join(AccountRow, AccountRow.id == Membership.account_id)
        .where(Membership.space_id == space.id)
        .order_by(AccountRow.name)
    ).all()
    client = db.scalar(select(Client).where(Client.space_id == space.id))
    teams = db.execute(
        select(TeamGrant, Team).join(Team, Team.id == TeamGrant.team_id).where(TeamGrant.space_id == space.id)
        .order_by(Team.name)
    ).all()
    return {
        "id": space.id,
        "name": space.name,
        "color": space.color,
        "role": rights.role_in(db, account, space.id),
        "client": client.id if client is not None else None,
        # Its rights come from nexsuite: changed there, not here.
        "managed": bool(space.external_id) and suite.connected(db),
        "teams": [{"id": team.id, "name": team.name, "color": team.color, "role": grant.role} for grant, team in teams],
        # Everybody who gets in, through a right of their own or a team, each once: the number on "Access", the same
        # the dialog says.
        "people": len({person.id for _membership, person in rows} | rights.team_members_of(db, space.id)),
        "members": [
            {
                "id": person.id,
                "name": person.name,
                "display_name": person.display_name,
                "role": membership.role,
                "avatar": person.avatar_at.isoformat() if person.avatar_at else None,
            }
            for membership, person in rows
        ],
    }


@router.get("", summary="The spaces the own account may read")
def listing(account: Account, db: DbSession) -> list[dict[str, Any]]:
    ids = rights.readable_ids(db, account)
    rows = db.scalars(select(Space).where(Space.id.in_(ids)).order_by(Space.created_at)) if ids else []
    return [_view(db, account, space) for space in rows]


@router.put("/{space_id}/teams/{team_id}", summary="Give a team a right in the space (managers)")
def give_team(
    space_id: SpaceId, team_id: SpaceId, payload: TeamRight, account: Account, db: DbSession
) -> dict[str, Any]:
    suite.refuse_if_space_managed(db, space_id, account)
    try:
        space = rights.check(db, account, space_id, MANAGE)
    except rights.RightsError as exc:
        raise _fail(exc) from exc
    if db.get(Team, team_id) is None or payload.role not in SPACE_ROLES:
        raise error("not_found", "Not found.", 404)
    grant = db.get(TeamGrant, (space_id, team_id))
    if grant is None:
        db.add(TeamGrant(space_id=space_id, team_id=team_id, role=payload.role))
    else:
        grant.role = payload.role
    db.commit()
    logger.info("Team right set space=%s team=%s role=%s by=%s", space_id, team_id, payload.role, account.name)
    return _view(db, account, space)


@router.delete("/{space_id}/teams/{team_id}", summary="Take a team's right in the space away (managers)")
def take_team(space_id: SpaceId, team_id: SpaceId, account: Account, db: DbSession) -> dict[str, Any]:
    suite.refuse_if_space_managed(db, space_id, account)
    try:
        space = rights.check(db, account, space_id, MANAGE)
    except rights.RightsError as exc:
        raise _fail(exc) from exc
    grant = db.get(TeamGrant, (space_id, team_id))
    if grant is not None:
        db.delete(grant)
        db.commit()
    # A manager who had the right only through this team may have lost the space now: then it is gone for them.
    if rights.role_in(db, account, space_id) is None:
        return {"id": space_id, "gone": True}
    return _view(db, account, space)
