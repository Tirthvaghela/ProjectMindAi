"""Best fit for you — every input must change the result.

Regression tests for the bug where choosing Beginner, Intermediate or
Advanced in the panel returned identical rankings: the experience level only
fed the timeline estimate, and the ranking score never looked at difficulty.
These assert on which projects are returned and in what order, not just on
an HTTP 200.

`recommend.search` is monkeypatched (as in test_recommend.py) so the tests
exercise personalized_recommend's own filtering and ranking, not embeddings.
"""

from __future__ import annotations

import pytest

from nlp import recommend, timeline
from nlp.similarity import ScoredProject


def _doc(pid, difficulty, weeks, technologies=("Python",), skills=("Modelling",)):
    return {
        "project_id": pid,
        "title": f"Project {pid}",
        "domain": "Machine Learning",
        "difficulty": difficulty,
        "technologies": list(technologies),
        "skills": list(skills),
        "duration_weeks": weeks,
    }


DOCS = {
    "beg": _doc("beg", "Beginner", 6),
    "int": _doc("int", "Intermediate", 8),
    "adv": _doc("adv", "Advanced", 10),
    "nodur": {**_doc("nodur", "Intermediate", None)},
}


class _FakeRetriever:
    def __init__(self, documents):
        self.documents = documents


def _scored(pid, score=0.5):
    return ScoredProject(
        project_id=pid, score=score, dense_score=score, sparse_score=0.0, matched_terms=[], document=DOCS[pid]
    )


@pytest.fixture(autouse=True)
def pool(monkeypatch):
    """All four projects at EQUAL relevance, so any ordering difference can
    only come from the user's own inputs. Captures the filters sent to search."""
    seen = {}
    monkeypatch.setattr(recommend, "get_retriever", lambda: _FakeRetriever(DOCS))

    def fake_search(query, filters=None, top_k=10, **_):
        seen["filters"] = filters
        seen["top_k"] = top_k
        return [_scored(pid) for pid in DOCS]

    monkeypatch.setattr(recommend, "search", fake_search)
    return seen


def _ids(**kwargs):
    return [r["project_id"] for r in recommend.personalized_recommend(known_skills=["Python"], **kwargs)]


# --- experience level (a ranking preference) ---------------------------------


@pytest.mark.parametrize(
    "level,expected_first",
    [("Beginner", "beg"), ("Intermediate", "int"), ("Advanced", "adv")],
)
def test_each_experience_level_puts_its_own_difficulty_first(level, expected_first):
    assert _ids(experience_level=level)[0] == expected_first


def test_changing_only_the_experience_level_changes_the_results():
    assert _ids(experience_level="Beginner") != _ids(experience_level="Advanced")


def test_advanced_experience_ranks_beginner_below_intermediate_below_advanced():
    order = _ids(experience_level="Advanced")
    assert order.index("adv") < order.index("int") < order.index("beg")


def test_a_below_level_project_is_labelled_not_passed_off_as_an_exact_match():
    results = recommend.personalized_recommend(known_skills=["Python"], experience_level="Advanced")
    beginner = next(r for r in results if r["project_id"] == "beg")
    assert beginner["difficulty_fit"] == 50
    assert "ahead of this project's Beginner difficulty" in beginner["difficulty_note"]
    assert "ahead of this project's Beginner difficulty" in beginner["recommendation_reason"]
    assert not any("matches this project" in f for f in beginner["matching_factors"])


def test_an_exact_difficulty_match_is_reported_as_one():
    results = recommend.personalized_recommend(known_skills=["Python"], experience_level="Advanced")
    adv = next(r for r in results if r["project_id"] == "adv")
    assert adv["difficulty_fit"] == 100
    assert any("matches this project" in f for f in adv["matching_factors"])


def test_without_an_experience_level_there_is_no_difficulty_signal():
    results = recommend.personalized_recommend(known_skills=["Python"])
    assert all(r["difficulty_fit"] is None and r["difficulty_note"] is None for r in results)


def test_an_unrecognised_experience_level_is_ignored_not_crashed_on():
    assert set(_ids(experience_level="Wizard")) == set(DOCS)


# --- maximum duration + team size (hard constraints on the estimate) ---------


def test_a_project_exactly_at_the_maximum_is_included():
    # Solo, no stated experience: estimate == baseline, so 6 weeks vs max 6.
    assert "beg" in _ids(max_duration_weeks=6)


def test_a_project_one_week_over_the_maximum_is_excluded():
    assert "beg" not in _ids(max_duration_weeks=5)


def test_team_size_changes_which_projects_qualify():
    # "adv" is 10 weeks solo. Two people (x0.625) estimate at 6 weeks.
    assert "adv" not in _ids(max_duration_weeks=6, team_size=1)
    assert "adv" in _ids(max_duration_weeks=6, team_size=2)


def test_experience_also_changes_which_projects_qualify():
    # Advanced on a Beginner project (x0.75): 6 -> 4.5 weeks fits a 5-week limit,
    # a Beginner on that same project (x1.0) stays at 6 and does not.
    assert "beg" in _ids(max_duration_weeks=5, experience_level="Advanced")
    assert "beg" not in _ids(max_duration_weeks=5, experience_level="Beginner")
    # Beginner on an Advanced project (x1.5): 10 -> 15 weeks, over a 14-week limit.
    assert "adv" not in _ids(max_duration_weeks=14, experience_level="Beginner")
    assert "adv" in _ids(max_duration_weeks=14, experience_level="Advanced")


def test_a_project_with_no_documented_duration_is_not_assumed_to_fit():
    assert "nodur" not in _ids(max_duration_weeks=52)
    assert "nodur" in _ids()  # no deadline -> nothing to violate


def test_search_prefilter_is_never_stricter_than_the_exact_estimate(pool):
    recommend.personalized_recommend(known_skills=["Python"], max_duration_weeks=6, team_size=2)
    # adv (10 weeks) qualifies for a team of 2, so the baseline bound passed
    # down to the retriever has to be at least 10.
    assert pool["filters"]["max_duration_weeks"] >= 10


@pytest.mark.parametrize("team_size", [1, 2, 3, 5, 10, 20])
@pytest.mark.parametrize("level", [None, "Beginner", "Intermediate", "Advanced"])
def test_min_weeks_multiplier_is_a_true_lower_bound(team_size, level):
    floor = timeline.min_weeks_multiplier(team_size, level)
    team, _ = timeline._team_multiplier(team_size)
    for difficulty in ("Beginner", "Intermediate", "Advanced"):
        experience, _ = timeline._experience_multiplier(difficulty, level)
        assert floor <= team * experience + 1e-12


# --- several inputs at once ---------------------------------------------------


def test_all_filters_together_exclude_and_rank_consistently():
    results = _ids(experience_level="Advanced", max_duration_weeks=6, team_size=2)
    # Estimates for a team of 2 at Advanced: beg 6*.75*.625=2.8->3, int 8*.85*.625=4.25->4,
    # adv 10*.625=6.25->6 — all fit; nodur is excluded; difficulty then orders them.
    assert results == ["adv", "int", "beg"]


def test_constraints_that_nothing_satisfies_return_an_empty_list():
    assert _ids(max_duration_weeks=1) == []


# --- skills -------------------------------------------------------------------


def test_skills_are_matched_against_project_technologies_case_insensitively():
    results = recommend.personalized_recommend(known_skills=["python"], experience_level=None)
    gap = results[0]["skill_gap"]
    assert "Python" in gap["skills_you_have"]
    assert "Modelling" in gap["skills_to_learn"]


def test_a_skill_does_not_match_an_unrelated_longer_word():
    docs = {"js": _doc("js", "Beginner", 4, technologies=("JavaScript",), skills=())}
    gap = recommend._skill_fit(docs["js"], ["Java"])
    assert gap["skills_you_have"] == []
    assert gap["skills_to_learn"] == ["JavaScript"]


def test_skill_credit_raises_the_score():
    with_skill = recommend.personalized_recommend(known_skills=["Python"])[0]["overall_score"]
    without = recommend.personalized_recommend(known_skills=["Cobol"])[0]["overall_score"]
    assert with_skill > without


# --- empty-state explanation ---------------------------------------------------


def test_explain_empty_reports_the_shortest_real_estimate():
    info = recommend.explain_empty(1, team_size=1, experience_level=None)
    assert info["shortest_estimated_weeks"] == 6  # beg is the shortest known duration
    assert info["max_duration_weeks"] == 1


def test_explain_empty_ignores_projects_with_unknown_duration():
    info = recommend.explain_empty(1)
    assert info["shortest_estimated_weeks"] is not None
