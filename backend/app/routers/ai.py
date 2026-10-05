"""The account's own AI service (``services/ai.py``): its access, the models it offers, three directions from a few
words, and the list of what went out. Every account sees only its own; the operator's lock is checked on every
request that sends."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..deps import Account, DbSession
from ..errors import error
from ..models import Account as AccountRow
from ..services import ai, brandset

router = APIRouter(prefix="/api/ai", tags=["ai"])

MOODS = ("warm", "fresh", "serious", "playful", "fine", "bold", "calm")


class AccessIn(BaseModel):
    active: bool | None = None
    url: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=200)
    #: Empty removes the key; left out keeps it.
    key: str | None = Field(default=None, max_length=1000)


class ModelsIn(BaseModel):
    """The address and key being typed, before they are saved; left out: the saved ones."""

    url: str | None = Field(default=None, max_length=500)
    key: str | None = Field(default=None, max_length=1000)


class DirectionsIn(BaseModel):
    brief: str = Field(min_length=3, max_length=2000)
    name: str = Field(default="", max_length=200)
    language: str = Field(default="English", max_length=40)


def _row(db: DbSession, account: Account) -> AccountRow:
    row = db.get(AccountRow, account.id)
    if row is None:
        raise error("sign_in_required", "Sign in first.", 401)
    return row


def _fail(exc: ai.AiError) -> Exception:
    return error(exc.code, exc.message, exc.status, **exc.values)


@router.get("", summary="The own AI service: allowed by the operator, and the access")
def read(account: Account, db: DbSession) -> dict[str, Any]:
    row = _row(db, account)
    return {"allowed": ai.allowed(db), "ready": ai.ready(db, row), "access": ai.view(row)}


@router.put("", summary="Change the own access; what is left out stays")
def save(payload: AccessIn, account: Account, db: DbSession) -> dict[str, Any]:
    row = _row(db, account)
    try:
        ai.save(db, row, active=payload.active, url=payload.url, model=payload.model, key=payload.key)
    except ai.AiError as exc:
        raise _fail(exc) from exc
    return read(account, db)


@router.post("/models", summary="The models the access offers (the test that address and key are right)")
def models(payload: ModelsIn, account: Account, db: DbSession) -> list[dict[str, str]]:
    row = _row(db, account)
    if not ai.allowed(db):
        raise error("ai_off", "The operator has not allowed AI.", 403)
    try:
        url = payload.url if payload.url is not None else row.ai_url
        key = payload.key if payload.key is not None else ai.key_of(row)
        return ai.list_models(db, url, key)
    except ai.AiError as exc:
        raise _fail(exc) from exc


@router.post("/directions", summary="Three directions for a new client from a few words")
def directions(payload: DirectionsIn, account: Account, db: DbSession) -> dict[str, Any]:
    row = _row(db, account)
    try:
        answer = ai.run(db, row, task="directions", material={"client": payload.name, "description": payload.brief},
                        language=payload.language, fonts=", ".join(brandset.CATALOG))
    except ai.AiError as exc:
        raise _fail(exc) from exc
    out = []
    for entry in (answer.get("directions") if isinstance(answer, dict) else None) or []:
        if not isinstance(entry, dict):
            continue
        try:
            hue = int(entry.get("hue")) % 360
            accent = int(entry.get("accent_hue", hue + 30)) % 360
            saturation = max(20, min(90, int(entry.get("saturation", 55))))
        except (TypeError, ValueError):
            continue
        head = entry.get("head") if entry.get("head") in brandset.CATALOG else "fraunces"
        body = entry.get("body") if entry.get("body") in brandset.CATALOG else "inter"
        out.append({
            "label": " ".join(str(entry.get("label") or "").split())[:80],
            "why": " ".join(str(entry.get("why") or "").split())[:400],
            "hue": hue, "accent_hue": accent, "saturation": saturation,
            "mood": entry.get("mood") if entry.get("mood") in MOODS else "calm",
            "head": head, "body": body,
        })
        if len(out) == 3:
            break
    if not out:
        raise error("ai_unreadable", "The AI service answered something else.", 502)
    return {"directions": out}


@router.get("/events", summary="What went out to the own AI service in the last days")
def events(account: Account, db: DbSession) -> list[dict[str, Any]]:
    return ai.events(db, _row(db, account))


@router.delete("/events", summary="Clear the own list of what went out")
def clear(account: Account, db: DbSession) -> dict[str, int]:
    return {"removed": ai.clear_events(db, _row(db, account))}
