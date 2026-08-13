"""nlp/recommend.py:personalized_recommend — the multi-factor orchestration
layer over search()/skill_gap()/timeline.predict().

`recommend.search` and `recommend.get_retriever` are monkeypatched rather
than built from a real HybridRetriever (contrast tests/test_similarity.py,
which tests the retriever itself): these tests are about personalized_
recommend's OWN logic — query fallback, matching_factors, weighted scoring,
sorting — which doesn't need real embeddings or BM25 to verify.
"""

from __future__ import annotations

import pytest

import config
from nlp import recommend
from nlp.similarity import ScoredProject

DOCS = {
    "a": {
        "project_id": "a",
        "title": "Beginner web dashboard",
        "domain": "Web Development",
        "difficulty": "Beginner",
        "technologies": ["React"],
        "skills": ["HTML", "CSS"],
        "duration_weeks": 4,
    },
    "b": {
        "project_id": "b",
        "title": "Advanced AI research system",
        "domain": "Artificial Intelligence",
        "difficulty": "Advanced",
        "technologies": ["Python", "PyTorch"],
        "skills": ["Deep learning"],
        "duration_weeks": 16,
    },
    "c": {
        "project_id": "c",
        "title": "Intermediate web app with Node",
        "domain": "Web Development",
        "difficulty": "Intermediate",
        "technologies": ["React", "Node.js"],
        "skills": ["React", "APIs"],
        "duration_weeks": 8,
    },
}


class _FakeRetriever:
    """Only what skill_gap() needs from the real HybridRetriever."""

    def __init__(self, documents):
        self.documents = documents


def _scored(project_id: str, score: float, matched_terms=None) -> ScoredProject:
    return ScoredProject(
        project_id=project_id,
        score=score,
        dense_score=score,
        sparse_score=0.0,
        matched_terms=matched_terms or [],
        document=DOCS[project_id],
    )


@pytest.fixture(autouse=True)
def fake_retriever(monkeypatch):
    monkeypatch.setattr(recommend, "get_retriever", lambda: _FakeRetriever(DOCS))


# --- _timeline_fit_score -----------------------------------------------------


def test_timeline_fit_score_within_deadline_is_perfect():
    assert recommend._timeline_fit_score(4, 6) == 100.0


def test_timeline_fit_score_at_the_deadline_is_perfect():
    assert recommend._timeline_fit_score(6, 6) == 100.0


def test_timeline_fit_score_over_deadline_is_penalized_proportionally():
    # 50% overrun relative to the deadline itself -> 50 points off.
    assert recommend._timeline_fit_score(9, 6) == 50.0


def test_timeline_fit_score_never_drops_below_zero():
    assert recommend._timeline_fit_score(30, 6) == 0.0


# --- personalized_recommend: query resolution --------------------------------


def test_returns_empty_with_no_query_skills_or_filters(monkeypatch):
    calls = []
    monkeypatch.setattr(recommend, "search", lambda *a, **k: calls.append((a, k)) or [])
    assert recommend.personalized_recommend() == []
    assert calls == []  # never even reaches the retriever


def test_builds_query_from_skills_and_technologies_when_query_is_empty(monkeypatch):
    seen = {}

    def fake_search(query, filters=None, top_k=10, profile=None):
        seen["query"] = query
        return []

    monkeypatch.setattr(recommend, "search", fake_search)
    recommend.personalized_recommend(known_skills=["Python", "Flask"])
    assert seen["query"] == "Python, Flask"


def test_explicit_query_is_used_as_is(monkeypatch):
    seen = {}

    def fake_search(query, filters=None, top_k=10, profile=None):
        seen["query"] = query
        return []

    monkeypatch.setattr(recommend, "search", fake_search)
    recommend.personalized_recommend(query="chatbot for customer support", known_skills=["Python"])
    assert seen["query"] == "chatbot for customer support"


def test_filters_are_forwarded_to_search(monkeypatch):
    seen = {}

    def fake_search(query, filters=None, top_k=10, profile=None):
        seen["filters"] = filters
        return []

    monkeypatch.setattr(recommend, "search", fake_search)
    recommend.personalized_recommend(
        query="anything", domain="Web Development", difficulty="Beginner",
        technologies=["React"], max_duration_weeks=6,
    )
    assert seen["filters"] == {
        "domain": "Web Development",
        "difficulty": "Beginner",
        "technologies": ["React"],
        "max_duration_weeks": 6,
    }


# --- personalized_recommend: skill-gap signal --------------------------------


def test_skill_gap_is_attached_and_distinguishes_have_from_need(monkeypatch):
    monkeypatch.setattr(recommend, "search", lambda *a, **k: [_scored("c", 0.8)])

    [result] = recommend.personalized_recommend(query="web app", known_skills=["React"])

    assert result["skill_gap"]["skills_you_have"] == ["React"]
    assert result["skill_gap"]["skills_to_learn"] == ["APIs"]
    assert any("Skill match" in factor and "React" in factor for factor in result["matching_factors"])


def test_no_known_skills_means_no_skill_gap_signal(monkeypatch):
    monkeypatch.setattr(recommend, "search", lambda *a, **k: [_scored("c", 0.8)])

    [result] = recommend.personalized_recommend(query="web app")

    assert result["skill_gap"] is None
    assert not any("Skill match" in f for f in result["matching_factors"])


# --- personalized_recommend: matching factors --------------------------------


def test_domain_and_technology_matches_are_reported(monkeypatch):
    monkeypatch.setattr(recommend, "search", lambda *a, **k: [_scored("c", 0.8)])

    [result] = recommend.personalized_recommend(
        query="web app", domain="Web Development", technologies=["React"]
    )

    assert "Domain match: Web Development" in result["matching_factors"]
    assert any("Technology match" in f and "React" in f for f in result["matching_factors"])


# --- personalized_recommend: timeline signal + ranking -----------------------


def test_timeline_fit_reorders_equal_relevance_candidates(monkeypatch):
    # "a" (4 weeks) comfortably fits a 6-week deadline; "b" (16 weeks) badly
    # overruns it. Equal relevance means timeline fit is the only thing that
    # can separate them, so it must decide the ordering.
    monkeypatch.setattr(recommend, "search", lambda *a, **k: [_scored("b", 0.5), _scored("a", 0.5)])

    results = recommend.personalized_recommend(query="a project", max_duration_weeks=6)

    assert [r["project_id"] for r in results] == ["a", "b"]
    assert results[0]["overall_score"] > results[1]["overall_score"]


def test_overall_score_is_pure_relevance_with_no_other_signals(monkeypatch):
    monkeypatch.setattr(recommend, "search", lambda *a, **k: [_scored("a", 0.7321)])

    [result] = recommend.personalized_recommend(query="a project")

    assert result["overall_score"] == round(0.7321 * 100, 1)


def test_top_k_caps_the_number_of_returned_recommendations(monkeypatch):
    monkeypatch.setattr(
        recommend, "search", lambda *a, **k: [_scored("a", 0.9), _scored("b", 0.8), _scored("c", 0.7)]
    )

    results = recommend.personalized_recommend(query="anything", top_k=2)

    assert len(results) == 2


def test_recommendation_reason_is_backend_composed_not_empty(monkeypatch):
    monkeypatch.setattr(recommend, "search", lambda *a, **k: [_scored("c", 0.8)])

    [result] = recommend.personalized_recommend(
        query="web app", known_skills=["React"], max_duration_weeks=6
    )

    assert isinstance(result["recommendation_reason"], str) and result["recommendation_reason"]


def test_weights_sum_to_something_reasonable():
    # Not a hard product requirement, just guards against a typo turning a
    # weight negative or absurdly large, which would silently invert ranking.
    assert 0 < config.RECOMMEND_RELEVANCE_WEIGHT <= 1
    assert 0 <= config.RECOMMEND_SKILL_WEIGHT <= 1
    assert 0 <= config.RECOMMEND_TIMELINE_WEIGHT <= 1
