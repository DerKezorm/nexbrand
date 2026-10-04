"""Public pages of a design set and reviews with the client: what leaves, what stays in, and the client's choice."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import Account
from app.services import settings_service

from .conftest import new_client
from .test_brands import SET, WOFF2, make_client, upload


def _open_pages() -> None:
    with SessionLocal() as db:
        settings_service.save(db, {"shares_allowed": True})
        db.commit()


def _published(client: TestClient, space: int, data: dict[str, Any] | None = None) -> tuple[str, str]:
    made = make_client(client, space, data)
    cid, vid = made["id"], made["versions"][0]["id"]
    assert client.post(f"/api/clients/{cid}/versions/{vid}/publish", json={"label": "2026"}).status_code == 200
    return cid, vid


def test_pages_stay_shut_until_the_operator_opens_them(client: TestClient, operator: Account, space: int) -> None:
    cid, _ = _published(client, space)
    answer = client.post(f"/api/clients/{cid}/shares", json={"label": "Printer"})
    assert answer.status_code == 403 and answer.json()["detail"]["code"] == "shares_off"


def test_a_page_shows_the_current_version_and_never_an_internal_font(client: TestClient, operator: Account,
                                                                      space: int) -> None:
    _open_pages()
    internal = upload(client, space, "house.woff2", WOFF2)
    free = upload(client, space, "free.woff2", WOFF2 + b"x")
    data = {**SET, "fonts": [{"family": "House", "license": "internal", "files": [internal]},
                             {"family": "Open", "license": "free", "files": [free]}]}
    cid, _ = _published(client, space, data)
    link = client.post(f"/api/clients/{cid}/shares", json={"label": "Printer"}).json()["link"]
    token = link.rsplit("/", 1)[1]
    with new_client() as visitor:
        page = visitor.get(f"/api/public/{token}").json()
        assert page["client"] == "Bäckerei Morgenrot" and page["version"]["label"] == "2026"
        fonts = {f["family"]: f["files"] for f in page["design"]["fonts"]}
        assert fonts == {"House": [], "Open": [free]}
        assert "checks" not in page
        assert visitor.get(f"/api/public/{token}/media/{free}").status_code == 200
        assert visitor.get(f"/api/public/{token}/media/{internal}").status_code == 404


def test_a_fixed_page_keeps_its_version_and_a_bin_closes_it(client: TestClient, operator: Account,
                                                            space: int) -> None:
    _open_pages()
    cid, first = _published(client, space)
    token = client.post(f"/api/clients/{cid}/shares", json={"version_id": first}).json()["link"].rsplit("/", 1)[1]
    newer = client.post(f"/api/clients/{cid}/versions", json={"label": "2027", "source": first}).json()
    client.post(f"/api/clients/{cid}/versions/{newer['id']}/publish", json={})
    with new_client() as visitor:
        assert visitor.get(f"/api/public/{token}").json()["version"]["label"] == "2026"
        assert client.delete(f"/api/clients/{cid}").status_code == 204
        assert visitor.get(f"/api/public/{token}").status_code == 404


def test_a_draft_never_goes_on_a_page(client: TestClient, operator: Account, space: int) -> None:
    _open_pages()
    made = make_client(client, space)
    answer = client.post(f"/api/clients/{made['id']}/shares", json={"version_id": made["versions"][0]["id"]})
    assert answer.status_code == 409
    assert client.post(f"/api/clients/{made['id']}/shares", json={}).status_code == 409


def test_a_password_guards_the_page(client: TestClient, operator: Account, space: int) -> None:
    _open_pages()
    cid, _ = _published(client, space)
    token = client.post(f"/api/clients/{cid}/shares", json={"password": "hidden words"}).json()["link"].rsplit(
        "/", 1)[1]
    with new_client() as visitor:
        assert visitor.get(f"/api/public/{token}").json() == {"password": True}
        assert visitor.post(f"/api/public/{token}", json={"password": "wrong"}).status_code == 401
        assert visitor.post(f"/api/public/{token}", json={"password": "hidden words"}).status_code == 200
        assert visitor.get(f"/api/public/{token}").json()["client"] == "Bäckerei Morgenrot"


# --- Reviews --------------------------------------------------------------------------------------------------------


def _review(client: TestClient, space: int) -> tuple[str, str, str]:
    _open_pages()
    made = make_client(client, space, project="Website")
    cid, vid = made["id"], made["versions"][0]["id"]
    bolder = {**SET, "colors": [{**SET["colors"][0], "hex": "#C23B2E"}, *SET["colors"][1:]]}
    answer = client.post(f"/api/clients/{cid}/reviews", json={
        "version_id": vid, "label": "1.0", "sender": "Studio Beispiel", "message": "Two directions.",
        "variants": [{"id": "a", "label": "Calm", "data": SET}, {"id": "b", "label": "Bold", "why": "More red.",
                                                                  "data": bolder}]})
    assert answer.status_code == 201, answer.text
    return cid, vid, answer.json()["link"].rsplit("/", 1)[1]


def test_the_client_comments_and_chooses_and_the_draft_becomes_the_version(client: TestClient, operator: Account,
                                                                           space: int) -> None:
    cid, vid, token = _review(client, space)
    with new_client() as visitor:
        page = visitor.get(f"/api/review/{token}").json()
        assert [v["label"] for v in page["variants"]] == ["Calm", "Bold"] and page["sender"] == "Studio Beispiel"
        said = visitor.post(f"/api/review/{token}/comments", json={"variant": "b", "author": "Frau Fink",
                                                                    "text": "Love the red."})
        assert said.status_code == 201 and said.json()["comments"][0]["author"] == "Frau Fink"
        assert visitor.post(f"/api/review/{token}/comments", json={"variant": "zz", "text": "x"}).status_code == 404
        chosen = visitor.post(f"/api/review/{token}/choose", json={"variant": "b", "author": "Frau Fink"})
        assert chosen.status_code == 200 and chosen.json()["status"] == "chosen"
        assert visitor.post(f"/api/review/{token}/choose", json={"variant": "a"}).status_code == 409
    whole = client.get(f"/api/clients/{cid}").json()
    version = next(v for v in whole["versions"] if v["id"] == vid)
    assert version["status"] == "published" and version["label"] == "1.0" and version["origin"] == "review"
    assert version["published_by"] == "Frau Fink" and version["data"]["colors"][0]["hex"] == "#C23B2E"
    assert whole["current"] == "1.0"


def test_only_a_draft_goes_before_the_client_once(client: TestClient, operator: Account, space: int) -> None:
    cid, vid, _ = _review(client, space)
    again = client.post(f"/api/clients/{cid}/reviews", json={
        "version_id": vid, "label": "1.0", "variants": [{"id": "a", "label": "A", "data": SET}]})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "review_open"


def test_a_withdrawn_review_is_gone_for_the_client(client: TestClient, operator: Account, space: int) -> None:
    cid, _, token = _review(client, space)
    review_id = client.get(f"/api/clients/{cid}/reviews").json()[0]["id"]
    assert client.delete(f"/api/clients/{cid}/reviews/{review_id}").status_code == 204
    with new_client() as visitor:
        assert visitor.get(f"/api/review/{token}").status_code == 404


def test_comments_are_braked_per_sender(client: TestClient, operator: Account, space: int) -> None:
    _, _, token = _review(client, space)
    with new_client() as visitor:
        codes = [visitor.post(f"/api/review/{token}/comments", json={"variant": "a", "text": f"n{i}"}).status_code
                 for i in range(32)]
    assert codes[:30] == [201] * 30 and 429 in codes[30:]


def test_the_agency_answers_on_the_review(client: TestClient, operator: Account, space: int) -> None:
    cid, _, token = _review(client, space)
    review_id = client.get(f"/api/clients/{cid}/reviews").json()[0]["id"]
    said = client.post(f"/api/clients/{cid}/reviews/{review_id}/comments", json={"variant": "a", "text": "Yes."})
    assert said.status_code == 201 and said.json()["comments"][0]["agency"] is True
    with new_client() as visitor:
        assert visitor.get(f"/api/review/{token}").json()["comments"][0]["text"] == "Yes."
