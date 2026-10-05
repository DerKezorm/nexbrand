"""Public read-only pages of a client's design set, for a printer, a photographer or the client itself.

* **Closed until the operator opens it** (``shares_allowed``); from write up a person of the agency makes a page;
  whoever made it, or a manager, changes it or takes it down.
* **The link is the key**: a long random token, kept so it can be copied again; it opens this one client only. Readers
  see that there are pages, never their links: they could hand the client's design set out unnoticed (A3).
* **As code too**: CSS, Tailwind, SCSS and design tokens, the same text as the export in the app, for a developer
  without an account.
* **A version fixed, or always the current one**: a print job keeps what it was ordered with.
* **An end date and a password** can be set; a wrong password counts on a brake per page and sender.
* **Only what the page shows leaves**: the files the shown version names, never a font kept in the house (it shows
  by name only), never the checks.
* **The password is asked once** per browser: the answer sets a cookie for this page alone, signed with the
  server's secret, so a guesser cannot make one.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi import Path as PathParam
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..config import get_settings
from ..db import SessionLocal
from ..deps import Account, DbSession, client_ip
from ..errors import detail, error, invalid_characters
from ..models import MANAGE, PUBLISHED, READ, WRITE, BrandVersion, Client, Media, Project, Share, Space, utcnow
from ..security import Brake, hash_password, verify_password
from ..services import brands, brandset, names, rights, settings_service, tokens
from .media import deliver

logger = logging.getLogger("nexbrand.shares")

router = APIRouter(prefix="/api", tags=["shares"])

ClientId = Annotated[str, PathParam(min_length=6, max_length=24, pattern=r"^[A-Za-z0-9_-]+$")]
Token = Annotated[str, PathParam(min_length=20, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]
MediaId = Annotated[str, PathParam(min_length=8, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")]
COOKIE = "nexbrand_page" + get_settings().cookie_name_suffix()
#: Pages one client may have.
MAX_SHARES = 50
_brake = Brake()


class ShareIn(BaseModel):
    label: str = Field(default="", max_length=120)
    #: A published version to keep showing; None: always the current one.
    version_id: str | None = Field(default=None, max_length=24)
    #: A page of one project; None: of the client's own design set.
    project_id: str | None = Field(default=None, max_length=24)
    #: Days until the page closes; None: never.
    days: int | None = Field(default=30, ge=1, le=3650)
    password: str = Field(default="", max_length=200)


class ShareChange(BaseModel):
    label: str | None = Field(default=None, max_length=120)
    days: int | None = Field(default=None, ge=1, le=3650)
    #: True: the page never closes.
    forever: bool = False
    #: A new password replaces the one there is.
    password: str = Field(default="", max_length=200)
    no_password: bool = False


def _label(value: str) -> str:
    try:
        return names.title(value, 120)
    except ValueError as exc:
        raise invalid_characters() from exc


class UnlockIn(BaseModel):
    password: str = Field(max_length=200)


def link(db: Any, request: Request, path: str) -> str:
    base = settings_service.public_url(db) or str(request.base_url).rstrip("/")
    return f"{base}{path}"


def _view(db: DbSession, request: Request, share: Share, account: Any, role: str | None) -> dict[str, Any]:
    version = db.get(BrandVersion, share.version_id) if share.version_id else None
    return {
        "id": share.id,
        "project_id": share.project_id,
        "label": share.label,
        # The link is the key: for those who write only.
        "link": link(db, request, f"/s/{share.token}") if rights.at_least(role, WRITE) else None,
        "mine": share.created_by == account.id,
        "version_id": share.version_id,
        "version_label": version.label if version else None,
        "views": share.views,
        "created_at": share.created_at.isoformat(),
        "expires_at": share.expires_at.isoformat() if share.expires_at else None,
        "password": bool(share.password_hash),
    }


def _client(db: DbSession, account: Any, client_id: str, need: str) -> Client:
    try:
        return rights.client_for(db, account, client_id, need)
    except rights.RightsError as exc:
        raise error(exc.code, exc.text, exc.status) from exc


def _role(db: DbSession, account: Any, client: Client) -> str | None:
    return rights.role_in(db, account, client.space_id)


def _share(db: DbSession, account: Any, share_id: int) -> tuple[Share, str | None]:
    """A page the account may change: one it made (writing still), or any of a client it manages."""
    share = db.get(Share, share_id)
    if share is None:
        raise error("not_found", "Not found.", 404)
    client = _client(db, account, share.client_id, WRITE)
    role = _role(db, account, client)
    if share.created_by != account.id and not rights.at_least(role, MANAGE):
        raise error("forbidden", "Whoever made the page, or a manager of the client, changes it.", 403)
    return share, role


@router.get("/clients/{client_id}/shares", summary="The public pages of a client (links: writers)")
def list_shares(client_id: ClientId, request: Request, account: Account, db: DbSession) -> list[dict[str, Any]]:
    client = _client(db, account, client_id, READ)
    role = _role(db, account, client)
    rows = db.scalars(select(Share).where(Share.client_id == client.id).order_by(Share.created_at.desc()))
    return [_view(db, request, row, account, role) for row in rows]


@router.post("/clients/{client_id}/shares", status_code=201, summary="A new public page of a client (writers)")
def make_share(client_id: ClientId, payload: ShareIn, request: Request, account: Account, db: DbSession) -> dict:
    if not settings_service.get(db, "shares_allowed"):
        raise error("shares_off", "The operator has not allowed public pages.", 403)
    client = _client(db, account, client_id, WRITE)
    if len(db.scalars(select(Share.id).where(Share.client_id == client.id)).all()) >= MAX_SHARES:
        raise error("too_many_shares", "This client has as many public pages as it may.", 409)
    try:
        project = brands.project_for(db, client, payload.project_id) if payload.project_id else None
    except brands.BrandError as exc:
        raise error(exc.code, exc.text, exc.status) from exc
    if payload.version_id:
        try:
            version = brands.version_for(db, client, payload.version_id)
        except brands.BrandError as exc:
            raise error(exc.code, exc.text, exc.status) from exc
        if version.status != PUBLISHED:
            raise error("not_published", "Only a published version goes on a page.", 409)
        if version.project_id != (project.id if project else None):
            raise error("not_found", "Not found.", 404)
    elif (brands.project_current(db, project) if project else brands.current(db, client)) is None:
        raise error("not_published", "This client has no published version yet.", 409)
    label = _label(payload.label)
    share = Share(token=secrets.token_urlsafe(24), client_id=client.id, space_id=client.space_id,
                  version_id=payload.version_id or None, project_id=project.id if project else None,
                  label=label,
                  created_by=account.id,
                  expires_at=utcnow() + timedelta(days=payload.days) if payload.days else None,
                  password_hash=hash_password(payload.password) if payload.password else "")
    db.add(share)
    db.commit()
    guarded = bool(payload.password)
    logger.info("Public page made client=%s fixed=%s ends=%s guarded=%s by=%s", client.id, bool(share.version_id),
                payload.days or "-", guarded, account.name)
    return _view(db, request, share, account, _role(db, account, client))


@router.patch("/shares/{share_id}", summary="Change a public page's name, end or password (its maker, managers)")
def change_share(share_id: int, payload: ShareChange, request: Request, account: Account, db: DbSession) -> dict:
    share, role = _share(db, account, share_id)
    if payload.label is not None:
        share.label = _label(payload.label)
    if payload.forever:
        share.expires_at = None
    elif payload.days is not None:
        share.expires_at = utcnow() + timedelta(days=payload.days)
    if payload.no_password:
        share.password_hash = ""
    elif payload.password:
        share.password_hash = hash_password(payload.password)
    db.commit()
    return _view(db, request, share, account, role)


@router.delete("/shares/{share_id}", status_code=204, summary="Take a public page down (its maker, managers)")
def delete_share(share_id: int, account: Account, db: DbSession) -> None:
    share, _ = _share(db, account, share_id)
    db.delete(share)
    db.commit()


# --- The page itself, without signing in ----------------------------------------------------------------------------


def _open(db: Any, token: str) -> tuple[Share, Client, BrandVersion]:
    """The page, its client and the version it shows, or the one answer for everything that is not a page any more."""
    share = db.scalar(select(Share).where(Share.token == token))
    client = db.get(Client, share.client_id) if share is not None else None
    space = db.get(Space, client.space_id) if client is not None else None
    version = None
    if client is not None and share is not None:
        project = db.get(Project, share.project_id) if share.project_id else None
        if share.version_id:
            version = db.get(BrandVersion, share.version_id)
        else:
            version = brands.project_current(db, project) if project else brands.current(db, client)
    if (
        share is None or client is None or client.deleted_at is not None
        # The space in the bin (here, or deleted in nexsuite): its clients are gone for everybody (A8).
        or space is None or space.deleted_at is not None
        or version is None or version.status != PUBLISHED
        or not settings_service.get(db, "shares_allowed")
        or (share.expires_at is not None and share.expires_at <= utcnow())
    ):
        raise error("not_found", "Not found.", 404)
    return share, client, version


def _pass(share: Share) -> str:
    key = get_settings().resolved_secret_key().encode()
    return hmac.new(key, f"page:{share.id}:{share.password_hash}".encode(), hashlib.sha256).hexdigest()


def _unlocked(request: Request, share: Share) -> bool:
    return not share.password_hash or hmac.compare_digest(request.cookies.get(COOKIE, ""), _pass(share))


def _page(db: Any, share: Share, client: Client, version: BrandVersion) -> dict[str, Any]:
    share.views += 1
    db.commit()
    data = brands.for_public(db, brands.effective(db, version), client.space_id)
    files = brandset.media_of(data)
    project = db.get(Project, share.project_id) if share.project_id else None
    rows = db.scalars(select(Media).where(Media.id.in_(files))) if files else []
    return {
        "client": client.name,
        "project": project.name if project else None,
        "sector": client.sector,
        "label": share.label,
        "version": {"label": version.label, "valid_from": version.valid_from},
        "design": data,
        "files": {row.id: {"name": row.name, "kind": row.kind, "size": row.size} for row in rows},
        "token": share.token,
    }


@router.get("/public/{token}", summary="A public page (no sign-in): the design set, or that it needs a password")
def public_page(token: Token, request: Request) -> dict[str, Any]:
    with SessionLocal() as db:
        share, client, version = _open(db, token)
        if not _unlocked(request, share):
            return {"password": True}
        return _page(db, share, client, version)


@router.post("/public/{token}", summary="Open a public page with its password")
def unlock(token: Token, payload: UnlockIn, request: Request, response: Response) -> dict[str, Any]:
    with SessionLocal() as db:
        share, client, version = _open(db, token)
        key = f"page:{share.id}:{client_ip(request)}"
        wait = _brake.wait_seconds(key)
        if wait:
            raise HTTPException(
                status_code=429,
                detail=detail("too_many_attempts", "Too many attempts. Try again later.", retry_after=wait),
                headers={"Retry-After": str(wait)},
            )
        if share.password_hash and not verify_password(payload.password, share.password_hash):
            _brake.failed(key)
            raise error("wrong_password", "The password is wrong.", 401)
        _brake.succeeded(key)
        response.set_cookie(COOKIE, _pass(share), httponly=True, samesite="lax", path=f"/api/public/{share.token}",
                            secure=request.url.scheme == "https")
        return _page(db, share, client, version)


@router.get("/public/{token}/code", response_model=None, summary="A public page's design set as code")
def public_code(
    token: Token, request: Request,
    format: Annotated[str, Query(pattern="^(css|tailwind|scss|json)$")] = "css",
    download: bool = False,
) -> Response:
    """The same text as the export in the app, of what the page shows: fonts kept in the house by name only."""
    with SessionLocal() as db:
        share, client, version = _open(db, token)
        if not _unlocked(request, share):
            raise error("not_found", "Not found.", 404)
        project = db.get(Project, share.project_id) if share.project_id else None
        title = f"{client.name}, {project.name}" if project else client.name
        text = tokens.render(brands.for_public(db, brands.effective(db, version), client.space_id), format,
                             title=f"{title} {version.label}")
        name = f"{tokens.slug(title)}-{tokens.slug(version.label)}"
    ending = {"css": "css", "tailwind": "css", "scss": "scss", "json": "tokens.json"}[format]
    headers = {"Cache-Control": "no-store"}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{name}.{ending}"'
    return Response(text, media_type="application/json" if format == "json" else "text/plain; charset=utf-8",
                    headers=headers)


@router.get("/public/{token}/media/{media_id}", response_model=None, summary="A file of a public page")
def public_media(token: Token, media_id: MediaId, request: Request, download: bool = False,
                 preview: bool = False) -> Response:
    with SessionLocal() as db:
        share, client, version = _open(db, token)
        if not _unlocked(request, share):
            raise error("not_found", "Not found.", 404)
        named = brandset.media_of(brands.for_public(db, brands.effective(db, version), client.space_id))
        row = db.get(Media, media_id)
        if row is None or media_id not in named or row.space_id != client.space_id:
            raise error("not_found", "Not found.", 404)
        db.expunge(row)
    return deliver(row, request, download, preview)
