"""Measure retrieval quality against labelled queries.

    cd backend
    venv\\Scripts\\python -m scripts.evaluate                          # v1 labels, whole catalogue (legacy default)
    venv\\Scripts\\python -m scripts.evaluate --dataset v2             # v2 labels, 868-project catalogue
    venv\\Scripts\\python -m scripts.evaluate --dataset v1 --max-project 500 --technology-weight 0
                                                                      # reproduce the historical 500-project baseline
    venv\\Scripts\\python -m scripts.evaluate --dataset v2 --sweep --json out.json

This is what "NLP accuracy testing" actually means: a fixed set of queries with
known-correct answers, scored with standard information-retrieval metrics.
Eyeballing a few searches tells you nothing about whether a change helped.

Metrics
-------
Recall@k  Of the projects that should have been found, what fraction appeared
          in the top k? Measures coverage.
MRR       Mean Reciprocal Rank — 1/rank of the first correct result. Measures
          how quickly the user sees something useful, which is what actually
          matters when only 3 results fit on screen.
nDCG@k    Rewards putting correct results high, discounted logarithmically by
          position, then normalised against the ideal ordering.

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
import json
import logging
import math
import re
from pathlib import Path
from typing import Any, Optional

import config
from db import client as db
from nlp import embeddings
from nlp.similarity import HybridRetriever

logging.disable(logging.INFO)

EVAL_FILE = config.DATASET_DIR / "eval_queries.json"
EVAL_V2_FILE = config.DATASET_DIR / "eval" / "eval_queries_v2.json"


# --- metric primitives ---------------------------------------------------------


def load_queries() -> list[dict]:
    if not EVAL_FILE.exists():
        raise SystemExit(f"Missing labelled queries: {EVAL_FILE}")
    return json.loads(EVAL_FILE.read_text(encoding="utf-8"))


def load_v2(path: Path = EVAL_V2_FILE) -> dict:
    if not path.exists():
        raise SystemExit(f"Missing v2 evaluation dataset: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def recall_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    return len(set(ranked[:k]) & relevant) / len(relevant)


def reciprocal_rank(ranked: list[str], relevant: set[str]) -> float:
    for position, pid in enumerate(ranked, start=1):
        if pid in relevant:
            return 1.0 / position
    return 0.0


def ndcg_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    # Binary relevance, so gain is 1 for a hit and 0 otherwise.
    dcg = sum(
        1.0 / math.log2(position + 1)
        for position, pid in enumerate(ranked[:k], start=1)
        if pid in relevant
    )
    ideal = sum(
        1.0 / math.log2(position + 1)
        for position in range(1, min(len(relevant), k) + 1)
    )
    return dcg / ideal if ideal else 0.0


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
    totals = {"recall": 0.0, "mrr": 0.0, "ndcg": 0.0}
    per_query = []

    for item in queries:
        relevant = set(item["relevant"])
        results = retriever.search(item["query"], top_k=10)
        ranked = [r.project_id for r in results]

        scores = {
            "recall": recall_at_k(ranked, relevant, k),
            "mrr": reciprocal_rank(ranked, relevant),
            "ndcg": ndcg_at_k(ranked, relevant, k),
        }
        for key in totals:
            totals[key] += scores[key]

        per_query.append({"query": item["query"], "top1": ranked[0] if ranked else None, **scores})

    count = len(queries) or 1
    return {
        "recall_at_k": totals["recall"] / count,
        "mrr": totals["mrr"] / count,
        "ndcg_at_k": totals["ndcg"] / count,
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
            sums[f"{view}/{bound}"] = {"recall": 0.0, "mrr": 0.0, "ndcg": 0.0}
    graded_total = 0.0
    judged_total = 0.0
    per_query = []

    for query in dataset["queries"]:
        ranked = [r.project_id for r in retriever.search(query["query"], top_k=10)]
        row: dict[str, Any] = {"query": query["query"], "top5": ranked[:5]}
        for view, threshold in V2_VIEWS:
            for bound in V2_BOUNDS:
                relevant = relevant_set(query, threshold, bound)
                scores = {
                    "recall": recall_at_k(ranked, relevant, k),
                    "mrr": reciprocal_rank(ranked, relevant),
                    "ndcg": ndcg_at_k(ranked, relevant, k),
                }
                for key, value in scores.items():
                    sums[f"{view}/{bound}"][key] += value
                if bound == "point":
                    row[f"{view}_ndcg"] = scores["ndcg"]
                    row[f"{view}_recall"] = scores["recall"]
        row["graded_ndcg"] = graded_ndcg_at_k(ranked, query["grades"], k)
        row["judged_at_k"] = sum(1 for p in ranked[:k] if p in query["grades"]) / max(1, min(k, len(ranked)))
        graded_total += row["graded_ndcg"]
        judged_total += row["judged_at_k"]
        per_query.append(row)

    n = len(dataset["queries"]) or 1
    metrics = {
        name: {"recall_at_k": s["recall"] / n, "mrr": s["mrr"] / n, "ndcg_at_k": s["ndcg"] / n}
        for name, s in sums.items()
    }
    return {
        "k": k,
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


def run_sweep(retriever: HybridRetriever, queries: list[dict], k: int, dataset: Optional[dict] = None) -> None:
    """Ablation across dense/sparse weightings.

    Mutates config at runtime, which is acceptable in a one-shot offline script
    and keeps the retriever (and its BM25 index) from being rebuilt each time.
    """
    original = (config.DENSE_WEIGHT, config.SPARSE_WEIGHT)

    header = f"{'dense':>7} {'sparse':>7} | {'Recall@%d' % k:>9} {'MRR':>7} {'nDCG@%d' % k:>8}"
    if dataset:
        header += f" | {'strict nDCG':>11} {'graded nDCG':>11}"
    print("\n" + header)
    print("-" * len(header))

    best = None
    try:
        for dense in [0.0, 0.2, 0.35, 0.5, 0.65, 0.8, 1.0]:
            config.DENSE_WEIGHT = dense
            config.SPARSE_WEIGHT = round(1.0 - dense, 2)

            if dataset:
                full = evaluate_v2(retriever, dataset, k=k)
                result = full["metrics"]["lenient/point"]
                extra = f" | {full['metrics']['strict/point']['ndcg_at_k']:>11.3f} {full['graded_ndcg_at_k']:>11.3f}"
            else:
                result = evaluate(retriever, queries, k=k)
                extra = ""
            label = ""
            if dense == 0.0:
                label = "  <- BM25 only"
            elif dense == 1.0:
                label = "  <- embeddings only"

            print(
                f"{dense:>7.2f} {config.SPARSE_WEIGHT:>7.2f} | "
                f"{result['recall_at_k']:>9.3f} {result['mrr']:>7.3f} "
                f"{result['ndcg_at_k']:>8.3f}{extra}{label}"
            )

            if best is None or result["ndcg_at_k"] > best[1]:
                best = (dense, result["ndcg_at_k"])
    finally:
        config.DENSE_WEIGHT, config.SPARSE_WEIGHT = original

    print("-" * len(header))
    print(f"Best nDCG@{k} at dense={best[0]:.2f} / sparse={1 - best[0]:.2f}")
    print(f"Currently configured: dense={original[0]:.2f} / sparse={original[1]:.2f}")


def _print_v2(result: dict, k: int) -> None:
    print(f"\n{'view':<10}{'bound':<7}{'Recall@%d' % k:>10}{'MRR':>8}{'nDCG@%d' % k:>9}")
    print("-" * 44)
    for view, _ in V2_VIEWS:
        for bound in V2_BOUNDS:
            m = result["metrics"][f"{view}/{bound}"]
            print(f"{view:<10}{bound:<7}{m['recall_at_k']:>10.3f}{m['mrr']:>8.3f}{m['ndcg_at_k']:>9.3f}")
    print("-" * 44)
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
        print(f"  Recall@{args.k} : {result['recall_at_k']:.3f}")
        print(f"  MRR       : {result['mrr']:.3f}")
        print(f"  nDCG@{args.k}   : {result['ndcg_at_k']:.3f}")
        if args.verbose:
            print(f"\n{'query':<48}{'MRR':>6}{'nDCG':>7}")
            print("-" * 61)
            for row in sorted(result["per_query"], key=lambda r: r["mrr"]):
                print(f"{row['query'][:46]:<48}{row['mrr']:>6.2f}{row['ndcg']:>7.2f}")

    if args.sweep:
        run_sweep(retriever, queries, k=args.k, dataset=dataset)

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
