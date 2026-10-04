"""Clients, their versions and projects over HTTP: the overview, one client with everything, drafts, publishing,
projects, favourites, the bin and the export as code.

Rights come from the client's space (``services/rights.py``): reading shows, writing changes and publishes, the bin
takes writing to put in and take out, and managing to delete for good.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Response
from fastapi import Path as PathParam
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..deps import Account, DbSession
from ..errors import error
from ..models import DRAFT, MANAGE, READ, WRITE, BrandVersion, Client, Favorite, Media, Project, Review, Share, Visit
from ..models import Account as AccountRow
from ..services import brands, brandset, rights, tokens

logger = logging.getLogger("nexbrand.clients")

router = APIRouter(prefix="/api", tags=["clients"])

ClientId = Annotated[str, PathParam(min_length=6, max_length=24, pattern=r"^[A-Za-z0-9_-]+$")]
VersionId = Annotated[str, PathParam(min_length=6, max_length=24, pattern=r"^[A-Za-z0-9_-]+$")]


class ClientIn(BaseModel):
    space_id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=400)
    sector: str = Field(default="", max_length=400)
    contact: str = Field(default="", max_length=400)
    note: str = Field(default="", max_length=8000)
    #: The first version's name, as the interface words it ("1", "Draft 1" …).
    label: str = Field(default="1", min_length=1, max_length=120)
    data: dict[str, Any] | None = None
    #: A first project, building on the first version.
    project: str = Field(default="", max_length=400)


class ClientChange(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=400)
    sector: str | None = Field(default=None, max_length=400)
    contact: str | None = Field(default=None, max_length=400)
    note: str | None = Field(default=None, max_length=8000)
    favorite: bool | None = None


class VersionIn(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    #: A version to start from (copied); empty: the design set given, or an empty one.
    source: str | None = Field(default=None, max_length=24)
    data: dict[str, Any] | None = None
    note: str = Field(default="", max_length=1000)
    #: Where it came from: by hand, or collected from websites, repositories and PDFs (shown in the history).
    origin: Literal["hand", "collect"] = "hand"


class VersionChange(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    note: str | None = Field(default=None, max_length=1000)
    data: dict[str, Any] | None = None


class PublishIn(BaseModel):
    valid_from: str | None = Field(default=None, max_length=10)
    label: str | None = Field(default=None, min_length=1, max_length=120)


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=400)
    version_id: str = Field(min_length=6, max_length=24)
    note: str = Field(default="", max_length=1000)
    own: list[dict[str, Any]] | None = None


class ProjectChange(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=400)
    note: str | None = Field(default=None, max_length=1000)
    version_id: str | None = Field(default=None, min_length=6, max_length=24)
    own: list[dict[str, Any]] | None = None


def _fail(exc: rights.RightsError | brands.BrandError) -> Exception:
    values = getattr(exc, "values", {})
    return error(exc.code, exc.text, exc.status, **values)


def client_of(db: DbSession, account: AccountRow, client_id: str, need: str, *, deleted: bool = False) -> Client:
    try:
        return rights.client_for(db, account, client_id, need, deleted=deleted)
    except rights.RightsError as exc:
        raise _fail(exc) from exc


def version_view(row: BrandVersion, *, data: bool = True) -> dict[str, Any]:
    view: dict[str, Any] = {
        "id": row.id,
        "label": row.label,
        "status": row.status,
        "valid_from": row.valid_from,
        "origin": row.origin,
        "author": row.author,
        "note": row.note,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "published_by": row.published_by,
    }
    if data:
        view["data"] = row.data
    return view


def project_view(row: Project) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "version_id": row.version_id,
        "note": row.note,
        "own": row.own or [],
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _face(version: BrandVersion | None) -> dict[str, Any]:
    """What the overview shows of a client: the colours and the small logo of the current version."""
    if version is None:
        return {"colors": [], "logo": None, "mark": None, "fonts": []}
    data = version.data or {}
    logos = data.get("logos", [])
    wide = next((item for item in logos if not item.get("compact")), None)
    small = next((item for item in logos if item.get("compact")), None)
    return {"colors": [c["hex"] for c in data.get("colors", [])][:10], "logo": wide or small, "mark": small or wide,
            "fonts": [f["family"] for f in data.get("fonts", [])][:4]}


def client_view(db: DbSession, account: AccountRow, client: Client) -> dict[str, Any]:
    versions = brands.versions(db, client)
    current = next((v for v in reversed(versions) if v.status != DRAFT), None)
    shown = current or (versions[0] if versions else None)
    visit = db.get(Visit, (account.id, client.id))
    projects = db.scalar(select(func.count()).select_from(Project).where(Project.client_id == client.id))
    return {
        "id": client.id,
        "space_id": client.space_id,
        "name": client.name,
        "sector": client.sector,
        "contact": client.contact,
        "created_at": client.created_at.isoformat(),
        "updated_at": client.updated_at.isoformat(),
        "updated_by": client.updated_by,
        "deleted_at": client.deleted_at.isoformat() if client.deleted_at else None,
        "favorite": db.get(Favorite, (account.id, client.id)) is not None,
        "opened_at": visit.opened_at.isoformat() if visit else None,
        "role": rights.role_in(db, account, client.space_id),
        "current": current.label if current else None,
        "drafts": sum(1 for v in versions if v.status == DRAFT),
        "projects": int(projects or 0),
        "face": _face(shown),
    }


@router.get("/clients", summary="The clients of every readable space, or of one, or those in the bin")
def listing(
    account: Account, db: DbSession, space: Annotated[int | None, Query(ge=1)] = None, deleted: bool = False,
) -> list[dict[str, Any]]:
    readable = rights.readable_ids(db, account)
    if deleted:
        readable = {sid for sid in readable if rights.at_least(rights.role_in(db, account, sid), WRITE)}
    if space is not None:
        readable &= {space}
    if not readable:
        return []
    query = select(Client).where(Client.space_id.in_(readable))
    query = query.where(Client.deleted_at.is_not(None) if deleted else Client.deleted_at.is_(None))
    return [client_view(db, account, row) for row in db.scalars(query.order_by(Client.name))]


@router.post("/clients", status_code=201, summary="A new client with a first draft (and a first project)")
def create(payload: ClientIn, account: Account, db: DbSession) -> dict[str, Any]:
    try:
        rights.check(db, account, payload.space_id, WRITE)
        client, version = brands.create_client(
            db, account, payload.space_id, payload.name, sector=payload.sector, contact=payload.contact,
            note=payload.note, label=payload.label, data=payload.data)
        if payload.project.strip():
            brands.create_project(db, account, client, name=payload.project, version_id=version.id)
    except (rights.RightsError, brands.BrandError) as exc:
        db.rollback()
        raise _fail(exc) from exc
    return whole(db, account, client)


def whole(db: DbSession, account: AccountRow, client: Client) -> dict[str, Any]:
    view = client_view(db, account, client)
    view["note"] = client.note
    view["versions"] = [version_view(v) for v in brands.versions(db, client)]
    projects = db.scalars(select(Project).where(Project.client_id == client.id).order_by(Project.created_at))
    view["projects"] = [project_view(p) for p in projects]
    view["shares"] = int(db.scalar(select(func.count()).select_from(Share).where(Share.client_id == client.id)) or 0)
    view["reviews"] = [
        {"id": r.id, "version_id": r.version_id, "status": r.status, "chosen": r.chosen}
        for r in db.scalars(select(Review).where(Review.client_id == client.id).order_by(Review.created_at))
    ]
    return view


@router.get("/clients/{client_id}", summary="One client with its versions and projects")
def read(client_id: ClientId, account: Account, db: DbSession) -> dict[str, Any]:
    client = client_of(db, account, client_id, READ)
    return whole(db, account, client)


@router.get("/clients/{client_id}/files", summary="Names and kinds of the files the client's versions name")
def files(client_id: ClientId, account: Account, db: DbSession) -> dict[str, dict[str, Any]]:
    client = client_of(db, account, client_id, READ)
    named: set[str] = set()
    for row in brands.versions(db, client):
        named |= brandset.media_of(row.data)
    if not named:
        return {}
    rows = db.scalars(select(Media).where(Media.id.in_(named), Media.space_id == client.space_id))
    return {row.id: {"name": row.name, "kind": row.kind, "size": row.size, "width": row.width, "height": row.height}
            for row in rows}


@router.patch("/clients/{client_id}", summary="Rename, describe, star")
def change(client_id: ClientId, payload: ClientChange, account: Account, db: DbSession) -> dict[str, Any]:
    if payload.favorite is not None:
        client = client_of(db, account, client_id, READ)
        brands.set_favorite(db, account, client, payload.favorite)
    fields = payload.model_dump(exclude={"favorite"}, exclude_none=True)
    if fields:
        client = client_of(db, account, client_id, WRITE)
        try:
            brands.change_client(db, account, client, **fields)
        except brands.BrandError as exc:
            raise _fail(exc) from exc
    client = client_of(db, account, client_id, READ)
    return client_view(db, account, client)


@router.post("/clients/{client_id}/visit", status_code=204, summary="Note that the account opened the client")
def visited(client_id: ClientId, account: Account, db: DbSession) -> None:
    brands.visit(db, account, client_of(db, account, client_id, READ))


@router.delete("/clients/{client_id}", status_code=204, summary="Move a client into the bin (writers)")
def trash(client_id: ClientId, account: Account, db: DbSession) -> None:
    brands.trash(db, client_of(db, account, client_id, WRITE))


@router.post("/clients/{client_id}/restore", summary="Bring a client back from the bin (writers)")
def restore(client_id: ClientId, account: Account, db: DbSession) -> dict[str, Any]:
    client = client_of(db, account, client_id, WRITE, deleted=True)
    brands.restore(db, client)
    return client_view(db, account, client)


@router.delete("/clients/{client_id}/purge", status_code=204, summary="Delete a client in the bin for good (managers)")
def purge(client_id: ClientId, account: Account, db: DbSession) -> None:
    brands.purge(db, client_of(db, account, client_id, MANAGE, deleted=True))


# --- Versions ---------------------------------------------------------------------------------------------------


def _version(db: DbSession, client: Client, version_id: str) -> BrandVersion:
    try:
        return brands.version_for(db, client, version_id)
    except brands.BrandError as exc:
        raise _fail(exc) from exc


@router.post("/clients/{client_id}/versions", status_code=201, summary="A new draft: a copy, a given set, or empty")
def new_version(client_id: ClientId, payload: VersionIn, account: Account, db: DbSession) -> dict[str, Any]:
    client = client_of(db, account, client_id, WRITE)
    source = _version(db, client, payload.source) if payload.source else None
    try:
        row = brands.create_version(db, account, client, label=payload.label, source=source, data=payload.data,
                                    note=payload.note, origin=payload.origin)
    except brands.BrandError as exc:
        raise _fail(exc) from exc
    return version_view(row)


@router.put("/clients/{client_id}/versions/{version_id}", summary="Change a draft")
def change_version(
    client_id: ClientId, version_id: VersionId, payload: VersionChange, account: Account, db: DbSession,
) -> dict[str, Any]:
    client = client_of(db, account, client_id, WRITE)
    try:
        row = brands.change_draft(db, account, client, _version(db, client, version_id), label=payload.label,
                                  note=payload.note, data=payload.data)
    except brands.BrandError as exc:
        raise _fail(exc) from exc
    return version_view(row)


@router.post("/clients/{client_id}/versions/{version_id}/publish", summary="Publish a draft; it never changes again")
def publish(
    client_id: ClientId, version_id: VersionId, payload: PublishIn, account: Account, db: DbSession,
) -> dict[str, Any]:
    client = client_of(db, account, client_id, WRITE)
    try:
        row = brands.publish(db, account, client, _version(db, client, version_id), valid_from=payload.valid_from,
                             label=payload.label)
    except brands.BrandError as exc:
        raise _fail(exc) from exc
    return version_view(row)


@router.delete("/clients/{client_id}/versions/{version_id}", status_code=204, summary="Delete a draft")
def delete_version(client_id: ClientId, version_id: VersionId, account: Account, db: DbSession) -> None:
    client = client_of(db, account, client_id, WRITE)
    try:
        brands.delete_draft(db, account, client, _version(db, client, version_id))
    except brands.BrandError as exc:
        raise _fail(exc) from exc


@router.get("/clients/{client_id}/export", response_model=None, summary="A version (or a project) as code")
def export(
    client_id: ClientId, account: Account, db: DbSession,
    format: Annotated[str, Query(pattern="^(css|tailwind|scss|json)$")] = "css",
    version: Annotated[str | None, Query(max_length=24)] = None,
    project: Annotated[str | None, Query(max_length=24)] = None,
    download: bool = False,
) -> Response:
    client = client_of(db, account, client_id, READ)
    try:
        color_list = None
        title = client.name
        if project:
            row = brands.project_for(db, client, project)
            chosen = brands.version_for(db, client, row.version_id)
            color_list = brands.project_colors(chosen, row)
            title = f"{client.name}, {row.name}"
        elif version:
            chosen = brands.version_for(db, client, version)
        else:
            found = brands.current(db, client) or (brands.versions(db, client) or [None])[0]
            if found is None:
                raise brands.BrandError("not_found", "Not found.", 404)
            chosen = found
    except brands.BrandError as exc:
        raise _fail(exc) from exc
    text = tokens.render(chosen.data, format, color_list=color_list, title=f"{title} {chosen.label}")
    ending = {"css": "css", "tailwind": "css", "scss": "scss", "json": "tokens.json"}[format]
    headers = {}
    if download:
        name = f"{tokens.slug(client.name)}-{tokens.slug(chosen.label)}.{ending}"
        headers["Content-Disposition"] = f'attachment; filename="{name}"'
    return Response(text, media_type="application/json" if format == "json" else "text/plain; charset=utf-8",
                    headers=headers)


# --- Projects ---------------------------------------------------------------------------------------------------


@router.post("/clients/{client_id}/projects", status_code=201, summary="A new project on a version")
def new_project(client_id: ClientId, payload: ProjectIn, account: Account, db: DbSession) -> dict[str, Any]:
    client = client_of(db, account, client_id, WRITE)
    try:
        row = brands.create_project(db, account, client, name=payload.name, version_id=payload.version_id,
                                    note=payload.note, own=payload.own)
    except brands.BrandError as exc:
        raise _fail(exc) from exc
    return project_view(row)


@router.patch("/clients/{client_id}/projects/{project_id}", summary="Rename, own colours, lift to another version")
def change_project(
    client_id: ClientId, project_id: VersionId, payload: ProjectChange, account: Account, db: DbSession,
) -> dict[str, Any]:
    client = client_of(db, account, client_id, WRITE)
    try:
        row = brands.change_project(db, account, client, brands.project_for(db, client, project_id),
                                    name=payload.name, note=payload.note, version_id=payload.version_id,
                                    own=payload.own)
    except brands.BrandError as exc:
        raise _fail(exc) from exc
    return project_view(row)


@router.delete("/clients/{client_id}/projects/{project_id}", status_code=204, summary="Remove a project")
def delete_project(client_id: ClientId, project_id: VersionId, account: Account, db: DbSession) -> None:
    client = client_of(db, account, client_id, WRITE)
    try:
        brands.delete_project(db, account, client, brands.project_for(db, client, project_id))
    except brands.BrandError as exc:
        raise _fail(exc) from exc
