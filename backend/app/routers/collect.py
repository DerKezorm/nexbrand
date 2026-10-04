"""Collecting a brand: websites, GitHub repositories, PDF style guides (``services/collect.py``), sorted by rules or
by the account's AI, and a logo found there taken into a space.

Websites and repositories are a way out: closed until the operator opens it (``collect_allowed``). A PDF is a file
already uploaded into a space the account may read; it never leaves the house.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from ..db import SessionLocal
from ..deps import Account
from ..errors import error
from ..models import READ, WRITE, Media
from ..models import Account as AccountRow
from ..security import decrypt_secret
from ..services import ai, brandset, collect, media, media_store, outbound, rights, settings_service
from .media import FILE_POLICY

logger = logging.getLogger("nexbrand.collect")

router = APIRouter(prefix="/api/collect", tags=["collect"])

MAX_SOURCES = 6
PICTURES = {"svg", "png", "jpeg", "webp", "gif", "avif"}


class Source(BaseModel):
    kind: Literal["website", "repo", "pdf"]
    #: An address (website, repository) or a media id (PDF).
    value: str = Field(min_length=1, max_length=2000)


class CollectIn(BaseModel):
    sources: Annotated[list[Source], Field(min_length=1, max_length=MAX_SOURCES)]
    #: Sort with the account's AI when it has one switched on.
    use_ai: bool = False
    language: str = Field(default="en", max_length=8)


class FontFile(BaseModel):
    url: str = Field(min_length=8, max_length=500)
    weight: str = Field(default="400", max_length=20)
    style: str = Field(default="normal", max_length=20)


class FontsIn(BaseModel):
    client_id: str = Field(min_length=6, max_length=24, pattern=r"^[A-Za-z0-9_-]+$")
    family: str = Field(min_length=1, max_length=80)
    files: Annotated[list[FontFile], Field(min_length=1, max_length=12)]
    #: The person confirmed that the agency holds a licence that allows keeping these files. Without it, nothing.
    licensed: bool = False


class LogoIn(BaseModel):
    client_id: str = Field(min_length=6, max_length=24, pattern=r"^[A-Za-z0-9_-]+$")
    url: str = Field(min_length=8, max_length=2000)


def _language_name(code: str) -> str:
    return {"de": "German", "en": "English", "fr": "French", "es": "Spanish", "it": "Italian", "nl": "Dutch"}.get(
        code[:2].lower(), "English")


def _collect(account_id: int, payload: CollectIn) -> dict[str, Any]:
    found = collect.Found()
    with SessionLocal() as db:
        outside = bool(settings_service.get(db, "collect_allowed"))
        token_enc = str(settings_service.get(db, "collect_github_token_enc") or "")
        account = db.get(AccountRow, account_id)
        assert account is not None
        for source in payload.sources:
            try:
                if source.kind in ("website", "repo"):
                    if not outside:
                        raise error("collect_off", "The operator has not allowed collecting from outside.", 403)
                    if source.kind == "website":
                        collect.from_website(found, source.value.strip())
                    else:
                        token = decrypt_secret(token_enc, "collect:github") if token_enc else ""
                        collect.from_repo(found, source.value.strip(), token)
                else:
                    row = db.get(Media, source.value)
                    if row is None or row.kind != "pdf" or not rights.at_least(
                            rights.role_in(db, account, row.space_id), READ):
                        raise error("not_found", "Not found.", 404)
                    collect.from_pdf(found, media_store.path_of(row.id), row.name)
            except outbound.FetchError as exc:
                found.notes.append({"source": source.value[:200], "problem": exc.code})
            except Exception as exc:
                if getattr(exc, "status_code", 0):
                    raise
                logger.warning("A source could not be read: %s", type(exc).__name__)
                found.notes.append({"source": source.value[:200], "problem": "unreadable"})
        items = collect.merged(found)
        language = payload.language[:2].lower()
        used_ai = False
        answer: Any = None
        if payload.use_ai and items and ai.ready(db, account):
            material = {"colors": [{k: i[k] for k in ("hex", "share", "names", "where")} for i in items],
                        "fonts": [{"family": f["family"], "where": sorted(f["where"])} for f in found.fonts.values()]}
            try:
                answer = ai.run(db, account, task="order", material=material, language=_language_name(language))
                used_ai = True
            except ai.AiError as exc:
                found.notes.append({"source": "ai", "problem": exc.code})
        ordered = collect.order_with_ai(items, answer, language) if used_ai else collect.order_by_rules(items, language)
        return {"colors": ordered, "fonts": collect.fonts_of(found, answer if used_ai else None), "logos": found.logos,
                "notes": found.notes, "ai": used_ai, "system_font": found.system_font}


@router.post("", summary="Collect colours, fonts and logos from websites, repositories and PDFs")
async def run(payload: CollectIn, account: Account) -> dict[str, Any]:
    logger.info("Collecting sources=%s by=%s", ",".join(s.kind for s in payload.sources), account.name)
    return await run_in_threadpool(_collect, account.id, payload)


MAX_PREVIEW = 3 * 1024 * 1024


@router.get("/preview", response_model=None, summary="A logo found while collecting, fetched by the server to look at")
async def preview(account: Account, url: Annotated[str, Query(min_length=8, max_length=2000)]) -> Response:
    """The page shows a found logo without loading it from the other website itself (that would tell it who looks).
    Only pictures, only public addresses, as small as the collecting; served as a sandboxed file, never as a page."""
    del account
    with SessionLocal() as db:
        if not settings_service.get(db, "collect_allowed"):
            raise error("collect_off", "The operator has not allowed collecting from outside.", 403)
    try:
        fetched = await run_in_threadpool(outbound.get, url, limit=MAX_PREVIEW, accept="image/*")
    except outbound.FetchError as exc:
        raise error("collect_failed", "The picture could not be fetched.", 502, problem=exc.code) from exc
    head = fetched.body[:1024]
    kind = media.sniff(head[:64]) or ("svg" if media_store.is_svg(head) else "file")
    if kind not in PICTURES:
        raise error("not_a_picture", "This is not a picture.", 422)
    return Response(fetched.body, media_type=media_store.SHOWN.get(kind, "application/octet-stream"), headers={
        "Content-Security-Policy": FILE_POLICY, "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, max-age=600"})


MAX_FONT_FILE = 8 * 1024 * 1024


@router.post("/fonts", status_code=201, summary="Take a font's files into a client's files (licence confirmed)")
async def take_fonts(payload: FontsIn, account: Account) -> dict[str, Any]:
    """A font's files from where a website keeps them. A font is someone's work: most licences allow it on the own
    website only. So nothing is fetched unless the person confirmed the licence; who did stands in the log."""
    if not payload.licensed:
        raise error("licence_not_confirmed", "Confirm that you hold a licence for this font.", 422)
    with SessionLocal() as db:
        if not settings_service.get(db, "collect_allowed"):
            raise error("collect_off", "The operator has not allowed collecting from outside.", 403)
        try:
            space_id = rights.client_for(db, account, payload.client_id, WRITE).space_id
        except rights.RightsError as exc:
            raise error(exc.code, exc.text, exc.status) from exc
    taken: list[dict[str, Any]] = []
    notes: list[dict[str, str]] = []
    stem = re.sub(r"[^A-Za-z0-9]+", "-", payload.family).strip("-") or "font"
    for item in payload.files:
        try:
            fetched = await run_in_threadpool(outbound.get, item.url, limit=MAX_FONT_FILE, accept="font/*, */*")
        except outbound.FetchError as exc:
            notes.append({"source": item.url[:200], "problem": exc.code})
            continue
        kind = media.sniff(fetched.body[:64])
        if kind not in brandset.FONT_KINDS:
            notes.append({"source": item.url[:200], "problem": "not_a_font"})
            continue
        received = media_store.temporary()
        received.write_bytes(fetched.body)
        italic = "-italic" if "italic" in item.style.lower() else ""
        name = f"{stem}-{re.sub(r'[^0-9a-z]+', '', item.weight.lower()) or '400'}{italic}.{kind}"

        def finish(received: Any = received, name: str = name) -> media_store.Stored:
            with SessionLocal() as db:
                return media_store.finish(db, account, space_id, received, name)

        try:
            stored = await run_in_threadpool(finish)
        finally:
            received.unlink(missing_ok=True)
        taken.append({"id": stored.id, "name": stored.name, "kind": stored.kind, "weight": item.weight,
                      "style": item.style})
    logger.info("Font files taken client=%s family=%s files=%s licence confirmed by=%s", payload.client_id,
                payload.family, len(taken), account.name)
    return {"files": taken, "notes": notes}


@router.post("/logo", status_code=201, summary="Take a logo found while collecting into a client's files")
async def take_logo(payload: LogoIn, account: Account) -> dict[str, Any]:
    with SessionLocal() as db:
        if not settings_service.get(db, "collect_allowed"):
            raise error("collect_off", "The operator has not allowed collecting from outside.", 403)
        try:
            space_id = rights.client_for(db, account, payload.client_id, WRITE).space_id
        except rights.RightsError as exc:
            raise error(exc.code, exc.text, exc.status) from exc
        limit = min(media_store.max_bytes(db), 5 * 1024 * 1024)
    try:
        fetched = await run_in_threadpool(outbound.get, payload.url, limit=limit, accept="image/*")
    except outbound.FetchError as exc:
        raise error("collect_failed", "The logo could not be fetched.", 502, problem=exc.code) from exc
    head = fetched.body[:1024]
    if (media.sniff(head[:64]) or ("svg" if media_store.is_svg(head) else "file")) not in PICTURES:
        raise error("not_a_picture", "This file is not a picture that works as a logo.", 422)
    received = media_store.temporary()
    received.write_bytes(fetched.body)
    name = os.path.basename(fetched.url.split("?")[0]) or "logo"

    def finish() -> media_store.Stored:
        with SessionLocal() as db:
            return media_store.finish(db, account, space_id, received, name)

    try:
        stored = await run_in_threadpool(finish)
    finally:
        received.unlink(missing_ok=True)
    return {"id": stored.id, "name": stored.name, "kind": stored.kind, "size": stored.size}
