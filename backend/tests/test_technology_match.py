"""Technology identity in retrieval — the "React Flask full stack" regression.

Reproduced on the real catalogue: for "React Flask full stack web application"
the top result was `Universal Link Router for a Content App` (a React Native
app with no Flask at all) while 28 projects that list both React and Flask sat
lower. Cause: the dense score is flat for framework names and min-max fusion
let the router's slightly higher dense score decide the ranking; BM25 gave it
credit for `react` because it tokenises "React Native" into react + native.
These tests use the real catalogue records involved and controlled dense
scores shaped like the observed ones, so they run without the embedding model.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

import config
from nlp import embeddings
from nlp.similarity import HybridRetriever, query_technologies

SEED = {r["title"]: r for r in json.loads(config.SEED_FILE.read_text(encoding="utf-8"))}

ROUTER = "Universal Link Router for a Content App"  # React Native, no Flask
BOTH = [  # list React AND Flask
    "Personal Finance Tracker with Analytics",
    "Secure Password Reset Flow Implementation",
    "Two-Factor Authentication Service",
    "Password Strength Analyser and Breach Checker",
]
REACT_ONLY = ["Bookmark Manager with Tagging", "Weather Dashboard with Location Search", "Habit Tracker with Streaks and Reminders"]
FILLER = [t for t in SEED if t not in {ROUTER, *BOTH, *REACT_ONLY}][:40]


def _vocab(documents):
    from nlp import skills

    return {skills.normalize_key(t): skills.display_name(t) for d in documents.values() for t in d["technologies"]}


@pytest.fixture
def catalogue(monkeypatch):
    """Real records; dense cosines shaped like the real query's: the router a
    touch ahead of everything, the genuine React+Flask projects just behind it."""
    titles = [ROUTER, *BOTH, *REACT_ONLY, *FILLER]
    documents = {SEED[t]["project_id"]: SEED[t] for t in titles}
    cosines = {ROUTER: 0.324}
    cosines.update({t: 0.26 for t in BOTH})
    cosines.update({t: 0.25 for t in REACT_ONLY})
    rng = np.random.default_rng(5)
    cosines.update({t: float(rng.uniform(-0.12, 0.18)) for t in FILLER})

    ids = [SEED[t]["project_id"] for t in titles]
    c = np.array([cosines[t] for t in titles], dtype=np.float32)
    matrix = np.stack([c, np.sqrt(1 - c**2)], axis=1)  # query vector (1, 0) -> cosine == c
    monkeypatch.setattr(embeddings, "encode_one", lambda text: np.array([1.0, 0.0], dtype=np.float32))
    retriever = HybridRetriever(matrix, ids, documents)
    monkeypatch.setattr(config, "TECHNOLOGY_WEIGHT", 0.25)
    return retriever


def _titles(results):
    return [r.document["title"] for r in results]


# --- the regression ---------------------------------------------------------------

QUERY = "React Flask full stack web application"


def test_without_technology_matching_the_react_native_router_wins(catalogue, monkeypatch):
    """Documents the bug being fixed (weight 0 == the old behaviour)."""
    monkeypatch.setattr(config, "TECHNOLOGY_WEIGHT", 0.0)
    assert _titles(catalogue.search(QUERY, top_k=5))[0] == ROUTER


def test_with_technology_matching_projects_that_list_both_outrank_the_router(catalogue):
    top = catalogue.search(QUERY, top_k=5)
    titles = _titles(top)
    assert set(titles[: len(BOTH)]) == set(BOTH)
    assert titles.index(ROUTER) > titles.index(BOTH[-1]) if ROUTER in titles else True
    assert all(r.technology_score == 1.0 for r in top[: len(BOTH)])


def test_a_project_with_only_one_of_the_named_technologies_ranks_between(catalogue):
    titles = _titles(catalogue.search(QUERY, top_k=len(catalogue.ids)))
    for react_only in REACT_ONLY:
        assert titles.index(react_only) > max(titles.index(t) for t in BOTH)


def test_react_native_is_not_react(catalogue):
    """The router lists React Native only, so it earns no credit for 'React'."""
    results = {r.document["title"]: r for r in catalogue.search(QUERY, top_k=len(catalogue.ids))}
    assert results[ROUTER].technology_score == 0.0
    assert results[REACT_ONLY[0]].technology_score == 0.5  # React yes, Flask no


def test_a_react_native_query_matches_react_native_projects_not_plain_react(catalogue):
    results = catalogue.search("React Native mobile app", top_k=len(catalogue.ids))
    by_title = {r.document["title"]: r.technology_score for r in results}
    assert by_title[ROUTER] == 1.0
    assert by_title[REACT_ONLY[0]] == 0.0


# --- the signal is inert unless the query names technologies -----------------------------


def test_queries_naming_no_technology_are_not_affected_at_all(catalogue, monkeypatch):
    with_weight = catalogue.search("secure login and password reset", top_k=10)
    monkeypatch.setattr(config, "TECHNOLOGY_WEIGHT", 0.0)
    without = catalogue.search("secure login and password reset", top_k=10)
    assert [(r.project_id, r.score) for r in with_weight] == [(r.project_id, r.score) for r in without]
    assert all(r.technology_score is None for r in with_weight)


def test_the_opt_out_flag_restores_the_unblended_scores(catalogue):
    blended = catalogue.search(QUERY, top_k=5)
    plain = catalogue.search(QUERY, top_k=5, technology_match=False)
    assert all(r.technology_score is None for r in plain)
    assert [r.project_id for r in blended] != [r.project_id for r in plain]


def test_scores_stay_within_the_zero_one_range_the_ui_renders_as_a_percentage(catalogue):
    assert all(0.0 <= r.score <= 1.0 for r in catalogue.search(QUERY, top_k=len(catalogue.ids)))


def test_filters_are_still_applied_before_ranking(catalogue):
    results = catalogue.search(QUERY, filters={"difficulty": "Beginner"}, top_k=20)
    assert results and all(r.document["difficulty"] == "Beginner" for r in results)


def test_the_blend_is_reported_in_the_api_payload(catalogue):
    first = catalogue.search(QUERY, top_k=1)[0].to_dict()
    assert first["relevance"]["technology"] == 1.0
    plain = catalogue.search("secure login", top_k=1)[0].to_dict()
    assert "technology" not in plain["relevance"]


def test_the_default_weight_is_a_valid_blend_share():
    assert 0.0 < config.TECHNOLOGY_WEIGHT < 1.0


# --- detecting technologies in a query -----------------------------------------------------


@pytest.fixture
def vocab():
    return _vocab({r["project_id"]: r for r in SEED.values()})


@pytest.mark.parametrize(
    "query,expected",
    [
        ("React Flask full stack", {"react", "flask"}),
        ("react native app", {"reactnative"}),  # longest phrase wins; not also "react"
        ("mobile app development with React Native", {"reactnative"}),
        ("sklearn and Pandas pipeline", {"scikitlearn", "pandas"}),  # alias resolved
        ("Node.js REST API with Express", {"nodejs", "expressjs"}),
        ("docker kubernetes devops pipeline", {"docker", "kubernetes"}),
        ("YOLOv8 object detection", {"yolov8"}),
        ("a project about healthcare", set()),
        ("", set()),
        ("   ", set()),
    ],
)
def test_query_technologies(vocab, query, expected):
    assert query_technologies(query, vocab) == expected


@pytest.mark.parametrize(
    "query,expected",
    [
        ("express delivery app", set()),  # plain English
        ("go to market strategy", set()),
        ("unity of purpose in teams", set()),
        ("Express REST API", {"expressjs"}),  # capitalised -> the technology
        ("Unity AR app", {"unity"}),
        ("Go microservice", {"go"}),
    ],
)
def test_ambiguous_english_word_technologies_need_a_capital_letter(vocab, query, expected):
    assert query_technologies(query, vocab) & {"expressjs", "unity", "go"} == expected


def test_unknown_technologies_are_ignored_not_guessed(vocab):
    assert query_technologies("Haskell Elm Prolog project", vocab) == set()


def test_java_is_not_javascript(vocab):
    named = query_technologies("JavaScript web app", vocab)
    assert "javascript" in named and "java" not in named
