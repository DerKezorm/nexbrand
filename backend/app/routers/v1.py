"""The API for programs (``/api/v1``): scripts, build pipelines, nexdeck. An API token in ``Authorization: Bearer``.

**The promise.** What is under ``/api/v1`` stays as it is: new fields may come, nothing is renamed or taken away. A
change that would break a program goes to ``/api/v2`` beside it. ``docs/api.md`` describes every route.

Walls, in this order: a request that carries an ``Origin`` is refused (browsers send one, programs do not; no web page
can use a token it found); API tokens must be switched on by the operator; the token must be valid; the token must stay
under its rate. The session cookie counts for nothing here.

A token reads with the rights of its account, limited to its spaces: a space or client it may not read answers like
one that does not exist. Only a ``draft`` token proposes, and only as a draft.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi import Path as PathParam
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from .. import __version__
from ..db import SessionLocal
from ..errors import error
from ..models import Client, Media
from ..services import apitokens, brandapi, brandset, checks, logs, media_store, rights, settings_service
from ..services.apitokens import Caller
from .media import FILE_POLICY

logger = logging.getLogger("nexbrand.api")

router = APIRouter(prefix="/api/v1", tags=["api v1"])

Key = Annotated[str, PathParam(min_length=1, max_length=200)]


def _token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    return header[7:].strip() if header[:7].lower() == "bearer " else None


def caller(request: Request) -> Caller:
    if request.headers.get("origin"):
        raise error("origin_refused", "The API is for programs, not web pages.", 403)
    with SessionLocal() as db:
        if not apitokens.allowed(db):
            raise error("api_off", "The operator has not switched API tokens on.", 401)
        found = apitokens.authenticate(db, _token(request))
    if found is None:
        raise error("token_invalid", "No valid API token.", 401)
    if not apitokens.brake(found.token_id):
        exc = error("slow_down", "Too many requests with this token. Wait a minute.", 429)
        exc.headers = {"Retry-After": "60"}
        raise exc
    logs.set_actor(found.account.name)
    return found


Reader = Annotated[Caller, Depends(caller)]


def base_url(request: Request, db: Any) -> str:
    return settings_service.public_url(db) or str(request.base_url).rstrip("/")


def _fail(exc: brandapi.ApiError) -> Exception:
    return error(exc.code, exc.text, exc.status, **exc.values)


@router.get("/me", summary="Who the token speaks for, and what it may")
def me(found: Reader) -> dict[str, Any]:
    with SessionLocal() as db:
        ids = rights.readable_ids(db, found.account)
    return {"name": found.account.name, "display_name": found.account.display_name, "level": found.level,
            "spaces": len(ids), "version": __version__}


@router.get("/spaces", summary="The spaces the token may read, with how many clients each holds")
def spaces(found: Reader) -> list[dict[str, Any]]:
    from ..models import Space

    with SessionLocal() as db:
        ids = rights.readable_ids(db, found.account)
        if not ids:
            return []
        counts = dict(db.execute(select(Client.space_id, func.count()).where(
            Client.space_id.in_(ids), Client.deleted_at.is_(None)).group_by(Client.space_id)).all())
        rows = db.scalars(select(Space).where(Space.id.in_(ids)).order_by(Space.name))
        return [{"id": s.id, "name": s.name, "color": s.color, "clients": int(counts.get(s.id, 0))} for s in rows]


@router.get("/clients", summary="Clients the token may read, with their current version and projects")
def clients(found: Reader, search: Annotated[str, Query(max_length=120)] = "") -> list[dict[str, Any]]:
    with SessionLocal() as db:
        return brandapi.list_clients(db, found, search)


@router.get("/clients/{client}", summary="A client's design set: current, a version, as of a day, or a project")
def brand(
    client: Key, request: Request, found: Reader,
    version: Annotated[str | None, Query(max_length=120)] = None,
    at: Annotated[str | None, Query(max_length=10)] = None,
    project: Annotated[str | None, Query(max_length=120)] = None,
) -> dict[str, Any]:
    with SessionLocal() as db:
        try:
            return brandapi.brand(db, found, client, version=version, at=at, project=project,
                                  base=base_url(request, db))
        except brandapi.ApiError as exc:
            raise _fail(exc) from exc


@router.get("/clients/{client}/versions", summary="Every version of a client's design set")
def versions(client: Key, found: Reader) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        try:
            return brandapi.versions(db, found, client)
        except brandapi.ApiError as exc:
            raise _fail(exc) from exc


@router.get("/clients/{client}/code", response_model=None, summary="The design set as CSS, Tailwind, SCSS or tokens")
def code(
    client: Key, found: Reader,
    format: Annotated[str, Query(pattern="^(css|tailwind|scss|json)$")] = "css",
    version: Annotated[str | None, Query(max_length=120)] = None,
    at: Annotated[str | None, Query(max_length=10)] = None,
    project: Annotated[str | None, Query(max_length=120)] = None,
) -> Response:
    with SessionLocal() as db:
        try:
            text = brandapi.as_code(db, found, client, format, version=version, at=at, project=project)
        except brandapi.ApiError as exc:
            raise _fail(exc) from exc
    return Response(text, media_type="application/json" if format == "json" else "text/plain; charset=utf-8")


class AuditIn(BaseModel):
    colors: list[str] = Field(max_length=500)
    project: str | None = Field(default=None, max_length=120)


@router.post("/clients/{client}/audit", summary="Colour values from code or a page, against the design set")
def audit(client: Key, payload: AuditIn, found: Reader) -> dict[str, Any]:
    with SessionLocal() as db:
        try:
            return brandapi.audit(db, found, client, payload.colors, project=payload.project)
        except brandapi.ApiError as exc:
            raise _fail(exc) from exc


class ProposeIn(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    data: dict[str, Any]
    note: str = Field(default="", max_length=500)
    #: A version whose parts not sent are kept (logos and fonts with their files, for instance).
    based_on: str | None = Field(default=None, max_length=120)


@router.post("/clients/{client}/drafts", status_code=201, summary="Propose a version as a draft (draft tokens)")
def propose(client: Key, payload: ProposeIn, found: Reader) -> dict[str, Any]:
    with SessionLocal() as db:
        try:
            return brandapi.propose(db, found, client, label=payload.label, data=payload.data, note=payload.note,
                                    source=payload.based_on)
        except brandapi.ApiError as exc:
            raise _fail(exc) from exc


@router.get("/contrast", summary="Contrast of two colours, with grades and the nearest passing colour")
def contrast(
    found: Reader,
    fg: Annotated[str, Query(max_length=9)],
    bg: Annotated[str, Query(max_length=9)],
) -> dict[str, Any]:
    del found
    try:
        return checks.pair(brandset.color_value(fg, "fg"), brandset.color_value(bg, "bg"))
    except brandset.SetError as exc:
        raise error("invalid_input", exc.text, 422, where=exc.where) from exc


@router.get("/files/{media_id}", response_model=None, summary="A logo, a free font or an example file")
def file(media_id: Annotated[str, PathParam(pattern=r"^[A-Za-z0-9_-]{8,40}$")], found: Reader) -> Response:
    with SessionLocal() as db:
        row = db.get(Media, media_id)
        if row is None or not rights.at_least(rights.role_in(db, found.account, row.space_id), "read"):
            raise error("not_found", "Not found.", 404)
        # A font kept in the house never leaves through a token, whichever version names it.
        from ..models import BrandVersion

        clients = select(Client.id).where(Client.space_id == row.space_id)
        for data in db.scalars(select(BrandVersion.data).where(BrandVersion.client_id.in_(clients))):
            if media_id in brandset.internal_media(data):
                raise error("not_found", "Not found.", 404)
        db.expunge(row)
    path = media_store.path_of(row.id)
    if not path.is_file():
        raise error("not_found", "Not found.", 404)
    return FileResponse(path, media_type=row.mime, filename=row.name, content_disposition_type="attachment",
                        headers={"Content-Security-Policy": FILE_POLICY, "X-Content-Type-Options": "nosniff"})
