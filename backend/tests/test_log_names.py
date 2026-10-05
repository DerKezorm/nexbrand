"""A person's name in the log stands under a key (``name=anna``, ``by=anna``), never as free text: only so does a
rename (B21, ``logs.rename_actor``) reach it. Read from the code: every call to a logger, under whatever name it goes
(``logger``, ``log = logger``, ``logging.getLogger(...)``), every helper that hands a parameter on to one (``refuse``
in the sign-in), and every way of putting a value into a text (``%s``, an f-string, ``"…" % …``, ``.format``), with the
``.name`` or ``.display_name`` of any object but those known to be no person, also through a variable (``who =
row.name``) or a choice (``row.name if row else ""``).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from app.services import logs

LEVELS = {"debug", "info", "warning", "error", "exception", "critical", "log"}
#: ``.name`` of these is no person: a table, a column, a file, a folder, a language file, a client, a team …
THINGS = {"table", "column", "path", "folder_path", "os", "client", "space", "team", "project", "version", "locale",
          "file", "media", "found", "font", "logo", "step", "row_space", "exc", "type(exc)", "settings"}
THINGS_IN = {("locales.py", "target")}
KEYS = tuple(f"{key}=" for key in logs.PERSON_KEYS)


def _texts(first: Any, rest: list[Any]) -> list[tuple[str, Any]]:
    """Each value a message text takes, with the text before it: from ``%s`` and the arguments after it, from an
    f-string, from ``"…" % (…)`` and from ``"…".format(…)``."""
    if isinstance(first, ast.JoinedStr):
        out, text = [], ""
        for part in first.values:
            if isinstance(part, ast.Constant):
                text += str(part.value)
            elif isinstance(part, ast.FormattedValue):
                out.append((text, part.value))
                text += "{}"
        return out
    if isinstance(first, ast.BinOp) and isinstance(first.op, ast.Mod) and isinstance(first.left, ast.Constant):
        text = str(first.left.value)
        values = first.right.elts if isinstance(first.right, ast.Tuple) else [first.right]
        return [(text[:m.start()], value) for m, value in zip(re.finditer(r"%[sdr]", text), values, strict=False)]
    if (isinstance(first, ast.Call) and isinstance(first.func, ast.Attribute) and first.func.attr == "format"
            and isinstance(first.func.value, ast.Constant)):
        text = str(first.func.value.value)
        named = {keyword.arg: keyword.value for keyword in first.keywords}
        out, index = [], 0
        for m in re.finditer(r"\{([A-Za-z_0-9]*)[^{}]*\}", text):
            field = m.group(1)
            if field.isdigit():
                value = first.args[int(field)] if int(field) < len(first.args) else None
            elif field:
                value = named.get(field)
            else:
                value = first.args[index] if index < len(first.args) else None
                index += 1
            if value is not None:
                out.append((text[:m.start()], value))
        return out
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        text = first.value
        return [(text[:m.start()], value) for m, value in zip(re.finditer(r"%[sdr]", text), rest, strict=False)]
    return []


def _person(value: Any, assigned: dict[str, Any], where: str, depth: int = 0) -> bool:
    """Whether ``value`` is a person's name: ``x.name``/``x.display_name`` of something not known to be a thing, also
    through a variable assigned in the same function, a choice, ``str(…)`` or ``(… or "")``."""
    if depth > 5:
        return False
    if isinstance(value, ast.Attribute) and value.attr in ("name", "display_name"):
        receiver = ast.unparse(value.value)
        return receiver not in THINGS and (where, receiver) not in THINGS_IN
    if isinstance(value, ast.IfExp):
        return any(_person(part, assigned, where, depth + 1) for part in (value.body, value.orelse))
    if isinstance(value, ast.BoolOp):
        return any(_person(part, assigned, where, depth + 1) for part in value.values)
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in ("str", "repr") \
            and value.args:
        return _person(value.args[0], assigned, where, depth + 1)
    if isinstance(value, ast.Name) and value.id in assigned:
        return _person(assigned[value.id], assigned, where, depth + 1)
    return False


def _loggers(tree: ast.AST) -> set[str]:
    """The names a logger goes by in a module: ``logger``, and whatever is assigned ``logging.getLogger(...)`` or
    another logger name."""
    names = {"logger", "logging"}
    for _ in range(3):
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                value = node.value
                if (isinstance(value, ast.Name) and value.id in names) or (
                        isinstance(value, ast.Call) and ast.unparse(value.func) == "logging.getLogger"):
                    names.add(node.targets[0].id)
    return names


def _is_log_call(node: Any, loggers: set[str]) -> bool:
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in LEVELS):
        return False
    receiver = node.func.value
    if isinstance(receiver, ast.Name):
        return receiver.id in loggers
    return isinstance(receiver, ast.Call) and ast.unparse(receiver.func) == "logging.getLogger"


def _wrappers(tree: ast.AST, loggers: set[str]) -> dict[str, list[int]]:
    """Functions that hand one of their parameters on to a logger: name and the places of those parameters."""
    found: dict[str, list[int]] = {}
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        params = [arg.arg for arg in function.args.args]
        handed = set()
        for node in ast.walk(function):
            if _is_log_call(node, loggers):
                for arg in node.args:
                    if isinstance(arg, ast.Name) and arg.id in params:
                        handed.add(params.index(arg.id))
        if handed:
            found[function.name] = sorted(handed)
    return found


def offences(source: str, where: str = "x.py") -> list[str]:
    tree = ast.parse(source)
    loggers = _loggers(tree)
    wrappers = _wrappers(tree, loggers)
    wrong: list[str] = []
    functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)]
    for scope in [tree, *functions]:
        assigned: dict[str, Any] = {}
        body = scope.body
        for statement in ast.walk(ast.Module(body=body, type_ignores=[])):
            if isinstance(statement, ast.Assign) and len(statement.targets) == 1 \
                    and isinstance(statement.targets[0], ast.Name):
                assigned[statement.targets[0].id] = statement.value
        for node in ast.walk(ast.Module(body=body, type_ignores=[])):
            messages: list[tuple[Any, list[Any]]] = []
            if _is_log_call(node, loggers) and node.args:
                messages.append((node.args[0], node.args[1:]))
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in wrappers:
                for place in wrappers[node.func.id]:
                    if place < len(node.args):
                        messages.append((node.args[place], []))
            for first, rest in messages:
                for before, value in _texts(first, rest):
                    if not _person(value, assigned, where):
                        continue
                    # The record of a rename keeps both names as they were (from=, to=), on purpose.
                    if before.endswith(("from=", "to=")) and "moved" in before:
                        continue
                    if not before.endswith(KEYS):
                        wrong.append(f"{where}:{node.lineno}: {before}…")
    return sorted(set(wrong))


def test_every_log_line_names_a_person_under_a_key() -> None:
    wrong = []
    for path in sorted(Path("app").rglob("*.py")):
        wrong += offences(path.read_text(encoding="utf-8"), path.name)
    assert not wrong, "\n".join(wrong)


def test_the_guard_reads_every_way_of_writing_a_line() -> None:
    """The guard above, against lines it must and must not object to."""
    bad = [
        'logger.info("Account %s linked", row.name)',
        'logger.info(f"Account {db.get(A, 1).name} linked")',
        'logger.info("Account %s linked" % (who.name,))',
        'logger.info("Account %s linked" % who.name)',
        'logger.info("Account {} linked by {by}".format(x.name, by=y.name))',
        'logger.info("Account {0} linked".format(x.name))',
        'logger.info("Signed in as %s", row.display_name)',
        'logger.info("Token of %s", owner.name if owner else "")',
        'logger.info("Token of %s", str(owner.name or ""))',
        'log = logger\nlog.warning("Account %s", row.name)',
        'import logging\nlogging.getLogger("x").info("Account %s", row.name)',
        'import logging\nother = logging.getLogger("x")\nother.info("Account %s", row.name)',
        'def f(row):\n    who = row.name\n    logger.info("Account %s", who)',
        ('def g(account):\n    def refuse(code, reason):\n        logger.warning("refused (%s)", reason)\n'
         '    refuse("x", f"account {account.name} is blocked")'),
    ]
    for source in bad:
        assert offences(source), source
    good = [
        'logger.info("Signed in name=%s", account.name)',
        'logger.info(f"Signed in by={row.name}")',
        'logger.info("Column %s added", column.name)',
        'logger.info("moved from=%s to=%s", old, holder.name)',
        ('def g(account):\n    def refuse(code, reason):\n        logger.warning("refused (%s)", reason)\n'
         '    refuse("x", f"blocked name={account.name}")'),
    ]
    for source in good:
        assert not offences(source), source
