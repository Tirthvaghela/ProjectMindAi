"""HTTP-level tests for POST /api/teams' project_id-vs-idea branching —
everything else about teams (join, roles, messages, membership) is already
covered at the service level in test_teams.py; this exercises the one route
that now accepts two different shapes of "what is this team for" over the
real Flask route, the way test_auth_routes.py does for auth.
"""

from __future__ import annotations

from db import client as db

IDEA = {
    "name": "Smart Campus Notes",
    "domain": "Artificial Intelligence",
    "difficulty": "Intermediate",
    "duration_weeks": 10,
    "technologies": ["Python", "FastAPI"],
    "problem": "Students lose track of scattered lecture notes.",
    "solution": "A unifying, searchable notes hub with AI summaries.",
}


def _signup(client, email="teamcreator@example.com"):
    res = client.post("/api/auth/signup", json={"email": email, "password": "correcthorse1", "name": "Creator"})
    assert res.status_code == 201, res.get_json()
    return res.get_json()["token"]


def _auth(token):
    return {"X-Auth-Token": token}


def test_create_team_with_a_project_id_still_works(client):
    db.projects().insert_one({"project_id": "pm-route-test", "title": "Route Test Project"})
    token = _signup(client)

    res = client.post("/api/teams", json={"project_id": "pm-route-test", "name": "My Team"}, headers=_auth(token))

    assert res.status_code == 201
    data = res.get_json()["data"]
    assert data["project_id"] == "pm-route-test"


def test_create_team_with_an_idea_works(client):
    token = _signup(client)

    res = client.post("/api/teams", json={"idea": IDEA, "name": "My Team"}, headers=_auth(token))

    assert res.status_code == 201
    data = res.get_json()["data"]
    assert data["project_id"] is None
    assert data["idea"]["name"] == IDEA["name"]
    assert data["project"]["title"] == IDEA["name"]


def test_create_team_rejects_neither_project_id_nor_idea(client):
    token = _signup(client)
    res = client.post("/api/teams", json={"name": "My Team"}, headers=_auth(token))
    assert res.status_code == 400


def test_create_team_rejects_both_project_id_and_idea(client):
    db.projects().insert_one({"project_id": "pm-route-test-2", "title": "Route Test Project 2"})
    token = _signup(client)
    res = client.post(
        "/api/teams",
        json={"project_id": "pm-route-test-2", "idea": IDEA, "name": "My Team"},
        headers=_auth(token),
    )
    assert res.status_code == 400


def test_create_team_rejects_a_non_object_idea(client):
    token = _signup(client)
    res = client.post("/api/teams", json={"idea": "not an object", "name": "My Team"}, headers=_auth(token))
    assert res.status_code == 400


def test_create_team_requires_sign_in(client):
    res = client.post("/api/teams", json={"idea": IDEA, "name": "My Team"})
    assert res.status_code == 401
