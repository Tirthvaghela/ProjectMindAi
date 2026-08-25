"""The Resource Estimator: nlp/feasibility.py:estimate_resources(), plus its
single dual-mode chat_tools.py wrapper (chat_tools.estimate_project_resources
— one tool for both a catalogue project and a generated idea, same lean
pattern as chat_tools.analyze_scope; see that function's own docstring for
why this is one tool rather than a project/idea pair).

estimate_resources() takes a plain project-shaped `doc` and calls no
database/retriever/LLM itself, so most of this file exercises it directly
with hand-built docs (same style test_feasibility.py/test_scope.py use).
Every section is checked against the real nlp/generator.py or
nlp/team_builder.py output it's built from, never a hand-picked expected
value — and every cost figure is checked for being a labelled estimate, per
the explicit "never invent exact costs" requirement.
"""

from __future__ import annotations

import pytest

from db import client as db
from nlp import chat_tools, feasibility, generator, team_builder

CV_DOC = {
    "project_id": "cv1",
    "title": "Real-Time Face Recognition Attendance",
    "domain": "Computer Vision",
    "difficulty": "Advanced",
    "duration_weeks": 6,
    "technologies": ["Python", "OpenCV", "TensorFlow", "Flask", "MongoDB"],
    "skills": ["Computer Vision", "Deep Learning", "Flask"],
    "description": "A real-time face recognition attendance system for classrooms.",
}

WEB_DOC = {
    "project_id": "web1",
    "title": "Simple Todo App",
    "domain": "Web Development",
    "difficulty": "Beginner",
    "duration_weeks": 4,
    "technologies": ["React", "Flask", "PostgreSQL"],
    "skills": ["HTML", "CSS"],
    "description": "A simple todo list app.",
}


# --- team: reuses the exact same team-size helper Feasibility uses -----------


def test_recommended_team_size_matches_feasibilitys_own_team_guidance():
    # Cross-checked against analyze_feasibility's own team factor rather than
    # a hand-picked number, so the two features can never silently disagree
    # about how big a team this domain needs.
    feasibility_team = feasibility.analyze_feasibility(CV_DOC)["team"]
    resources_team = feasibility.estimate_resources(CV_DOC)["team"]
    assert resources_team["recommended_size"] == feasibility_team["recommended_size"]


def test_given_team_size_is_echoed_back():
    result = feasibility.estimate_resources(WEB_DOC, team_size=3)
    assert result["team"]["given_size"] == 3


def test_roles_are_the_domains_own_real_modules_with_real_categories():
    profile = generator.domain_profile(CV_DOC["domain"])
    result = feasibility.estimate_resources(CV_DOC)
    roles = result["team"]["roles"]
    assert [r["role"] for r in roles] == profile["modules"]
    for r in roles:
        assert r["category"] == team_builder.category_for(r["role"])


def test_required_skills_are_the_projects_own_real_skills():
    result = feasibility.estimate_resources(CV_DOC)
    assert result["team"]["required_skills"] == CV_DOC["skills"]


# --- technology stack: real technologies, never invented ---------------------


def test_technology_stack_only_contains_the_projects_own_technologies():
    result = feasibility.estimate_resources(CV_DOC)
    all_bucketed = [t for bucket in result["technology"].values() for t in bucket]
    for tech in all_bucketed:
        assert tech in CV_DOC["technologies"]


def test_technology_stack_buckets_known_technologies_correctly():
    result = feasibility.estimate_resources(CV_DOC)["technology"]
    assert "TensorFlow" in result["ai_ml"]
    assert "OpenCV" in result["ai_ml"]
    assert "Flask" in result["backend"]
    assert "MongoDB" in result["database"]


def test_technology_stack_has_all_five_expected_keys_even_when_empty():
    result = feasibility.estimate_resources({**WEB_DOC, "technologies": []})["technology"]
    assert set(result.keys()) == {"frontend", "backend", "database", "ai_ml", "infrastructure"}
    assert all(bucket == [] for bucket in result.values())


# --- resources: dataset/compute reuse the same domain hints, never invented --


def test_dataset_and_compute_notes_reuse_the_same_domain_profile_hints():
    profile = generator.domain_profile(CV_DOC["domain"])
    result = feasibility.estimate_resources(CV_DOC)["resources"]
    assert result["dataset"]["note"] == profile["dataset_hint"]
    assert result["compute"]["note"] == profile["infra_hint"]
    assert result["dataset"]["is_estimate"] is True
    assert result["compute"]["is_estimate"] is True


def test_storage_note_is_present_and_flagged_as_an_estimate():
    result = feasibility.estimate_resources(CV_DOC)["resources"]
    assert result["storage"]["note"]
    assert result["storage"]["is_estimate"] is True


def test_apis_and_external_services_come_only_from_real_technologies():
    doc = {**CV_DOC, "technologies": ["Python", "Google Maps API", "AWS S3", "Flask"]}
    result = feasibility.estimate_resources(doc)["resources"]
    assert result["apis"] == ["Google Maps API"]
    assert result["external_services"] == ["AWS S3"]


def test_apis_and_external_services_are_empty_when_nothing_matches():
    result = feasibility.estimate_resources(WEB_DOC)["resources"]
    assert result["apis"] == []
    assert result["external_services"] == []


# --- cost: never an exact invented figure, always labelled -------------------


def test_cost_is_always_flagged_as_an_estimate():
    result = feasibility.estimate_resources(CV_DOC)["cost"]
    assert result["is_estimate"] is True


def test_cost_notes_never_contain_a_specific_non_zero_dollar_figure():
    # The only numeral allowed in any cost note is "0" (a free tier) — a
    # concrete non-zero price would mean the LLM's own words leaked into a
    # deterministic field, or that this function invented a number nothing
    # backs. Every digit in every note must be part of "$0" or "0" itself.
    import re

    result = feasibility.estimate_resources(CV_DOC)["cost"]
    for key in ("development", "infrastructure", "api", "hosting"):
        digits = re.findall(r"\d+", result[key])
        assert all(d == "0" for d in digits), f"{key} note contains a non-zero figure: {result[key]!r}"


def test_free_alternatives_are_grounded_in_this_projects_own_data():
    # GPU-needing domain (Computer Vision) + MongoDB in its technologies ->
    # both grounded suggestions should appear; a Web Development project
    # with no MongoDB should not get either.
    cv_alternatives = feasibility.estimate_resources(CV_DOC)["cost"]["free_alternatives"]
    assert any("GPU" in a for a in cv_alternatives)
    assert any("MongoDB Atlas" in a for a in cv_alternatives)

    web_alternatives = feasibility.estimate_resources(WEB_DOC)["cost"]["free_alternatives"]
    assert not any("GPU" in a for a in web_alternatives)
    assert not any("MongoDB Atlas" in a for a in web_alternatives)


# --- works on a generated-idea doc, not just a catalogue project -------------


def test_works_on_a_synthetic_idea_doc_with_no_project_id():
    doc = generator.idea_doc("QuizWhiz", domain="Natural Language Processing", duration_weeks=6, technologies=["Python", "Flask"])
    result = feasibility.estimate_resources(doc)
    assert result["project_id"] is None
    assert result["title"] == "QuizWhiz"
    assert result["team"]["recommended_size"] >= 1


# --- chat_tools.estimate_project_resources (dual-mode dispatch) -------------


class _FakeProjects:
    def __init__(self, docs):
        self._docs = docs

    def find_one(self, query, *_args, **_kwargs):
        return self._docs.get(query.get("project_id"))


@pytest.fixture
def fake_projects(monkeypatch):
    docs = {"cv1": CV_DOC, "web1": WEB_DOC}
    fake = _FakeProjects(docs)
    monkeypatch.setattr(db, "projects", lambda: fake)
    return fake


def test_estimate_resources_project_id_path_returns_a_resources_block(fake_projects):
    for_model, block = chat_tools.estimate_project_resources(project_id="web1")
    assert block["type"] == "resources"
    assert block["project_id"] == "web1"
    assert for_model["team"] == block["team"]


def test_estimate_resources_name_path_needs_no_db_lookup():
    for_model, block = chat_tools.estimate_project_resources(name="QuizWhiz", domain="Natural Language Processing", duration_weeks=6)
    assert block["type"] == "resources"
    assert block["project_id"] is None
    assert block["title"] == "QuizWhiz"


def test_estimate_resources_unknown_project_returns_an_error(fake_projects):
    for_model, block = chat_tools.estimate_project_resources(project_id="does-not-exist")
    assert "error" in for_model
    assert block is None


def test_estimate_resources_with_neither_project_id_nor_name_returns_an_error():
    for_model, block = chat_tools.estimate_project_resources()
    assert "error" in for_model
    assert block is None


def test_call_tool_dispatches_estimate_project_resources(fake_projects):
    for_model, block = chat_tools.call_tool("estimate_project_resources", {"project_id": "web1", "team_size": 2})
    assert block["type"] == "resources"
    assert block["team"]["given_size"] == 2


def test_resources_tool_is_registered_in_tool_schemas():
    names = {t["function"]["name"] for t in chat_tools.TOOL_SCHEMAS}
    assert "estimate_project_resources" in names
    assert "estimate_project_resources_idea" not in names
    # The schema-size budget itself is asserted once, in
    # test_feasibility.py:test_tool_schemas_stay_within_the_pre_trim_token_budget.
