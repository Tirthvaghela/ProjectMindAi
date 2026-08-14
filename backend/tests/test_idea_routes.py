"""Tests for routes/ideas.py — the idea-scoped mirror of routes/projects.py's
synopsis/roadmap/milestones and routes/search.py's skill-gap/team-builder/
timeline-predict, plus an idea-scoped chat mirroring
POST /project/<id>/chat (see test_assistant_routes.py for that route's own
tests, which this file's chat tests deliberately parallel).

None of these routes touch Mongo (a generated idea is never persisted — see
nlp/ai_assistant.py's module docstring) — the `client` fixture is used only
for its Flask test client, not for any data it seeds.
"""

from __future__ import annotations

import pytest

from nlp import ai_assistant

IDEA = {
    "name": "Smart Campus Notes",
    "domain": "Artificial Intelligence",
    "difficulty": "Intermediate",
    "duration_weeks": 10,
    "technologies": ["Python", "FastAPI", "React"],
    "problem": "Students lose track of scattered lecture notes.",
    "solution": "A unifying, searchable notes hub with AI summaries.",
}


# --- /api/idea/skill-gap ------------------------------------------------------


def test_idea_skill_gap_compares_known_skills_against_technologies(client):
    resp = client.post(
        "/api/idea/skill-gap",
        json={**IDEA, "skills": ["Python", "Something Else Entirely"]},
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert "Python" in data["skills_you_have"]
    assert data["project_id"] is None


def test_idea_skill_gap_requires_a_name(client):
    resp = client.post("/api/idea/skill-gap", json={"skills": ["Python"]})
    assert resp.status_code == 400


def test_idea_skill_gap_rejects_non_string_skills(client):
    resp = client.post("/api/idea/skill-gap", json={**IDEA, "skills": [1, 2]})
    assert resp.status_code == 400


# --- /api/idea/synopsis / roadmap / milestones --------------------------------


def test_idea_synopsis_is_grounded_in_problem_and_solution(client):
    resp = client.post("/api/idea/synopsis", json=IDEA)
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["title"] == IDEA["name"]
    assert "scattered lecture notes" in data["abstract"]


def test_idea_roadmap_matches_the_ideas_duration(client):
    resp = client.post("/api/idea/roadmap", json=IDEA)
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["total_weeks"] == IDEA["duration_weeks"]
    assert sum(p["weeks"] for p in data["phases"]) == IDEA["duration_weeks"]


def test_idea_milestones_derive_from_the_same_roadmap(client):
    resp = client.post("/api/idea/milestones", json=IDEA)
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["total_weeks"] == IDEA["duration_weeks"]
    assert len(data["milestones"]) > 0


def test_idea_roadmap_requires_a_name(client):
    resp = client.post("/api/idea/roadmap", json={"domain": "Artificial Intelligence"})
    assert resp.status_code == 400


# --- /api/idea/timeline -------------------------------------------------------


def test_idea_timeline_personalises_against_team_size(client):
    solo = client.post("/api/idea/timeline", json={**IDEA, "team_size": 1}).get_json()["data"]
    team = client.post("/api/idea/timeline", json={**IDEA, "team_size": 5}).get_json()["data"]
    assert team["predicted_weeks"] <= solo["predicted_weeks"]


# --- /api/idea/team-builder ----------------------------------------------------


def test_idea_team_builder_assigns_a_role_per_member(client):
    resp = client.post(
        "/api/idea/team-builder",
        json={
            "domain": IDEA["domain"],
            "technologies": IDEA["technologies"],
            "members": [{"name": "Alex", "skills": ["Python", "TensorFlow"]}],
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    # A solo builder is still a fixed team of one — no third person is
    # coming, so Alex ends up owning every module rather than the response
    # reporting the rest as unfilled (see nlp/team_builder.py).
    assert len(data["assignments"]) == len(data["roles"])
    assert data["unfilled_roles"] == []
    assert all(a["member"] == "Alex" for a in data["assignments"])


def test_idea_team_builder_rejects_empty_members(client):
    resp = client.post("/api/idea/team-builder", json={"domain": IDEA["domain"], "members": []})
    assert resp.status_code == 400


def test_idea_team_builder_does_not_require_a_name(client):
    # Unlike the other idea routes, only `domain` actually drives the role
    # list — an idea's name is irrelevant to team-building.
    resp = client.post(
        "/api/idea/team-builder",
        json={"domain": IDEA["domain"], "members": [{"skills": ["Python"]}]},
    )
    assert resp.status_code == 200


# --- /api/idea/chat ------------------------------------------------------------
#
# Mirrors test_assistant_routes.py's POST /project/<id>/chat tests — same
# fake-Groq-completion pattern, just against an idea's own fields instead of
# a Mongo-backed project doc.


class _FakeMessage:
    def __init__(self, content=""):
        self.content = content


class _FakeChoice:
    def __init__(self, message):
        self.message = message


class _FakeCompletion:
    def __init__(self, message):
        self.choices = [_FakeChoice(message)]


def _text_completion(content):
    return _FakeCompletion(_FakeMessage(content=content))


@pytest.fixture(autouse=True)
def assistant_enabled(monkeypatch):
    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)


def test_idea_chat_grounds_replies_in_the_ideas_own_fields(client, monkeypatch):
    captured = {}

    def capture(**kwargs):
        captured["messages"] = kwargs["messages"]
        return _text_completion("Use FastAPI as the idea already does.")

    monkeypatch.setattr(ai_assistant, "_create_completion", capture)

    resp = client.post(
        "/api/idea/chat",
        json={"idea": IDEA, "message": "what backend framework should I use?"},
    )

    assert resp.status_code == 200
    assert resp.get_json()["data"]["reply"] == "Use FastAPI as the idea already does."
    system_message = captured["messages"][0]["content"]
    assert IDEA["name"] in system_message
    assert "FastAPI" in system_message


def test_idea_chat_requires_an_idea_object(client, monkeypatch):
    monkeypatch.setattr(ai_assistant, "_create_completion", lambda **_: _text_completion("hi"))
    resp = client.post("/api/idea/chat", json={"message": "hello"})
    assert resp.status_code == 400


def test_idea_chat_requires_a_message(client, monkeypatch):
    monkeypatch.setattr(ai_assistant, "_create_completion", lambda **_: _text_completion("hi"))
    resp = client.post("/api/idea/chat", json={"idea": IDEA})
    assert resp.status_code == 400


def test_idea_chat_returns_503_when_the_assistant_is_not_configured(client, monkeypatch):
    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", False)
    resp = client.post("/api/idea/chat", json={"idea": IDEA, "message": "hello"})
    assert resp.status_code == 503
    assert resp.get_json()["code"] == "LLM_UNAVAILABLE"


def test_idea_chat_returns_502_with_llm_error_code_on_an_unexpected_failure(client, monkeypatch):
    def boom(**_):
        raise RuntimeError("simulated provider/network failure")

    monkeypatch.setattr(ai_assistant, "_create_completion", boom)
    resp = client.post("/api/idea/chat", json={"idea": IDEA, "message": "hello"})

    assert resp.status_code == 502
    assert resp.get_json()["code"] == "LLM_ERROR"
