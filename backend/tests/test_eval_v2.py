"""The versioned evaluation dataset (v2) and the harness that scores it.

Two kinds of test: the metric/labelling logic on tiny hand-built cases, and
integrity checks on the real dataset files (so labels cannot drift out of
sync with the catalogue, and the historical v1 baseline stays untouched).
"""

from __future__ import annotations

import hashlib
import json
import math

import pytest

import config
from scripts import eval_dataset as ed
from scripts import evaluate as ev

# --- metric logic ---------------------------------------------------------------------


def test_graded_ndcg_rewards_putting_grade_two_before_grade_one():
    grades = {"a": 2, "b": 1, "c": 0}
    best = ev.graded_ndcg_at_k(["a", "b", "c"], grades, 5)
    worse = ev.graded_ndcg_at_k(["b", "a", "c"], grades, 5)
    assert best == pytest.approx(1.0)
    assert worse < best
    expected = (1 / math.log2(2) + 2 / math.log2(3)) / (2 / math.log2(2) + 1 / math.log2(3))
    assert worse == pytest.approx(expected)


def test_graded_ndcg_ignores_unjudged_results_as_zero_gain():
    assert ev.graded_ndcg_at_k(["x", "a"], {"a": 2}, 5) == pytest.approx(1 / math.log2(3) / (2 / math.log2(2)) * 2)
    assert ev.graded_ndcg_at_k(["a"], {}, 5) == 0.0


QUERY = {"query": "q", "grades": {"p1": 2, "p2": 1, "p3": 0, "p4": 1, "p5": 2}, "uncertain": ["p2", "p3", "p5"]}


def test_relevant_sets_at_each_threshold_and_bound():
    assert ev.relevant_set(QUERY, 1) == {"p1", "p2", "p4", "p5"}  # lenient
    assert ev.relevant_set(QUERY, 2) == {"p1", "p5"}  # strict
    assert ev.relevant_set(QUERY, 1, "low") == {"p1", "p4"}  # uncertain relevant items dropped
    assert ev.relevant_set(QUERY, 1, "high") == {"p1", "p2", "p3", "p4", "p5"}  # uncertain 0 counted
    assert ev.relevant_set(QUERY, 2, "low") == {"p1"}
    assert ev.relevant_set(QUERY, 2, "high") == {"p1", "p2", "p5"}  # uncertain grade-1 counted


def test_low_never_exceeds_point_never_exceeds_high():
    for threshold in (1, 2):
        low, point, high = (ev.relevant_set(QUERY, threshold, b) for b in ("low", "point", "high"))
        assert low <= point <= high


class _Result:
    def __init__(self, pid):
        self.project_id = pid


class _FixedRetriever:
    """Returns the same ranking every time: isolates scoring from retrieval."""

    def __init__(self, ranking):
        self.ranking = ranking

    def search(self, query, top_k=10, **_):
        return [_Result(p) for p in self.ranking[:top_k]]


DATASET = {"version": "t", "queries": [QUERY]}


def test_v2_evaluation_is_deterministic_for_the_same_labels_and_ranking():
    retriever = _FixedRetriever(["p1", "p3", "p2", "p9", "p5", "p4"])
    first = ev.evaluate_v2(retriever, DATASET, k=5)
    second = ev.evaluate_v2(_FixedRetriever(["p1", "p3", "p2", "p9", "p5", "p4"]), DATASET, k=5)
    assert first == second


def test_v2_metrics_match_a_hand_computation():
    retriever = _FixedRetriever(["p1", "p3", "p2", "p9", "p5"])
    result = ev.evaluate_v2(retriever, DATASET, k=5)
    lenient = result["metrics"]["lenient/point"]
    relevant = {"p1", "p2", "p4", "p5"}
    dcg = 1 / math.log2(2) + 1 / math.log2(4) + 1 / math.log2(6)
    ideal = sum(1 / math.log2(i + 1) for i in range(1, 5))
    assert lenient["ndcg_at_k"] == pytest.approx(dcg / ideal)
    assert lenient["recall_at_k"] == pytest.approx(3 / len(relevant))
    assert lenient["mrr"] == 1.0
    # p9 is not in the labels: counted as not relevant, and reported as unjudged.
    assert result["judged_at_k"] == pytest.approx(4 / 5)


def test_strict_is_never_easier_than_lenient_on_recall():
    retriever = _FixedRetriever(["p3", "p9", "p2", "p4", "p1"])
    metrics = ev.evaluate_v2(retriever, DATASET, k=5)["metrics"]
    assert metrics["strict/point"]["recall_at_k"] <= 1.0
    assert metrics["lenient/low"]["ndcg_at_k"] <= metrics["lenient/high"]["ndcg_at_k"] + 1e-12


# --- labelling logic ------------------------------------------------------------------


def test_parse_judgments_reads_grades_and_uncertainty_flags():
    parsed = ed.parse_judgments("# comment\nabc123 2\ndef456 1u   # trailing\n\n789abc 0\n")
    assert parsed == {"abc123": (2, False), "def456": (1, True), "789abc": (0, False)}


@pytest.mark.parametrize("bad", ["abc123 3", "abc123", "abc123 2 extra", "abc123 two", "abc123 2\nabc123 1"])
def test_parse_judgments_rejects_malformed_lines_and_double_judgments(bad):
    with pytest.raises(ValueError):
        ed.parse_judgments(bad)


def test_blinded_ids_are_stable_unique_and_hide_the_project_id():
    ids = [f"pm-{n:03d}" for n in range(1, 400)]
    blind = [ed.opaque_id(3, p) for p in ids]
    assert len(set(blind)) == len(ids)
    assert blind == [ed.opaque_id(3, p) for p in ids]
    assert ed.opaque_id(3, "pm-001") != ed.opaque_id(4, "pm-001")  # differs per query


def test_build_dataset_refuses_missing_or_unknown_judgments():
    docs = {"pm-001": {"project_id": "pm-001", "title": "T", "description": "d", "domain": "Robotics",
                       "technologies": ["Python"], "difficulty": "Beginner", "duration_weeks": 5, "skills": ["x"], "keywords": ["k"]}}
    v1 = [{"query": "q", "relevant": ["pm-001"]}]
    pools = [{"pm-001": ["v1_label"]}]
    criteria = {"q": {"2": "a", "1": "b"}}
    good = {ed.opaque_id(1, "pm-001"): (2, False)}
    dataset = ed.build_dataset(docs, v1, pools, [good], criteria)
    assert dataset["queries"][0]["grades"] == {"pm-001": 2}
    with pytest.raises(ValueError):
        ed.build_dataset(docs, v1, pools, [{}], criteria)  # unjudged candidate
    with pytest.raises(ValueError):
        ed.build_dataset(docs, v1, pools, [{**good, "ffffff": (1, False)}], criteria)  # unknown id


def test_catalogue_snapshot_changes_when_any_searchable_text_changes():
    docs = {"pm-001": {"project_id": "pm-001", "title": "A", "description": "x", "domain": "Robotics", "technologies": ["Python"], "skills": ["s"]}}
    before = ed.catalogue_snapshot(docs)
    docs["pm-001"]["description"] = "y"
    after = ed.catalogue_snapshot(docs)
    assert before["sha256"] != after["sha256"] and before["project_count"] == after["project_count"] == 1


# (human-review agreement statistics are tested in tests/test_eval_review.py)


# --- integrity of the real dataset files -----------------------------------------------

def _v2():
    return json.loads(ed.V2_FILE.read_text(encoding="utf-8"))


def _seed():
    return {r["project_id"]: r for r in json.loads(config.SEED_FILE.read_text(encoding="utf-8"))}


def test_the_v2_labels_were_made_against_exactly_this_catalogue():
    """If this fails the catalogue changed after the labels were made, so the
    labels are missing every new project. Build a v3 dataset (scripts/
    eval_dataset.py) instead of comparing numbers across catalogues."""
    snapshot = ed.catalogue_snapshot(_seed())
    assert snapshot["sha256"] == _v2()["catalogue"]["sha256"]
    assert snapshot["project_count"] == _v2()["catalogue"]["project_count"]


def test_v2_covers_every_v1_query_with_documented_criteria():
    v1 = json.loads(ed.V1_FILE.read_text(encoding="utf-8"))
    v2 = _v2()
    assert [q["query"] for q in v2["queries"]] == [q["query"] for q in v1]
    for query, old in zip(v2["queries"], v1):
        assert query["criteria"]["2"] and query["criteria"]["1"]
        assert query["v1_relevant"] == sorted(old["relevant"])


def test_v2_grades_are_valid_and_refer_to_real_projects():
    seed = _seed()
    for query in _v2()["queries"]:
        assert query["grades"], query["query"]
        assert set(query["grades"].values()) <= {0, 1, 2}
        assert set(query["grades"]) <= set(seed)
        assert set(query["uncertain"]) <= set(query["grades"])
        assert 2 in query["grades"].values()  # every query has at least one fully relevant answer


def test_v2_judged_pool_includes_every_v1_label_and_the_new_projects():
    v2 = _v2()
    for query in v2["queries"]:
        assert set(query["v1_relevant"]) <= set(query["grades"])
    judged_new = {p for q in v2["queries"] for p in q["grades"] if int(p.split("-")[1]) > 500}
    assert len(judged_new) >= 100  # the 368 new projects are genuinely represented


def test_the_frozen_pool_is_exactly_what_was_judged():
    frozen = json.loads(ed.POOLS_FILE.read_text(encoding="utf-8"))
    for pool, query in zip(frozen["pools"], _v2()["queries"]):
        assert set(pool["candidates"]) == set(query["grades"])


def test_annotation_limitations_are_recorded_in_the_dataset_itself():
    annotation = _v2()["annotation"]
    assert "conflict_of_interest" in annotation and "independent_review" in annotation
    assert _v2()["pooling"]["assumption"]


def test_the_historical_v1_dataset_and_baseline_are_preserved():
    v1_bytes = ed.V1_FILE.read_bytes()
    assert len(json.loads(v1_bytes)) == 25
    assert hashlib.sha256(v1_bytes).hexdigest() == _V1_HASH
    baseline = json.loads((config.DATASET_DIR / "reports" / "eval_v1_500_baseline.json").read_text(encoding="utf-8"))
    assert baseline["max_project"] == 500 and baseline["catalogue"]["project_count"] == 500
    assert round(baseline["result"]["ndcg_at_k"], 3) == 0.892
    assert round(baseline["result"]["recall_at_k"], 3) == 0.417


# sha256 of dataset/eval_queries.json as of the v2 work; it is the historical baseline and must not change.
_V1_HASH = "b6d02ed0d730980885d5d784c755c5e3c9fcdfb5c7363eb2dbc39aba20214676"
