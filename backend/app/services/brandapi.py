"""What programs and AI may ask of nexbrand, once for both ways in: ``/api/v1`` (``routers/v1.py``) and MCP
(``routers/mcp.py``). Every function takes the caller of a token and goes through the same rights as the interface.

What leaves here is the design set as a page outside sees it (``brandset.for_public``): fonts kept in the house by
name only. Files travel by an address under ``/api/v1/files``, which asks for the token again.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import READ, WRITE, BrandVersion, Client, Media, Project, Space
from . import brands, brandset, checks, rights, tokens
from .apitokens import Caller


class ApiError(Exception):
    def __init__(self, code: str, text: str, status: int = 422, **values: Any) -> None:
        super().__init__(text)
        self.code = code
        self.text = text
        self.status = status
        self.values = values


def _client(db: Session, caller: Caller, client_id: str, need: str = READ) -> Client:
    try:
        return rights.client_for(db, caller.account, str(client_id), need)
    except rights.RightsError as exc:
        raise ApiError(exc.code, exc.text, exc.status) from exc


def _spaces(db: Session, caller: Caller) -> dict[int, str]:
    ids = rights.readable_ids(db, caller.account)
    if not ids:
        return {}
    return dict(db.execute(select(Space.id, Space.name).where(Space.id.in_(ids))).all())


def version_summary(row: BrandVersion) -> dict[str, Any]:
    return {"id": row.id, "label": row.label, "status": row.status, "valid_from": row.valid_from or None,
            "origin": row.origin, "author": row.author, "note": row.note}


def list_clients(db: Session, caller: Caller, search: str = "") -> list[dict[str, Any]]:
    spaces = _spaces(db, caller)
    if not spaces:
        return []
    query = select(Client).where(Client.space_id.in_(spaces), Client.deleted_at.is_(None)).order_by(Client.name)
    out = []
    needle = search.casefold().strip()
    for client in db.scalars(query):
        if needle and needle not in client.name.casefold() and needle not in client.sector.casefold():
            continue
        current = brands.current(db, client)
        projects = db.scalars(select(Project).where(Project.client_id == client.id).order_by(Project.name))
        out.append({
            "id": client.id, "name": client.name, "sector": client.sector, "space": spaces[client.space_id],
            "current_version": current.label if current else None,
            "colors": [c["hex"] for c in (current.data if current else {}).get("colors", [])][:12],
            "projects": [{"id": p.id, "name": p.name} for p in projects],
        })
    return out


def _chosen(
    db: Session, client: Client, *, version: str | None = None, at: str | None = None, project: str | None = None,
) -> tuple[BrandVersion, Project | None]:
    try:
        if project:
            found = _project(db, client, project)
            return brands.version_for(db, client, found.version_id), found
        if version:
            return _version(db, client, version), None
        row = brands.valid_on(db, client, at) if at else brands.current(db, client)
    except brands.BrandError as exc:
        raise ApiError(exc.code, exc.text, exc.status) from exc
    if row is None:
        drafts = brands.versions(db, client)
        if at or not drafts:
            raise ApiError("no_version", "No published version on that day." if at else "No version yet.", 404)
        row = drafts[0]
    return row, None


def _project(db: Session, client: Client, key: str) -> Project:
    """A project by its id or its name (an AI knows the name it was told)."""
    row = db.get(Project, key)
    if row is not None and row.client_id == client.id:
        return row
    needle = key.casefold().strip()
    for found in db.scalars(select(Project).where(Project.client_id == client.id)):
        if found.name.casefold() == needle:
            return found
    raise ApiError("not_found", "Not found.", 404)


def _version(db: Session, client: Client, key: str) -> BrandVersion:
    """A version by its id or its label."""
    row = db.get(BrandVersion, key)
    if row is not None and row.client_id == client.id:
        return row
    for found in brands.versions(db, client):
        if found.label.casefold() == key.casefold().strip():
            return found
    raise ApiError("not_found", "Not found.", 404)


def find_client(db: Session, caller: Caller, key: str, need: str = READ) -> Client:
    """A client by its id or, failing that, by its name among those the token may read."""
    row = db.get(Client, key)
    if row is not None:
        return _client(db, caller, key, need)
    needle = key.casefold().strip()
    spaces = _spaces(db, caller)
    matches = [c for c in db.scalars(select(Client).where(Client.space_id.in_(spaces), Client.deleted_at.is_(None)))
               if c.name.casefold() == needle] if spaces else []
    if len(matches) != 1:
        raise ApiError("not_found", "Not found.", 404)
    return _client(db, caller, matches[0].id, need)


def files_of(db: Session, data: dict[str, Any], base: str) -> dict[str, dict[str, Any]]:
    """What the files a design set names are, with an address each (only those a program may have)."""
    ids = brandset.media_of(data) - brandset.internal_media(data)
    if not ids:
        return {}
    rows = db.scalars(select(Media).where(Media.id.in_(ids)))
    return {row.id: {"name": row.name, "kind": row.kind, "size": row.size, "url": f"{base}/api/v1/files/{row.id}"}
            for row in rows}


def brand(
    db: Session, caller: Caller, client_key: str, *, version: str | None = None, at: str | None = None,
    project: str | None = None, base: str = "",
) -> dict[str, Any]:
    client = find_client(db, caller, client_key)
    row, chosen_project = _chosen(db, client, version=version, at=at, project=project)
    data = brandset.for_public(row.data)
    if chosen_project is not None:
        data["colors"] = brands.project_colors(row, chosen_project)
    return {
        "client": {"id": client.id, "name": client.name, "sector": client.sector},
        "project": {"id": chosen_project.id, "name": chosen_project.name} if chosen_project else None,
        "version": version_summary(row),
        "current": row.status == "published" and brands.current(db, client) is row,
        "design": data,
        "files": files_of(db, row.data, base),
        "checks": checks.check(row.data, data["colors"] if chosen_project else None),
    }


def versions(db: Session, caller: Caller, client_key: str) -> list[dict[str, Any]]:
    client = find_client(db, caller, client_key)
    return [version_summary(row) for row in brands.versions(db, client)]


def as_code(
    db: Session, caller: Caller, client_key: str, fmt: str, *, version: str | None = None, at: str | None = None,
    project: str | None = None,
) -> str:
    if fmt not in tokens.FORMATS:
        raise ApiError("invalid_input", "Formats: css, tailwind, scss, json.")
    client = find_client(db, caller, client_key)
    row, chosen_project = _chosen(db, client, version=version, at=at, project=project)
    color_list = brands.project_colors(row, chosen_project) if chosen_project else None
    title = f"{client.name}, {chosen_project.name}" if chosen_project else client.name
    return tokens.render(row.data, fmt, color_list=color_list, title=f"{title} {row.label}")


def compare(db: Session, caller: Caller, client_key: str, older: str, newer: str) -> dict[str, Any]:
    client = find_client(db, caller, client_key)
    a, b = _version(db, client, older), _version(db, client, newer)
    before = {c["name"].casefold(): c for c in a.data.get("colors", [])}
    after = {c["name"].casefold(): c for c in b.data.get("colors", [])}
    from . import colors

    changed = [{"name": after[k]["name"], "from": before[k]["hex"], "to": after[k]["hex"],
                "delta_e": round(colors.delta_e(before[k]["hex"], after[k]["hex"]), 2)}
               for k in after if k in before and before[k]["hex"] != after[k]["hex"]]
    fonts_a = {f["family"] for f in a.data.get("fonts", [])}
    fonts_b = {f["family"] for f in b.data.get("fonts", [])}
    return {
        "from": version_summary(a), "to": version_summary(b),
        "colors_changed": changed,
        "colors_added": [after[k] for k in after if k not in before],
        "colors_removed": [before[k] for k in before if k not in after],
        "fonts_added": sorted(fonts_b - fonts_a), "fonts_removed": sorted(fonts_a - fonts_b),
    }


def audit(
    db: Session, caller: Caller, client_key: str, found: list[str], *, project: str | None = None,
) -> dict[str, Any]:
    """Colour values found in code or on a page, against the design set: the same, nearly (a slip?), or foreign."""
    from . import colors

    client = find_client(db, caller, client_key)
    row, chosen_project = _chosen(db, client, project=project)
    palette = brands.project_colors(row, chosen_project) if chosen_project else row.data.get("colors", [])
    out = []
    for raw in found[:500]:
        try:
            value = brandset.color_value(raw, "value")
        except brandset.SetError:
            out.append({"value": raw, "verdict": "unreadable"})
            continue
        if not palette:
            out.append({"value": value, "verdict": "foreign"})
            continue
        nearest = min(palette, key=lambda c: colors.delta_e(c["hex"], value))
        d = colors.delta_e(nearest["hex"], value)
        verdict = "same" if d < 1 else "near" if d < 8 else "foreign"
        item = {"value": value, "verdict": verdict, "nearest": nearest["name"], "nearest_hex": nearest["hex"],
                "delta_e": round(d, 2)}
        out.append(item)
    return {"version": version_summary(row), "colors": out}


def propose(
    db: Session, caller: Caller, client_key: str, *, label: str, data: Any, note: str = "",
    source: str | None = None,
) -> dict[str, Any]:
    """A draft from outside (an AI writing back a redesign). Needs a ``draft`` token and the right to write; never
    publishes."""
    if caller.level != "draft":
        raise ApiError("level_too_low", "This token may only read.", 403)
    client = find_client(db, caller, client_key, WRITE)
    base = _version(db, client, source) if source else None
    merged: Any = data
    if base is not None and isinstance(data, dict):
        merged = {**base.data, **data}
    try:
        row = brands.create_version(db, caller.account, client, label=label, source=base, data=merged, note=note,
                                    origin="mcp", author=caller.name or caller.account.name)
    except brands.BrandError as exc:
        raise ApiError(exc.code, exc.text, exc.status, **exc.values) from exc
    return {"version": version_summary(row), "checks": checks.check(row.data)}
