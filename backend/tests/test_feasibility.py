"""The Feasibility Analyzer: nlp/feasibility.py:analyze_feasibility(), plus
its two chat_tools.py wrappers (analyze_project_feasibility for a catalogue
project, analyze_idea_feasibility for a generated idea).

analyze_feasibility() takes a plain project-shaped `doc` and calls no
database/retriever/LLM itself — it is pure and deterministic, so most of this
file exercises it directly with hand-built docs, no mocking required (same
style tests/test_timeline.py uses for nlp/timeline.py:predict()). The
chat_tools wrapper tests at the bottom cover only the lookup/dispatch glue,
reusing the same fake-Mongo pattern tests/test_evaluation_engine.py already
established for recommend_decision/compare_projects.
"""

from __future__ import annotations

import json

import pytest

from db import client as db
from nlp import chat_tools, feasibility, generator, recommend, team_builder

CV_DOC = {
    "project_id": "cv1",
    "title": "Real-Time Face Recognition Attendance",
    "domain": "Computer Vision",
    "difficulty": "Advanced",
    "duration_weeks": 6,
    "technologies": ["Python", "OpenCV", "TensorFlow", "Flask", "React", "MongoDB", "Docker"],
    "skills": ["Computer Vision", "Deep Learning", "Flask"],
    "description": "A real-time face recognition attendance system.",
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


# --- analyze_feasibility: overall shape / bounds ------------------------------


def test_feasibility_score_is_always_within_0_100():
    for doc in (CV_DOC, WEB_DOC):
        result = feasibility.analyze_feasibility(doc)
        assert 0 <= result["feasibility_score"] <= 100


def test_feasibility_score_needs_no_optional_arguments():
    # Smoke test: no known_skills/team_size/experience_level/target_weeks at
    # all — every optional factor should degrade to "unavailable", not crash.
    result = feasibility.analyze_feasibility(WEB_DOC)
    assert result["risk_level"] in ("Low", "Medium", "High")
    skill_factor = next(f for f in result["factors"] if f["factor"] == "Skill Fit")
    assert skill_factor["score"] is None


def test_risk_level_is_low_for_an_easy_well_matched_project():
    result = feasibility.analyze_feasibility(
        WEB_DOC, known_skills=["HTML", "CSS", "React", "Flask"], experience_level="Beginner", team_size=1
    )
    assert result["risk_level"] == "Low"


def test_risk_level_is_higher_for_a_hard_mismatched_project():
    result = feasibility.analyze_feasibility(
        CV_DOC, known_skills=[], experience_level="Beginner", team_size=1, target_weeks=2
    )
    assert result["risk_level"] in ("Medium", "High")


# --- skill fit -----------------------------------------------------------------


def test_skill_fit_is_unavailable_without_known_skills():
    result = feasibility.analyze_feasibility(WEB_DOC)
    skill_factor = next(f for f in result["factors"] if f["factor"] == "Skill Fit")
    assert skill_factor["score"] is None
    assert result["skills_you_have"] == []
    assert result["skills_to_learn"] == []


def test_skill_fit_matches_recommend_skill_gap_for_doc_exactly():
    # Same number recommend.skill_gap_for_doc() would give directly — never a
    # second computation.
    known = ["HTML"]
    expected = recommend.skill_gap_for_doc(WEB_DOC, known)

    result = feasibility.analyze_feasibility(WEB_DOC, known_skills=known)

    skill_factor = next(f for f in result["factors"] if f["factor"] == "Skill Fit")
    assert skill_factor["score"] == expected["readiness_percent"]
    assert result["skills_you_have"] == expected["skills_you_have"]
    assert result["skills_to_learn"] == expected["skills_to_learn"]


# --- timeline fit ----------------------------------------------------------


def test_timeline_fit_is_100_when_the_estimate_beats_the_target():
    result = feasibility.analyze_feasibility(WEB_DOC, target_weeks=52)
    timeline_factor = next(f for f in result["factors"] if f["factor"] == "Timeline Fit")
    assert timeline_factor["score"] == 100


def test_timeline_fit_drops_when_the_estimate_overruns_the_target():
    result = feasibility.analyze_feasibility(CV_DOC, target_weeks=1)
    timeline_factor = next(f for f in result["factors"] if f["factor"] == "Timeline Fit")
    assert timeline_factor["score"] < 100


def test_timeline_fit_falls_back_to_the_projects_own_baseline_without_a_target():
    # No target_weeks given — solo/no-experience estimate should equal the
    # doc's own duration_weeks closely, scoring near 100 on the baseline check.
    result = feasibility.analyze_feasibility(WEB_DOC)
    timeline_factor = next(f for f in result["factors"] if f["factor"] == "Timeline Fit")
    assert timeline_factor["score"] >= 90


# --- difficulty fit (shared with recommend.difficulty_fit) -------------------


def test_difficulty_fit_matches_recommend_difficulty_fit_exactly():
    expected_score, expected_note = recommend.difficulty_fit(CV_DOC["difficulty"], "Beginner")

    result = feasibility.analyze_feasibility(CV_DOC, experience_level="Beginner")

    difficulty_factor = next(f for f in result["factors"] if f["factor"] == "Difficulty Fit")
    assert difficulty_factor["score"] == expected_score
    assert difficulty_factor["note"] == expected_note


def test_difficulty_fit_is_unavailable_without_experience_level():
    result = feasibility.analyze_feasibility(CV_DOC)
    difficulty_factor = next(f for f in result["factors"] if f["factor"] == "Difficulty Fit")
    assert difficulty_factor["score"] is None


# --- technical complexity ------------------------------------------------------


def test_complexity_increases_with_more_technologies_at_the_same_difficulty():
    lean = {**WEB_DOC, "technologies": ["React"]}
    heavy = {**WEB_DOC, "technologies": ["React", "Flask", "MongoDB", "Docker", "Redis", "GraphQL"]}

    lean_score = feasibility.analyze_feasibility(lean)["technical_complexity"]["score"]
    heavy_score = feasibility.analyze_feasibility(heavy)["technical_complexity"]["score"]

    assert heavy_score > lean_score


def test_advanced_difficulty_starts_from_a_higher_complexity_base_than_beginner():
    beginner = {**WEB_DOC, "difficulty": "Beginner", "technologies": ["React"]}
    advanced = {**WEB_DOC, "difficulty": "Advanced", "technologies": ["React"]}

    beginner_score = feasibility.analyze_feasibility(beginner)["technical_complexity"]["score"]
    advanced_score = feasibility.analyze_feasibility(advanced)["technical_complexity"]["score"]

    assert advanced_score > beginner_score


def test_high_complexity_in_a_model_heavy_domain_recommends_a_pretrained_model():
    result = feasibility.analyze_feasibility(CV_DOC)
    assert result["technical_complexity"]["level"] == "High"
    assert any("pretrained model" in r for r in result["recommendations"])


def test_high_complexity_in_a_real_time_sensitive_domain_recommends_dropping_real_time_work():
    result = feasibility.analyze_feasibility(CV_DOC)
    assert any("real-time" in r for r in result["recommendations"])


# --- team size guidance --------------------------------------------------------


def test_recommended_team_size_comes_from_the_domains_real_module_categories():
    profile = generator.domain_profile(WEB_DOC["domain"])
    expected_categories = {team_builder.category_for(m) for m in profile["modules"]}

    result = feasibility.analyze_feasibility(WEB_DOC)

    assert result["team"]["recommended_size"] == max(1, min(6, len(expected_categories)))


def test_team_size_fit_is_unavailable_without_a_given_team_size():
    result = feasibility.analyze_feasibility(WEB_DOC)
    assert result["team"]["score"] is None
    assert result["team"]["given_size"] is None


def test_team_size_fit_is_perfect_when_it_matches_the_recommendation():
    recommended = feasibility.analyze_feasibility(WEB_DOC)["team"]["recommended_size"]
    result = feasibility.analyze_feasibility(WEB_DOC, team_size=recommended)
    assert result["team"]["score"] == 100


def test_team_size_fit_degrades_the_further_it_is_from_the_recommendation():
    recommended = feasibility.analyze_feasibility(WEB_DOC)["team"]["recommended_size"]
    far_off = feasibility.analyze_feasibility(WEB_DOC, team_size=recommended + 4)
    assert far_off["team"]["score"] < 100


# --- infrastructure / dataset: always labelled as estimates -------------------


def test_infrastructure_and_dataset_are_flagged_as_estimates():
    result = feasibility.analyze_feasibility(CV_DOC)
    assert result["infrastructure"]["is_estimate"] is True
    assert result["dataset"]["is_estimate"] is True
    # Same static hint generator.domain_profile() already carries for this
    # domain — not a second, independently-invented piece of text.
    profile = generator.domain_profile(CV_DOC["domain"])
    assert result["infrastructure"]["note"] == profile["infra_hint"]
    assert result["dataset"]["note"] == profile["dataset_hint"]


# --- works on a generated-idea doc, not just a catalogue project -------------


def test_works_on_a_synthetic_idea_doc_with_no_project_id():
    doc = generator.idea_doc("QuizWhiz", domain="Natural Language Processing", duration_weeks=6, technologies=["Python", "Flask"])
    result = feasibility.analyze_feasibility(doc, known_skills=["Python"])
    assert result["project_id"] is None
    assert result["title"] == "QuizWhiz"
    assert 0 <= result["feasibility_score"] <= 100


# --- chat_tools.py wrappers ----------------------------------------------------


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


def test_analyze_project_feasibility_unknown_project_returns_an_error(fake_projects):
    for_model, block = chat_tools.analyze_project_feasibility("does-not-exist")
    assert "error" in for_model
    assert block is None


def test_analyze_project_feasibility_returns_a_feasibility_block(fake_projects):
    for_model, block = chat_tools.analyze_project_feasibility("web1", known_skills=["HTML"])
    assert block["type"] == "feasibility"
    assert block["project_id"] == "web1"
    assert for_model["feasibility_score"] == block["feasibility_score"]


def test_analyze_idea_feasibility_returns_a_feasibility_block_with_no_db_lookup():
    for_model, block = chat_tools.analyze_idea_feasibility(
        name="QuizWhiz", domain="Natural Language Processing", duration_weeks=6, technologies=["Python"]
    )
    assert block["type"] == "feasibility"
    assert block["project_id"] is None
    assert block["title"] == "QuizWhiz"
    assert for_model["feasibility_score"] == block["feasibility_score"]


def test_call_tool_dispatches_analyze_project_feasibility(fake_projects):
    for_model, block = chat_tools.call_tool("analyze_project_feasibility", {"project_id": "web1"})
    assert block["type"] == "feasibility"


def test_call_tool_dispatches_analyze_idea_feasibility():
    for_model, block = chat_tools.call_tool("analyze_idea_feasibility", {"name": "QuizWhiz"})
    assert block["type"] == "feasibility"


# --- TOOL_SCHEMAS registration / size budget ----------------------------------


def test_feasibility_tools_are_registered_in_tool_schemas():
    names = {t["function"]["name"] for t in chat_tools.TOOL_SCHEMAS}
    assert "analyze_project_feasibility" in names
    assert "analyze_idea_feasibility" in names


def test_tool_schemas_stay_within_the_pre_trim_token_budget():
    # This session previously trimmed TOOL_SCHEMAS from ~19,454 to ~15,870
    # JSON chars specifically to protect Groq's tokens-per-minute budget (see
    # config.py's GROQ_MODEL comment). Adding Feasibility+Scope pushed it back
    # to 19,200; an optimization pass (dropping enum constraints on fields
    # copied from existing project/idea context, trimming verbose
    # descriptions) brought it down to 17,475. Adding Resources — as one lean
    # dual-mode tool, same pattern as analyze_scope — brought it to 18,438.
    # 19,000 is this codebase's own documented "stop and optimize" line for
    # new-tool growth; guard against silently drifting past it.
    size = len(json.dumps(chat_tools.TOOL_SCHEMAS))
    assert size < 19000
