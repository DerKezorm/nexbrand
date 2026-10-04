"""MCP over HTTP (``POST /api/mcp``): an AI in an editor reads the client's design set while it builds, and writes a
redesign back as a draft.

The protocol is JSON-RPC 2.0 as MCP's "Streamable HTTP" transport has it, without streams (as in nexlore): every
request gets its answer as ``application/json``, a notification gets 202. No session is kept; each request names its
token (the same API tokens as ``/api/v1``, ``services/apitokens.py``).

Walls, in this order: a request that carries an ``Origin`` is refused (browsers send one, MCP clients do not; so no
web page can talk to this with a token it guessed or stole, and DNS rebinding goes nowhere); API tokens must be on;
the token must be valid; the token must stay under its rate. The tools go through ``services/brandapi.py``: the same
rights as the interface, the same "not found" for what the account may not read. Proposing needs a ``draft`` token
and the right to write, and lands as a draft; publishing is a person's act in nexbrand.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response

from .. import __version__
from ..db import SessionLocal
from ..services import apitokens, brandapi, brandset, checks, logs, settings_service
from ..services.apitokens import Caller

logger = logging.getLogger("nexbrand.mcp")

router = APIRouter(tags=["mcp"])

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = (
    "nexbrand keeps the corporate design of an agency's clients: colours, fonts, logos, type sizes, rules, in "
    "versions. "
    "Before building anything for a client, call get_brand with the client's name (and the project, if one is named) "
    "and use exactly its colours and fonts; get_code gives them as CSS, Tailwind, SCSS or design tokens. Never invent "
    "colour values. To check colours used in code, call audit. A redesign goes back with propose_version: it becomes "
    "a draft a person reviews and publishes in nexbrand."
)

_CLIENT = {"type": "string", "maxLength": 200, "description": "The client's name or id."}
_PROJECT = {"type": "string", "maxLength": 120, "description": "A project's name or id: its own colours apply."}
_VERSION = {"type": "string", "maxLength": 120, "description": "A version's label or id; empty: the current one."}
_AT = {"type": "string", "maxLength": 10, "description": "A day (YYYY-MM-DD): the version that held then."}

TOOLS: list[dict[str, Any]] = [
    {"name": "list_clients", "level": "read",
     "description": "The clients you may see, with their current version, main colours and projects.",
     "inputSchema": {"type": "object", "properties": {
         "search": {"type": "string", "maxLength": 120, "description": "Part of a name or sector."}},
         "additionalProperties": False}},
    {"name": "get_brand", "level": "read",
     "description": "A client's design set: colours with roles, fonts, logos with file addresses, type scale, rules, "
                    "and the checks (contrast, colour vision). Current version unless a version, a day or a project "
                    "is given.",
     "inputSchema": {"type": "object", "properties": {"client": _CLIENT, "project": _PROJECT, "version": _VERSION,
                                                      "at": _AT},
                     "required": ["client"], "additionalProperties": False}},
    {"name": "get_code", "level": "read",
     "description": "The design set as code to paste: CSS variables, a Tailwind 4 theme, SCSS or design tokens (JSON), "
                    "with colour scales from 50 to 950 and font stacks.",
     "inputSchema": {"type": "object", "properties": {
         "client": _CLIENT, "format": {"type": "string", "enum": ["css", "tailwind", "scss", "json"]},
         "project": _PROJECT, "version": _VERSION, "at": _AT},
         "required": ["client", "format"], "additionalProperties": False}},
    {"name": "list_versions", "level": "read",
     "description": "Every version of a client's design set, published ones with the day they hold from, then drafts.",
     "inputSchema": {"type": "object", "properties": {"client": _CLIENT}, "required": ["client"],
                     "additionalProperties": False}},
    {"name": "compare_versions", "level": "read",
     "description": "What changed between two versions: colours changed (with their distance), added, removed; fonts.",
     "inputSchema": {"type": "object", "properties": {"client": _CLIENT, "from": _VERSION, "to": _VERSION},
                     "required": ["client", "from", "to"], "additionalProperties": False}},
    {"name": "check_contrast", "level": "read",
     "description": "Contrast of a text colour on a ground (WCAG 2.2), for colour vision deficiencies too, and the "
                    "nearest colour of the same hue that passes when it does not.",
     "inputSchema": {"type": "object", "properties": {
         "foreground": {"type": "string", "maxLength": 9}, "background": {"type": "string", "maxLength": 9}},
         "required": ["foreground", "background"], "additionalProperties": False}},
    {"name": "audit", "level": "read",
     "description": "Colour values found in code or on a page, against the client's design set: the same, nearly the "
                    "same (probably a slip, with the right value), or not part of it. With css (a style sheet), "
                    "its colours are added, and each CSS rule that sets both color and background is held against "
                    "the set's forbidden colour pairs and against 4.5:1. Only pairs inside one CSS rule are seen.",
     "inputSchema": {"type": "object", "properties": {
         "client": _CLIENT, "project": _PROJECT,
         "colors": {"type": "array", "items": {"type": "string"}, "maxItems": 500},
         "css": {"type": "string", "maxLength": 500000}},
         "required": ["client"], "additionalProperties": False}},
    {"name": "propose_version", "level": "draft",
     "description": "Write a new version back as a draft, e.g. after a redesign. Give the parts that change "
                    "(colors, fonts, scale, rules) in nexbrand's shape; with based_on, the rest is kept from that "
                    "version. A person reviews and publishes it in nexbrand. Answers the checks of the draft.",
     "inputSchema": {"type": "object", "properties": {
         "client": _CLIENT,
         "label": {"type": "string", "maxLength": 60, "description": "A name for the version, e.g. 'Redesign 2027'."},
         "based_on": _VERSION,
         "note": {"type": "string", "maxLength": 500, "description": "What changed and why."},
         "data": {"type": "object", "description": (
             "colors: [{name, hex '#RRGGBB', role: primary|secondary|accent|neutral}], "
             "fonts: [{family, role, weights, license: free|internal|system, fallback}], "
             "scale: [{name, use: h1|h2|h3|h4|lead|body|small|caption|label, size (px), weight, font, line_height}], "
             "rules: [{type: text, kind: do|dont, text, topic: logo|color|font|image|tone}] or checkable ones: "
             "{type: pair, kind, fg: colour name, bg: colour name, size: text|large}, "
             "{type: logo, kind, logo: logo id, grounds: [colour names]}, "
             "{type: font, kind, font: family, use: ''|headings|h1|body|..., min_size: px}")}},
         "required": ["client", "label", "data"], "additionalProperties": False}},
]
BY_NAME = {tool["name"]: tool for tool in TOOLS}


def _visible(caller: Caller, tool: dict[str, Any]) -> bool:
    return tool["level"] == "read" or caller.level == "draft"


def _check(schema: dict[str, Any], args: dict[str, Any]) -> str | None:
    """What is wrong with the arguments by the tool's schema, before anything runs."""
    properties = schema.get("properties", {})
    for key in schema.get("required", []):
        if args.get(key) is None:
            return f"'{key}' is missing."
    kinds = {"string": str, "integer": int, "boolean": bool, "array": list, "object": dict}
    for key, value in args.items():
        spec = properties.get(key)
        if spec is None:
            return f"There is no argument '{key}'."
        if value is None and key not in schema.get("required", []):
            continue
        wanted = kinds.get(spec.get("type", ""))
        if wanted is not None and (not isinstance(value, wanted) or (wanted is int and isinstance(value, bool))):
            return f"'{key}' must be of type {spec['type']}."
        if "enum" in spec and value not in spec["enum"]:
            return f"'{key}' must be one of {', '.join(map(str, spec['enum']))}."
        if isinstance(value, str) and len(value) > spec.get("maxLength", len(value)):
            return f"'{key}' holds at most {spec['maxLength']} characters."
        if isinstance(value, list) and len(value) > spec.get("maxItems", len(value)):
            return f"'{key}' holds at most {spec['maxItems']} entries."
    return None


def _tool_result(value: Any, failed: bool = False) -> dict[str, Any]:
    value = jsonable_encoder(value)
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    result: dict[str, Any] = {"content": [{"type": "text", "text": text}], "isError": failed}
    if not failed and isinstance(value, dict):
        result["structuredContent"] = value
    return result


def _run(caller: Caller, name: str, args: dict[str, Any], base: str) -> Any:
    with SessionLocal() as db:
        if name == "list_clients":
            return {"clients": brandapi.list_clients(db, caller, args.get("search") or "")}
        if name == "get_brand":
            return brandapi.brand(db, caller, args["client"], version=args.get("version"), at=args.get("at"),
                                  project=args.get("project"), base=base)
        if name == "get_code":
            return brandapi.as_code(db, caller, args["client"], args["format"], version=args.get("version"),
                                    at=args.get("at"), project=args.get("project"))
        if name == "list_versions":
            return {"versions": brandapi.versions(db, caller, args["client"])}
        if name == "compare_versions":
            return brandapi.compare(db, caller, args["client"], args["from"], args["to"])
        if name == "check_contrast":
            return checks.pair(brandset.color_value(args["foreground"], "foreground"),
                               brandset.color_value(args["background"], "background"))
        if name == "audit":
            return brandapi.audit(db, caller, args["client"], [str(c) for c in args.get("colors") or []],
                                  project=args.get("project"), css=args.get("css"))
        if name == "propose_version":
            return brandapi.propose(db, caller, args["client"], label=args["label"], data=args["data"],
                                    note=args.get("note") or "", source=args.get("based_on"))
    raise KeyError(name)


def call_tool(caller: Caller, name: Any, args: Any, base: str) -> dict[str, Any]:
    tool = BY_NAME.get(name) if isinstance(name, str) else None
    if tool is None or not _visible(caller, tool):
        # A tool above the token's level is as unknown as one that does not exist.
        return _tool_result(f"No tool called {name!r}.", failed=True)
    if not isinstance(args, dict):
        return _tool_result("'arguments' must be an object.", failed=True)
    problem = _check(tool["inputSchema"], args)
    if problem:
        return _tool_result(problem, failed=True)
    logger.info("MCP tool called tool=%s token_id=%s", name, caller.token_id)
    try:
        return _tool_result(_run(caller, name, args, base))
    except brandapi.ApiError as exc:
        where = exc.values.get("where")
        return _tool_result(f"{exc.text}" + (f" ({where})" if where else ""), failed=True)
    except brandset.SetError as exc:
        return _tool_result(f"{exc.where}: {exc.text}", failed=True)


def _error(message_id: Any, code: int, text: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": text}}


def handle(message: Any, caller: Caller, base: str) -> dict[str, Any] | None:
    """One JSON-RPC message: its answer, or None for a notification."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        return _error(message.get("id") if isinstance(message, dict) else None, -32600, "Invalid request.")
    method = message["method"]
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    if "id" not in message:
        return None
    message_id = message["id"]
    if method == "initialize":
        asked = params.get("protocolVersion")
        version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return {"jsonrpc": "2.0", "id": message_id, "result": {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "nexbrand", "version": __version__},
            "instructions": INSTRUCTIONS,
        }}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": message_id, "result": {}}
    if method == "tools/list":
        tools = [{"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"],
                  "annotations": {"readOnlyHint": t["level"] == "read", "destructiveHint": False}}
                 for t in TOOLS if _visible(caller, t)]
        return {"jsonrpc": "2.0", "id": message_id, "result": {"tools": tools}}
    if method == "tools/call":
        return {"jsonrpc": "2.0", "id": message_id,
                "result": call_tool(caller, params.get("name"), params.get("arguments", {}), base)}
    return _error(message_id, -32601, "Method not found.")


def _refuse(status: int, code: str, text: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse({"detail": {"code": code, "message": text}}, status_code=status, headers=headers)


@router.post("/api/mcp", summary="MCP (JSON-RPC over HTTP) with an API token in Authorization: Bearer")
async def endpoint(request: Request) -> Response:
    if request.headers.get("origin"):
        return _refuse(403, "origin_refused", "MCP is not for web pages.")
    asked = request.headers.get("mcp-protocol-version")
    if asked is not None and asked not in PROTOCOL_VERSIONS:
        return _refuse(400, "protocol_version", "This MCP protocol version is not spoken here.")
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header[:7].lower() == "bearer " else None
    with SessionLocal() as db:
        if not apitokens.allowed(db):
            return _refuse(401, "api_off", "The operator has not switched API tokens on.")
        caller = apitokens.authenticate(db, token)
        base = settings_service.public_url(db) or str(request.base_url).rstrip("/")
    if caller is None:
        return _refuse(401, "token_invalid", "No valid API token.")
    if not apitokens.brake(caller.token_id):
        return _refuse(429, "slow_down", "Too many requests with this token. Wait a minute.", {"Retry-After": "60"})
    logs.set_actor(caller.account.name)
    try:
        message = json.loads(await request.body())
    except (ValueError, UnicodeDecodeError, RecursionError):
        return JSONResponse(_error(None, -32700, "Parse error."), status_code=400)
    answer = await run_in_threadpool(handle, message, caller, base)
    if answer is None:
        return Response(status_code=202)
    return JSONResponse(answer)


@router.get("/api/mcp", include_in_schema=False)
def no_stream() -> Response:
    # No server-sent stream: every answer comes with its request.
    return Response(status_code=405, headers={"Allow": "POST"})
