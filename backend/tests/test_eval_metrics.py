"""Precision@k, Recall@k, F1@k, MRR and nDCG@k, and the structured sweep built on them.

These are retrieval-ranking metrics, checked here against hand computations on
tiny cases so a formula change cannot slip through as a "different number".
"""

from __future__ import annotations

import json
import math

import pytest

import config
from scripts import evaluate as ev


def _dcg(positions):
    return sum(1 / math.log2(p + 1) for p in positions)


# --- single-query formulas ------------------------------------------------------------


def test_every_metric_matches_a_hand_computation():
    ranked = ["a", "x", "b", "y", "z", "c"]  # relevant at ranks 1, 3 and 6
    relevant = {"a", "b", "c", "d"}
    scores = ev.score_ranking(ranked, relevant, 5)
    precision, recall = 2 / 5, 2 / 4  # a and b are inside the top 5; c (rank 6) is not
    assert scores["precision"] == pytest.approx(precision)
    assert scores["recall"] == pytest.approx(recall)
    assert scores["f1"] == pytest.approx(2 * precision * recall / (precision + recall))
    assert scores["mrr"] == pytest.approx(1.0)
    assert scores["ndcg"] == pytest.approx(_dcg([1, 3]) / _dcg([1, 2, 3, 4]))


def test_mrr_uses_the_whole_retrieved_list_not_only_the_top_k():
    ranked = ["x1", "x2", "x3", "x4", "x5", "x6", "hit"]  # first relevant at rank 7
    assert ev.reciprocal_rank(ranked, {"hit"}) == pytest.approx(1 / 7)
    assert ev.precision_at_k(ranked, {"hit"}, 5) == 0.0  # outside the top 5
    assert ev.reciprocal_rank(ranked, {"nothing-here"}) == 0.0


def test_perfect_and_empty_rankings():
    relevant = {"a", "b", "c", "d", "e"}
    perfect = ev.score_ranking(["a", "b", "c", "d", "e"], relevant, 5)
    assert perfect == {key: pytest.approx(1.0) for key in ("precision", "recall", "f1", "mrr", "ndcg")}
    nothing = ev.score_ranking(["x", "y", "z"], relevant, 5)
    assert nothing == {key: 0.0 for key in ("precision", "recall", "f1", "mrr", "ndcg")}


def test_f1_is_zero_when_both_precision_and_recall_are_zero_and_never_divides_by_zero():
    assert ev.f1_score(0.0, 0.0) == 0.0
    assert ev.f1_score(1.0, 0.0) == 0.0
    assert ev.f1_score(0.5, 0.5) == pytest.approx(0.5)
    assert ev.f1_at_k(["x"], {"a"}, 5) == 0.0


def test_f1_is_the_harmonic_mean_not_the_average():
    # 5 results, all relevant, but the query has 50 relevant projects: precision 1, recall 0.1.
    relevant = {f"p{i}" for i in range(50)}
    ranked = [f"p{i}" for i in range(5)]
    assert ev.precision_at_k(ranked, relevant, 5) == pytest.approx(1.0)
    assert ev.recall_at_k(ranked, relevant, 5) == pytest.approx(0.1)
    assert ev.f1_at_k(ranked, relevant, 5) == pytest.approx(2 * 1.0 * 0.1 / 1.1)  # 0.182, not 0.55


# --- queries with no relevant results -------------------------------------------------


def test_a_query_with_no_relevant_projects_scores_zero_everywhere_without_error():
    scores = ev.score_ranking(["a", "b", "c", "d", "e"], set(), 5)
    assert scores == {key: 0.0 for key in ("precision", "recall", "f1", "mrr", "ndcg")}
    assert all(math.isfinite(v) for v in scores.values())


def test_no_results_at_all_is_handled():
    assert ev.score_ranking([], {"a"}, 5) == {key: 0.0 for key in ("precision", "recall", "f1", "mrr", "ndcg")}
    assert ev.score_ranking([], set(), 5)["f1"] == 0.0


# --- fewer than k results, duplicates, cutoffs ----------------------------------------


def test_fewer_than_k_results_are_penalised_because_precision_divides_by_k():
    # Two results, both relevant: Precision@5 is 2/5, not 2/2.
    assert ev.precision_at_k(["a", "b"], {"a", "b", "c"}, 5) == pytest.approx(2 / 5)
    assert ev.recall_at_k(["a", "b"], {"a", "b", "c"}, 5) == pytest.approx(2 / 3)
    assert ev.ndcg_at_k(["a", "b"], {"a", "b", "c"}, 5) == pytest.approx(_dcg([1, 2]) / _dcg([1, 2, 3]))


def test_a_repeated_result_earns_credit_once_at_its_first_position():
    ranked = ["a", "a", "a", "b", "c", "d"]
    relevant = {"a", "b"}
    assert ev.unique_ranked(ranked) == ["a", "b", "c", "d"]
    assert ev.precision_at_k(ranked, relevant, 5) == pytest.approx(2 / 5)  # not 4/5
    assert ev.recall_at_k(ranked, relevant, 5) == pytest.approx(1.0)
    assert ev.ndcg_at_k(ranked, relevant, 5) == pytest.approx(1.0)  # a, b at ranks 1, 2: ideal
    assert ev.reciprocal_rank(["x", "x", "b"], {"b"}) == pytest.approx(1 / 2)
    assert ev.ndcg_at_k(ranked, relevant, 5) <= 1.0


def test_the_cutoff_changes_precision_and_recall_but_not_mrr():
    ranked = ["x", "a", "b", "y", "z", "c"]
    relevant = {"a", "b", "c"}
    assert ev.precision_at_k(ranked, relevant, 2) == pytest.approx(1 / 2)
    assert ev.precision_at_k(ranked, relevant, 6) == pytest.approx(3 / 6)
    assert ev.recall_at_k(ranked, relevant, 3) == pytest.approx(2 / 3)
    assert ev.reciprocal_rank(ranked, relevant) == pytest.approx(1 / 2)


def test_a_non_positive_k_cannot_divide_by_zero():
    assert ev.precision_at_k(["a"], {"a"}, 0) == 0.0
    assert ev.ndcg_at_k(["a"], {"a"}, 0) == 0.0


def test_ndcg_never_exceeds_one_and_orders_better_rankings_higher():
    relevant = {"a", "b", "c"}
    best = ev.ndcg_at_k(["a", "b", "c", "x", "y"], relevant, 5)
    worse = ev.ndcg_at_k(["x", "a", "b", "c", "y"], relevant, 5)
    worst = ev.ndcg_at_k(["x", "y", "a", "b", "c"], relevant, 5)
    assert best == pytest.approx(1.0)
    assert best > worse > worst > 0.0


# --- macro averaging over queries -----------------------------------------------------


class _Result:
    def __init__(self, pid):
        self.project_id = pid


class _PerQueryRetriever:
    """Returns a fixed ranking per query text, so scoring is isolated from retrieval."""

    def __init__(self, rankings):
        self.rankings = rankings
        self.ids = ["a", "b", "c", "d", "e", "f"]
        self.calls = []

    def search(self, query, top_k=10, **kwargs):
        self.calls.append((query, top_k, kwargs))
        return [_Result(p) for p in self.rankings[query][:top_k]]


DATASET = {
    "version": "test",
    "queries": [
        {"query": "q1", "grades": {"a": 2, "b": 1, "c": 0}, "uncertain": []},
        {"query": "q2", "grades": {"d": 2, "e": 2}, "uncertain": []},
        {"query": "q3", "grades": {"f": 0}, "uncertain": []},  # nothing relevant: still in the average
    ],
}
RANKINGS = {"q1": ["a", "b", "x", "y", "z"], "q2": ["x", "d", "y", "z", "w"], "q3": ["a", "b", "c", "d", "e"]}


def test_macro_average_is_the_mean_of_per_query_scores_including_empty_queries():
    retriever = _PerQueryRetriever(RANKINGS)
    result = ev.evaluate_v2(retriever, DATASET, k=5)
    lenient = result["metrics"]["lenient/point"]
    q1 = ev.score_ranking(RANKINGS["q1"], {"a", "b"}, 5)
    q2 = ev.score_ranking(RANKINGS["q2"], {"d", "e"}, 5)
    for key, name in (("precision", "precision_at_k"), ("recall", "recall_at_k"), ("f1", "f1_at_k"), ("mrr", "mrr"), ("ndcg", "ndcg_at_k")):
        assert lenient[name] == pytest.approx((q1[key] + q2[key] + 0.0) / 3)  # q3 scores 0, divisor is 3
    assert result["queries_without_relevant"] == 1
    assert retriever.calls[0][1] == ev.RETRIEVAL_DEPTH  # every query retrieves the same depth
    assert all(call[2] == {} for call in retriever.calls)  # no filters, no profile: the plain search


def test_per_query_rows_carry_every_metric():
    result = ev.evaluate_v2(_PerQueryRetriever(RANKINGS), DATASET, k=5)
    row = result["per_query"][0]
    for key in ("precision", "recall", "f1", "mrr", "ndcg"):
        assert row[f"lenient_{key}"] == pytest.approx(ev.score_ranking(RANKINGS["q1"], {"a", "b"}, 5)[key])


def test_v1_evaluation_reports_the_new_metrics_too():
    queries = [{"query": "q1", "relevant": ["a", "b"]}, {"query": "q3", "relevant": []}]
    result = ev.evaluate(_PerQueryRetriever(RANKINGS), queries, k=5)
    assert result["precision_at_k"] == pytest.approx((2 / 5 + 0) / 2)
    assert result["f1_at_k"] == pytest.approx((ev.f1_at_k(RANKINGS["q1"], {"a", "b"}, 5) + 0) / 2)
    assert result["queries_without_relevant"] == 1


# --- the structured sweep -------------------------------------------------------------


def test_sweep_rows_cover_every_weight_restore_config_and_mark_the_configured_one(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "DENSE_WEIGHT", 0.8)
    monkeypatch.setattr(config, "SPARSE_WEIGHT", 0.2)
    seen = []

    class _Recording(_PerQueryRetriever):
        def search(self, query, top_k=10, **kwargs):
            seen.append((config.DENSE_WEIGHT, config.SPARSE_WEIGHT))
            return super().search(query, top_k=top_k, **kwargs)

    retriever = _Recording(RANKINGS)
    production = ev.evaluate_v2(retriever, DATASET, k=5)
    rows = ev.run_sweep(retriever, DATASET["queries"], k=5, dataset=DATASET)
    capsys.readouterr()

    assert [r["dense_weight"] for r in rows] == list(ev.SWEEP_DENSE_WEIGHTS)
    assert [r["sparse_weight"] for r in rows] == [round(1 - d, 2) for d in ev.SWEEP_DENSE_WEIGHTS]
    assert rows[0]["label"] == "sparse only (BM25)" and rows[-1]["label"] == "dense only (embeddings)"
    assert {w for w in seen} >= {(d, round(1 - d, 2)) for d in ev.SWEEP_DENSE_WEIGHTS}  # each weighting was really applied
    assert (config.DENSE_WEIGHT, config.SPARSE_WEIGHT) == (0.8, 0.2)  # restored

    dataset_file = tmp_path / "d.json"
    dataset_file.write_text(json.dumps(DATASET), encoding="utf-8")
    payload = ev.build_sweep_payload(
        rows, production, DATASET, {"project_count": 6, "sha256": "x"}, 5, retriever, dataset_file, "cmd"
    )
    assert json.loads(json.dumps(payload, allow_nan=False)) == payload  # valid JSON: no NaN or Infinity anywhere
    meta = payload["metadata"]
    assert meta["metric_cutoff_k"] == 5 and meta["mrr_cutoff"] == ev.RETRIEVAL_DEPTH
    assert meta["dataset"]["queries"] == 3 and len(meta["dataset"]["sha256"]) == 64
    assert [c["dense"] for c in meta["weight_configurations"]] == list(ev.SWEEP_DENSE_WEIGHTS)
    assert "macro average" in meta["aggregation"]
    assert [r["is_production"] for r in payload["sweep"]].count(True) == 1
    assert next(r for r in payload["sweep"] if r["is_production"])["dense_weight"] == 0.8
    assert payload["production"]["dense_weight"] == 0.8 and payload["production"]["sparse_weight"] == 0.2
    for row in payload["sweep"]:
        for key in ("precision_at_k", "recall_at_k", "f1_at_k", "mrr", "ndcg_at_k"):
            assert 0.0 <= row[key] <= 1.0 and math.isfinite(row[key])
        assert row["bands"]["lenient/low"]["f1_at_k"] <= row["bands"]["lenient/high"]["f1_at_k"] + 1e-12


def test_best_configuration_reports_ties_instead_of_picking_one():
    rows = [
        {"dense_weight": 0.0, "f1_at_k": 0.3},
        {"dense_weight": 0.5, "f1_at_k": 0.4},
        {"dense_weight": 1.0, "f1_at_k": 0.4},
    ]
    best = ev._best(rows, "f1_at_k")
    assert best == {"value": 0.4, "dense_weights": [0.5, 1.0], "tied": True}


def test_standard_error_is_zero_for_identical_scores_and_safe_for_tiny_samples():
    assert ev._stderr([0.5, 0.5, 0.5]) == 0.0
    assert ev._stderr([0.5]) == 0.0 and ev._stderr([]) == 0.0
    assert ev._stderr([0.0, 1.0]) == pytest.approx(0.5)


def test_ceiling_is_a_perfect_ranking_so_f1_at_k_is_capped_when_queries_have_more_than_k_relevant():
    dataset = {"version": "t", "queries": [
        {"query": "many", "grades": {f"p{i}": 1 for i in range(10)}, "uncertain": []},  # 10 relevant, k = 5
        {"query": "few", "grades": {"a": 2, "b": 1}, "uncertain": []},  # 2 relevant
    ]}
    ceiling = ev.metric_ceiling(dataset, 5)
    assert ceiling["precision_at_k"] == pytest.approx((1.0 + 2 / 5) / 2)
    assert ceiling["recall_at_k"] == pytest.approx((5 / 10 + 1.0) / 2)
    assert ceiling["f1_at_k"] == pytest.approx((ev.f1_score(1.0, 0.5) + ev.f1_score(0.4, 1.0)) / 2)
    assert ceiling["f1_at_k"] < 1.0 and ceiling["mrr"] == 1.0 and ceiling["ndcg_at_k"] == pytest.approx(1.0)
    assert ceiling["mean_relevant_per_query"] == 6 and ceiling["max_relevant_per_query"] == 10
    assert ev.metric_ceiling({"version": "t", "queries": []}, 5)["mean_relevant_per_query"] == 0.0
