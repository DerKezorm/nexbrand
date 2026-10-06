"""Reviews: a draft put before the client on a page of its own, without an account.

The agency picks one or more directions (each a whole design set), a few words and an end date; the client sees each
on a sample page, comments, and chooses one. The choice is written into the draft and publishes it, under the label
the agency gave ("1.0"): from then on it is the client's current design set, and its history says the client chose
it.

* **Closed until the operator opens it**, the same switch as public pages (``shares_allowed``); from write up a
  person of the agency puts a draft before the client and comments from the agency's side; whoever made a review, or
  a manager, withdraws it.
* **The link is the key**, as for public pages; a review that ran out or was withdrawn answers like none. Readers see
  that there is a review and what was said, never the link: with it they could choose for the client (A2).
* **By mail if wanted**: with a mail server set up, the link goes to the address given, in the language of the person
  who puts the draft forward.
* **Comments are brakes**: thirty an hour per page and sender, at most ``MAX_COMMENTS`` in all.
* **Only what the page shows leaves**: the files the directions name, never a font kept in the house as a file.
"""

from __future__ import annotations

import logging
import secrets
import unicodedata
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi import Path as PathParam
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from ..db import SessionLocal
from ..deps import Account, DbSession, client_ip
from ..errors import detail, error, invalid_characters
from ..models import DRAFT, MANAGE, READ, WRITE, BrandVersion, Client, Media, Review, ReviewComment, Space, utcnow
from ..security import Brake
from ..services import accounts, brands, brandset, mailer, names, rights, settings_service
from .media import deliver
from .shares import link

logger = logging.getLogger("nexbrand.reviews")

router = APIRouter(prefix="/api", tags=["reviews"])

ClientId = Annotated[str, PathParam(min_length=6, max_length=24, pattern=r"^[A-Za-z0-9_-]+$")]
Token = Annotated[str, PathParam(min_length=20, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]
MediaId = Annotated[str, PathParam(min_length=8, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")]
MAX_VARIANTS = 4
MAX_COMMENTS = 500
COMMENTS_PER_HOUR = 30
#: Review mails one account may send in an hour (the operator's mail server is not for sending without end).
MAILS_PER_HOUR = 20
_comments = Brake()
_mails = Brake()


class VariantIn(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9]{1,16}$")
    label: str = Field(min_length=1, max_length=80)
    why: str = Field(default="", max_length=600)
    data: dict[str, Any]


class ReviewIn(BaseModel):
    version_id: str = Field(min_length=6, max_length=24)
    variants: list[VariantIn] = Field(min_length=1, max_length=MAX_VARIANTS)
    #: The version's name once the client chose.
    label: str = Field(min_length=1, max_length=60)
    sender: str = Field(default="", max_length=120)
    message: str = Field(default="", max_length=1000)
    days: int = Field(default=30, ge=1, le=365)
    #: Where the link goes by mail; empty: nowhere, the link is copied.
    email: str = Field(default="", max_length=255)
    #: The language the person sees the app in, for the mail when the account has none of its own.
    language: str = Field(default="", max_length=16)


class CommentIn(BaseModel):
    variant: str = Field(pattern=r"^[a-z0-9]{1,16}$")
    #: An example of the direction the comment is about (its media id); empty: the direction as a whole.
    sample: str | None = Field(default=None, min_length=8, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    text: str = Field(min_length=1, max_length=2000)
    author: str = Field(default="", max_length=80)


class ChooseIn(BaseModel):
    variant: str = Field(pattern=r"^[a-z0-9]{1,16}$")
    author: str = Field(default="", max_length=80)


def _client(db: DbSession, account: Any, client_id: str, need: str) -> Client:
    try:
        return rights.client_for(db, account, client_id, need)
    except rights.RightsError as exc:
        raise error(exc.code, exc.text, exc.status) from exc


def _comments_of(db: Any, review: Review) -> list[dict[str, Any]]:
    rows = db.scalars(select(ReviewComment).where(ReviewComment.review_id == review.id).order_by(ReviewComment.id))
    return [{"id": c.id, "variant": c.variant, "sample": c.sample, "author": c.author, "text": c.text,
             "agency": c.agency, "at": c.created_at.isoformat()} for c in rows]


def _clean_name(value: str) -> str:
    """The client's name on the page: spaces gathered, no control or format characters (a right-to-left override
    lets a name read other than it is, as for the display names of accounts)."""
    # Cc: every control character, C0, DEL and C1 (U+0080 to U+009F); Cf: format characters.
    if any(unicodedata.category(char) in ("Cc", "Cf") for char in value):
        raise error("invalid_name", "A name cannot hold control or invisible characters.", 422)
    return " ".join(value.split())[:80]


def _title(value: str, most: int) -> str:
    """A direction's name, the version's name the client chooses, the sender: no control character (C1 and DEL too)."""
    try:
        return names.title(value, most)
    except ValueError as exc:
        raise invalid_characters() from exc


def _view(db: Any, request: Request, review: Review, account: Any, role: str | None) -> dict[str, Any]:
    return {
        "id": review.id,
        # The link is the key to choosing for the client: for those who write only.
        "link": link(db, request, f"/r/{review.token}") if rights.at_least(role, WRITE) else None,
        "mine": review.created_by == account.id,
        "version_id": review.version_id,
        "label": review.label,
        "sender": review.sender,
        "message": review.message,
        "status": review.status,
        "chosen": review.chosen,
        "chosen_by": review.chosen_by,
        "chosen_at": review.chosen_at.isoformat() if review.chosen_at else None,
        "variants": review.variants,
        "comments": _comments_of(db, review),
        "news": brands.review_news(db, review.client_id, review.id),
        "seen_at": review.seen_at.isoformat() if review.seen_at else None,
        "created_at": review.created_at.isoformat(),
        "expires_at": review.expires_at.isoformat() if review.expires_at else None,
    }


def _review(db: DbSession, account: Any, client_id: str, review_id: int, need: str) -> tuple[Client, Review]:
    client = _client(db, account, client_id, need)
    review = db.get(Review, review_id)
    if review is None or review.client_id != client.id:
        raise error("not_found", "Not found.", 404)
    return client, review


def _role(db: Any, account: Any, client: Client) -> str | None:
    return rights.role_in(db, account, client.space_id)


@router.get("/clients/{client_id}/reviews", summary="The reviews of a client, with their comments (links: writers)")
def list_reviews(client_id: ClientId, request: Request, account: Account, db: DbSession) -> list[dict[str, Any]]:
    client = _client(db, account, client_id, READ)
    role = _role(db, account, client)
    rows = db.scalars(select(Review).where(Review.client_id == client.id).order_by(Review.created_at.desc()))
    return [_view(db, request, row, account, role) for row in rows]


def _mail_to(db: Any, account: Any, email: str) -> str:
    """The address the link is to go to, checked before anything is made; empty: no mail."""
    email = email.strip()
    if not email:
        return ""
    if not accounts.EMAIL_PATTERN.match(email):
        raise error("invalid_email", "This is not a mail address.", 422)
    if not mailer.configured(db):
        raise error("mail_off", "No mail server is set up.", 409)
    # The link in a mail is the public address's, never one the request made up (the Host header).
    if not settings_service.public_url(db):
        raise error("public_url_missing", "Mail needs the public address of nexbrand; the operator sets it.", 409)
    if _mails.wait_seconds(f"review-mail:{account.id}", free=MAILS_PER_HOUR):
        raise error("too_many_attempts", "Too many mails. Try again later.", 429)
    return email


@router.post("/clients/{client_id}/reviews", status_code=201, summary="Put a draft before the client (writers)")
def make_review(client_id: ClientId, payload: ReviewIn, request: Request, account: Account, db: DbSession) -> dict:
    if not settings_service.get(db, "shares_allowed"):
        raise error("shares_off", "The operator has not allowed public pages.", 403)
    client = _client(db, account, client_id, WRITE)
    email = _mail_to(db, account, payload.email)
    try:
        version = brands.version_for(db, client, payload.version_id)
    except brands.BrandError as exc:
        raise error(exc.code, exc.text, exc.status) from exc
    if version.status != DRAFT:
        raise error("not_a_draft", "Only a draft is put before the client.", 409)
    if db.scalar(select(func.count()).select_from(Review).where(Review.version_id == version.id,
                                                                 Review.status == "open")):
        raise error("review_open", "This draft is before the client already.", 409)
    if len({v.id for v in payload.variants}) != len(payload.variants):
        raise error("invalid_input", "Two directions may not share an id.", 422)
    variants = []
    for index, variant in enumerate(payload.variants):
        try:
            data = brandset.clean(variant.data, db, client.space_id)
        except brandset.SetError as exc:
            raise error("invalid_set", exc.text, 422, where=f"variants.{index}.{exc.where}") from exc
        variants.append({"id": variant.id, "label": _title(variant.label, 80),
                         "why": variant.why.strip(), "data": data})
    review = Review(token=secrets.token_urlsafe(24), client_id=client.id, space_id=client.space_id,
                    version_id=version.id, variants=variants, label=_title(payload.label, 60),
                    sender=_title(payload.sender, 120), message=payload.message.strip()[:1000],
                    created_by=account.id, expires_at=utcnow() + timedelta(days=payload.days))
    db.add(review)
    db.commit()
    logger.info("Review made client=%s version=%s directions=%s by=%s", client.id, version.id, len(variants),
                account.name)
    view = _view(db, request, review, account, _role(db, account, client))
    if not email:
        return view
    # The review stands whatever the mail does: its link is in the app to copy.
    _mails.failed(f"review-mail:{account.id}")
    try:
        mailer.send_review(db, email, view["link"], client=client.name,
                           sender=review.sender or account.display_name or account.name, message=review.message,
                           language=account.language or payload.language)
    except mailer.MailError as exc:
        return {**view, "mailed": False, "mail_problem": exc.code}
    logger.info("Review link mailed client=%s by=%s", client.id, account.name)
    return {**view, "mailed": True, "mail_problem": None}


@router.post("/clients/{client_id}/reviews/{review_id}/comments", status_code=201,
             summary="A comment from the agency's side (writers)")
def agency_comment(client_id: ClientId, review_id: int, payload: CommentIn, request: Request, account: Account,
                   db: DbSession) -> dict[str, Any]:
    client, review = _review(db, account, client_id, review_id, WRITE)
    _comment(db, review, payload.variant, account.display_name or account.name, payload.text, agency=True,
             sample=payload.sample)
    # Answering is reading: what the client said before is no longer new.
    review.seen_at = utcnow()
    db.commit()
    return _view(db, request, review, account, _role(db, account, client))


@router.post("/clients/{client_id}/reviews/{review_id}/seen", summary="Somebody of the agency looked at the review")
def seen(client_id: ClientId, review_id: int, request: Request, account: Account, db: DbSession) -> dict[str, Any]:
    client, review = _review(db, account, client_id, review_id, READ)
    review.seen_at = utcnow()
    db.commit()
    return _view(db, request, review, account, _role(db, account, client))


@router.delete("/clients/{client_id}/reviews/{review_id}", status_code=204,
               summary="Withdraw a review (whoever put it forward, or a manager)")
def withdraw(client_id: ClientId, review_id: int, account: Account, db: DbSession) -> None:
    client, review = _review(db, account, client_id, review_id, WRITE)
    if review.created_by != account.id and not rights.at_least(_role(db, account, client), MANAGE):
        raise error("forbidden", "Whoever put the draft forward, or a manager of the client, withdraws it.", 403)
    # Conditional, as the client's choice: a review chosen at the same moment stays chosen.
    db.execute(update(Review).where(Review.id == review.id, Review.status == "open").values(status="closed")
               .execution_options(synchronize_session=False))
    db.commit()


def _comment(db: Any, review: Review, variant: str, author: str, text: str, *, agency: bool,
             sample: str | None = None) -> None:
    direction = next((v for v in review.variants if v["id"] == variant), None)
    if direction is None:
        raise error("not_found", "Not found.", 404)
    if sample and sample not in {s.get("media") for s in direction["data"].get("samples", [])}:
        raise error("not_found", "Not found.", 404)
    if review.status != "open":
        raise error("review_closed", "This review is closed.", 409)
    count = db.scalar(select(func.count()).select_from(ReviewComment).where(ReviewComment.review_id == review.id))
    if (count or 0) >= MAX_COMMENTS:
        raise error("too_many_comments", "This review has reached its limit of comments.", 409)
    clean = text.strip()
    if not clean or any(ord(char) < 32 and char not in "\n\t" for char in clean):
        raise error("invalid_input", "The input is not valid.", 422)
    db.add(ReviewComment(review_id=review.id, variant=variant, sample=sample or None,
                         author=" ".join(author.split())[:80], text=clean, agency=agency))
    db.commit()


# --- The page itself, without signing in ----------------------------------------------------------------------------


def _open(db: Any, token: str) -> tuple[Review, Client]:
    review = db.scalar(select(Review).where(Review.token == token))
    client = db.get(Client, review.client_id) if review is not None else None
    space = db.get(Space, client.space_id) if client is not None else None
    if (
        review is None or client is None or client.deleted_at is not None
        or space is None or space.deleted_at is not None
        or review.status == "closed"
        or not settings_service.get(db, "shares_allowed")
        # Run out is run out, chosen too: withdrawing the links of a blocked person ends a chosen page this way (A15).
        or (review.expires_at is not None and review.expires_at <= utcnow())
    ):
        raise error("not_found", "Not found.", 404)
    return review, client


def _variants(db: Any, review: Review, client: Client) -> list[dict[str, Any]]:
    """The directions as the client sees them: a project's draft on the client version it stands on, without a file
    the client keeps in the house anywhere (``brands.for_public``), so the page and its files say the same."""
    version = db.get(BrandVersion, review.version_id)
    base = db.get(BrandVersion, version.base_id) if version is not None and version.base_id else None
    from ..services import inherit

    kept = brands.kept_in_house(db, client.space_id)
    return [{**v, "data": brandset.for_public(inherit.resolve(base.data, v["data"]) if base is not None else v["data"],
                                             kept)} for v in review.variants]


def _page(db: Any, review: Review, client: Client) -> dict[str, Any]:
    variants = _variants(db, review, client)
    files: set[str] = set()
    for variant in variants:
        files |= brandset.media_of(variant["data"])
    rows = db.scalars(select(Media).where(Media.id.in_(files))) if files else []
    return {
        "client": client.name,
        "sender": review.sender,
        "message": review.message,
        "status": review.status,
        "chosen": review.chosen,
        "chosen_by": review.chosen_by,
        "variants": variants,
        "comments": [{k: c[k] for k in ("variant", "sample", "author", "text", "agency", "at")}
                     for c in _comments_of(db, review)],
        "files": {row.id: {"name": row.name, "kind": row.kind} for row in rows},
        "expires_at": review.expires_at.isoformat() if review.expires_at else None,
    }


def _slow_down(request: Request, review: Review) -> None:
    key = f"review:{review.token[:16]}:{client_ip(request)}"
    wait = _comments.wait_seconds(key, free=COMMENTS_PER_HOUR)
    if wait:
        raise HTTPException(status_code=429, headers={"Retry-After": str(wait)},
                            detail=detail("too_many_attempts", "Too many at once. Try again later.",
                                          retry_after=wait))
    _comments.failed(key)


@router.get("/review/{token}", summary="A review page (no sign-in)")
def review_page(token: Token) -> dict[str, Any]:
    with SessionLocal() as db:
        review, client = _open(db, token)
        return _page(db, review, client)


@router.post("/review/{token}/comments", status_code=201, summary="A comment from the client")
def client_comment(token: Token, payload: CommentIn, request: Request) -> dict[str, Any]:
    with SessionLocal() as db:
        review, client = _open(db, token)
        _slow_down(request, review)
        _comment(db, review, payload.variant, _clean_name(payload.author), payload.text, agency=False,
                 sample=payload.sample)
        return _page(db, review, client)


@router.post("/review/{token}/choose", summary="The client chooses a direction; the draft becomes the next version")
def choose(token: Token, payload: ChooseIn, request: Request) -> dict[str, Any]:
    with SessionLocal() as db:
        review, client = _open(db, token)
        if review.status != "open":
            raise error("review_closed", "This review is closed.", 409)
        who = _clean_name(payload.author)
        _slow_down(request, review)
        variant = next((v for v in review.variants if v["id"] == payload.variant), None)
        version = db.get(BrandVersion, review.version_id)
        if variant is None or version is None:
            raise error("not_found", "Not found.", 404)
        if version.status != DRAFT:
            # Published in the meantime by the agency: the choice has nothing left to write into.
            raise error("review_closed", "This review is closed.", 409)
        try:
            version.data = brandset.clean(variant["data"], db, client.space_id)
        except brandset.SetError as exc:
            raise error("invalid_set", exc.text, 422, where=exc.where) from exc
        version.origin = "review"
        said = f"Chosen by the client: {variant['label']}."
        version.note = ((version.note + " " if version.note else "") + said)[:500]
        version.status = "published"
        version.label = review.label or version.label
        version.valid_from = brands.day(None)
        version.published_at = utcnow()
        version.published_by = who or client.name
        version.updated_at = utcnow()
        client.updated_at = utcnow()
        # Only while it is still open, decided by the database: a withdrawal at the same moment is never overwritten
        # with "chosen", and then nothing of the choice is kept (A15).
        taken = db.execute(update(Review).where(Review.id == review.id, Review.status == "open")
                           .values(status="chosen", chosen=variant["id"], chosen_by=who, chosen_at=utcnow())
                           .execution_options(synchronize_session=False))
        if taken.rowcount != 1:
            db.rollback()
            raise error("review_closed", "This review is closed.", 409)
        db.commit()
        db.refresh(review)
        logger.info("Review chosen client=%s version=%s direction=%s", client.id, version.id, variant["id"])
        return _page(db, review, client)


@router.get("/review/{token}/media/{media_id}", response_model=None, summary="A file of a review page")
def review_media(token: Token, media_id: MediaId, request: Request, download: bool = False,
                 preview: bool = False) -> Response:
    with SessionLocal() as db:
        review, client = _open(db, token)
        named: set[str] = set()
        for variant in _variants(db, review, client):
            named |= brandset.media_of(variant["data"])
        row = db.get(Media, media_id)
        if row is None or media_id not in named or row.space_id != client.space_id:
            raise error("not_found", "Not found.", 404)
        db.expunge(row)
    return deliver(row, request, download, preview)
