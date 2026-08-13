"""Quick manual check of retrieval quality.

    cd backend
    venv\\Scripts\\python -m scripts.smoke_search

Prints ranked results for a handful of representative queries so you can eyeball
whether the hybrid scorer is behaving. Not a substitute for scripts/evaluate.py,
which measures this properly against labelled data.
"""

from __future__ import annotations

import logging

from nlp import recommend

logging.disable(logging.INFO)

QUERIES = [
    "I want an AI based healthcare project using Python",
    "YOLOv8",
    "React Flask project",
    "beginner project for farming",
    "blockchain voting system",
]


def main() -> int:
    for query in QUERIES:
        print(f"\nQUERY: {query!r}")
        results = recommend.search(query, top_k=3)
        if not results:
            print("   (no results)")
            continue
        for r in results:
            doc = r.document
            print(
                f"  {r.score:.3f}  sem={r.dense_score:+.3f} kw={r.sparse_score:6.2f}  "
                f"{doc['title'][:50]}"
            )
            if r.matched_terms:
                print(f"          matched: {', '.join(r.matched_terms[:6])}")

    print("\n--- FILTER TEST: difficulty=Beginner ---")
    for r in recommend.search("image recognition project", filters={"difficulty": "Beginner"}, top_k=3):
        print(f"  {r.document['difficulty']:<13}{r.document['title'][:50]}")

    print("\n--- FILTER TEST: domain=Blockchain ---")
    for r in recommend.search("secure system", filters={"domain": "Blockchain"}, top_k=3):
        print(f"  {r.document['domain']:<13}{r.document['title'][:50]}")

    print("\n--- SIMILAR TO pm-002 (Retinal Disease Detection) ---")
    for r in recommend.similar("pm-002", top_k=3):
        print(f"  {r.score:.3f}  {r.document['title'][:50]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
