"""HTTP-level tests for routes/projects.py — browsing, filtering, and the
deterministic per-project generators (synopsis/roadmap/milestones) as
exposed over the API. The generators' own content correctness (phase
weighting, template selection, ...) is covered directly against
nlp/generator.py (test_generator.py); this only checks that the route wires
a project id to the right generator, maps a missing project to 404, and
returns the documented envelope.

Every route here does a direct `db.projects().find_one(...)`/`.find(...)`,
redirected to the throwaway `mongo_test_db` by the `client` fixture — so
every "known project" case seeds its own fixture project rather than
assuming anything about the real catalogue (contrast test_search_routes.py,
where two routes go through the in-memory retriever instead).
"""

from __future__ import annotations

import pytest

from db import client as db
from db.schema import DIFFICULTIES, DOMAINS

PROJECT = {
    "project_id": "pm-route-proj-001",
    "title": "Campus Ride Share Matcher",
    "description": "Matches students commuting similar routes for shared rides.",
    "domain": "Web Development",
    "difficulty": "Intermediate",
    "technologies": ["Python", "Flask", "React"],
    "skills": ["Flask", "React", "REST APIs"],
    "duration_weeks": 10,
}


@pytest.fixture
def seeded_project(mongo_test_db):
    db.projects().insert_one(dict(PROJECT))
    return PROJECT


# --- GET /api/projects -----------------------------------------------------


def test_list_projects_returns_the_documented_envelope(client, seeded_project):
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    body = resp.get_json()
    for key in ("data", "total", "limit", "skip", "has_more", "filters"):
        assert key in body
    assert body["total"] == 1
    assert [p["project_id"] for p in body["data"]] == [PROJECT["project_id"]]


def test_list_projects_never_leaks_the_mongo_id(client, seeded_project):
    resp = client.get("/api/projects")
    assert "_id" not in resp.get_json()["data"][0]


def test_list_projects_filters_by_domain(client, seeded_project):
    db.projects().insert_one(
        {**PROJECT, "project_id": "pm-route-proj-002", "domain": "Blockchain"}
    )
    resp = client.get("/api/projects?domain=Blockchain")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["total"] == 1
    assert body["data"][0]["project_id"] == "pm-route-proj-002"


def test_list_projects_filters_by_technology_case_insensitively(client, seeded_project):
    resp = client.get("/api/projects?technologies=flask")
    assert resp.status_code == 200
    assert resp.get_json()["total"] == 1


def test_list_projects_technology_filter_is_exact_not_substring(client, seeded_project):
    """'Flask' must not match a project whose only tech is 'Flask-Limiter' —
    the route uses an anchored `^...$` regex specifically to avoid this."""
    db.projects().insert_one(
        {**PROJECT, "project_id": "pm-route-proj-003", "technologies": ["Flask-Limiter"]}
    )
    resp = client.get("/api/projects?technologies=Flask")
    assert resp.status_code == 200
    assert [p["project_id"] for p in resp.get_json()["data"]] == [PROJECT["project_id"]]


def test_list_projects_a_filter_matching_nothing_returns_an_empty_but_well_formed_result(client, seeded_project):
    resp = client.get("/api/projects?domain=Robotics")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["data"] == []
    assert body["total"] == 0
    assert body["has_more"] is False


def test_list_projects_respects_limit_and_skip(client, mongo_test_db):
    db.projects().insert_many(
        [{**PROJECT, "project_id": f"pm-route-proj-page-{i}", "title": f"Project {i}"} for i in range(5)]
    )
    resp = client.get("/api/projects?limit=2&skip=1")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["data"]) == 2
    assert body["limit"] == 2
    assert body["skip"] == 1
    assert body["total"] == 5
    assert body["has_more"] is True


# --- GET /api/project/<id> ---------------------------------------------------


def test_get_project_404s_for_an_unknown_project(client):
    resp = client.get("/api/project/does-not-exist")
    assert resp.status_code == 404


def test_get_project_returns_the_full_public_document(client, seeded_project):
    resp = client.get(f"/api/project/{PROJECT['project_id']}")
    assert resp.status_code == 200
    body = resp.get_json()["data"]
    assert body["title"] == PROJECT["title"]
    assert "_id" not in body


# --- GET /api/project/<id>/synopsis, /roadmap, /milestones -----------------


@pytest.mark.parametrize(
    ("path", "expected_keys"),
    [
        ("synopsis", {"abstract", "problem_statement", "objectives", "technology_stack"}),
        ("roadmap", {"phases"}),
        ("milestones", {"milestones"}),
    ],
)
def test_project_generator_routes_404_for_an_unknown_project(client, path, expected_keys):
    resp = client.get(f"/api/project/does-not-exist/{path}")
    assert resp.status_code == 404


@pytest.mark.parametrize(
    ("path", "expected_keys"),
    [
        ("synopsis", {"abstract", "problem_statement", "objectives", "technology_stack"}),
        ("roadmap", {"phases"}),
        ("milestones", {"milestones"}),
    ],
)
def test_project_generator_routes_succeed_for_a_seeded_project(client, seeded_project, path, expected_keys):
    resp = client.get(f"/api/project/{PROJECT['project_id']}/{path}")
    assert resp.status_code == 200
    body = resp.get_json()["data"]
    assert expected_keys <= set(body)


def test_milestones_agree_with_the_roadmaps_own_phases(client, seeded_project):
    """Regression guard for generator.py's own documented invariant —
    milestones are a running sum over the SAME roadmap's phases, never a
    second computation that could silently disagree with it: same phase
    names in the same order, and the last milestone's cumulative week lands
    exactly on the roadmap's total_weeks."""
    roadmap = client.get(f"/api/project/{PROJECT['project_id']}/roadmap").get_json()["data"]
    milestones = client.get(f"/api/project/{PROJECT['project_id']}/milestones").get_json()["data"]
    assert [p["phase"] for p in roadmap["phases"]] == [m["phase"] for m in milestones["milestones"]]
    assert milestones["milestones"][-1]["week"] == roadmap["total_weeks"]


# --- GET /api/filters -------------------------------------------------------


def test_filters_returns_the_full_domain_and_difficulty_sets_regardless_of_catalogue(client, mongo_test_db):
    """Domains/difficulties come from the schema (the full allowed set), not
    from whatever happens to be in the catalogue — even an empty catalogue
    should still offer every domain/difficulty as a filter option."""
    resp = client.get("/api/filters")
    assert resp.status_code == 200
    body = resp.get_json()["data"]
    assert set(body["domains"]) == set(DOMAINS)
    assert set(body["difficulties"]) == set(DIFFICULTIES)
    assert body["technologies"] == []


def test_filters_technologies_reflect_only_whats_actually_in_the_catalogue(client, seeded_project):
    resp = client.get("/api/filters")
    body = resp.get_json()["data"]
    assert set(PROJECT["technologies"]) <= set(body["technologies"])
    assert body["technologies"] == sorted(body["technologies"])
