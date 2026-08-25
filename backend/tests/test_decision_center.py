"""The Project Decision / Action Center: nlp/decision_center.py:build().

build() takes an already-resolved project_id or idea and combines
feasibility.analyze_feasibility()/analyze_scope()/estimate_resources() (pure,
no mocking needed — same style as test_feasibility.py) with, for a catalogue
project only, chat_tools.recommend_decision() (needs the same fake-Mongo +
fake-similar pattern test_evaluation_engine.py/test_feasibility.py already
established, reused here rather than reinvented).
"""

from __future__ import annotations

import pytest

from db import client as db
from nlp import decision_center, recommend

IDEA = {
    "name": "EcoRoute Optimizer",
    "domain": "Artificial Intelligence",
    "difficulty": "Intermediate",
    "duration_weeks": 10,
    "technologies": ["Python", "TensorFlow"],
    "originality_score": 78,
    "is_unique": True,
}

PROJECT_DOC = {
    "project_id": "dc-1",
    "title": "Real-Time Face Recognition Attendance",
    "domain": "Computer Vision",
    "difficulty": "Advanced",
    "duration_weeks": 6,
    "technologies": ["Python", "OpenCV", "TensorFlow", "Flask"],
    "skills": ["Computer Vision", "Deep Learning", "Flask"],
    "description": "A real-time face recognition attendance system.",
}


class _FakeCursor(list):
    pass


class _FakeProjects:
    def __init__(self, docs):
        self._docs = docs

    def find_one(self, query, *_args, **_kwargs):
        return self._docs.get(query.get("project_id"))

    def find(self, query, *_args, **_kwargs):
        ids = set(query.get("project_id", {}).get("$in", []))
        return _FakeCursor(doc for pid, doc in self._docs.items() if pid in ids)


@pytest.fixture
def fake_projects(monkeypatch):
    fake = _FakeProjects({"dc-1": PROJECT_DOC})
    monkeypatch.setattr(db, "projects", lambda: fake)
    monkeypatch.setattr(recommend, "get_retriever", lambda: type("R", (), {"documents": {"dc-1": PROJECT_DOC}})())
    return fake


@pytest.fixture(autouse=True)
def fake_similar(monkeypatch):
    from nlp.similarity import ScoredProject

    def fake(project_id, top_k=1):
        return [ScoredProject(project_id="other", score=0.4, dense_score=0.4, sparse_score=0.0)]

    monkeypatch.setattr(recommend, "similar", fake)


# --- no target ------------------------------------------------------------


def test_build_with_neither_project_nor_idea_returns_an_error():
    result = decision_center.build()
    assert "error" in result


def test_build_with_unknown_project_id_returns_an_error(fake_projects):
    result = decision_center.build(project_id="does-not-exist")
    assert "error" in result


# --- idea mode --------------------------------------------------------------


def test_build_idea_mode_needs_no_database_at_all():
    # No fake_projects fixture used here on purpose — an idea has no
    # project_id, so nothing here should ever touch db.projects().
    result = decision_center.build(idea=IDEA, known_skills=["Python"], team_size=2)
    assert result["kind"] == "idea"
    assert result["project_id"] is None
    assert result["name"] == "EcoRoute Optimizer"


def test_build_idea_mode_reuses_the_ideas_own_originality_never_rechecks():
    result = decision_center.build(idea=IDEA)
    assert result["originality"]["score"] == 78
    assert result["originality"]["is_unique"] is True
    assert result["originality"]["source"] == "generated_idea_originality"


def test_build_idea_mode_originality_is_none_when_the_idea_carries_none():
    idea = {k: v for k, v in IDEA.items() if k not in ("originality_score", "is_unique")}
    result = decision_center.build(idea=idea)
    assert result["originality"]["score"] is None


def test_build_idea_mode_recommendation_score_is_the_feasibility_score():
    result = decision_center.build(idea=IDEA, known_skills=["Python"])
    assert result["overall_recommendation"]["score"] == result["feasibility"]["score"]


def test_build_idea_mode_skill_fit_unavailable_without_known_skills():
    result = decision_center.build(idea=IDEA)
    assert result["skill_fit"] is None
    assert result["known_skills_provided"] is False
    assert "skill gap" in result["recommended_next_step"].lower()


def test_build_idea_mode_skill_fit_available_with_known_skills():
    result = decision_center.build(idea=IDEA, known_skills=["Python", "TensorFlow"])
    assert result["skill_fit"] == 100.0
    assert result["known_skills_provided"] is True
    assert result["skills_to_learn"] == []


def test_build_idea_mode_includes_scope_and_resources():
    result = decision_center.build(idea=IDEA)
    assert result["scope"]["mvp"]
    assert result["resources"]["team_recommended_size"] >= 1


def test_build_idea_mode_reduced_scope_recommendation_when_target_is_tight():
    # known_skills fully covers technologies so the higher-priority
    # "check your skill gap" / "learn X first" next-step branches don't
    # pre-empt this one (see decision_center._recommended_next_step's
    # priority order).
    result = decision_center.build(idea=IDEA, known_skills=["Python", "TensorFlow"], target_weeks=2)
    assert result["scope"]["reduced_scope"] is not None
    assert "scope reduction" in result["recommended_next_step"].lower()


# --- catalogue project mode --------------------------------------------------


def test_build_project_mode_uses_the_decision_engines_overall_fit(fake_projects):
    result = decision_center.build(project_id="dc-1", known_skills=["Python", "OpenCV"])
    assert result["kind"] == "project"
    assert result["project_id"] == "dc-1"
    # overall_fit, not feasibility_score -- the two scores are allowed to differ
    # (different weightings, see nlp/decision_center.py's own docstring).
    assert isinstance(result["overall_recommendation"]["score"], int)


def test_build_project_mode_originality_is_the_catalogue_uniqueness(fake_projects):
    result = decision_center.build(project_id="dc-1")
    assert result["originality"]["score"] == 60  # round((1 - 0.4) * 100), from fake_similar
    assert result["originality"]["source"] == "catalogue_uniqueness"
    assert result["originality"]["is_unique"] is None  # not a meaningful field for a catalogue project


def test_build_project_mode_merges_decision_and_feasibility_strengths_and_risks_without_duplicates(fake_projects):
    result = decision_center.build(project_id="dc-1", known_skills=["Python"], experience_level="Beginner")
    assert len(result["strengths"]) == len(set(result["strengths"]))
    assert len(result["risks"]) == len(set(result["risks"]))


def test_build_project_mode_skill_fit_matches_feasibility_and_decision_engine(fake_projects):
    # Both chat_tools.recommend_decision and feasibility.analyze_feasibility
    # derive skill_fit from the exact same recommend.skill_gap_for_doc() call
    # — this is the regression guard that the two never quietly disagree.
    from nlp import feasibility

    result = decision_center.build(project_id="dc-1", known_skills=["Python", "OpenCV"])
    direct = feasibility.analyze_feasibility(PROJECT_DOC, known_skills=["Python", "OpenCV"])
    assert result["skill_fit"] == direct["factors"][0]["score"]


def test_build_project_mode_recommended_next_step_is_present(fake_projects):
    result = decision_center.build(project_id="dc-1")
    assert isinstance(result["recommended_next_step"], str) and result["recommended_next_step"]
