"""Measure retrieval quality against labelled queries.

    cd backend
    venv\\Scripts\\python -m scripts.evaluate
    venv\\Scripts\\python -m scripts.evaluate --sweep

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

--sweep re-runs the whole evaluation across dense/sparse weightings, which is
how the DENSE_WEIGHT / SPARSE_WEIGHT defaults should be chosen: by measurement,
not intuition. It also produces the ablation table for the project report.
"""

from __future__ import annotations

import argparse
import json
import logging
import math

import config
from db import client as db
from nlp import embeddings, recommend
from nlp.similarity import HybridRetriever

logging.disable(logging.INFO)

EVAL_FILE = config.DATASET_DIR / "eval_queries.json"


def load_queries() -> list[dict]:
    if not EVAL_FILE.exists():
        raise SystemExit(f"Missing labelled queries: {EVAL_FILE}")
    return json.loads(EVAL_FILE.read_text(encoding="utf-8"))


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


def build_retriever() -> HybridRetriever:
    matrix, ids = embeddings.load_index()
    documents = {doc["project_id"]: doc for doc in db.projects().find({}, {"_id": 0})}
    return HybridRetriever(matrix, ids, documents)


def run_sweep(retriever: HybridRetriever, queries: list[dict], k: int) -> None:
    """Ablation across dense/sparse weightings.

    Mutates config at runtime, which is acceptable in a one-shot offline script
    and keeps the retriever (and its BM25 index) from being rebuilt each time.
    """
    original = (config.DENSE_WEIGHT, config.SPARSE_WEIGHT)

    print(f"\n{'dense':>7} {'sparse':>7} | {'Recall@%d' % k:>9} {'MRR':>7} {'nDCG@%d' % k:>8}")
    print("-" * 46)

    best = None
    try:
        for dense in [0.0, 0.2, 0.35, 0.5, 0.65, 0.8, 1.0]:
            config.DENSE_WEIGHT = dense
            config.SPARSE_WEIGHT = round(1.0 - dense, 2)

            result = evaluate(retriever, queries, k=k)
            label = ""
            if dense == 0.0:
                label = "  <- BM25 only"
            elif dense == 1.0:
                label = "  <- embeddings only"

            print(
                f"{dense:>7.2f} {config.SPARSE_WEIGHT:>7.2f} | "
                f"{result['recall_at_k']:>9.3f} {result['mrr']:>7.3f} "
                f"{result['ndcg_at_k']:>8.3f}{label}"
            )

            if best is None or result["ndcg_at_k"] > best[1]:
                best = (dense, result["ndcg_at_k"])
    finally:
        config.DENSE_WEIGHT, config.SPARSE_WEIGHT = original

    print("-" * 46)
    print(f"Best nDCG@{k} at dense={best[0]:.2f} / sparse={1 - best[0]:.2f}")
    print(f"Currently configured: dense={original[0]:.2f} / sparse={original[1]:.2f}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate retrieval quality.")
    parser.add_argument("--k", type=int, default=5, help="Cutoff for Recall/nDCG.")
    parser.add_argument("--sweep", action="store_true", help="Ablate dense/sparse weights.")
    parser.add_argument("--verbose", action="store_true", help="Show per-query scores.")
    args = parser.parse_args()

    if not db.ping():
        print(f"Cannot reach MongoDB at {config.MONGO_URI}")
        return 1

    queries = load_queries()
    retriever = build_retriever()

    print(f"Evaluating {len(queries)} labelled queries over {len(retriever.ids)} projects")

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
        run_sweep(retriever, queries, k=args.k)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
