"""The Scope Analyzer: nlp/feasibility.py:analyze_scope(), plus its single
dual-mode chat_tools.py wrapper (chat_tools.analyze_scope — one tool for
both a catalogue project and a generated idea, kept as one schema rather
than a pair to protect Groq's tool-schema token budget; see that function's
own docstring).

analyze_scope() takes a plain project-shaped `doc` and calls no database/
retriever/LLM itself, so most of this file exercises it directly with
hand-built docs (same style test_feasibility.py uses for analyze_feasibility).
Every tier/field is checked against the real nlp/generator.py output it's
built from, never a hand-picked expected value, so a change to a domain
profile can't silently desync these tests from the engine.
"""

from __future__ import annotations

import pytest

from db import client as db
from nlp import chat_tools, feasibility, generator

CV_DOC = {
    "project_id": "cv1",
    "title": "Real-Time Face Recognition Attendance",
    "domain": "Computer Vision",
    "difficulty": "Advanced",
    "duration_weeks": 6,
    "technologies": ["Python", "OpenCV", "TensorFlow", "Flask"],
    "skills": ["Computer Vision", "Deep Learning", "Flask"],
    "description": "A real-time face recognition attendance system for classrooms.",
}

WEB_DOC = {
    "project_id": "web1",
    "title": "Simple Todo App",
    "domain": "Web Development",
    "difficulty": "Beginner",
    "duration_weeks": 4,
    "technologies": ["React", "Flask"],
    "skills": ["HTML", "CSS"],
    "description": "A simple todo list app.",
}


# --- tier partitioning: real domain data, never invented ---------------------


def test_tiers_together_cover_every_real_domain_module_exactly_once():
    profile = generator.domain_profile(CV_DOC["domain"])
    result = feasibility.analyze_scope(CV_DOC)
    combined = result["mvp"] + result["core"] + result["advanced"]
    assert combined == profile["modules"]


def test_tiers_preserve_the_domain_profiles_own_module_order():
    # MVP is a prefix, core the next slice, advanced the rest — never
    # reordered or reshuffled.
    profile = generator.domain_profile(WEB_DOC["domain"])
    result = feasibility.analyze_scope(WEB_DOC)
    n_mvp, n_core = len(result["mvp"]), len(result["core"])
    assert result["mvp"] == profile["modules"][:n_mvp]
    assert result["core"] == profile["modules"][n_mvp : n_mvp + n_core]
    assert result["advanced"] == profile["modules"][n_mvp + n_core :]


def test_every_tier_gets_at_least_one_module_for_a_typical_domain_profile():
    for domain in ("Computer Vision", "Web Development", "Internet of Things", "Blockchain"):
        result = feasibility.analyze_scope({**WEB_DOC, "domain": domain})
        assert result["mvp"], domain
        assert result["core"], domain
        assert result["advanced"], domain


def test_future_is_exactly_synopsis_fors_own_future_scope():
    expected = generator.synopsis_for(CV_DOC)["future_scope"]
    result = feasibility.analyze_scope(CV_DOC)
    assert result["future"] == expected
    assert result["out_of_scope"] == expected


def test_in_scope_is_every_tier_combined():
    result = feasibility.analyze_scope(CV_DOC)
    assert result["in_scope"] == result["mvp"] + result["core"] + result["advanced"]


def test_dependencies_are_the_projects_own_real_technologies():
    result = feasibility.analyze_scope(CV_DOC)
    assert result["dependencies"] == CV_DOC["technologies"]


def test_technical_constraints_reuse_the_same_domain_hints_feasibility_uses():
    profile = generator.domain_profile(CV_DOC["domain"])
    result = feasibility.analyze_scope(CV_DOC)
    assert profile["infra_hint"] in result["technical_constraints"]
    assert profile["dataset_hint"] in result["technical_constraints"]


# --- target_weeks: advisory only, never mutates the doc -----------------------


def test_no_reduction_without_a_target():
    result = feasibility.analyze_scope(CV_DOC)
    assert result["reduced_scope"] is None


def test_no_reduction_when_the_target_already_meets_the_baseline():
    result = feasibility.analyze_scope(CV_DOC, target_weeks=CV_DOC["duration_weeks"])
    assert result["reduced_scope"] is None


def test_reduction_triggers_when_the_target_is_tighter_than_the_baseline():
    result = feasibility.analyze_scope(CV_DOC, target_weeks=2)
    assert result["reduced_scope"] is not None
    assert result["reduced_scope"]["remove"] == result["advanced"]
    assert result["reduced_scope"]["keep"] == result["mvp"] + result["core"]


def test_reduction_reason_names_the_real_week_gap():
    result = feasibility.analyze_scope(CV_DOC, target_weeks=2)
    reason = result["reduced_scope"]["reason"]
    assert "2-week" in reason
    assert "4 weeks" in reason  # 6-week baseline - 2-week target
    assert "6-week" in reason


def test_reduction_does_not_mutate_the_input_doc():
    original = dict(CV_DOC)
    feasibility.analyze_scope(CV_DOC, target_weeks=1)
    assert CV_DOC == original


def test_reduction_with_no_advanced_modules_left_degrades_gracefully(monkeypatch):
    monkeypatch.setattr(
        generator,
        "domain_profile",
        lambda domain: {"core_phase": "X", "core_focus": "x", "modules": ["Only Module"], "infra_hint": "", "dataset_hint": ""},
    )
    result = feasibility.analyze_scope(CV_DOC, target_weeks=1)
    assert result["advanced"] == []
    assert result["reduced_scope"]["remove"] == []
    assert "no optional modules" in result["reduced_scope"]["reason"]


# --- works on a generated-idea doc, not just a catalogue project -------------


def test_works_on_a_synthetic_idea_doc_with_no_project_id():
    doc = generator.idea_doc("QuizWhiz", domain="Natural Language Processing", duration_weeks=6, technologies=["Python"])
    result = feasibility.analyze_scope(doc, target_weeks=2)
    assert result["project_id"] is None
    assert result["title"] == "QuizWhiz"
    assert result["reduced_scope"] is not None


# --- chat_tools.analyze_scope (dual-mode dispatch) ----------------------------


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


def test_analyze_scope_project_id_path_returns_a_scope_block(fake_projects):
    for_model, block = chat_tools.analyze_scope(project_id="web1")
    assert block["type"] == "scope"
    assert block["project_id"] == "web1"
    assert for_model["mvp"] == block["mvp"]


def test_analyze_scope_name_path_needs_no_db_lookup():
    for_model, block = chat_tools.analyze_scope(name="QuizWhiz", domain="Natural Language Processing", duration_weeks=6)
    assert block["type"] == "scope"
    assert block["project_id"] is None
    assert block["title"] == "QuizWhiz"


def test_analyze_scope_unknown_project_returns_an_error(fake_projects):
    for_model, block = chat_tools.analyze_scope(project_id="does-not-exist")
    assert "error" in for_model
    assert block is None


def test_analyze_scope_with_neither_project_id_nor_name_returns_an_error():
    for_model, block = chat_tools.analyze_scope()
    assert "error" in for_model
    assert block is None


def test_call_tool_dispatches_analyze_scope(fake_projects):
    for_model, block = chat_tools.call_tool("analyze_scope", {"project_id": "web1", "target_weeks": 1})
    assert block["type"] == "scope"
    assert block["reduced_scope"] is not None


def test_scope_tool_is_registered_in_tool_schemas():
    names = {t["function"]["name"] for t in chat_tools.TOOL_SCHEMAS}
    assert "analyze_scope" in names
    # Consolidated as ONE dual-mode tool, not a project/idea pair, per the
    # explicit schema-size constraint this feature was built under.
    assert "analyze_project_scope" not in names
    assert "analyze_idea_scope" not in names
