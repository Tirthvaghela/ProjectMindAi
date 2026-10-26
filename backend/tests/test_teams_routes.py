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


# --- GET /api/teams/<id>/roles (Suggested roles) ---------------------------


def test_roles_requires_sign_in(client):
    assert client.get("/api/teams/any-team/roles").status_code == 401


def test_roles_for_a_team_the_caller_is_not_in_is_404(client):
    owner = _signup(client, "roles-owner@example.com")
    team = client.post("/api/teams", json={"idea": IDEA, "name": "T"}, headers=_auth(owner)).get_json()["data"]
    outsider = _signup(client, "roles-outsider@example.com")

    res = client.get(f"/api/teams/{team['team_id']}/roles", headers=_auth(outsider))
    assert res.status_code == 404


def test_roles_with_no_skills_recorded_reports_it_instead_of_inventing_roles(client):
    token = _signup(client, "roles-noskills@example.com")
    team = client.post("/api/teams", json={"idea": IDEA, "name": "T"}, headers=_auth(token)).get_json()["data"]

    res = client.get(f"/api/teams/{team['team_id']}/roles", headers=_auth(token))

    assert res.status_code == 200
    data = res.get_json()["data"]
    assert data["assignments"] == []
    assert [u["reason"] for u in data["unassigned_members"]] == ["no_skills"]
    assert data["unfilled_roles"] == data["roles"]


def test_roles_assigns_one_role_per_real_member_from_their_recorded_skills(client):
    owner = _signup(client, "roles-a@example.com")
    team = client.post("/api/teams", json={"idea": IDEA, "name": "T"}, headers=_auth(owner)).get_json()["data"]
    client.post(f"/api/teams/{team['team_id']}/skills", json={"skills": ["Python", "TensorFlow"]}, headers=_auth(owner))

    res = client.get(f"/api/teams/{team['team_id']}/roles", headers=_auth(owner))

    data = res.get_json()["data"]
    assert len(data["assignments"]) == 1  # a solo owner is never given every role
    assert data["assignments"][0]["category"] == "Data / ML"
    assert data["assignments"][0]["fallback"] is False
    assert len(data["unfilled_roles"]) == len(data["roles"]) - 1
