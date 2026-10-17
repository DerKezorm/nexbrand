"""What leaves nexbrand through the client's links, and what comes in as a file.

* The links of reviews and public pages are keys: a reader sees that there are some, never the address.
* A font kept in the house never leaves as a file, whatever part of the set names it.
* A file is refused when it could run something (SVG) or blow up in memory (pixels).
"""

from __future__ import annotations

import struct
import zlib
from email.message import EmailMessage
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import Account
from app.services import accounts, mailer, media_store, outbound, settings_service, tokens

from . import test_suite
from .conftest import join, make_account, new_client
from .test_brands import SET, SVG, WOFF2, make_client, upload

# The fixtures of the suite tests, under the names pytest looks for.
fake = test_suite.fake
world = test_suite.world


def _open_pages() -> None:
    with SessionLocal() as db:
        settings_service.save(db, {"shares_allowed": True})
        db.commit()


def _draft(client: TestClient, space: int) -> tuple[str, str]:
    made = make_client(client, space)
    return made["id"], made["versions"][0]["id"]


def _review(client: TestClient, cid: str, vid: str, **extra: Any) -> Any:
    return client.post(f"/api/clients/{cid}/reviews", json={
        "version_id": vid, "label": "1.0", "variants": [{"id": "a", "label": "Calm", "data": SET}], **extra})


def _token(link: str) -> str:
    return link.rsplit("/", 1)[1]


# --- the links are for those who write ----------------------------------------------------------------------


def test_a2_a_reader_never_gets_the_review_link_and_cannot_choose_for_the_client(
    client: TestClient, operator: Account, space: int
) -> None:
    _open_pages()
    cid, vid = _draft(client, space)
    mila, wim = make_account("mila"), make_account("wim")
    join(client, space, "mila", "read")
    join(client, space, "wim", "write")
    made = _review(client, cid, vid)
    assert made.status_code == 201 and made.json()["link"]
    with new_client(mila) as reader:
        listed = reader.get(f"/api/clients/{cid}/reviews").json()
        assert len(listed) == 1 and listed[0]["status"] == "open"
        assert listed[0].get("link") is None, "a reader must not get the key to the client's page"
        assert reader.post(f"/api/clients/{cid}/reviews/{listed[0]['id']}/seen").json().get("link") is None
        # Neither may a reader put a draft before the client.
        second = client.post(f"/api/clients/{cid}/versions", json={"label": "B", "data": SET}).json()["id"]
        assert _review(reader, cid, second).status_code == 403
    with new_client(wim) as writer:
        assert writer.get(f"/api/clients/{cid}/reviews").json()[0]["link"] == made.json()["link"]
        # From write up a review is made, and withdrawn by whoever made it (or a manager).
        own = _review(writer, cid, second)
        assert own.status_code == 201, own.text
        assert writer.delete(f"/api/clients/{cid}/reviews/{made.json()['id']}").status_code == 403
        assert writer.delete(f"/api/clients/{cid}/reviews/{own.json()['id']}").status_code == 204


def test_a3_a_reader_sees_that_there_are_public_pages_but_not_their_links(
    client: TestClient, operator: Account, space: int
) -> None:
    _open_pages()
    cid, vid = _draft(client, space)
    assert client.post(f"/api/clients/{cid}/versions/{vid}/publish", json={"label": "2026"}).status_code == 200
    page = client.post(f"/api/clients/{cid}/shares", json={"label": "Printer"})
    assert page.status_code == 201
    mila, wim = make_account("mila"), make_account("wim")
    join(client, space, "mila", "read")
    join(client, space, "wim", "write")
    with new_client(mila) as reader:
        listed = reader.get(f"/api/clients/{cid}/shares").json()
        assert [s["label"] for s in listed] == ["Printer"] and listed[0].get("link") is None
        assert reader.post(f"/api/clients/{cid}/shares", json={"label": "Mine"}).status_code == 403
    with new_client(wim) as writer:
        assert writer.get(f"/api/clients/{cid}/shares").json()[0]["link"] == page.json()["link"]
        own = writer.post(f"/api/clients/{cid}/shares", json={"label": "Photographer"})
        assert own.status_code == 201, own.text
        assert writer.delete(f"/api/shares/{page.json()['id']}").status_code == 403
        assert writer.patch(f"/api/shares/{own.json()['id']}", json={"label": "Studio"}).status_code == 200
        assert writer.delete(f"/api/shares/{own.json()['id']}").status_code == 204


# --- a font kept in the house stays there -----------------------------------------------------------------------


def test_a4_an_internal_font_file_never_leaves_as_an_example_or_a_logo_download(
    client: TestClient, operator: Account, space: int
) -> None:
    _open_pages()
    house = upload(client, space, "house.woff2", WOFF2)
    logo = upload(client, space, "logo.svg", SVG)
    data = {**SET,
            "fonts": [{"family": "House", "license": "internal", "license_note": "Bought for the agency only",
                       "source": "Invoice 4711", "files": [house]}],
            "logos": [{"id": "main", "name": "Logo", "media": logo, "files": [house, logo]}],
            "samples": [{"name": "Font sheet", "media": house}, {"name": "Logo sheet", "media": logo}]}
    cid, vid = make_client(client, space, data)["id"], None
    vid = client.get(f"/api/clients/{cid}").json()["versions"][0]["id"]
    review = _review(client, cid, vid, variants=[{"id": "a", "label": "Calm", "data": data}]).json()
    assert client.post(f"/api/clients/{cid}/versions", json={"label": "2", "data": data}).status_code == 201
    published = client.get(f"/api/clients/{cid}").json()["versions"]
    other = next(v["id"] for v in published if v["id"] != vid)
    assert client.post(f"/api/clients/{cid}/versions/{other}/publish", json={"label": "2026"}).status_code == 200
    share = client.post(f"/api/clients/{cid}/shares", json={"label": "Printer"}).json()
    with new_client() as visitor:
        for kind, token in (("public", _token(share["link"])), ("review", _token(review["link"]))):
            page = visitor.get(f"/api/{kind}/{token}").json()
            design = page["design"] if kind == "public" else page["variants"][0]["data"]
            assert [s["name"] for s in design["samples"]] == ["Logo sheet"], kind
            assert design["logos"][0]["files"] == [logo], kind
            assert design["fonts"][0]["files"] == [] and design["fonts"][0]["family"] == "House"
            assert design["fonts"][0]["license_note"] == "" and design["fonts"][0]["source"] == "", kind
            assert house not in page["files"], kind
            assert visitor.get(f"/api/{kind}/{token}/media/{house}").status_code == 404, kind
            assert visitor.get(f"/api/{kind}/{token}/media/{logo}").status_code == 200, kind


# --- a name cannot end the comment above the code ----------------------------------------------------------------


@pytest.mark.parametrize("fmt", ["css", "tailwind", "scss"])
def test_a6_a_name_cannot_end_the_comment_of_the_code(fmt: str) -> None:
    text = tokens.render(SET, fmt, title="Shop */ body { display: none } /* 1.0\nnext")
    head = text.split("\n", 1)[0]
    assert head.startswith("/* ") and head.endswith(" */") and head.count("*/") == 1, head
    assert "body { display: none }" not in text.replace(head, "")


def test_a6_the_export_route_keeps_the_comment_closed(client: TestClient, operator: Account, space: int) -> None:
    cid, _ = _draft(client, space)
    assert client.patch(f"/api/clients/{cid}", json={"name": "Shop */ a { b: c } /*"}).status_code == 200
    head = client.get(f"/api/clients/{cid}/export?format=css").text.split("\n", 1)[0]
    assert head.count("*/") == 1 and head.endswith(" */"), head


# --- pixels are counted before a picture is decoded --------------------------------------------------------------


def _png(width: int, height: int) -> bytes:
    """A black-and-white PNG of any size, a few kilobytes on disk (as the bomb of the check was)."""
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    row = b"\x00" + bytes((width + 7) // 8)
    packer = zlib.compressobj(9)
    raw = b"".join(packer.compress(row) for _ in range(height)) + packer.flush()
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


def test_a7_a_picture_with_more_pixels_than_a_profile_picture_may_have_is_refused(
    client: TestClient, operator: Account, space: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    def never(*_: Any) -> bool:
        raise AssertionError("decoded before the pixels were counted")

    monkeypatch.setattr(media_store, "_make_preview", never)
    bomb = _png(8000, 8000)  # 64 million pixels, a few kilobytes
    assert len(bomb) < 200_000
    answer = client.post(f"/api/media?space={space}&name=example.png", content=bomb)
    assert answer.status_code == 422, answer.text
    assert answer.json()["detail"]["code"] == "too_many_pixels"
    assert answer.json()["detail"]["max_million"] == media_store.MAX_PIXELS // 1_000_000
    # Below the line a picture comes in as before.
    small = client.post(f"/api/media?space={space}&name=small.png", content=_png(40, 30))
    assert small.status_code == 201 and small.json()["width"] == 40


# --- a key goes to its own host only ---------------------------------------------------------------------------


def test_a11_a_redirect_to_another_host_drops_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    seen: list[tuple[str, str | None]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append((request.headers["host"], request.headers.get("authorization")))
        if request.headers["host"] == "api.github.com" and request.url.path == "/repos/a/b":
            return httpx.Response(302, headers={"location": "/repos/a/c"})
        if request.headers["host"] == "api.github.com":
            return httpx.Response(302, headers={"location": "https://elsewhere.example.org/x"})
        return httpx.Response(200, content=b"ok")

    monkeypatch.setattr(outbound, "transport", httpx.MockTransport(answer))
    monkeypatch.setattr(outbound, "resolver", lambda host, port: ["93.184.216.34"])
    outbound.get("https://api.github.com/repos/a/b", limit=1000, headers={"Authorization": "Bearer example"})
    assert seen == [("api.github.com", "Bearer example"), ("api.github.com", "Bearer example"),
                    ("elsewhere.example.org", None)]


# --- an SVG that could run something is refused -----------------------------------------------------------------


HOSTILE_SVGS = {
    "script": b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
    "event": b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><rect width="1" height="1"/></svg>',
    "event_inside": b'<svg xmlns="http://www.w3.org/2000/svg"><rect ONclick="x()" width="1" height="1"/></svg>',
    "javascript": (b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
                   b'<a xlink:href=" java&#x09;script:alert(1)"><rect width="1" height="1"/></a></svg>'),
    "foreign": (b'<svg xmlns="http://www.w3.org/2000/svg"><foreignObject><div xmlns="http://www.w3.org/1999/xhtml">'
                b'x</div></foreignObject></svg>'),
    "entity": (b'<?xml version="1.0"?>\n<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]>\n'
               b'<svg xmlns="http://www.w3.org/2000/svg"><text>&x;</text></svg>'),
    "doctype": (b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">'
                b'<svg xmlns="http://www.w3.org/2000/svg"/>'),
    "broken": b'<svg xmlns="http://www.w3.org/2000/svg"><rect',
    "hidden_as_file": b'junk before <svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
}


@pytest.mark.parametrize("case", sorted(HOSTILE_SVGS))
def test_a12_an_svg_that_could_run_something_is_refused(client: TestClient, operator: Account, space: int,
                                                         case: str) -> None:
    answer = client.post(f"/api/media?space={space}&name=logo.svg", content=HOSTILE_SVGS[case])
    assert answer.status_code == 422, answer.text
    assert answer.json()["detail"]["code"] == "svg_unsafe"


def test_a12_a_plain_svg_with_styles_and_links_inside_comes_in(client: TestClient, operator: Account,
                                                               space: int) -> None:
    plain = (b'<?xml version="1.0" encoding="UTF-8"?>\n<!-- drawn by hand -->\n'
             b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 9 9">'
             b'<defs><linearGradient id="g"><stop offset="0" stop-color="#2f7bff"/></linearGradient></defs>'
             b'<style>.a { fill: url(#g); }</style><use xlink:href="#r"/><rect id="r" class="a" width="9" height="9"/>'
             b'<text font-family="Fraunces">online</text></svg>')
    answer = client.post(f"/api/media?space={space}&name=logo.svg", content=plain)
    assert answer.status_code == 201 and answer.json()["kind"] == "svg", answer.text


# --- no control characters in a mail address --------------------------------------------------------------------


@pytest.mark.parametrize("address", ["anna\x00@example.com", "anna@example.com\n", "an\x1bna@example.com",
                                     "anna@exam\x7fple.com", "anna@example.com\x00",
                                     # C1 (U+0080 to U+009F): the CSI in an address went through before.
                                     "anna@exa\x9bmple.com", "an\x80na@example.com"])
def test_a13_a_mail_address_with_a_control_character_is_none(address: str) -> None:
    assert not accounts.EMAIL_PATTERN.match(address)


def test_a13_an_invitation_mail_to_such_an_address_is_refused(client: TestClient, operator: Account,
                                                              space: int) -> None:
    answer = client.post(f"/api/spaces/{space}/invites", json={"role": "read", "email": "anna\x00@example.com"})
    assert answer.status_code == 422 and answer.json()["detail"]["code"] == "invalid_email"
    assert accounts.EMAIL_PATTERN.match("anna@example.com")


# --- the client's name on a review ------------------------------------------------------------------------


def test_a14_a_name_on_the_review_page_holds_no_control_or_format_characters(client: TestClient,
                                                                              operator: Account, space: int) -> None:
    _open_pages()
    cid, vid = _draft(client, space)
    token = _token(_review(client, cid, vid).json()["link"])
    with new_client() as visitor:
        for author in ("\u202eKundin", "Kun\x07din", "Kun\u200bdin"):
            said = visitor.post(f"/api/review/{token}/comments", json={"variant": "a", "text": "Nice", "author": author})
            assert said.status_code == 422 and said.json()["detail"]["code"] == "invalid_name", author
        chose = visitor.post(f"/api/review/{token}/choose", json={"variant": "a", "author": "Kun\x07din"})
        assert chose.status_code == 422
        # Without a name the comment says so itself, not with a dash.
        said = visitor.post(f"/api/review/{token}/comments", json={"variant": "a", "text": "Nice"})
        assert said.status_code == 201 and said.json()["comments"][0]["author"] == ""


# --- a draft before the client is deleted on purpose only --------------------------------------------------------


def test_f5_a_draft_before_the_client_is_deleted_only_when_the_review_goes_with_it(
    client: TestClient, operator: Account, space: int
) -> None:
    _open_pages()
    cid, _ = _draft(client, space)
    second = client.post(f"/api/clients/{cid}/versions", json={"label": "B", "data": SET}).json()["id"]
    token = _token(_review(client, cid, second).json()["link"])
    refused = client.delete(f"/api/clients/{cid}/versions/{second}")
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "review_open"
    with new_client() as visitor:
        assert visitor.get(f"/api/review/{token}").status_code == 200
    assert client.delete(f"/api/clients/{cid}/versions/{second}?with_review=true").status_code == 204
    with new_client() as visitor:
        assert visitor.get(f"/api/review/{token}").status_code == 404
    # A draft without a review goes as before.
    third = client.post(f"/api/clients/{cid}/versions", json={"label": "C", "data": SET}).json()["id"]
    assert client.delete(f"/api/clients/{cid}/versions/{third}").status_code == 204


# --- the public page as code, and the review link by mail ------------------------------------------------------


def test_f27_the_public_page_gives_the_design_as_code(client: TestClient, operator: Account, space: int) -> None:
    _open_pages()
    cid, vid = _draft(client, space)
    assert client.post(f"/api/clients/{cid}/versions/{vid}/publish", json={"label": "2026"}).status_code == 200
    open_page = client.post(f"/api/clients/{cid}/shares", json={"label": "Developer"}).json()
    guarded = client.post(f"/api/clients/{cid}/shares", json={"label": "Printer", "password": "example-pass"}).json()
    with new_client() as visitor:
        token = _token(open_page["link"])
        css = visitor.get(f"/api/public/{token}/code?format=css")
        assert css.status_code == 200 and "--color-ofenrot: #B8322A;" in css.text
        assert css.text.startswith("/* Bäckerei Morgenrot 2026 */")
        assert "@theme" in visitor.get(f"/api/public/{token}/code?format=tailwind").text
        assert "$color-ofenrot" in visitor.get(f"/api/public/{token}/code?format=scss").text
        assert visitor.get(f"/api/public/{token}/code?format=json").json()["color"]["ofenrot"]["$value"] == "#B8322A"
        saved = visitor.get(f"/api/public/{token}/code?format=css&download=true")
        assert saved.headers["content-disposition"].startswith("attachment")
        assert visitor.get(f"/api/public/{token}/code?format=html").status_code == 422
        # Behind a password the code is too.
        locked = _token(guarded["link"])
        assert visitor.get(f"/api/public/{locked}/code?format=css").status_code == 404
        assert visitor.post(f"/api/public/{locked}", json={"password": "example-pass"}).status_code == 200
        assert visitor.get(f"/api/public/{locked}/code?format=css").status_code == 200


def _mail_ready(client: TestClient) -> None:
    assert client.put("/api/settings", json={"smtp_host": "mail.example.com", "smtp_from": "brand@example.com",
                                             "public_url": "https://brand.example.com"}).status_code == 200


def test_f27_the_review_link_goes_by_mail_in_the_language_of_who_puts_it_forward(
    client: TestClient, operator: Account, space: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[EmailMessage] = []
    monkeypatch.setattr(mailer, "_send", lambda db, message: sent.append(message))
    _open_pages()
    cid, vid = _draft(client, space)
    second = client.post(f"/api/clients/{cid}/versions", json={"label": "B", "data": SET}).json()["id"]
    # Without a mail server there is no mail to send.
    off = _review(client, cid, vid, email="kunde@example.com")
    assert off.status_code == 409 and off.json()["detail"]["code"] == "mail_off" and not sent
    _mail_ready(client)
    bad = _review(client, cid, vid, email="kunde\x00@example.com")
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "invalid_email"
    made = _review(client, cid, vid, email="kunde@example.com", sender="Studio Beispiel", language="de")
    assert made.status_code == 201 and made.json()["mailed"] is True, made.text
    assert sent[0]["To"] == "kunde@example.com" and "Studio Beispiel" in sent[0]["Subject"]
    body = sent[0].get_content()
    assert made.json()["link"] in body and "Bäckerei Morgenrot" in body and "Entwürfe" in body
    # The account's own language wins over the page's, English when there is none.
    with SessionLocal() as db:
        db.get(Account, operator.id).language = "en"  # type: ignore[union-attr]
        db.commit()
    again = _review(client, cid, second, email="kunde@example.com", language="de")
    assert again.status_code == 201 and "drafts" in sent[1].get_content() and "Entwürfe" not in sent[1].get_content()
    # Without an address nothing goes out.
    assert len(sent) == 2


def test_f27_a_mail_that_fails_keeps_the_review_and_says_so(
    client: TestClient, operator: Account, space: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(db: Any, message: EmailMessage) -> None:
        raise mailer.MailError("mail_failed", "The mail server did not take the mail.")

    monkeypatch.setattr(mailer, "_send", fail)
    _open_pages()
    _mail_ready(client)
    cid, vid = _draft(client, space)
    made = _review(client, cid, vid, email="kunde@example.com")
    assert made.status_code == 201 and made.json()["mailed"] is False
    assert made.json()["mail_problem"] == "mail_failed" and made.json()["link"]


# --- From the first block: an operator from the directory service is refused before any password ----------------------------------


def test_connected_an_operator_who_is_not_the_emergency_account_is_refused_before_the_password(
    client: TestClient, operator: Account, world: dict, fake: Any
) -> None:
    from app.models import SIGN_IN_PASSWORD
    from app.services import backups

    from .conftest import sign_in
    from .test_suite import connect

    name = backups.create().name
    connect(client, world, operator)
    fake.people["2"]["operator"] = True
    client.post("/api/suite/sync")
    with SessionLocal() as db:
        # Even one with a password here (say, from before connecting) is not asked for it first.
        db.get(Account, world["anna"].id).sign_in = SIGN_IN_PASSWORD  # type: ignore[union-attr]
        db.commit()
    with new_client() as anna:
        sign_in(anna, world["anna"])
        for answer in (anna.post(f"/api/backups/{name}/download", json={"password": "wrong"}),
                       anna.request("DELETE", f"/api/backups/{name}", json={"password": "wrong"})):
            assert answer.status_code == 403 and answer.json()["detail"]["code"] == "backups_emergency_only", answer.text


# --- what one version keeps in the house, every other way keeps in too ----------------


def _font(media: str, license: str = "internal") -> dict[str, Any]:
    return {"family": "House", "license": license, "files": [media]}


def _publish(client: TestClient, cid: str, data: dict[str, Any], label: str) -> str:
    made = client.post(f"/api/clients/{cid}/versions", json={"label": label, "data": data})
    assert made.status_code == 201, made.text
    vid = made.json()["id"]
    assert client.post(f"/api/clients/{cid}/versions/{vid}/publish", json={"label": label}).status_code == 200
    return str(vid)


def test_a4_a_second_direction_does_not_carry_the_first_ones_internal_font_out(
    client: TestClient, operator: Account, space: int
) -> None:
    """(a) Direction A keeps the font in the house, direction B shows its file as an example."""
    _open_pages()
    house = upload(client, space, "house.woff2", WOFF2)
    cid, vid = _draft(client, space)
    a = {**SET, "fonts": [_font(house)]}
    b = {**SET, "samples": [{"name": "Font sheet", "media": house}]}
    review = _review(client, cid, vid, variants=[{"id": "a", "label": "A", "data": a},
                                                 {"id": "b", "label": "B", "data": b}])
    assert review.status_code == 201, review.text
    token = _token(review.json()["link"])
    with new_client() as visitor:
        page = visitor.get(f"/api/review/{token}").json()
        assert page["variants"][1]["data"]["samples"] == [] and house not in page["files"]
        assert visitor.get(f"/api/review/{token}/media/{house}").status_code == 404


def test_a4_a_version_without_the_font_does_not_carry_its_file_out(
    client: TestClient, operator: Account, space: int
) -> None:
    """(b) Another version keeps the font in the house; this one names the file only as an example (and a project
    keeping it in counts as well)."""
    _open_pages()
    house = upload(client, space, "house.woff2", WOFF2)
    sheet = upload(client, space, "other.woff2", WOFF2 + b"o")
    cid, _ = _draft(client, space)
    assert client.post(f"/api/clients/{cid}/versions", json={"label": "Kept", "data": {
        **SET, "fonts": [_font(house)]}}).status_code == 201
    shown = {**SET, "samples": [{"name": "Font sheet", "media": house}, {"name": "Other", "media": sheet}]}
    published = _publish(client, cid, shown, "2026")
    project = client.post(f"/api/clients/{cid}/projects", json={
        "name": "Web", "version_id": published, "data": {"fonts": [_font(sheet)], "inherit": {"fonts": "own"}}})
    assert project.status_code == 201, project.text
    share = client.post(f"/api/clients/{cid}/shares", json={"label": "Printer"}).json()
    token = _token(share["link"])
    with new_client() as visitor:
        page = visitor.get(f"/api/public/{token}").json()
        assert page["design"]["samples"] == [], "the project keeps the other file in the house too"
        for media in (house, sheet):
            assert visitor.get(f"/api/public/{token}/media/{media}").status_code == 404


def test_a4_a_newer_version_keeping_the_font_in_closes_an_older_fixed_page(
    client: TestClient, operator: Account, space: int
) -> None:
    """(c) The older version called the font free; a newer one keeps the same file in the house."""
    _open_pages()
    house = upload(client, space, "house.woff2", WOFF2)
    cid, _ = _draft(client, space)
    older = _publish(client, cid, {**SET, "fonts": [_font(house, "free")]}, "2025")
    share = client.post(f"/api/clients/{cid}/shares", json={"label": "Printer", "version_id": older}).json()
    token = _token(share["link"])
    with new_client() as visitor:
        assert visitor.get(f"/api/public/{token}/media/{house}").status_code == 200
    assert client.post(f"/api/clients/{cid}/versions", json={"label": "Next", "data": {
        **SET, "fonts": [_font(house)]}}).status_code == 201
    with new_client() as visitor:
        assert visitor.get(f"/api/public/{token}").json()["design"]["fonts"][0]["files"] == []
        assert visitor.get(f"/api/public/{token}/media/{house}").status_code == 404


# --- an SVG in another encoding than UTF-8 --------------------------------------------------------------------


WIDE = '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><script>alert(2)</script></svg>'


@pytest.mark.parametrize(("name", "body"), [
    ("logo.svg", WIDE.encode("utf-16")),
    ("logo.svg", WIDE.encode("utf-16-be")),
    ("logo.svg", WIDE.encode("utf-16-le")),
    ("logo.svg", WIDE.encode("utf-32")),
    ("download.bin", WIDE.encode("utf-16")),
    ("logo.svg", ('<?xml version="1.0" encoding="UTF-16"?>' + WIDE[:-6] + "</svg>").encode("utf-8")),
], ids=["utf16-bom", "utf16-be", "utf16-le", "utf32-bom", "other-name", "declared"])
def test_a12_an_svg_not_in_utf8_is_refused(client: TestClient, operator: Account, space: int, name: str,
                                           body: bytes) -> None:
    answer = client.post(f"/api/media?space={space}&name={name}", content=body)
    assert answer.status_code == 422, answer.text
    assert answer.json()["detail"]["code"] == "svg_encoding"


def test_a12_a_binary_file_with_zero_bytes_still_comes_in(client: TestClient, operator: Account, space: int) -> None:
    answer = client.post(f"/api/media?space={space}&name=data.bin", content=bytes(range(256)) * 16)
    assert answer.status_code == 201 and answer.json()["kind"] == "file"


def test_a12_a_large_archive_is_looked_at_by_its_first_bytes_only(
    client: TestClient, operator: Account, space: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An archive full of zero bytes (as ZIP, EPS and font packages are) is not read further than its beginning to
    tell whether it is a wide SVG: before, every such upload read and decoded up to 32 MB four times."""
    seen: list[int] = []
    real = media_store.wide_markup

    def counted(head: bytes) -> bool:
        seen.append(len(head))
        return real(head)

    monkeypatch.setattr(media_store, "wide_markup", counted)
    archive = b"PK" + bytes([3, 4]) + bytes(6 * 1024 * 1024)
    answer = client.post(f"/api/media?space={space}&name=fonts.zip", content=archive)
    assert answer.status_code == 201 and answer.json()["kind"] == "file", answer.text
    assert seen and max(seen) <= media_store.WIDE_HEAD


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-le", "utf-16-be", "utf-32", "utf-32-le", "utf-32-be"])
def test_a12_wide_markup_is_told_by_its_beginning(encoding: str) -> None:
    svg = "  \n<svg xmlns='http://www.w3.org/2000/svg'/>"
    assert media_store.wide_markup(svg.encode(encoding))
    assert not media_store.wide_markup(b"PK" + bytes(4000))
    assert not media_store.wide_markup(svg.encode("utf-8"))


HIDDEN = "<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"


@pytest.mark.parametrize("body", [
    (" " * 3000 + HIDDEN).encode("utf-16"),
    (" " * 3000 + HIDDEN).encode("utf-16-le"),
    (" " * 3000 + HIDDEN).encode("utf-16-be"),
    ("\n" * 3000 + HIDDEN).encode("utf-32"),
    (" " * 3000 + HIDDEN).encode("utf-32-be"),
    b"   " + (" " * 3000 + HIDDEN).encode("utf-16-le"),
    b"  \n " + HIDDEN.encode("utf-16-le"),
    b" " + (" " * 10 + HIDDEN).encode("utf-16-be"),
], ids=["utf16-bom", "utf16-le", "utf16-be", "utf32-bom", "utf32-be", "ascii-then-utf16-blanks", "ascii-then-utf16",
        "ascii-odd-then-utf16-be"])
def test_a12_blanks_beyond_the_head_hide_no_wide_svg(client: TestClient, operator: Account, space: int,
                                                     body: bytes) -> None:
    """Blanks in a wide encoding up to the end of what is read are refused: markup may follow beyond it."""
    for name in ("download.bin", "logo.svg"):
        answer = client.post(f"/api/media?space={space}&name={name}", content=body)
        assert answer.status_code == 422 and answer.json()["detail"]["code"] == "svg_encoding", (name, answer.text)


def test_a12_binaries_and_plain_text_are_not_taken_for_wide_blanks(client: TestClient, operator: Account,
                                                                   space: int) -> None:
    for body in (b"\x00" + bytes([255]) * 5000, b"    " + b"plain text " * 500, bytes(5000)):
        answer = client.post(f"/api/media?space={space}&name=data.bin", content=body)
        assert answer.status_code == 201 and answer.json()["kind"] == "file", answer.text


# --- once kept in the house, a file stays so ------------------------------------------------------------------


def test_a4_a_file_once_kept_in_the_house_stays_so_after_its_draft_is_gone(
    client: TestClient, operator: Account, space: int
) -> None:
    _open_pages()
    house = upload(client, space, "house.woff2", WOFF2)
    cid, _ = _draft(client, space)
    kept = client.post(f"/api/clients/{cid}/versions", json={"label": "Kept", "data": {**SET, "fonts": [_font(house)]}})
    assert kept.status_code == 201
    assert client.delete(f"/api/clients/{cid}/versions/{kept.json()['id']}").status_code == 204
    _publish(client, cid, {**SET, "samples": [{"name": "Font sheet", "media": house}]}, "2026")
    token = _token(client.post(f"/api/clients/{cid}/shares", json={"label": "Printer"}).json()["link"])
    with new_client() as visitor:
        assert visitor.get(f"/api/public/{token}/media/{house}").status_code == 404
    # Whoever wants to share it uploads it anew: the same bytes come as a file of their own.
    again = upload(client, space, "house.woff2", WOFF2)
    assert again != house


def _shared_example(client: TestClient, cid: str, media: str) -> str:
    """A published version showing ``media`` as an example, on a public page; the page's token."""
    _publish(client, cid, {**SET, "samples": [{"name": "Font sheet", "media": media}]}, "2026")
    return _token(client.post(f"/api/clients/{cid}/shares", json={"label": "Printer"}).json()["link"])


def test_a4_a_draft_changed_to_internal_marks_the_file_before_it_is_deleted(
    client: TestClient, operator: Account, space: int
) -> None:
    """Saved with a free font first, then changed to internal: the change marks the file as well."""
    _open_pages()
    house = upload(client, space, "house.woff2", WOFF2)
    cid, _ = _draft(client, space)
    draft = client.post(f"/api/clients/{cid}/versions", json={"label": "Free", "data": {
        **SET, "fonts": [_font(house, "free")]}}).json()["id"]
    saved = client.put(f"/api/clients/{cid}/versions/{draft}", json={"data": {**SET, "fonts": [_font(house)]}})
    assert saved.status_code == 200, saved.text
    assert client.delete(f"/api/clients/{cid}/versions/{draft}").status_code == 204
    token = _shared_example(client, cid, house)
    with new_client() as visitor:
        assert visitor.get(f"/api/public/{token}/media/{house}").status_code == 404


def test_a4_a_review_direction_marks_the_file_before_draft_and_review_go(
    client: TestClient, operator: Account, space: int
) -> None:
    """The internal font only in a direction of a review; the draft goes, its review with it."""
    _open_pages()
    house = upload(client, space, "house.woff2", WOFF2)
    cid, _ = _draft(client, space)
    draft = client.post(f"/api/clients/{cid}/versions", json={"label": "B", "data": SET}).json()["id"]
    made = _review(client, cid, draft, variants=[{"id": "a", "label": "A", "data": {**SET, "fonts": [_font(house)]}}])
    assert made.status_code == 201, made.text
    assert client.delete(f"/api/clients/{cid}/versions/{draft}?with_review=true").status_code == 204
    token = _shared_example(client, cid, house)
    with new_client() as visitor:
        assert visitor.get(f"/api/public/{token}/media/{house}").status_code == 404


def test_a4_files_named_before_the_mark_get_it_at_start(client: TestClient, operator: Account, space: int) -> None:
    from sqlalchemy import update

    from app.db import init_db
    from app.models import Media

    house = upload(client, space, "house.woff2", WOFF2)
    cid, _ = _draft(client, space)
    assert client.post(f"/api/clients/{cid}/versions", json={"label": "Kept", "data": {
        **SET, "fonts": [_font(house)]}}).status_code == 201
    with SessionLocal() as db:
        assert db.get(Media, house).kept_in_house is True  # type: ignore[union-attr]
        db.execute(update(Media).values(kept_in_house=False))
        db.commit()
    init_db()
    with SessionLocal() as db:
        assert db.get(Media, house).kept_in_house is True  # type: ignore[union-attr]


# --- every kind of picture is counted -------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["JPEG", "WEBP", "GIF"])
def test_a7_jpeg_webp_and_gif_are_counted_too(client: TestClient, operator: Account, space: int,
                                              monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    import io

    from PIL import Image

    monkeypatch.setattr(media_store, "MAX_PIXELS", 1000)

    def picture(side: int) -> bytes:
        out = io.BytesIO()
        Image.new("RGB", (side, side), (200, 40, 40)).save(out, kind)
        return out.getvalue()

    big = client.post(f"/api/media?space={space}&name=big.{kind.lower()}", content=picture(40))
    assert big.status_code == 422 and big.json()["detail"]["code"] == "too_many_pixels", big.text
    small = client.post(f"/api/media?space={space}&name=small.{kind.lower()}", content=picture(20))
    assert small.status_code == 201, small.text


# --- The mail brake, the public address, C1 characters ----------------------------------------------------------------


def test_f27_twenty_review_mails_then_the_brake(client: TestClient, operator: Account, space: int,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    from app import security

    # The clock stands still: the brake decides by counting, not by how fast the test runs.
    monkeypatch.setattr(security.time, "monotonic", lambda: 1000.0)
    monkeypatch.setattr(mailer, "_send", lambda db, message: None)
    _open_pages()
    _mail_ready(client)
    cid, vid = _draft(client, space)
    for _ in range(20):
        made = _review(client, cid, vid, email="kunde@example.com")
        assert made.status_code == 201 and made.json()["mailed"] is True, made.text
        assert client.delete(f"/api/clients/{cid}/reviews/{made.json()['id']}").status_code == 204
    braked = _review(client, cid, vid, email="kunde@example.com")
    assert braked.status_code == 429 and braked.json()["detail"]["code"] == "too_many_attempts"
    # Without a mail the draft still goes before the client.
    assert _review(client, cid, vid).status_code == 201


def test_f27_the_page_knows_whether_a_mail_can_carry_a_link(client: TestClient, operator: Account) -> None:
    assert client.get("/api/auth/me").json()["public_url"] is False
    assert client.put("/api/settings", json={"public_url": "https://brand.example.com"}).status_code == 200
    assert client.get("/api/auth/me").json()["public_url"] is True


@pytest.mark.parametrize("code", [0x80, 0x85, 0x9B, 0x9F])
def test_a14_c1_control_characters_are_refused_in_names(client: TestClient, operator: Account, space: int,
                                                        code: int) -> None:
    profile = client.put("/api/me/profile", json={"display_name": f"Kim{chr(code)}"})
    assert profile.status_code == 422 and profile.json()["detail"]["code"] == "display_name_invalid"
    _open_pages()
    cid, vid = _draft(client, space)
    token = _token(_review(client, cid, vid).json()["link"])
    with new_client() as visitor:
        said = visitor.post(f"/api/review/{token}/comments",
                            json={"variant": "a", "text": "Nice", "author": f"Kun{chr(code)}din"})
        assert said.status_code == 422 and said.json()["detail"]["code"] == "invalid_name"
