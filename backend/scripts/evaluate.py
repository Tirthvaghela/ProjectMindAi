"""Measure retrieval quality against labelled queries.

    cd backend
    venv\\Scripts\\python -m scripts.evaluate                          # v1 labels, whole catalogue (legacy default)
    venv\\Scripts\\python -m scripts.evaluate --dataset v2             # v2 labels, 868-project catalogue
    venv\\Scripts\\python -m scripts.evaluate --dataset v1 --max-project 500 --technology-weight 0
                                                                      # reproduce the historical 500-project baseline
    venv\\Scripts\\python -m scripts.evaluate --dataset v2 --sweep --json out.json
    venv\\Scripts\\python -m scripts.evaluate --dataset v2 --sweep-json reports/eval_v2_sweep.json

This is what "NLP accuracy testing" actually means: a fixed set of queries with
known-correct answers, scored with standard information-retrieval metrics.
Eyeballing a few searches tells you nothing about whether a change helped.

Metrics
-------
All five are RETRIEVAL ranking metrics over a top-k list. They are not
classification accuracy: there is no fixed set of classes and no "negative"
prediction, only a ranked list that is right or wrong in each position.

Precision@k  Of the k results shown, what fraction are relevant? The divisor is
             always k, so a list shorter than k is penalised, not flattered.
Recall@k     Of the projects that should have been found, what fraction appeared
             in the top k? Measures coverage.
F1@k         Harmonic mean of Precision@k and Recall@k (0 when both are 0).
MRR          Mean Reciprocal Rank: 1/rank of the first relevant result. Measures
             how quickly the user sees something useful. Computed over the
             RETRIEVAL_DEPTH (10) results the evaluation retrieves, NOT only the
             top k: a first hit at rank 7 scores 1/7; no hit in the 10 scores 0.
nDCG@k       Rewards putting relevant results high, discounted logarithmically
             by position, then normalised against the ideal ordering.

Conventions shared by every metric: one relevance set per query (v2 "lenient":
grade >= 1, labels taken at face value, unless a view says otherwise); a result
id that appears twice is counted once, at its first position; a query with NO
relevant projects scores 0 on every metric (never a division by zero) and stays
in the denominator, so macro averages are over ALL queries and the count of such
queries is reported alongside. Every number is computed per query first and then
macro-averaged (each query weighs the same however many relevant projects it has).

Datasets
--------
v1  dataset/eval_queries.json — binary labels made over the original 500
    projects. Kept unchanged as the historical baseline. Run against a larger
    catalogue it undercounts: a good project it never judged counts as a miss.
v2  dataset/eval/eval_queries_v2.json — graded (0/1/2) labels over the
    868-project catalogue, built by pooling several systems and reviewing the
    candidates blind (see scripts/eval_dataset.py and dataset/eval/README.md).
    Reported three ways: lenient (grade >= 1, closest to how v1 labelled),
    strict (grade 2) and graded nDCG; each with a low/high band that treats
    the annotator's `uncertain` labels as wrong in one direction and then the
    other. `judged@k` says how many of a system's top-k were ever reviewed, so
    a system that surfaces projects the pool never saw can be recognised.

--sweep re-runs the whole evaluation across dense/sparse weightings, which is
how the DENSE_WEIGHT / SPARSE_WEIGHT defaults should be chosen: by measurement,
not intuition. It also produces the ablation table for the project report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Optional

import config
from db import client as db
from nlp import embeddings
from nlp.similarity import HybridRetriever

logging.disable(logging.INFO)

EVAL_FILE = config.DATASET_DIR / "eval_queries.json"
EVAL_V2_FILE = config.DATASET_DIR / "eval" / "eval_queries_v2.json"

# How many results every query retrieves. Precision/Recall/F1/nDCG look only at
# the top k of these; MRR looks at all of them (see the module docstring).
RETRIEVAL_DEPTH = 10
# The dense weights the ablation visits (sparse = 1 - dense).
SWEEP_DENSE_WEIGHTS = (0.0, 0.2, 0.35, 0.5, 0.65, 0.8, 1.0)


# --- metric primitives ---------------------------------------------------------


def load_queries() -> list[dict]:
    if not EVAL_FILE.exists():
        raise SystemExit(f"Missing labelled queries: {EVAL_FILE}")
    return json.loads(EVAL_FILE.read_text(encoding="utf-8"))


def load_v2(path: Path = EVAL_V2_FILE) -> dict:
    if not path.exists():
        raise SystemExit(f"Missing v2 evaluation dataset: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def unique_ranked(ranked: list[str]) -> list[str]:
    """`ranked` with repeats removed, keeping each id's first position. A
    ranking never legitimately lists a project twice; if one does, the repeat
    must not earn credit a second time."""
    return list(dict.fromkeys(ranked))


def precision_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    """Relevant results in the top k, divided by k (not by how many came back)."""
    if k <= 0:
        return 0.0
    return len(set(unique_ranked(ranked)[:k]) & relevant) / k


def recall_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    return len(set(unique_ranked(ranked)[:k]) & relevant) / len(relevant)


def f1_score(precision: float, recall: float) -> float:
    total = precision + recall
    return 2 * precision * recall / total if total > 0 else 0.0


def f1_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    return f1_score(precision_at_k(ranked, relevant, k), recall_at_k(ranked, relevant, k))


def reciprocal_rank(ranked: list[str], relevant: set[str]) -> float:
    for position, pid in enumerate(unique_ranked(ranked), start=1):
        if pid in relevant:
            return 1.0 / position
    return 0.0


def ndcg_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    # Binary relevance, so gain is 1 for a hit and 0 otherwise.
    dcg = sum(
        1.0 / math.log2(position + 1)
        for position, pid in enumerate(unique_ranked(ranked)[:k], start=1)
        if pid in relevant
    )
    ideal = sum(
        1.0 / math.log2(position + 1)
        for position in range(1, min(len(relevant), k) + 1)
    )
    return dcg / ideal if ideal else 0.0


def score_ranking(ranked: list[str], relevant: set[str], k: int) -> dict[str, float]:
    """All five metrics for ONE query, from the same ranking and relevance set."""
    precision = precision_at_k(ranked, relevant, k)
    recall = recall_at_k(ranked, relevant, k)
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1_score(precision, recall),
        "mrr": reciprocal_rank(ranked, relevant),
        "ndcg": ndcg_at_k(ranked, relevant, k),
    }


def graded_ndcg_at_k(ranked: list[str], grades: dict[str, int], k: int) -> float:
    """nDCG with the 0/1/2 grade itself as the gain (linear), normalised by the
    best ordering of the judged items."""
    dcg = sum(
        grades.get(pid, 0) / math.log2(position + 1)
        for position, pid in enumerate(ranked[:k], start=1)
    )
    best = sorted(grades.values(), reverse=True)[:k]
    ideal = sum(g / math.log2(position + 1) for position, g in enumerate(best, start=1))
    return dcg / ideal if ideal else 0.0


# --- v1 --------------------------------------------------------------------------


def evaluate(retriever: HybridRetriever, queries: list[dict], k: int = 5) -> dict:
    totals = {"precision": 0.0, "recall": 0.0, "f1": 0.0, "mrr": 0.0, "ndcg": 0.0}
    per_query = []

    for item in queries:
        relevant = set(item["relevant"])
        results = retriever.search(item["query"], top_k=RETRIEVAL_DEPTH)
        ranked = [r.project_id for r in results]

        scores = score_ranking(ranked, relevant, k)
        for key in totals:
            totals[key] += scores[key]

        per_query.append({"query": item["query"], "top1": ranked[0] if ranked else None, **scores})

    count = len(queries) or 1
    return {
        "precision_at_k": totals["precision"] / count,
        "recall_at_k": totals["recall"] / count,
        "f1_at_k": totals["f1"] / count,
        "mrr": totals["mrr"] / count,
        "ndcg_at_k": totals["ndcg"] / count,
        "queries_without_relevant": sum(1 for item in queries if not item["relevant"]),
        "per_query": per_query,
        "k": k,
    }


# --- v2 --------------------------------------------------------------------------


def relevant_set(query: dict, threshold: int, bound: str = "point") -> set[str]:
    """Projects counted relevant at `threshold` (1 = lenient, 2 = strict).

    bound "point" takes every grade at face value; "low" drops the uncertain
    items that would count as relevant; "high" also counts uncertain items one
    grade below the threshold. Together they bracket the effect of the
    annotator's own doubt.
    """
    grades = query["grades"]
    uncertain = set(query.get("uncertain", []))
    relevant = {p for p, g in grades.items() if g >= threshold}
    if bound == "low":
        relevant -= uncertain
    elif bound == "high":
        relevant |= {p for p in uncertain if grades[p] >= threshold - 1}
    return relevant


V2_VIEWS = (("lenient", 1), ("strict", 2))
V2_BOUNDS = ("low", "point", "high")


def evaluate_v2(retriever: HybridRetriever, dataset: dict, k: int = 5) -> dict:
    """One ranking per query, scored every way v2 defines."""
    sums: dict[str, dict[str, float]] = {}
    for view, _ in V2_VIEWS:
        for bound in V2_BOUNDS:
            sums[f"{view}/{bound}"] = {"precision": 0.0, "recall": 0.0, "f1": 0.0, "mrr": 0.0, "ndcg": 0.0}
    graded_total = 0.0
    judged_total = 0.0
    per_query = []

    for query in dataset["queries"]:
        ranked = [r.project_id for r in retriever.search(query["query"], top_k=RETRIEVAL_DEPTH)]
        row: dict[str, Any] = {"query": query["query"], "top5": ranked[:5]}
        for view, threshold in V2_VIEWS:
            for bound in V2_BOUNDS:
                relevant = relevant_set(query, threshold, bound)
                scores = score_ranking(ranked, relevant, k)
                for key, value in scores.items():
                    sums[f"{view}/{bound}"][key] += value
                if bound == "point":
                    for key, value in scores.items():
                        row[f"{view}_{key}"] = value
        row["graded_ndcg"] = graded_ndcg_at_k(ranked, query["grades"], k)
        row["judged_at_k"] = sum(1 for p in ranked[:k] if p in query["grades"]) / max(1, min(k, len(ranked)))
        graded_total += row["graded_ndcg"]
        judged_total += row["judged_at_k"]
        per_query.append(row)

    n = len(dataset["queries"]) or 1
    metrics = {
        name: {
            "precision_at_k": s["precision"] / n,
            "recall_at_k": s["recall"] / n,
            "f1_at_k": s["f1"] / n,
            "mrr": s["mrr"] / n,
            "ndcg_at_k": s["ndcg"] / n,
        }
        for name, s in sums.items()
    }
    return {
        "k": k,
        "queries_without_relevant": sum(1 for q in dataset["queries"] if not relevant_set(q, 1)),
        "metrics": metrics,
        "graded_ndcg_at_k": graded_total / n,
        "judged_at_k": judged_total / n,
        "per_query": per_query,
    }


# --- retriever -------------------------------------------------------------------


def _project_number(project_id: str) -> int:
    match = re.match(r"^pm-(\d+)$", project_id)
    return int(match.group(1)) if match else 10**9


def build_retriever(max_project: Optional[int] = None) -> HybridRetriever:
    """The retriever over the stored index and database. `max_project`
    restricts it to pm-001..pm-<max_project>, which is how the historical
    500-project catalogue is reproduced without needing the old database."""
    matrix, ids = embeddings.load_index()
    documents = {doc["project_id"]: doc for doc in db.projects().find({}, {"_id": 0})}
    if max_project is not None:
        keep = [i for i, pid in enumerate(ids) if _project_number(pid) <= max_project]
        matrix = matrix[keep]
        ids = [ids[i] for i in keep]
        documents = {pid: documents[pid] for pid in ids}
    return HybridRetriever(matrix, ids, documents)


def configuration() -> dict[str, Any]:
    return {
        "dense_weight": config.DENSE_WEIGHT,
        "sparse_weight": config.SPARSE_WEIGHT,
        "technology_weight": config.TECHNOLOGY_WEIGHT,
        "embedding_model": config.EMBEDDING_MODEL,
    }


def _stderr(values: list[float]) -> float:
    """Standard error of the macro average: how far the mean of THIS query set
    could plausibly sit from the mean of another one. Not a significance test."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1)) / math.sqrt(n)


def _sweep_label(dense: float) -> str:
    if dense <= 0.0:
        return "sparse only (BM25)"
    if dense >= 1.0:
        return "dense only (embeddings)"
    return "hybrid"


def _v2_row(dense: float, sparse: float, full: dict) -> dict[str, Any]:
    """One weighting's results from a v2 evaluation: the lenient point estimate
    (the headline), its uncertainty bounds, and the stricter views."""
    lenient = full["metrics"]["lenient/point"]
    rows = full["per_query"]
    return {
        "dense_weight": dense,
        "sparse_weight": sparse,
        "label": _sweep_label(dense),
        "precision_at_k": lenient["precision_at_k"],
        "recall_at_k": lenient["recall_at_k"],
        "f1_at_k": lenient["f1_at_k"],
        "mrr": lenient["mrr"],
        "ndcg_at_k": lenient["ndcg_at_k"],
        "stderr": {
            "f1_at_k": _stderr([r["lenient_f1"] for r in rows]),
            "ndcg_at_k": _stderr([r["lenient_ndcg"] for r in rows]),
        },
        "bands": {
            name: {"f1_at_k": full["metrics"][name]["f1_at_k"], "ndcg_at_k": full["metrics"][name]["ndcg_at_k"]}
            for name in ("lenient/low", "lenient/high")
        },
        "strict": {key: full["metrics"]["strict/point"][key] for key in ("precision_at_k", "recall_at_k", "f1_at_k", "mrr", "ndcg_at_k")},
        "graded_ndcg_at_k": full["graded_ndcg_at_k"],
        "judged_at_k": full["judged_at_k"],
        "queries_without_relevant": full["queries_without_relevant"],
        "per_query": [
            {"query": r["query"], **{key: r[f"lenient_{key}"] for key in ("precision", "recall", "f1", "mrr", "ndcg")}}
            for r in rows
        ],
    }


def run_sweep(retriever: HybridRetriever, queries: list[dict], k: int, dataset: Optional[dict] = None) -> list[dict]:
    """Ablation across dense/sparse weightings. Prints the table and returns the
    rows (v2 only; the v1 sweep has fewer metrics and returns an empty list).

    Mutates config at runtime, which is acceptable in a one-shot offline script
    and keeps the retriever (and its BM25 index) from being rebuilt each time.
    The technology weight is left at its configured value, because the sweep is
    meant to describe the system as the application runs it; it only touches
    queries that name a known technology.
    """
    original = (config.DENSE_WEIGHT, config.SPARSE_WEIGHT)

    header = f"{'dense':>7} {'sparse':>7} | {'P@%d' % k:>6} {'R@%d' % k:>6} {'F1@%d' % k:>6} {'MRR':>6} {'nDCG@%d' % k:>7}"
    if dataset:
        header += f" | {'strict nDCG':>11} {'graded nDCG':>11}"
    print("\n" + header)
    print("-" * len(header))

    rows: list[dict] = []
    best_ndcg = best_f1 = None
    try:
        for dense in SWEEP_DENSE_WEIGHTS:
            config.DENSE_WEIGHT = dense
            config.SPARSE_WEIGHT = round(1.0 - dense, 2)

            if dataset:
                full = evaluate_v2(retriever, dataset, k=k)
                row = _v2_row(dense, config.SPARSE_WEIGHT, full)
                rows.append(row)
                result = row
                extra = f" | {row['strict']['ndcg_at_k']:>11.3f} {row['graded_ndcg_at_k']:>11.3f}"
            else:
                result = evaluate(retriever, queries, k=k)
                extra = ""
            label = {0.0: "  <- BM25 only", 1.0: "  <- embeddings only"}.get(dense, "")
            if abs(dense - original[0]) < 1e-9:
                label += "  [configured]"

            print(
                f"{dense:>7.2f} {config.SPARSE_WEIGHT:>7.2f} | "
                f"{result['precision_at_k']:>6.3f} {result['recall_at_k']:>6.3f} {result['f1_at_k']:>6.3f} "
                f"{result['mrr']:>6.3f} {result['ndcg_at_k']:>7.3f}{extra}{label}"
            )

            if best_ndcg is None or result["ndcg_at_k"] > best_ndcg[1]:
                best_ndcg = (dense, result["ndcg_at_k"])
            if best_f1 is None or result["f1_at_k"] > best_f1[1]:
                best_f1 = (dense, result["f1_at_k"])
    finally:
        config.DENSE_WEIGHT, config.SPARSE_WEIGHT = original

    print("-" * len(header))
    print(f"Best F1@{k}   at dense={best_f1[0]:.2f} / sparse={1 - best_f1[0]:.2f}")
    print(f"Best nDCG@{k} at dense={best_ndcg[0]:.2f} / sparse={1 - best_ndcg[0]:.2f}")
    print(f"Currently configured: dense={original[0]:.2f} / sparse={original[1]:.2f}")
    return rows


def metric_ceiling(dataset: dict, k: int) -> dict[str, float]:
    """The best any ranking could score, from the labels alone: put every
    relevant project (up to k) first. Precision/Recall/F1 at k are bounded by
    this because a query with more than k relevant projects can never reach
    Recall@k = 1, so a low F1@k does not by itself mean poor retrieval."""
    counts = [len(relevant_set(q, 1)) for q in dataset["queries"]]
    scored = [score_ranking(sorted(relevant_set(q, 1))[:k], relevant_set(q, 1), k) for q in dataset["queries"]]
    n = len(scored) or 1
    return {
        "mean_relevant_per_query": sum(counts) / n,
        "min_relevant_per_query": min(counts, default=0),
        "max_relevant_per_query": max(counts, default=0),
        "precision_at_k": sum(r["precision"] for r in scored) / n,
        "recall_at_k": sum(r["recall"] for r in scored) / n,
        "f1_at_k": sum(r["f1"] for r in scored) / n,
        "mrr": sum(r["mrr"] for r in scored) / n,
        "ndcg_at_k": sum(r["ndcg"] for r in scored) / n,
    }


def _best(rows: list[dict], key: str) -> dict[str, Any]:
    top = max(row[key] for row in rows)
    winners = [row for row in rows if row[key] >= top - 1e-12]
    return {
        "value": top,
        "dense_weights": [row["dense_weight"] for row in winners],
        "tied": len(winners) > 1,
    }


def _package_version(name: str) -> Optional[str]:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _git_commit() -> dict[str, Any]:
    try:
        root = Path(__file__).resolve().parents[2]
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=10).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain", "--", "backend"], cwd=root, capture_output=True, text=True, timeout=10).stdout.strip())
        return {"commit": commit or None, "backend_has_uncommitted_changes": dirty}
    except Exception:  # noqa: BLE001 - metadata only; never fail an evaluation over it
        return {"commit": None, "backend_has_uncommitted_changes": None}


def build_sweep_payload(
    rows: list[dict],
    production: dict,
    dataset: dict,
    snapshot: dict,
    k: int,
    retriever: HybridRetriever,
    dataset_path: Path,
    command: str,
) -> dict[str, Any]:
    """The machine-readable sweep: metadata, one row per weighting, the
    configured production weighting measured on its own, and which rows win."""
    cfg = configuration()
    prod_row = _v2_row(cfg["dense_weight"], cfg["sparse_weight"], production)
    return {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "command": command,
            "catalogue": snapshot,
            "index_projects": len(retriever.ids),
            "dataset": {
                "version": dataset["version"],
                "path": str(dataset_path),
                "sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
                "queries": len(dataset["queries"]),
                "labels": "graded 0/1/2 with an uncertainty flag; single AI annotator, no independent review",
            },
            "metric_cutoff_k": k,
            "mrr_cutoff": RETRIEVAL_DEPTH,
            "relevance_rule": "lenient point estimate: a project is relevant when its grade is >= 1, uncertain labels at face value",
            "aggregation": "per-query score, then macro average over all queries; a query with no relevant projects scores 0 and stays in the denominator",
            "duplicate_results": "a repeated project id is counted once, at its first position",
            "weight_configurations": [{"dense": d, "sparse": round(1.0 - d, 2)} for d in SWEEP_DENSE_WEIGHTS],
            "retrieval": {
                "call": f"HybridRetriever.search(query, top_k={RETRIEVAL_DEPTH})",
                "filters": None,
                "personalisation_profile": None,
                "technology_match": True,
                "technology_weight_in_sweep": config.TECHNOLOGY_WEIGHT,
                "note": "same HybridRetriever class, index and database the application uses; the sweep changes only DENSE_WEIGHT and SPARSE_WEIGHT",
            },
            "configuration": cfg,
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "numpy": _package_version("numpy"),
                "sentence-transformers": _package_version("sentence-transformers"),
                "rank-bm25": _package_version("rank-bm25"),
                "source": _git_commit(),
            },
        },
        "ceiling": {
            "definition": "mean score of a perfect ranking (all relevant projects first) under the same labels and cutoff; an upper bound, not a target",
            **metric_ceiling(dataset, k),
        },
        "production": {**prod_row, "note": "the configured weighting, measured by its own run with the application's configuration"},
        "sweep": [{**row, "is_production": abs(row["dense_weight"] - cfg["dense_weight"]) < 1e-9} for row in rows],
        "summary": {
            "best_f1_at_k": _best(rows, "f1_at_k"),
            "best_ndcg_at_k": _best(rows, "ndcg_at_k"),
        },
    }


def _print_v2(result: dict, k: int) -> None:
    print(f"\n{'view':<10}{'bound':<7}{'P@%d' % k:>8}{'R@%d' % k:>8}{'F1@%d' % k:>8}{'MRR':>8}{'nDCG@%d' % k:>9}")
    print("-" * 58)
    for view, _ in V2_VIEWS:
        for bound in V2_BOUNDS:
            m = result["metrics"][f"{view}/{bound}"]
            print(f"{view:<10}{bound:<7}{m['precision_at_k']:>8.3f}{m['recall_at_k']:>8.3f}{m['f1_at_k']:>8.3f}{m['mrr']:>8.3f}{m['ndcg_at_k']:>9.3f}")
    print("-" * 58)
    print(f"graded nDCG@{k} (gain = grade 0/1/2): {result['graded_ndcg_at_k']:.3f}")
    print(f"judged@{k} (share of top-{k} results that were ever reviewed): {result['judged_at_k']:.3f}")


def snapshot_problem(dataset: dict, snapshot: dict) -> Optional[str]:
    """Why `dataset` cannot be used against the catalogue described by
    `snapshot`, or None when it can."""
    if snapshot["sha256"] == dataset["catalogue"]["sha256"]:
        return None
    return (
        f"The catalogue ({snapshot['project_count']} projects, {snapshot['sha256'][:12]}) is not the one "
        f"{dataset['version']} was labelled against ({dataset['catalogue']['project_count']} projects, "
        f"{dataset['catalogue']['sha256'][:12]}). Labels for projects added since are missing; build a new "
        f"dataset version (scripts/eval_next_version.py) rather than compare these numbers."
    )


def compare_reports(a: dict, b: dict) -> dict[str, Any]:
    """Whether two saved evaluation reports (--json output) may be compared, and
    why not. Numbers from different label sets or catalogues are different
    quantities: a project nobody judged counts as a miss, so a bigger catalogue
    lowers a score without the ranker getting worse."""
    reasons = []
    if a["dataset"] != b["dataset"]:
        reasons.append(f"different label sets ({a['dataset']} vs {b['dataset']}): each version has its own relevance judgements")
    if a["catalogue"]["sha256"] != b["catalogue"]["sha256"]:
        reasons.append(
            f"different catalogues ({a['catalogue']['project_count']} vs {b['catalogue']['project_count']} projects): "
            "projects the labels never saw are counted as not relevant"
        )
    config_diff = {k: (a["configuration"].get(k), b["configuration"].get(k)) for k in set(a["configuration"]) | set(b["configuration"]) if a["configuration"].get(k) != b["configuration"].get(k)}
    return {
        "comparable": not reasons,
        "reasons": reasons,
        "configuration_differences": config_diff,
        "advice": (
            "Compare the two configurations directly: same labels, same catalogue."
            if not reasons
            else "Do not subtract these numbers. To compare rankers across a catalogue change, evaluate BOTH on the new dataset version."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate retrieval quality.")
    parser.add_argument("--k", type=int, default=5, help="Cutoff for Recall/nDCG.")
    parser.add_argument("--dataset", default="v1", help="v1 (default), v2, or a path to a dataset JSON.")
    parser.add_argument("--max-project", type=int, help="Restrict the catalogue to pm-001..pm-N.")
    parser.add_argument("--technology-weight", type=float, help="Override TECHNOLOGY_WEIGHT (0 disables it).")
    parser.add_argument("--allow-snapshot-mismatch", action="store_true", help="Evaluate v2 even if the catalogue changed.")
    parser.add_argument("--sweep", action="store_true", help="Ablate dense/sparse weights.")
    parser.add_argument("--sweep-json", type=Path, help="Run the sweep (v2 only) and write the full machine-readable report here.")
    parser.add_argument("--verbose", action="store_true", help="Show per-query scores.")
    parser.add_argument("--json", type=Path, help="Write results, configuration and snapshot to this file.")
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("A.json", "B.json"), help="Say whether two saved reports are comparable.")
    args = parser.parse_args()

    if args.compare:
        verdict = compare_reports(*[json.loads(p.read_text(encoding="utf-8")) for p in args.compare])
        print(json.dumps(verdict, indent=2))
        return 0 if verdict["comparable"] else 3

    if not db.ping():
        print(f"Cannot reach MongoDB at {config.MONGO_URI}")
        return 1

    if args.technology_weight is not None:
        config.TECHNOLOGY_WEIGHT = args.technology_weight

    dataset: Optional[dict] = None
    if args.dataset == "v1":
        queries = load_queries()
    else:
        dataset = load_v2(EVAL_V2_FILE if args.dataset == "v2" else Path(args.dataset))
        queries = dataset["queries"]

    retriever = build_retriever(args.max_project)

    from scripts.eval_dataset import catalogue_snapshot

    snapshot = catalogue_snapshot(retriever.documents)
    problem = snapshot_problem(dataset, snapshot) if dataset is not None else None
    if problem:
        if not args.allow_snapshot_mismatch:
            print(problem)
            return 2
        print("WARNING:", problem)

    print(f"Evaluating {len(queries)} labelled queries over {len(retriever.ids)} projects "
          f"(dataset {dataset['version'] if dataset else 'v1'})")
    cfg = configuration()
    print(f"Configuration: dense={cfg['dense_weight']}, sparse={cfg['sparse_weight']}, technology={cfg['technology_weight']}")

    if dataset:
        result = evaluate_v2(retriever, dataset, k=args.k)
        _print_v2(result, args.k)
        if args.verbose:
            print(f"\n{'query':<48}{'lenient':>8}{'strict':>8}{'graded':>8}{'judged':>8}")
            print("-" * 80)
            for row in sorted(result["per_query"], key=lambda r: r["lenient_ndcg"]):
                print(f"{row['query'][:46]:<48}{row['lenient_ndcg']:>8.2f}{row['strict_ndcg']:>8.2f}"
                      f"{row['graded_ndcg']:>8.2f}{row['judged_at_k']:>8.2f}")
    else:
        result = evaluate(retriever, queries, k=args.k)
        print(f"\n--- Current configuration (dense={config.DENSE_WEIGHT}, sparse={config.SPARSE_WEIGHT}) ---")
        print(f"  Precision@{args.k}: {result['precision_at_k']:.3f}")
        print(f"  Recall@{args.k} : {result['recall_at_k']:.3f}")
        print(f"  F1@{args.k}     : {result['f1_at_k']:.3f}")
        print(f"  MRR       : {result['mrr']:.3f}")
        print(f"  nDCG@{args.k}   : {result['ndcg_at_k']:.3f}")
        if args.verbose:
            print(f"\n{'query':<48}{'MRR':>6}{'nDCG':>7}")
            print("-" * 61)
            for row in sorted(result["per_query"], key=lambda r: r["mrr"]):
                print(f"{row['query'][:46]:<48}{row['mrr']:>6.2f}{row['ndcg']:>7.2f}")

    if args.sweep or args.sweep_json:
        if args.sweep_json and dataset is None:
            print("--sweep-json needs a v2 dataset (--dataset v2).")
            return 1
        # Measured with the application's own configuration BEFORE the sweep touches it.
        production = evaluate_v2(retriever, dataset, k=args.k) if dataset else None
        rows = run_sweep(retriever, queries, k=args.k, dataset=dataset)
        if args.sweep_json:
            dataset_path = EVAL_V2_FILE if args.dataset == "v2" else Path(args.dataset)
            payload = build_sweep_payload(
                rows, production, dataset, snapshot, args.k, retriever, dataset_path,
                command="python -m scripts.evaluate " + " ".join(sys.argv[1:]),
            )
            args.sweep_json.parent.mkdir(parents=True, exist_ok=True)
            args.sweep_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            print(f"\nSweep written to {args.sweep_json}")

    if args.json:
        payload = {
            "dataset": dataset["version"] if dataset else "v1",
            "k": args.k,
            "configuration": cfg,
            "catalogue": snapshot,
            "max_project": args.max_project,
            "result": result,
        }
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"\nResults written to {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
