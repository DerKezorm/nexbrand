"""Collecting a brand and the account's AI service, against stand-ins: no request in these tests leaves the machine."""

from __future__ import annotations

import io
import json
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.db import SessionLocal
from app.models import Account, AiEvent, Media
from app.services import ai, collect, outbound, settings_service

from .conftest import join, make_account, new_client

PUBLIC = "93.184.215.14"
Pages = dict[str, tuple[int, str, bytes]]


def _pages(pages: Pages, seen: list[httpx.Request] | None = None) -> Callable[[httpx.Request], httpx.Response]:
    """Answers by Host header and path, as the server asks the checked address with the name kept in Host."""

    def answer(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        key = request.headers["host"] + request.url.raw_path.decode()
        if key not in pages:
            return httpx.Response(404)
        status, kind, body = pages[key]
        headers = {"content-type": kind}
        if status in (301, 302):
            headers["location"] = body.decode()
            body = b""
        return httpx.Response(status, headers=headers, content=body)

    return answer


@pytest.fixture
def web(monkeypatch: pytest.MonkeyPatch) -> Iterator[Pages]:
    """The outside world as a dictionary; every name resolves to one public address unless a test says otherwise."""
    pages: Pages = {}
    monkeypatch.setattr(outbound, "resolver", lambda host, port: ["10.0.0.7"] if host.endswith(".lan") else [PUBLIC])
    monkeypatch.setattr(outbound, "transport", httpx.MockTransport(_pages(pages)))
    yield pages


@pytest.fixture
def opened(client: TestClient, operator: Account) -> None:
    assert client.put("/api/settings", json={"collect_allowed": True}).status_code == 200


SITE = b"""<!doctype html><html><head>
<meta name="theme-color" content="#2F7BFF">
<link rel="stylesheet" href="/site.css">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:wght@600&family=Inter">
<link rel="icon" href="/logo.svg">
<style>:root { --brand-primary: #2f7bff; --brand-accent: #e255f5; } body { color: #1a1a1a; }</style>
</head><body><img src="/img/logo.png" alt="Logo"></body></html>"""
SHEET = b".button { background: #2f7bff; } .tag { background-color: rgb(226, 85, 245); } h1 { font-family: Fraunces, serif; }"


def test_collecting_is_closed_until_the_operator_opens_it(client: TestClient, operator: Account, web: Pages) -> None:
    web["example.com/"] = (200, "text/html", SITE)
    answer = client.post("/api/collect", json={"sources": [{"kind": "website", "value": "https://example.com/"}]})
    assert answer.status_code == 403
    assert answer.json()["detail"]["code"] == "collect_off"


def test_a_website_gives_its_colours_fonts_and_logos(client: TestClient, opened: None, web: Pages) -> None:
    web["example.com/"] = (200, "text/html; charset=utf-8", SITE)
    web["example.com/site.css"] = (200, "text/css", SHEET)
    answer = client.post("/api/collect", json={"sources": [{"kind": "website", "value": "https://example.com/"}],
                                               "language": "de"})
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["ai"] is False
    by_hex = {c["hex"]: c for c in body["colors"]}
    assert by_hex["#2F7BFF"]["role"] == "primary"
    assert by_hex["#2F7BFF"]["name"] == "primary"  # "--brand-" says nothing
    assert by_hex["#E255F5"]["role"] == "accent"
    assert by_hex["#1A1A1A"]["role"] == "neutral"
    assert body["colors"][0]["hex"] == "#2F7BFF"  # meta, variable and sheet together weigh the most
    families = {f["family"]: f for f in body["fonts"]}
    assert families["Fraunces"]["license"] == "free"
    assert "Inter" in families
    assert {logo["url"] for logo in body["logos"]} == {"https://example.com/logo.svg", "https://example.com/img/logo.png"}


def test_an_address_in_the_own_network_is_never_asked(client: TestClient, opened: None, web: Pages) -> None:
    web["router.lan/"] = (200, "text/html", SITE)
    answer = client.post("/api/collect", json={"sources": [{"kind": "website", "value": "http://router.lan/"}]})
    assert answer.status_code == 200
    assert answer.json()["notes"] == [{"source": "http://router.lan/", "problem": "not_public"}]
    assert answer.json()["colors"] == []


def test_a_redirect_into_the_own_network_is_refused(web: Pages) -> None:
    web["example.com/"] = (302, "text/html", b"http://nas.lan/admin")
    with pytest.raises(outbound.FetchError) as caught:
        outbound.get("https://example.com/", limit=1000)
    assert caught.value.code == "not_public"


@pytest.mark.parametrize("address", ["127.0.0.1", "10.1.2.3", "192.168.1.1", "169.254.169.254", "100.64.0.1",
                                     "::1", "fe80::1", "::ffff:10.0.0.1", "224.0.0.1"])
def test_special_addresses_are_not_public(address: str) -> None:
    assert outbound.public(address) is False


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/", "https://user:pw@example.com/",
                                 "https://example.com:99999/"])
def test_only_plain_web_addresses_go(web: Pages, url: str) -> None:
    with pytest.raises(outbound.FetchError) as caught:
        outbound.get(url, limit=1000)
    assert caught.value.code == "bad_address"


def test_an_answer_above_the_limit_stops(web: Pages) -> None:
    web["example.com/big"] = (200, "text/css", b"x" * 5000)
    with pytest.raises(outbound.FetchError) as caught:
        outbound.get("https://example.com/big", limit=4000)
    assert caught.value.code == "too_large"
    assert outbound.get("https://example.com/big", limit=5000).body == b"x" * 5000


def test_the_connection_goes_to_the_checked_address_with_the_name_in_host(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []
    monkeypatch.setattr(outbound, "resolver", lambda host, port: [PUBLIC])
    monkeypatch.setattr(outbound, "transport", httpx.MockTransport(
        _pages({"example.com/": (200, "text/html", b"<html></html>")}, seen)))
    outbound.get("https://example.com/", limit=1000)
    assert seen[0].url.host == PUBLIC
    assert seen[0].headers["host"] == "example.com"


def test_a_repository_gives_tailwind_tokens_and_fonts(client: TestClient, opened: None, web: Pages) -> None:
    tree = {"tree": [
        {"path": "tailwind.config.js", "type": "blob", "size": 300},
        {"path": "tokens/colors.json", "type": "blob", "size": 200},
        {"path": "package.json", "type": "blob", "size": 100},
        {"path": "node_modules/x/style.css", "type": "blob", "size": 10},
    ]}
    web["api.github.com/repos/example/site"] = (200, "application/json", b'{"default_branch": "main"}')
    web["api.github.com/repos/example/site/git/trees/main?recursive=1"] = (200, "application/json",
                                                                            json.dumps(tree).encode())
    raw = "raw.githubusercontent.com/example/site/main/"
    web[raw + "tailwind.config.js"] = (200, "text/plain", (b"colors: { 'brand': '#0F766E', sun: '#FFE14A' }, "
                                                           b"fontFamily: { sans: ['Inter'] }"))
    web[raw + "tokens/colors.json"] = (200, "text/plain", b'{"color": {"ink": {"$value": "#111827"}}}')
    web[raw + "package.json"] = (200, "text/plain", b'{"dependencies": {"@fontsource/source-serif-4": "5"}}')
    answer = client.post("/api/collect", json={"sources": [{"kind": "repo",
                                                            "value": "https://github.com/example/site"}]})
    assert answer.status_code == 200, answer.text
    by_hex = {c["hex"]: c for c in answer.json()["colors"]}
    assert by_hex["#0F766E"]["names"] == ["brand"]
    assert by_hex["#111827"]["names"] == ["color ink"]
    assert "#FFE14A" in by_hex
    assert {f["family"] for f in answer.json()["fonts"]} >= {"Inter", "Source Serif 4"}


def test_a_private_repository_uses_the_operators_token(client: TestClient, opened: None,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []
    pages: Pages = {"api.github.com/repos/example/site/git/trees/dev?recursive=1": (200, "application/json",
                                                                                  b'{"tree": []}')}
    monkeypatch.setattr(outbound, "resolver", lambda host, port: [PUBLIC])
    monkeypatch.setattr(outbound, "transport", httpx.MockTransport(_pages(pages, seen)))
    token = "gh" + "p_" + "a" * 36
    assert client.put("/api/settings", json={"collect_github_token": token}).status_code == 200
    settings = client.get("/api/settings").json()
    assert settings["collect_github_token_set"] is True
    assert token not in json.dumps(settings)
    with SessionLocal() as db:
        assert token not in str(settings_service.get(db, "collect_github_token_enc"))
    client.post("/api/collect", json={"sources": [{"kind": "repo", "value": "https://github.com/example/site/tree/dev"}]})
    assert seen[0].headers["authorization"] == f"Bearer {token}"


def test_something_that_is_not_a_repository_says_so(client: TestClient, opened: None, web: Pages) -> None:
    answer = client.post("/api/collect", json={"sources": [{"kind": "repo", "value": "https://gitlab.com/a/b"}]})
    assert answer.json()["notes"] == [{"source": "https://gitlab.com/a/b", "problem": "not_a_repo"}]


def _pdf(lines: list[str]) -> bytes:
    """A small PDF with one line of Helvetica text per entry, written by hand."""
    text = "BT /F1 11 Tf 40 760 Td 14 TL " + " ".join(f"({line}) '" for line in lines) + " ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> "
         "/Contents 5 0 R >>"),
        "<< /Type /Font /Subtype /Type1 /BaseFont /ABCDEF+Fraunces-SemiBold >>",
        f"<< /Length {len(text)} >>\nstream\n{text}\nendstream",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1")
    start = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()
    return out


def _upload(client: TestClient, space: int, name: str, body: bytes) -> str:
    answer = client.post(f"/api/media?space={space}&name={name}", content=body)
    assert answer.status_code == 201, answer.text
    return str(answer.json()["id"])


def test_a_pdf_style_guide_gives_named_colours_and_its_fonts(client: TestClient, space: int) -> None:
    media_id = _upload(client, space, "styleguide.pdf", _pdf([
        "Hausfarben",
        "Morgenrot HEX #C23B2E CMYK 0 80 80 15",
        "Nachtblau",
        "RGB 20 40 90 Pantone 2766 C",
    ]))
    # A PDF never leaves the house: it works with collecting closed.
    answer = client.post("/api/collect", json={"sources": [{"kind": "pdf", "value": media_id}]})
    assert answer.status_code == 200, answer.text
    by_hex = {c["hex"]: c for c in answer.json()["colors"]}
    assert by_hex["#C23B2E"]["names"] == ["Morgenrot"]
    assert by_hex["#C23B2E"]["cmyk"] == "0 80 80 15"
    assert by_hex["#14285A"]["names"] == ["Nachtblau"]
    assert by_hex["#14285A"]["pantone"].startswith("Pantone 2766")
    assert [f["family"] for f in answer.json()["fonts"]] == ["Fraunces"]


def test_a_pdf_of_a_space_one_cannot_read_is_not_found(client: TestClient, space: int) -> None:
    media_id = _upload(client, space, "styleguide.pdf", _pdf(["Rot #C23B2E"]))
    make_account("mia")
    stranger = new_client()
    from .conftest import sign_in

    with SessionLocal() as db:
        mia = db.query(Account).filter_by(name="mia").one()
        db.expunge(mia)
    sign_in(stranger, mia)
    answer = stranger.post("/api/collect", json={"sources": [{"kind": "pdf", "value": media_id}]})
    assert answer.status_code == 404
    join(client, space, "mia", "read")
    assert stranger.post("/api/collect", json={"sources": [{"kind": "pdf", "value": media_id}]}).status_code == 200


def test_a_picture_is_not_a_pdf(client: TestClient, space: int) -> None:
    media_id = _upload(client, space, "logo.svg", b'<svg xmlns="http://www.w3.org/2000/svg"></svg>')
    answer = client.post("/api/collect", json={"sources": [{"kind": "pdf", "value": media_id}]})
    assert answer.status_code == 404


def _png() -> bytes:
    """A one-pixel PNG, made at run time (a long hex literal looks like a token to the scanners)."""
    out = io.BytesIO()
    Image.new("RGB", (1, 1), (47, 123, 255)).save(out, "PNG")
    return out.getvalue()


PNG = _png()


def test_a_logo_found_is_taken_into_the_space(client: TestClient, opened: None, space: int, web: Pages) -> None:
    web["example.com/img/logo.png"] = (200, "image/png", PNG)
    web["example.com/page"] = (200, "text/html", b"<html>not a logo</html>")
    answer = client.post("/api/collect/logo", json={"space_id": space, "url": "https://example.com/img/logo.png"})
    assert answer.status_code == 201, answer.text
    assert answer.json()["kind"] == "png"
    assert answer.json()["name"] == "logo.png"
    refused = client.post("/api/collect/logo", json={"space_id": space, "url": "https://example.com/page"})
    assert refused.status_code == 422
    with SessionLocal() as db:
        assert db.query(Media).count() == 1


def test_a_logo_needs_the_right_to_write(client: TestClient, opened: None, space: int, web: Pages) -> None:
    web["example.com/logo.png"] = (200, "image/png", PNG)
    make_account("mia")
    join(client, space, "mia", "read")
    from .conftest import sign_in

    reader = new_client()
    with SessionLocal() as db:
        mia = db.query(Account).filter_by(name="mia").one()
        db.expunge(mia)
    sign_in(reader, mia)
    answer = reader.post("/api/collect/logo", json={"space_id": space, "url": "https://example.com/logo.png"})
    assert answer.status_code == 403


# --- Sorting --------------------------------------------------------------------------------------------------------


def test_rules_leave_out_near_repeats_and_tiny_shares() -> None:
    found = collect.Found()
    found.color("#2F7BFF", 10, "a")
    found.color("#2E7AFE", 5, "a")  # the same to the eye: merged
    found.color("#3D86FF", 3, "a")  # near: shown, not kept
    found.color("#E255F5", 4, "a")
    found.color("#00AA00", 0.05, "a")  # a speck
    items = collect.merged(found)
    assert [i["hex"] for i in items] == ["#2F7BFF", "#E255F5", "#3D86FF", "#00AA00"]
    ordered = {i["hex"]: i for i in collect.order_by_rules(items, "en")}
    assert ordered["#2F7BFF"]["keep"] and ordered["#2F7BFF"]["role"] == "primary"
    assert ordered["#E255F5"]["keep"] and ordered["#E255F5"]["role"] == "accent"
    assert ordered["#3D86FF"]["keep"] is False
    assert ordered["#00AA00"]["keep"] is False
    assert ordered["#E255F5"]["name"] == "Pink"


def test_an_ai_may_not_bring_a_colour_of_its_own() -> None:
    found = collect.Found()
    found.color("#2F7BFF", 10, "a")
    found.color("#E255F5", 4, "a")
    answer = {"colors": [
        {"hex": "#e255f5", "role": "primary", "name": "Signal", "reason": "most visible"},
        {"hex": "#123456", "role": "accent", "name": "Invented"},
        {"hex": "#E255F5", "role": "accent", "name": "Twice"},
    ]}
    ordered = collect.order_with_ai(collect.merged(found), answer, "en")
    assert [(i["hex"], i["role"], i["name"], i["keep"]) for i in ordered] == [
        ("#E255F5", "primary", "Signal", True), ("#2F7BFF", "primary", "Blue", False)]


# --- The AI service --------------------------------------------------------------------------------------------------


def _ai_answer(content: Any, status: int = 200) -> Callable[[httpx.Request], httpx.Response]:
    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "small-model"}]})
        text = content if isinstance(content, str) else json.dumps(content)
        return httpx.Response(status, json={"choices": [{"message": {"content": text}}],
                                            "usage": {"prompt_tokens": 120, "completion_tokens": 40}})

    return answer


@pytest.fixture
def service(client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch) -> Callable[[Any], None]:
    """Allows AI, sets up the account's access, and lets a test say what the service answers."""
    monkeypatch.setattr(ai, "resolver", lambda host, port: [PUBLIC])
    ai.pace.forget()
    assert client.put("/api/settings", json={"ai_allowed": True}).status_code == 200
    saved = client.put("/api/ai", json={"url": "https://ai.example.com/v1", "model": "small-model",
                                        "key": "k-" + "x" * 20, "active": True})
    assert saved.status_code == 200, saved.text

    def answers(content: Any, status: int = 200) -> None:
        monkeypatch.setattr(ai, "transport", httpx.MockTransport(_ai_answer(content, status)))

    return answers


def test_the_key_never_comes_back(client: TestClient, service: Callable[[Any], None]) -> None:
    body = client.get("/api/ai").json()
    assert body == {"allowed": True, "ready": True, "access": {"active": True, "url": "https://ai.example.com/v1/",
                                                                  "model": "small-model", "key_set": True}}


def test_models_are_listed_through_the_access(client: TestClient, service: Callable[[Any], None]) -> None:
    service({})
    assert client.post("/api/ai/models", json={}).json() == [{"id": "small-model", "name": ""}]


def test_ai_sorts_what_was_collected_and_what_went_out_is_listed(client: TestClient, opened: None, web: Pages,
                                                                 service: Callable[[Any], None]) -> None:
    web["example.com/"] = (200, "text/html", SITE)
    service({"colors": [{"hex": "#E255F5", "role": "primary", "name": "Magenta", "keep": True}],
             "fonts": [{"family": "Inter", "use": "headings"}]})
    answer = client.post("/api/collect", json={"sources": [{"kind": "website", "value": "https://example.com/"}],
                                               "use_ai": True})
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["ai"] is True
    assert body["colors"][0]["hex"] == "#E255F5" and body["colors"][0]["role"] == "primary"
    assert all(c["keep"] is False for c in body["colors"][1:])
    assert {f["family"]: f["use"] for f in body["fonts"]}["Inter"] == "headings"
    events = client.get("/api/ai/events").json()
    assert len(events) == 1 and events[0]["task"] == "order"
    assert client.delete("/api/ai/events").json() == {"removed": 1}


def test_a_failing_ai_falls_back_to_the_rules(client: TestClient, opened: None, web: Pages,
                                              service: Callable[[Any], None]) -> None:
    web["example.com/"] = (200, "text/html", SITE)
    service("this is not json")
    body = client.post("/api/collect", json={"sources": [{"kind": "website", "value": "https://example.com/"}],
                                             "use_ai": True}).json()
    assert body["ai"] is False
    assert {"source": "ai", "problem": "ai_not_json"} in body["notes"]
    assert body["colors"][0]["role"] == "primary"


def test_directions_are_checked_before_they_reach_the_workbench(client: TestClient,
                                                                service: Callable[[Any], None]) -> None:
    service({"directions": [
        {"label": "Warm  bakery", "why": "flour and fire", "hue": 380, "saturation": 150, "accent_hue": 40,
         "mood": "warm", "head": "fraunces", "body": "inter"},
        {"label": "Odd", "hue": "red"},
        {"label": "Unknown fonts", "hue": 200, "mood": "sinister", "head": "Comic Sans", "body": "x"},
        {"label": "Fourth", "hue": 10},
        {"label": "Fifth", "hue": 20},
    ]})
    answer = client.post("/api/ai/directions", json={"brief": "a bakery with a wood oven", "name": "Example"})
    assert answer.status_code == 200, answer.text
    directions = answer.json()["directions"]
    assert len(directions) == 3
    assert directions[0] == {"label": "Warm bakery", "why": "flour and fire", "hue": 20, "accent_hue": 40,
                             "saturation": 90, "mood": "warm", "head": "fraunces", "body": "inter"}
    assert directions[1]["label"] == "Unknown fonts"
    assert (directions[1]["mood"], directions[1]["head"], directions[1]["body"]) == ("calm", "fraunces", "inter")


def test_an_answer_without_a_direction_is_an_error(client: TestClient, service: Callable[[Any], None]) -> None:
    service({"something": "else"})
    answer = client.post("/api/ai/directions", json={"brief": "a bakery"})
    assert answer.status_code == 502
    assert answer.json()["detail"]["code"] == "ai_unreadable"


def test_the_operators_lock_holds_for_a_ready_access(client: TestClient, service: Callable[[Any], None]) -> None:
    service({"directions": []})
    assert client.put("/api/settings", json={"ai_allowed": False}).status_code == 200
    answer = client.post("/api/ai/directions", json={"brief": "a bakery"})
    assert answer.status_code == 403
    assert answer.json()["detail"]["code"] == "ai_off"
    assert client.get("/api/ai").json()["ready"] is False
    with SessionLocal() as db:
        assert db.query(AiEvent).count() == 0


def test_an_ai_service_in_the_own_network_needs_the_operator(client: TestClient, service: Callable[[Any], None],
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    service({"directions": [{"label": "A", "hue": 10}]})
    monkeypatch.setattr(ai, "resolver", lambda host, port: ["192.168.1.20"])
    client.put("/api/ai", json={"url": "http://ollama.lan:11434/v1"})
    refused = client.post("/api/ai/directions", json={"brief": "a bakery"})
    assert refused.json()["detail"]["code"] == "ai_address_private"
    assert client.put("/api/settings", json={"ai_private_hosts": "ollama.lan:11434"}).status_code == 200
    assert client.post("/api/ai/directions", json={"brief": "a bakery"}).status_code == 200
    bad = client.put("/api/settings", json={"ai_private_hosts": "not a host/with path"})
    assert bad.status_code == 422


def test_an_account_sees_only_its_own_events(client: TestClient, service: Callable[[Any], None]) -> None:
    service({"directions": [{"label": "A", "hue": 10}]})
    client.post("/api/ai/directions", json={"brief": "a bakery"})
    other = make_account("mia")
    stranger = new_client()
    from .conftest import sign_in

    sign_in(stranger, other)
    assert stranger.get("/api/ai/events").json() == []
    assert stranger.get("/api/ai").json()["access"]["key_set"] is False


def test_a_collected_draft_says_where_it_came_from(client: TestClient, operator: Account, space: int) -> None:
    from .test_brands import make_client

    cid = make_client(client, space)["id"]
    made = client.post(f"/api/clients/{cid}/versions", json={"label": "Collected", "origin": "collect"})
    assert made.status_code == 201, made.text
    assert made.json()["origin"] == "collect"
    # Only a person in the app or a client's choice may say "by hand" or "chosen"; MCP is the token's own way.
    assert client.post(f"/api/clients/{cid}/versions", json={"label": "X", "origin": "mcp"}).status_code == 422
    assert client.post(f"/api/clients/{cid}/versions", json={"label": "Y"}).json()["origin"] == "hand"


def test_an_answer_without_a_declared_length_stops_at_the_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(outbound, "resolver", lambda host, port: [PUBLIC])
    monkeypatch.setattr(outbound, "transport", httpx.MockTransport(
        lambda request: httpx.Response(200, content=iter([b"x" * 3000, b"x" * 3000]))))
    with pytest.raises(outbound.FetchError) as caught:
        outbound.get("https://example.com/endless", limit=4000)
    assert caught.value.code == "too_large"


def test_a_paper_tint_is_a_neutral() -> None:
    found = collect.Found()
    found.color("#2F7BFF", 10, "a")
    found.color("#F7F1E6", 5, "a")
    ordered = {i["hex"]: i for i in collect.order_by_rules(collect.merged(found), "de")}
    assert ordered["#F7F1E6"]["role"] == "neutral"
    assert ordered["#F7F1E6"]["name"] == "Hell"
