"""The clean-up keeps every file a version or a review points at, and removes the rest after a day."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import Account, Media, utcnow
from app.services import cleanup, media_store, settings_service

from .test_brands import SET, SVG, make_client, upload


def _age(*ids: str) -> None:
    with SessionLocal() as db:
        for media_id in ids:
            db.get(Media, media_id).created_at = utcnow() - timedelta(hours=cleanup.ORPHAN_HOURS + 1)
        db.commit()


def _alive(media_id: str) -> bool:
    with SessionLocal() as db:
        return db.get(Media, media_id) is not None and media_store.path_of(media_id).is_file()


def test_files_in_versions_and_reviews_stay_the_rest_goes(client: TestClient, operator: Account, space: int) -> None:
    in_version = upload(client, space, "a.svg", SVG)
    in_review = upload(client, space, "b.svg", SVG + b" ")
    unused = upload(client, space, "c.svg", SVG + b"  ")
    fresh = upload(client, space, "d.svg", SVG + b"   ")
    logo = {"id": "main", "name": "Logo", "fg": "#000000", "ground": "#FFFFFF"}
    made = make_client(client, space, {**SET, "logos": [{**logo, "media": in_version}]})
    with SessionLocal() as db:
        settings_service.save(db, {"shares_allowed": True})
        db.commit()
    answer = client.post(f"/api/clients/{made['id']}/reviews", json={
        "version_id": made["versions"][0]["id"], "label": "1.0",
        "variants": [{"id": "a", "label": "A", "data": {**SET, "logos": [{**logo, "media": in_review}]}}]})
    assert answer.status_code == 201
    _age(in_version, in_review, unused)
    cleanup.run_once()
    assert _alive(in_version) and _alive(in_review) and _alive(fresh)
    assert not _alive(unused)


def test_a_client_long_in_the_bin_goes_with_its_versions(client: TestClient, operator: Account, space: int) -> None:
    from app.models import BrandVersion, Client

    made = make_client(client, space)
    client.delete(f"/api/clients/{made['id']}")
    with SessionLocal() as db:
        db.get(Client, made["id"]).deleted_at = utcnow() - timedelta(days=cleanup.BIN_DAYS + 1)
        db.commit()
    cleanup.run_once()
    with SessionLocal() as db:
        assert db.get(Client, made["id"]) is None
        assert db.query(BrandVersion).count() == 0
