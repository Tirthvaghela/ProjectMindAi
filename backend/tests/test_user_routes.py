"""Tests for the persistence contract routes/user.py exposes over HTTP —
favourite-project persistence (by project id, never a duplicated project
document), search-history persistence, and feedback capture. All three are
device-scoped (see routes/helpers.py:device_id), the same anonymous identity
model conversations use, so device isolation is the recurring property under
test here, alongside the catalogue-is-the-source-of-truth contract for
favourites (store an id, resolve the project from the catalogue at read time).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from db import client as db
from tests.conftest import ensure_indexes_for_test

DEVICE_A = "device-favs-aaaa"
DEVICE_B = "device-favs-bbbb"

PROJECT_1 = {
    "project_id": "pm-fav-001",
    "title": "Campus Event Recommender",
    "description": "Suggests campus events to students based on their interests.",
    "domain": "Machine Learning",
    "difficulty": "Beginner",
    "technologies": ["Python", "Flask"],
    "skills": ["Recommendation systems"],
    "duration_weeks": 6,
}

PROJECT_2 = {
    "project_id": "pm-fav-002",
    "title": "Smart Irrigation Controller",
    "description": "IoT controller that waters crops based on soil moisture readings.",
    "domain": "Internet of Things",
    "difficulty": "Intermediate",
    "technologies": ["Python", "MQTT"],
    "skills": ["Embedded systems"],
    "duration_weeks": 8,
}


def _hdr(device: str) -> dict[str, str]:
    return {"X-Device-Id": device}


@pytest.fixture
def two_projects(mongo_test_db):
    db.projects().insert_many([dict(PROJECT_1), dict(PROJECT_2)])
    return PROJECT_1, PROJECT_2


# --- favourites --------------------------------------------------------------


def test_add_favorite_requires_a_project_id(client):
    resp = client.post("/api/favorite", json={}, headers=_hdr(DEVICE_A))
    assert resp.status_code == 400


def test_add_favorite_404s_for_an_unknown_project(client):
    resp = client.post("/api/favorite", json={"project_id": "does-not-exist"}, headers=_hdr(DEVICE_A))
    assert resp.status_code == 404


def test_add_favorite_then_list_returns_the_full_catalogue_project(client, two_projects):
    project_1, _ = two_projects
    resp = client.post("/api/favorite", json={"project_id": project_1["project_id"]}, headers=_hdr(DEVICE_A))
    assert resp.status_code == 200
    assert resp.get_json()["data"] == {"project_id": project_1["project_id"], "favorited": True, "created": True}

    listed = client.get("/api/favorites", headers=_hdr(DEVICE_A)).get_json()["data"]
    assert len(listed) == 1
    # The full project document, not just the id — same fields the catalogue holds.
    assert listed[0]["title"] == project_1["title"]
    assert listed[0]["technologies"] == project_1["technologies"]


def test_favoriting_the_same_project_twice_is_idempotent(client, two_projects):
    # This behaviour is enforced by the uq_device_project unique index (see
    # routes/user.py:add_favorite's DuplicateKeyError handling), which a
    # fresh mongo_test_db doesn't have yet — build it before relying on it.
    ensure_indexes_for_test()
    project_1, _ = two_projects
    client.post("/api/favorite", json={"project_id": project_1["project_id"]}, headers=_hdr(DEVICE_A))
    second = client.post("/api/favorite", json={"project_id": project_1["project_id"]}, headers=_hdr(DEVICE_A))

    assert second.status_code == 200
    assert second.get_json()["data"]["created"] is False

    listed = client.get("/api/favorites", headers=_hdr(DEVICE_A)).get_json()["data"]
    assert len(listed) == 1  # not duplicated


def test_remove_favorite_removes_it(client, two_projects):
    project_1, _ = two_projects
    client.post("/api/favorite", json={"project_id": project_1["project_id"]}, headers=_hdr(DEVICE_A))

    resp = client.delete(f"/api/favorite/{project_1['project_id']}", headers=_hdr(DEVICE_A))
    assert resp.status_code == 200
    assert resp.get_json()["data"]["removed"] == 1
    assert client.get("/api/favorites", headers=_hdr(DEVICE_A)).get_json()["data"] == []


def test_removing_a_favorite_that_was_never_added_is_harmless(client, two_projects):
    project_1, _ = two_projects
    resp = client.delete(f"/api/favorite/{project_1['project_id']}", headers=_hdr(DEVICE_A))
    assert resp.status_code == 200
    assert resp.get_json()["data"]["removed"] == 0


def test_favorites_are_isolated_between_devices(client, two_projects):
    project_1, project_2 = two_projects
    client.post("/api/favorite", json={"project_id": project_1["project_id"]}, headers=_hdr(DEVICE_A))
    client.post("/api/favorite", json={"project_id": project_2["project_id"]}, headers=_hdr(DEVICE_B))

    a_favs = {p["project_id"] for p in client.get("/api/favorites", headers=_hdr(DEVICE_A)).get_json()["data"]}
    b_favs = {p["project_id"] for p in client.get("/api/favorites", headers=_hdr(DEVICE_B)).get_json()["data"]}
    assert a_favs == {project_1["project_id"]}
    assert b_favs == {project_2["project_id"]}


def test_list_favorites_skips_a_project_deleted_after_favoriting(client, two_projects):
    """The catalogue is the one source of truth for project data — a
    favourite only ever stores the id, so a project removed from the
    catalogue after being favourited must disappear from the list instead of
    crashing it or resurrecting stale, duplicated data."""
    project_1, project_2 = two_projects
    client.post("/api/favorite", json={"project_id": project_1["project_id"]}, headers=_hdr(DEVICE_A))
    client.post("/api/favorite", json={"project_id": project_2["project_id"]}, headers=_hdr(DEVICE_A))

    db.projects().delete_one({"project_id": project_1["project_id"]})

    listed = client.get("/api/favorites", headers=_hdr(DEVICE_A)).get_json()["data"]
    assert [p["project_id"] for p in listed] == [project_2["project_id"]]


def test_list_favorites_returns_most_recently_favorited_first(client, two_projects):
    project_1, project_2 = two_projects
    client.post("/api/favorite", json={"project_id": project_1["project_id"]}, headers=_hdr(DEVICE_A))
    client.post("/api/favorite", json={"project_id": project_2["project_id"]}, headers=_hdr(DEVICE_A))

    listed = client.get("/api/favorites", headers=_hdr(DEVICE_A)).get_json()["data"]
    assert [p["project_id"] for p in listed] == [project_2["project_id"], project_1["project_id"]]


# --- search history ------------------------------------------------------


def _seed_history(device: str, queries: list[str]) -> None:
    now = datetime.now(timezone.utc)
    db.history().insert_many(
        [
            {"device_id": device, "query": query, "created_at": now - timedelta(minutes=len(queries) - i)}
            for i, query in enumerate(queries)
        ]
    )


def test_list_history_returns_only_this_devices_entries_most_recent_first(client):
    _seed_history(DEVICE_A, ["nlp projects", "computer vision"])
    _seed_history(DEVICE_B, ["blockchain"])

    listed = client.get("/api/history", headers=_hdr(DEVICE_A)).get_json()["data"]
    assert [row["query"] for row in listed] == ["computer vision", "nlp projects"]


def test_clear_history_removes_only_this_devices_entries(client):
    _seed_history(DEVICE_A, ["nlp projects"])
    _seed_history(DEVICE_B, ["blockchain"])

    resp = client.delete("/api/history", headers=_hdr(DEVICE_A))
    assert resp.status_code == 200
    assert resp.get_json()["data"]["deleted"] == 1

    assert client.get("/api/history", headers=_hdr(DEVICE_A)).get_json()["data"] == []
    assert len(client.get("/api/history", headers=_hdr(DEVICE_B)).get_json()["data"]) == 1


# --- feedback --------------------------------------------------------------


def test_feedback_requires_a_message_or_a_rating(client):
    resp = client.post("/api/feedback", json={}, headers=_hdr(DEVICE_A))
    assert resp.status_code == 400


def test_feedback_rejects_an_out_of_range_rating(client):
    resp = client.post("/api/feedback", json={"rating": 7}, headers=_hdr(DEVICE_A))
    assert resp.status_code == 400


def test_feedback_accepts_a_rating_with_no_message(client):
    resp = client.post("/api/feedback", json={"rating": 4}, headers=_hdr(DEVICE_A))
    assert resp.status_code == 201
    assert resp.get_json()["data"]["received"] is True
