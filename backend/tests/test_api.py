"""Programs and AI: ``/api/v1`` and MCP, with the same tokens and the same rights as the interface."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.models import Account
from app.services import apitokens

from .conftest import make_account, new_client
from .test_brands import SET, SVG, WOFF2, make_client, upload


@pytest.fixture(autouse=True)
def _tokens_on(client: TestClient, operator: Account) -> Iterator[None]:
    apitokens.forget()
    assert client.put("/api/settings", json={"api_tokens_allowed": True}).status_code == 200
    yield
    apitokens.forget()


def _token(client: TestClient, level: str = "read") -> dict[str, str]:
    answer = client.post("/api/api-tokens", json={"name": "Editor", "level": level, "all_clients": True,
                                                  "days": None})
    assert answer.status_code in (200, 201), answer.text
    return {"Authorization": f"Bearer {answer.json()['secret']}"}


def _program() -> TestClient:
    """A program: no tab header, no cookie, no Origin."""
    from app.main import app

    return TestClient(app, base_url="http://testserver")


def _published(client: TestClient, space: int, data: dict[str, Any] | None = None) -> str:
    made = make_client(client, space, data, project="Website")
    cid, vid = made["id"], made["versions"][0]["id"]
    client.post(f"/api/clients/{cid}/versions/{vid}/publish", json={"label": "2026", "valid_from": "2026-01-19"})
    return cid


def test_a_token_reads_clients_by_name_and_code(client: TestClient, space: int) -> None:
    _published(client, space)
    auth = _token(client)
    with _program() as program:
        assert program.get("/api/v1/me", headers=auth).json()["level"] == "read"
        listed = program.get("/api/v1/clients", headers=auth).json()
        assert listed[0]["name"] == "Bäckerei Morgenrot" and listed[0]["projects"][0]["name"] == "Website"
        brand = program.get("/api/v1/clients/bäckerei morgenrot", headers=auth).json()
        assert brand["version"]["label"] == "2026" and brand["current"] is True
        assert any(h["code"] == "white_on" for h in brand["checks"])
        code = program.get("/api/v1/clients/Bäckerei Morgenrot/code?format=tailwind", headers=auth).text
        assert "--color-ofenrot: #B8322A;" in code
        assert program.get("/api/v1/clients/Bäckerei Morgenrot?at=2020-01-01", headers=auth).status_code == 404


def test_the_walls_of_the_api(client: TestClient, space: int) -> None:
    auth = _token(client)
    with _program() as program:
        assert program.get("/api/v1/me").status_code == 401
        assert program.get("/api/v1/me", headers={**auth, "Origin": "https://evil.example"}).status_code == 403
        client.put("/api/settings", json={"api_tokens_allowed": False})
        assert program.get("/api/v1/me", headers=auth).json()["detail"]["code"] == "api_off"


def test_a_token_never_sees_what_its_account_may_not(client: TestClient, space: int) -> None:
    _published(client, space)
    stranger = make_account("stranger")
    with new_client(stranger) as browser:
        auth = _token(browser)
    with _program() as program:
        assert program.get("/api/v1/clients", headers=auth).json() == []
        assert program.get("/api/v1/clients/Bäckerei Morgenrot", headers=auth).status_code == 404


def test_an_internal_font_never_leaves_through_a_token(client: TestClient, space: int) -> None:
    internal = upload(client, space, "house.woff2", WOFF2)
    _published(client, space, {**SET, "fonts": [{"family": "House", "license": "internal", "files": [internal]}]})
    auth = _token(client)
    with _program() as program:
        brand = program.get("/api/v1/clients/Bäckerei Morgenrot", headers=auth).json()
        assert brand["design"]["fonts"][0]["files"] == [] and brand["files"] == {}
        assert program.get(f"/api/v1/files/{internal}", headers=auth).status_code == 404


def test_a_file_another_version_keeps_in_the_house_is_not_even_named(client: TestClient, space: int) -> None:
    """(A4) The published version shows the file only as an example and a logo download; a draft keeps it as an
    internal font. Neither the brand nor its files, over the API or MCP, name its id."""
    house = upload(client, space, "house.woff2", WOFF2)
    logo = upload(client, space, "logo.svg", SVG)
    shown = {**SET, "samples": [{"name": "Font sheet", "media": house}],
             "logos": [{"id": "main", "name": "Logo", "media": logo, "files": [house, logo]}]}
    cid = _published(client, space, shown)
    assert client.post(f"/api/clients/{cid}/versions", json={"label": "Kept", "data": {
        **SET, "fonts": [{"family": "House", "license": "internal", "files": [house]}]}}).status_code == 201
    auth = _token(client)
    with _program() as program:
        brand = program.get("/api/v1/clients/Bäckerei Morgenrot", headers=auth)
        assert brand.status_code == 200 and house not in brand.text and logo in brand.json()["files"]
        result = _rpc(program, auth, "tools/call", {"name": "get_brand", "arguments": {"client": "Bäckerei Morgenrot"}})
        assert result["isError"] is False and house not in str(result)
        assert program.get(f"/api/v1/files/{house}", headers=auth).status_code == 404


def test_only_a_draft_token_proposes_and_it_lands_as_a_draft(client: TestClient, space: int) -> None:
    cid = _published(client, space)
    redesign = {"colors": [{"name": "Ofenrot", "hex": "#C23B2E", "role": "primary"},
                           {"name": "Mehl", "hex": "#F3E4C8", "role": "neutral"}]}
    with _program() as program:
        refused = program.post("/api/v1/clients/Bäckerei Morgenrot/drafts", headers=_token(client),
                               json={"label": "Redesign", "data": redesign})
        assert refused.status_code == 403
        made = program.post("/api/v1/clients/Bäckerei Morgenrot/drafts", headers=_token(client, "draft"),
                            json={"label": "Redesign", "data": redesign, "based_on": "2026"})
        assert made.status_code == 201, made.text
        assert made.json()["version"]["status"] == "draft" and made.json()["version"]["origin"] == "mcp"
    whole = client.get(f"/api/clients/{cid}").json()
    draft = next(v for v in whole["versions"] if v["label"] == "Redesign")
    assert draft["author"] == "Editor" and draft["data"]["fonts"][0]["family"] == "Fraunces", "kept from 2026"
    assert whole["current"] == "2026"


def test_a_draft_token_still_needs_the_right_to_write(client: TestClient, space: int) -> None:
    _published(client, space)
    reader = make_account("reader")
    from .conftest import join

    join(client, space, "reader", "read")
    with new_client(reader) as browser:
        auth = _token(browser, "draft")
    with _program() as program:
        answer = program.post("/api/v1/clients/Bäckerei Morgenrot/drafts", headers=auth,
                              json={"label": "X", "data": {"colors": []}})
        assert answer.status_code == 403


def test_the_audit_finds_slips(client: TestClient, space: int) -> None:
    _published(client, space)
    auth = _token(client)
    with _program() as program:
        found = program.post("/api/v1/clients/Bäckerei Morgenrot/audit", headers=auth,
                             json={"colors": ["#B9332A", "#C23B2E", "#6B7280", "nope"]}).json()["colors"]
    assert [c["verdict"] for c in found] == ["same", "near", "foreign", "unreadable"]
    assert found[1]["nearest"] == "Ofenrot" and found[1]["nearest_hex"] == "#B8322A"


def test_contrast_for_programs(client: TestClient, space: int) -> None:
    auth = _token(client)
    with _program() as program:
        answer = program.get("/api/v1/contrast?fg=%23E9A23B&bg=%23FFFFFF", headers=auth).json()
    assert answer["ratio"] == 2.16 and answer["text"] == "fail" and answer["nearest_passing"]


# --- MCP ------------------------------------------------------------------------------------------------------------


def _rpc(program: TestClient, auth: dict[str, str], method: str, params: dict[str, Any] | None = None) -> Any:
    answer = program.post("/api/mcp", headers=auth, json={"jsonrpc": "2.0", "id": 1, "method": method,
                                                          "params": params or {}})
    assert answer.status_code == 200, answer.text
    return answer.json()["result"]


def test_mcp_lists_tools_by_level_and_answers_get_brand(client: TestClient, space: int) -> None:
    _published(client, space)
    read = _token(client)
    with _program() as program:
        assert _rpc(program, read, "initialize", {"protocolVersion": "2025-06-18"})["serverInfo"]["name"] == "nexbrand"
        names = {tool["name"] for tool in _rpc(program, read, "tools/list")["tools"]}
        assert "get_brand" in names and "propose_version" not in names
        result = _rpc(program, read, "tools/call", {"name": "get_brand",
                                                    "arguments": {"client": "Bäckerei Morgenrot",
                                                                  "project": "website"}})
        assert result["isError"] is False
        assert result["structuredContent"]["project"]["name"] == "Website"
        hidden = _rpc(program, read, "tools/call", {"name": "propose_version",
                                                    "arguments": {"client": "x", "label": "x", "data": {}}})
        assert hidden["isError"] is True and "No tool" in hidden["content"][0]["text"]


def test_mcp_proposes_with_a_draft_token_and_says_what_is_wrong(client: TestClient, space: int) -> None:
    _published(client, space)
    auth = _token(client, "draft")
    with _program() as program:
        bad = _rpc(program, auth, "tools/call", {"name": "propose_version", "arguments": {
            "client": "Bäckerei Morgenrot", "label": "R", "data": {"colors": [{"name": "A", "hex": "red"}]}}})
        assert bad["isError"] is True and "colors.0.hex" in bad["content"][0]["text"]
        good = _rpc(program, auth, "tools/call", {"name": "propose_version", "arguments": {
            "client": "Bäckerei Morgenrot", "label": "R", "based_on": "2026",
            "data": {"colors": [{"name": "Ofenrot", "hex": "#C23B2E", "role": "primary"}]}}})
        assert good["isError"] is False and good["structuredContent"]["version"]["status"] == "draft"
        assert good["structuredContent"]["version"]["based_on"]["label"] == "2026"


def test_mcp_refuses_browsers_and_unknown_tokens(client: TestClient, space: int) -> None:
    with _program() as program:
        assert program.post("/api/mcp", json={}).status_code == 401
        auth = _token(client)
        assert program.post("/api/mcp", headers={**auth, "Origin": "https://x.example"}, json={}).status_code == 403
        assert program.post("/api/mcp", headers=auth, json={"jsonrpc": "2.0", "method": "x"}).status_code == 202


def test_a_proposed_colour_stays_as_it_is_and_the_check_names_what_it_misses(client: TestClient, space: int) -> None:
    """Decided 06.10.2026: a colour somebody brings is never darkened on the way in. #D04343 reads on white, not on
    the off-white beside it; the draft keeps it, and the checks that come back say so."""
    cid = _published(client, space)
    data = {"colors": [{"name": "Signal", "hex": "#D04343", "role": "primary"},
                       {"name": "Paper", "hex": "#F9F1F1", "role": "neutral"},
                       {"name": "White", "hex": "#FFFFFF", "role": "neutral"}]}

    def kept(answer: dict[str, Any]) -> None:
        missing = [h for h in answer["checks"] if h["code"] == "primary_as_text"]
        assert [(h["colors"], h["ratio"]) for h in missing] == [(["Signal", "Paper"], 4.13)]

    with _program() as program:
        made = program.post(f"/api/v1/clients/{cid}/drafts", headers=_token(client, "draft"),
                            json={"label": "API", "data": data})
        assert made.status_code == 201, made.text
        kept(made.json())
        over_mcp = _rpc(program, _token(client, "draft"), "tools/call", {"name": "propose_version", "arguments": {
            "client": cid, "label": "MCP", "data": data}})
        assert over_mcp["isError"] is False
        kept(over_mcp["structuredContent"])
    for version in client.get(f"/api/clients/{cid}").json()["versions"]:
        if version["label"] in ("API", "MCP"):
            assert [c["hex"] for c in version["data"]["colors"]] == ["#D04343", "#F9F1F1", "#FFFFFF"], version["label"]
