"""Tests for the assistant's tool layer (nlp/chat_tools.py).

Scoped to the tools that are pure Mongo lookups or deterministic generators —
no hybrid-search/embedding-index dependency (nlp/recommend.py's retriever),
so these never need a built index and stay fast and hermetic, same spirit as
test_teams.py/test_auth.py using mongo_test_db against a throwaway database.
"""

from __future__ import annotations

import pytest

from db import client as db
from nlp import chat_tools

DOC = {
    "project_id": "pm-chat-001",
    "title": "AI-Powered Medical Diagnosis Assistant",
    "description": "A clinical decision support system that predicts likely conditions.",
    "domain": "Artificial Intelligence",
    "difficulty": "Advanced",
    "technologies": ["Python", "scikit-learn", "Flask"],
    "skills": ["Supervised learning", "REST API development"],
    "duration_weeks": 12,
}

OTHER_DOC = {
    "project_id": "pm-chat-002",
    "title": "Campus Event Recommender",
    "description": "Suggests campus events to students based on their interests.",
    "domain": "Machine Learning",
    "difficulty": "Beginner",
    "technologies": ["Python", "Flask", "MongoDB"],
    "skills": ["Recommendation systems"],
    "duration_weeks": 6,
}


@pytest.fixture
def project(mongo_test_db):
    db.projects().insert_one(dict(DOC))
    return DOC


@pytest.fixture
def two_projects(mongo_test_db):
    db.projects().insert_many([dict(DOC), dict(OTHER_DOC)])
    return DOC, OTHER_DOC


# --- get_project_details -----------------------------------------------------


def test_get_project_details_returns_real_fields(project):
    result = chat_tools.get_project_details(project["project_id"])
    assert result["title"] == DOC["title"]
    assert result["technologies"] == DOC["technologies"]


def test_get_project_details_reports_missing_project(mongo_test_db):
    result = chat_tools.get_project_details("does-not-exist")
    assert "error" in result


# --- generate_roadmap / generate_synopsis ------------------------------------


def test_generate_roadmap_sums_to_project_duration(project):
    roadmap = chat_tools.generate_roadmap(project["project_id"])
    assert sum(p["weeks"] for p in roadmap["phases"]) == roadmap["total_weeks"] == DOC["duration_weeks"]


def test_generate_roadmap_missing_project_is_an_error_not_a_crash(mongo_test_db):
    result = chat_tools.generate_roadmap("does-not-exist")
    assert "error" in result


def test_generate_synopsis_uses_the_projects_own_technologies(project):
    synopsis = chat_tools.generate_synopsis(project["project_id"])
    assert synopsis["technology_stack"] == DOC["technologies"]


# --- generate_milestones ------------------------------------------------------


def test_generate_milestones_returns_a_milestones_block(project):
    result, block = chat_tools.generate_milestones(project["project_id"])
    assert result["milestones"]
    assert block["type"] == "milestones"
    assert block["milestones"] == result["milestones"]


def test_generate_milestones_missing_project_returns_error_and_no_block(mongo_test_db):
    result, block = chat_tools.generate_milestones("does-not-exist")
    assert "error" in result
    assert block is None


def test_generate_milestones_last_week_matches_project_duration(project):
    result, _block = chat_tools.generate_milestones(project["project_id"])
    assert result["milestones"][-1]["week"] == DOC["duration_weeks"]


# --- predict_timeline ---------------------------------------------------------


def test_predict_timeline_defaults_to_solo(project):
    result, block = chat_tools.predict_timeline(project["project_id"])
    assert result["team_size"] == 1
    assert block["type"] == "timeline"


def test_predict_timeline_missing_project_returns_error_and_no_block(mongo_test_db):
    result, block = chat_tools.predict_timeline("does-not-exist")
    assert "error" in result
    assert block is None


def test_predict_timeline_clamps_team_size_to_a_sane_range(project):
    result, _block = chat_tools.predict_timeline(project["project_id"], team_size=999)
    assert result["team_size"] <= 20


# --- get_learning_path ---------------------------------------------------------


def test_get_learning_path_returns_a_bundle_per_skill():
    result, block = chat_tools.get_learning_path(["Python", "React"])
    assert [s["skill"] for s in result["skills"]] == ["Python", "React"]
    assert block["type"] == "learning_path"


def test_get_learning_path_rejects_an_empty_list():
    result, block = chat_tools.get_learning_path([])
    assert "error" in result
    assert block is None


# --- select_project ------------------------------------------------------------


def test_select_project_returns_a_project_selected_block(project):
    result, block = chat_tools.select_project(project["project_id"])
    assert result["project_id"] == project["project_id"]
    assert block == {"type": "project_selected", "project": result}


def test_select_project_missing_project_returns_error_and_no_block(mongo_test_db):
    result, block = chat_tools.select_project("does-not-exist")
    assert "error" in result
    assert block is None


# --- select_idea -----------------------------------------------------------------
# The idea-context mirror of select_project (see nlp/ai_assistant.py's
# active-idea note) — unlike select_project, this never touches Mongo: a
# generated idea has no catalogue record, so the model supplies its own
# current fields, same as refine_project_idea already does.


def test_select_idea_returns_an_idea_selected_block():
    result, block = chat_tools.select_idea(
        id="idea-2",
        name="Smart Campus Notes",
        problem="Students lose track of scattered lecture notes.",
        solution="A unifying, searchable notes hub with AI summaries.",
        unique_point="Cross-references notes against the syllabus automatically.",
        technologies=["Python", "FastAPI", "React"],
        domain="Artificial Intelligence",
        difficulty="Intermediate",
        duration_weeks=10,
    )
    assert result["id"] == "idea-2"
    assert result["name"] == "Smart Campus Notes"
    assert result["duration_weeks"] == 10
    assert block == {"type": "idea_selected", "idea": result}


def test_select_idea_rejects_a_blank_name():
    result, block = chat_tools.select_idea(id="idea-1", name="   ")
    assert "error" in result
    assert block is None


def test_select_idea_defaults_a_missing_id():
    result, _block = chat_tools.select_idea(id=None, name="Untitled but real idea")
    assert result["id"] == "idea-1"


def test_select_idea_ignores_an_out_of_enum_domain_and_difficulty():
    result, _block = chat_tools.select_idea(
        id="idea-1", name="Some Idea", domain="Not A Real Domain", difficulty="Expert"
    )
    assert result["domain"] == ""
    assert result["difficulty"] == ""


def test_select_idea_ignores_a_non_numeric_duration():
    result, _block = chat_tools.select_idea(id="idea-1", name="Some Idea", duration_weeks="soon")
    assert result["duration_weeks"] is None


def test_select_idea_caps_technologies_at_six():
    result, _block = chat_tools.select_idea(
        id="idea-1",
        name="Some Idea",
        technologies=[f"tech-{i}" for i in range(10)],
    )
    assert len(result["technologies"]) == 6


# --- match_resume_projects ----------------------------------------------------
# Only the retriever-independent path (no known_skills) is exercised directly
# against the real function — the happy path mocks recommend.personalized_
# recommend wholesale, same spirit as tests/test_recommend.py mocking
# recommend.search to test personalized_recommend's own logic without a real
# embedding index. This keeps match_resume_projects's own card-building logic
# tested without ever needing the hybrid retriever this file otherwise avoids.


def test_match_resume_projects_rejects_empty_known_skills():
    result, block = chat_tools.match_resume_projects([])
    assert "error" in result
    assert block is None


def test_match_resume_projects_ignores_non_string_and_blank_skills():
    result, block = chat_tools.match_resume_projects([123, "  ", None])
    assert "error" in result
    assert block is None


def test_call_tool_dispatches_match_resume_projects_with_empty_skills_is_an_error_not_a_crash():
    result, block = chat_tools.call_tool("match_resume_projects", {"known_skills": []})
    assert "error" in result
    assert block is None


def test_match_resume_projects_builds_cards_from_personalized_recommend(monkeypatch):
    fake_rec = {
        "project_id": "pm-resume-1",
        "title": "Résumé-matched project",
        "domain": "Web Development",
        "difficulty": "Beginner",
        "duration_weeks": 4,
        "description": "A project matching real résumé skills.",
        "technologies": ["React"],
        "overall_score": 82.5,
        "matching_factors": ["Skill match: you already have React"],
        "skill_gap": {"skills_you_have": ["React"], "skills_to_learn": ["Node.js"]},
        "timeline": {"predicted_weeks": 4},
        "recommendation_reason": "Strong match because your résumé contains React.",
    }
    monkeypatch.setattr(chat_tools.recommend, "personalized_recommend", lambda **_: [fake_rec])

    result, block = chat_tools.match_resume_projects(["React"])

    assert result["count"] == 1
    assert result["projects"][0]["project_id"] == "pm-resume-1"
    assert result["projects"][0]["skills_to_learn"] == ["Node.js"]
    assert block["type"] == "project_recommendations"
    assert block["projects"][0]["match_score"] == 0.825


def test_match_resume_projects_reports_no_matches_without_crashing(monkeypatch):
    monkeypatch.setattr(chat_tools.recommend, "personalized_recommend", lambda **_: [])
    result, block = chat_tools.match_resume_projects(["Python"])
    assert result["count"] == 0
    assert block is None


# --- generated-idea planning (roadmap/timeline/milestones) -------------------
# All pure functions over a synthetic doc built from the idea's own fields —
# no Mongo lookup, no retriever — same reasoning as generate_roadmap's own
# tests not needing mongo_test_db once a doc is in hand.


def test_generate_idea_roadmap_is_grounded_in_the_ideas_own_technologies():
    roadmap = chat_tools.generate_idea_roadmap(
        "Smart Campus Notes", domain="Artificial Intelligence", duration_weeks=10,
        technologies=["Python", "FastAPI", "React"],
    )
    core_phase = next(p for p in roadmap["phases"] if p["phase"] == "Model Development & Training")
    assert core_phase["technologies"] == ["Python", "FastAPI", "React"]


def test_generate_idea_roadmap_defaults_duration_to_eight_weeks():
    roadmap = chat_tools.generate_idea_roadmap("Untitled Idea")
    assert roadmap["total_weeks"] == 8


def test_generate_idea_roadmap_ignores_an_out_of_enum_domain():
    roadmap = chat_tools.generate_idea_roadmap("Untitled Idea", domain="Not A Real Domain")
    phase_names = [p["phase"] for p in roadmap["phases"]]
    assert "Core Feature Development" in phase_names  # falls back to the default profile


def test_generate_idea_timeline_returns_a_timeline_block():
    result, block = chat_tools.generate_idea_timeline(
        "Smart Campus Notes", domain="Artificial Intelligence", difficulty="Intermediate",
        duration_weeks=10, team_size=2, experience_level="Beginner",
    )
    assert result["base_weeks"] == 10
    assert block["type"] == "timeline"
    assert block["predicted_weeks"] == result["predicted_weeks"]


def test_generate_idea_timeline_defaults_to_solo_with_no_team_size():
    result, _block = chat_tools.generate_idea_timeline("Untitled Idea", duration_weeks=6)
    assert result["team_size"] == 1


def test_generate_idea_milestones_returns_a_milestones_block():
    result, block = chat_tools.generate_idea_milestones(
        "Smart Campus Notes", domain="Artificial Intelligence", duration_weeks=10
    )
    assert block["type"] == "milestones"
    assert result["milestones"][-1]["week"] == 10


def test_generate_idea_milestones_agrees_with_generate_idea_roadmap():
    # Milestones for an idea must be derived from the same roadmap
    # generate_idea_roadmap returns, not a second computation that could drift.
    roadmap = chat_tools.generate_idea_roadmap("X", domain="Web Development", duration_weeks=9)
    milestones_result, _block = chat_tools.generate_idea_milestones("X", domain="Web Development", duration_weeks=9)
    assert [m["phase"] for m in milestones_result["milestones"]] == [p["phase"] for p in roadmap["phases"]]


# --- call_tool dispatch (reliability) --------------------------------------------
# RELIABILITY requirement: the assistant must never crash because the model
# requested an unexpected tool — see nlp/ai_assistant.py:general_reply, which
# relies on call_tool() always returning (result, block) rather than raising.


def test_call_tool_dispatches_select_idea_by_name():
    result, block = chat_tools.call_tool(
        "select_idea", {"id": "idea-3", "name": "Dispatch Test Idea"}
    )
    assert result["name"] == "Dispatch Test Idea"
    assert block["type"] == "idea_selected"


def test_call_tool_returns_an_error_for_an_unknown_tool_name():
    result, block = chat_tools.call_tool("this_tool_does_not_exist", {})
    assert "error" in result
    assert block is None


def test_call_tool_select_project_missing_id_argument_does_not_raise(mongo_test_db):
    result, block = chat_tools.call_tool("select_project", {})
    assert "error" in result
    assert block is None


def test_call_tool_compare_projects_with_too_few_ids_is_an_error_not_a_crash(two_projects):
    doc_a, _doc_b = two_projects
    result, block = chat_tools.call_tool("compare_projects", {"project_ids": [doc_a["project_id"]]})
    assert "error" in result
    assert block is None
