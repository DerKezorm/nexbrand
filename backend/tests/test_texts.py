"""The page's sentences for the server's error codes: every code the server sends has one in both shipped languages,
every sentence belongs to a code something still sends, and no API message is the code with its underscores gone.

The codes are read from the source: ``error("code", ...)``, the typed errors (``AiError("code")`` and the like), the
middleware's and MCP's refusals and the sign-in redirects (``?error=code``). A code built at run time is named in
``BUILT`` with where it comes from.

The shared sign-in module (``app/vendor/nexoidc``) is checked where it is made (bauplaene/oidc) and copied unchanged:
its codes have their sentences in its own wording files (``oidc.error.*``, ``oidc.formError.*``), the same in every
nex app, and the house rules for words below are nexbrand's, not the module's.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import Account

from .conftest import make_account, new_client, new_group

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "backend" / "app"
FRONTEND = ROOT / "frontend" / "src"

#: Codes put together at run time or passed on from the directory service, with their source.
BUILT = {
    # services/suite.py: f"{what}_twice", f"{what}_unknown" for person, client, team
    "person_twice", "client_twice", "team_twice", "person_unknown", "client_unknown", "team_unknown",
    # services/suite.py: the directory service's own code, passed on when it refuses to pair (409)
    "app_still_connected", "app_not_reachable",
}

#: The fixed codes of the shared sign-in module: their sentences come with it (``frontend/src/vendor/nexoidc``).
MODULE = ROOT / "frontend" / "src" / "vendor" / "nexoidc"

#: Typed errors that carry an error code to the page (``SetError`` names a field, ``FetchError`` a collect problem).
TYPED = "Ai|Api|Account|Avatar|Backup|Brand|Locale|Mail|Media|Notice|Oidc|Rights|Space|Suite|Team|Token"
RAISED = re.compile(
    rf"""(?:\berror|(?:{TYPED})Error|AppRefusal|NameTaken|\brefuse|_to_login|_to_account|_refuse\(\d+,|_text\([^)]*?,)"""
    r"""\(?\s*"([a-z][a-z0-9_]+)\"""",
)


def _own(folder: Path, pattern: str = "*") -> list[Path]:
    """The app's own files, without the shared module copied in (``vendor``)."""
    return sorted(path for path in folder.rglob(pattern) if "vendor" not in path.parts)


def _sources(folder: Path, suffixes: tuple[str, ...]) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in _own(folder)
        if path.suffix in suffixes and ".test." not in path.name and "i18n" not in path.parts
    )


def module_codes() -> set[str]:
    """The codes with a sentence in the shared module's wording, in both languages."""
    found: set[str] | None = None
    for language in ("de", "en"):
        tree = json.loads((MODULE / f"oidc.{language}.json").read_text(encoding="utf-8"))["oidc"]
        codes = set(tree["error"]) | set(tree["formError"])
        found = codes if found is None else found & codes
    return found or set()


def server_codes() -> set[str]:
    return set(RAISED.findall(_sources(APP, (".py",)))) | BUILT


def texts(language: str) -> dict[str, str]:
    return json.loads((FRONTEND / "i18n" / f"{language}.json").read_text(encoding="utf-8"))["errors"]


def test_the_scan_finds_the_codes_it_should() -> None:
    codes = server_codes()
    # One of each way in: error(), a typed error, a refusal of the middleware, of MCP, a sign-in redirect, _text().
    assert {"not_found", "ai_not_on", "too_large", "token_invalid", "suite_no_account", "invalid_sector"} <= codes
    assert {"oidc_no_account", "slug_taken", "oidc_only_account"} <= module_codes()


@pytest.mark.parametrize("language", ["de", "en"])
def test_every_code_the_server_sends_has_a_sentence(language: str) -> None:
    assert sorted(server_codes() - set(texts(language)) - module_codes()) == []


def test_every_sentence_belongs_to_a_code_still_used() -> None:
    # Sent: a quoted literal anywhere in the server (a default argument, a returned code, a table of codes) or a code
    # the page makes itself (``'network'``).
    backend, frontend = _sources(APP, (".py",)), _sources(FRONTEND, (".ts", ".tsx"))
    unused = [code for code in texts("de") if code not in server_codes() and f'"{code}"' not in backend
              and f"'{code}'" not in frontend]
    # The module's codes speak with its own sentences; one of nexbrand's own beside it would never be shown.
    unused += sorted(set(texts("de")) & module_codes())
    assert unused == []


def test_no_api_message_is_the_code_spelt_out() -> None:
    source = _sources(APP, (".py",))
    assert ".code.replace(" not in source
    from app.services import ai, avatars

    for module in (ai, avatars):
        assert module.MESSAGES, module.__name__
        for code, text in module.MESSAGES.items():
            assert text.endswith(".") and text[0].isupper() and text.lower().rstrip(".") != code.replace("_", " ")
    raised = set(re.findall(r'AiError\(\s*"([a-z_]+)"', source)) | set(re.findall(r'AvatarError\(\s*"([a-z_]+)"', source))
    assert sorted(raised - set(ai.MESSAGES) - set(avatars.MESSAGES)) == []


def _values(tree: object) -> list[str]:
    if isinstance(tree, dict):
        return [text for value in tree.values() for text in _values(value)]
    if isinstance(tree, list):
        return [text for value in tree for text in _values(value)]
    return [tree] if isinstance(tree, str) else []


def _strings(source: str) -> list[tuple[int, str]]:
    """Every piece of text in Python source, with its line: plain strings, docstrings, and the literal parts of f- and
    t-strings (since Python 3.12 the tokenizer hands those out in pieces, not as one string)."""
    return [(node.lineno, node.value) for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Constant) and isinstance(node.value, str)]


def test_the_strings_of_the_server_include_f_strings() -> None:
    found = [text for _, text in _strings('x = f"A {a} is in the bin."\n"""Doc."""\ny = "plain"\n')]
    assert sorted(found) == [" is in the bin.", "A ", "Doc.", "plain"]


def test_english_says_trash_where_german_says_papierkorb() -> None:
    """The family says "trash": the page, what's new, the server's sentences and the API's own
    descriptions. Keys, routes and fields named ``bin`` stay: the directory service reads them."""
    bin_word = re.compile(r"\bbins?\b", re.IGNORECASE)
    found = []
    for path in (FRONTEND / "i18n" / "en.json", FRONTEND / "i18n" / "whatsnew" / "en.json"):
        found += [text for text in _values(json.loads(path.read_text(encoding="utf-8"))) if bin_word.search(text)]
    for path in (ROOT / "README.md", ROOT / "docs" / "api.md"):
        text = path.read_text(encoding="utf-8").replace(".venv/bin", "")
        found += [f"{path.name}: {line.strip()}" for line in text.splitlines() if bin_word.search(line)]
    files = strings = 0
    for path in _own(APP, "*.py"):
        pieces = _strings(path.read_text(encoding="utf-8"))
        files, strings = files + 1, strings + len(pieces)
        found += [f"{path.name}:{line}" for line, text in pieces if bin_word.search(text)]
    # A floor: the guard read the server, not an empty folder that passes.
    assert files >= 40 and strings >= 2000, (files, strings)
    # The guard sees what it should: the German word is there, and so are the keys it leaves alone.
    assert "Papierkorb" in (FRONTEND / "i18n" / "de.json").read_text(encoding="utf-8")
    assert '"binEmpty": "The trash is empty."' in (FRONTEND / "i18n" / "en.json").read_text(encoding="utf-8")
    assert found == []


def test_the_server_speaks_english_not_german_word_for_word() -> None:
    """As ``used.test.ts`` for the page: enter, create and contain, not give, make and hold. Every
    string a program or the log can show counts, f-strings included; of the docstrings only those of routes, which
    FastAPI shows in the API description."""
    stiff = re.compile(r"\bGive (a|the)\b|\bMake a new\b|\bholds\b|\bmak(e|es|ing) (a |an |its own |their own |read-only )?"
                       r"(clients?|accounts?|tokens?|drafts?|pages?|links?)\b|\b(is|are) made (there|here|in nexsuite)\b",
                       re.IGNORECASE)
    found = []
    files = strings = 0
    for path in _own(APP, "*.py"):
        files += 1
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docs = {id(node.body[0].value) for node in ast.walk(tree)
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body
                and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)
                and not _is_route(node)}
        shown = [node for node in ast.walk(tree)
                 if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs]
        strings += len(shown)
        found += [f"{path.name}:{node.lineno}" for node in shown if stiff.search(node.value)]
    assert stiff.search("The archive holds it.") and not stiff.search("Make an operator")
    # A floor: the guard read the server, not an empty folder that passes.
    assert files >= 40 and strings >= 2000, (files, strings)
    assert found == []


def _is_route(node: ast.AST) -> bool:
    """A function under ``@router.get(…)`` and the like: FastAPI shows its docstring in the API description."""
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
        isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
        and d.func.attr in {"get", "post", "put", "patch", "delete"} for d in node.decorator_list)


def test_no_other_app_speaks_in_the_texts() -> None:
    found = []
    for language in ("de", "en"):
        raw = (FRONTEND / "i18n" / f"{language}.json").read_text(encoding="utf-8")
        found += re.findall(r"notes\.example\.com|wie in nexlore|as in nexlore|nextrmnl|Tresor|Leinwand|vault", raw)
        found += re.findall(r"wie in nexlore|as in nexlore", (FRONTEND / "i18n" / "whatsnew" / f"{language}.json").read_text(encoding="utf-8"))
    assert found == []


def test_the_api_says_a_sentence_for_a_picture_and_for_ai(client: TestClient, operator: Account) -> None:
    refused = client.put("/api/auth/avatar", content=b"not a picture").json()["detail"]
    assert refused["code"] == "avatar_not_a_picture"
    assert refused["message"] == "That is not a picture nexbrand takes (JPEG, PNG, WebP, GIF, HEIC or AVIF)."
    off = client.post("/api/ai/directions", json={"brief": "a warm bakery"}).json()["detail"]
    assert off["code"] in {"ai_off", "ai_not_on"} and off["message"].endswith(".") and " " in off["message"]
    assert off["message"].lower().rstrip(".") != off["code"].replace("_", " ")


def test_a_file_that_is_not_there_answers_like_every_not_found(client: TestClient) -> None:
    for path in ("/assets/index-gone.js", "/no/such/route"):
        answer = client.get(path)
        if answer.status_code == 404:
            assert answer.json() == {"detail": {"code": "not_found", "message": "Not found."}}, path


def test_a_notice_about_the_reader_says_you_and_names_people_by_their_display_name(
    client: TestClient, operator: Account
) -> None:
    anna, ben = make_account("anna"), make_account("ben")
    with SessionLocal() as db:
        for person, shown in ((anna, "Anna Brandt"), (ben, "Ben Ott")):
            row = db.get(Account, person.id)
            assert row is not None
            row.display_name = shown
        db.commit()
    with new_client(anna) as browser:
        hers = new_group(browser, "Workshop")
    assert client.put(f"/api/spaces/{hers}/members/ben", json={"role": "read"}).status_code == 200
    with new_client(ben) as browser:
        [notice] = browser.get("/api/notices").json()
        assert (notice["subject"], notice["mine"]) == ("Ben Ott", True)
    with new_client(anna) as browser:
        [notice] = browser.get("/api/notices").json()
        assert (notice["subject"], notice["mine"]) == ("Ben Ott", False)


def test_the_api_description_names_nexsuite_only_where_the_coupling_is() -> None:
    """What every instance shows (the API description, with ``NEXBRAND_API_DOCS``) says "the directory service" for the coupling
    routes only: an instance that never couples has no reason to know the name."""
    from app.main import app

    spec = app.openapi()
    named = sorted(path for path, operations in spec["paths"].items()
                   if "nexsuite" in json.dumps(operations).lower() and not path.startswith("/api/suite"))
    assert named == []
    assert any(path.startswith("/api/suite") and "nexsuite" in json.dumps(ops).lower()
               for path, ops in spec["paths"].items()), "the test still looks at something"


def test_the_readme_and_the_docs_do_not_name_nexsuite() -> None:
    files = [ROOT / "README.md", ROOT / "SECURITY.md", *sorted((ROOT / "docs").glob("*.md"))]
    assert len(files) >= 3
    assert [path.name for path in files if "nexsuite" in path.read_text(encoding="utf-8").lower()] == []
