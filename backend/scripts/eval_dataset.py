"""Build and inspect the versioned retrieval-evaluation dataset (v2).

    cd backend
    venv\\Scripts\\python -m scripts.eval_dataset stats           # pool sizes per query
    venv\\Scripts\\python -m scripts.eval_dataset sheet 5         # blinded review sheet for query 5
    venv\\Scripts\\python -m scripts.eval_dataset build           # judgments -> dataset/eval/eval_queries_v2.json

Why v2 exists
-------------
dataset/eval_queries.json (v1) labelled relevance over the original 500
projects. After the catalogue grew to 868 a good new project in the top five
counted as a miss, so v1 numbers stopped being comparable. v1 and its recorded
results are left untouched as the historical baseline.

Method (TREC-style pooling, blinded)
------------------------------------
* Grading criteria for every query are written first, from the query text
  alone (dataset/eval/judgments_v2/criteria.json).
* The candidate pool for a query is the union of the top POOL_DEPTH results of
  several different systems (dense only, BM25 only, three hybrid settings, one
  with technology matching) plus every project v1 had labelled relevant, so no
  single ranker decides what gets judged.
* Candidates are reviewed from a *blinded sheet*: shuffled by a hash, showing
  only title, domain, difficulty, technologies and description. Project ids,
  rank, scores, which system returned it, and v1 labels are not shown.
* Grades: 2 = directly satisfies the intent, 1 = related/partial, 0 = not
  relevant; a trailing `u` marks the annotator as uncertain. Uncertain labels
  are kept and reported, and every metric is also computed with them flipped
  both ways (a sensitivity bound).
* Anything outside the pool is unjudged and treated as not relevant. That is
  the standard pooling assumption, and the dataset records it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

import config
from db import schema

EVAL_DIR = config.DATASET_DIR / "eval"
JUDGMENTS_DIR = EVAL_DIR / "judgments_v2"
V1_FILE = config.DATASET_DIR / "eval_queries.json"
V2_FILE = EVAL_DIR / "eval_queries_v2.json"
POOLS_FILE = JUDGMENTS_DIR / "pools.json"
POOL_DEPTH = 10
BLIND_SALT = "projectmind-eval-v2"

# (name, dense weight, sparse weight, technology weight)
POOL_SYSTEMS = [
    ("dense_only", 1.0, 0.0, 0.0),
    ("bm25_only", 0.0, 1.0, 0.0),
    ("hybrid_0.8_0.2", 0.8, 0.2, 0.0),
    ("hybrid_0.5_0.5", 0.5, 0.5, 0.0),
    ("hybrid_0.8_0.2+tech_0.25", 0.8, 0.2, 0.25),
    ("hybrid_0.8_0.2+tech_0.4", 0.8, 0.2, 0.4),
]

GRADE_RE = re.compile(r"^([012])(u?)$")


# --- snapshot -------------------------------------------------------------------


def catalogue_snapshot(documents: dict[str, dict]) -> dict[str, Any]:
    """A fingerprint of the catalogue an evaluation ran against: change any
    project's id or searchable text and the hash changes."""
    digest = hashlib.sha256()
    for pid in sorted(documents):
        digest.update(pid.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(schema.embedding_text(documents[pid]).encode("utf-8"))
        digest.update(b"\x01")
    numbers = sorted(int(p.split("-")[1]) for p in documents if re.match(r"^pm-\d+$", p))
    return {
        "project_count": len(documents),
        "id_range": [f"pm-{numbers[0]:03d}", f"pm-{numbers[-1]:03d}"] if numbers else None,
        "sha256": digest.hexdigest(),
    }


# --- pooling -----------------------------------------------------------------------


def opaque_id(query_index: int, project_id: str) -> str:
    return hashlib.sha256(f"{BLIND_SALT}:{query_index}:{project_id}".encode()).hexdigest()[:6]


def rank_with(retriever, query: str, dense: float, sparse: float, tech: float, k: int) -> list[str]:
    """Top-k ids for one system configuration. Mutates config for the call and
    always restores it (an offline script; the retriever is not rebuilt)."""
    saved = (config.DENSE_WEIGHT, config.SPARSE_WEIGHT, config.TECHNOLOGY_WEIGHT)
    config.DENSE_WEIGHT, config.SPARSE_WEIGHT, config.TECHNOLOGY_WEIGHT = dense, sparse, tech
    try:
        return [r.project_id for r in retriever.search(query, top_k=k, technology_match=tech > 0)]
    finally:
        config.DENSE_WEIGHT, config.SPARSE_WEIGHT, config.TECHNOLOGY_WEIGHT = saved


def build_pool(retriever, item: dict, depth: int = POOL_DEPTH) -> dict[str, list[str]]:
    """project_id -> the systems that put it in the pool."""
    pool: dict[str, list[str]] = {}
    for name, dense, sparse, tech in POOL_SYSTEMS:
        for pid in rank_with(retriever, item["query"], dense, sparse, tech, depth):
            pool.setdefault(pid, []).append(name)
    for pid in item["relevant"]:
        pool.setdefault(pid, []).append("v1_label")
    return pool


def sheet_lines(documents: dict[str, dict], pool: dict[str, list[str]], query_index: int, query: str, criteria: dict, blind=None) -> str:
    blind = blind or opaque_id
    entries = sorted(pool, key=lambda pid: blind(query_index, pid))
    out = [f"QUERY {query_index}: {query!r}", f"  2 = {criteria['2']}", f"  1 = {criteria['1']}", "  0 = does not satisfy the intent", f"  {len(entries)} candidates, blinded and shuffled\n"]
    for pid in entries:
        d = documents[pid]
        out.append(
            f"[{blind(query_index, pid)}] {d['title']} | {d['domain']} | {d['difficulty']} | "
            f"{', '.join(d['technologies'])}\n    {d['description']}"
        )
    return "\n".join(out)


# --- judgments -----------------------------------------------------------------------


def parse_judgments(text: str) -> dict[str, tuple[int, bool]]:
    grades: dict[str, tuple[int, bool]] = {}
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2 or not GRADE_RE.match(parts[1]):
            raise ValueError(f"line {number}: expected '<id> <0|1|2>[u]', got {raw!r}")
        key, grade = parts[0], GRADE_RE.match(parts[1])
        if key in grades:
            raise ValueError(f"line {number}: {key} judged twice")
        grades[key] = (int(grade.group(1)), bool(grade.group(2)))
    return grades


def build_dataset(documents: dict[str, dict], v1: list[dict], pools: list[dict[str, list[str]]], judgments: list[dict[str, tuple[int, bool]]], criteria: dict) -> dict[str, Any]:
    queries = []
    for index, (item, pool, graded) in enumerate(zip(v1, pools, judgments), 1):
        by_opaque = {opaque_id(index, pid): pid for pid in pool}
        unknown = set(graded) - set(by_opaque)
        missing = set(by_opaque) - set(graded)
        if unknown or missing:
            raise ValueError(f"query {index}: {len(unknown)} unknown and {len(missing)} unjudged candidate id(s)")
        grades = {by_opaque[k]: g for k, (g, _) in graded.items()}
        uncertain = sorted(by_opaque[k] for k, (_, u) in graded.items() if u)
        queries.append(
            {
                "query": item["query"],
                "v1_note": item.get("note", ""),
                "criteria": criteria[item["query"]],
                "grades": dict(sorted(grades.items())),
                "uncertain": uncertain,
                "v1_relevant": sorted(item["relevant"]),
            }
        )
    return {
        "version": "v2",
        "catalogue": catalogue_snapshot(documents),
        "relevance_scale": {
            "2": "directly satisfies the query intent",
            "1": "related or partially satisfies the intent",
            "0": "does not satisfy the intent",
            "views": {
                "lenient": "relevant = grade >= 1 (closest to how v1 labelled)",
                "strict": "relevant = grade == 2",
            },
        },
        "pooling": {
            "depth": POOL_DEPTH,
            "systems": [name for name, *_ in POOL_SYSTEMS] + ["v1_label"],
            "assumption": "projects outside the pool are unjudged and counted as not relevant",
        },
        "annotation": {
            "annotator": "single annotator (an AI assistant), blinded to rank, score, system, project id and v1 label",
            "conflict_of_interest": "the same assistant authored the projects pm-501..pm-868; blinding hides ids but cannot erase that familiarity",
            "uncertain_labels": "marked with a trailing 'u' in the judgment files and listed per query",
            "independent_review": "not performed; blinded sheets are exported for a human reviewer (see dataset/eval/README.md)",
        },
        "queries": queries,
    }


def load_documents() -> dict[str, dict]:
    return {r["project_id"]: r for r in json.loads(config.SEED_FILE.read_text(encoding="utf-8"))}


# --- manifest: every frozen input, fingerprinted ------------------------------------------------


MANIFEST_FILE = EVAL_DIR / "MANIFEST_v2.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def project_text_hash(doc: dict[str, Any]) -> str:
    """Fingerprint of the text retrieval and review actually see for one project.
    Recorded per project so a later dataset version can tell which earlier
    labels still describe the same text and which must be judged again."""
    return hashlib.sha1(schema.embedding_text(doc).encode("utf-8")).hexdigest()[:16]


def frozen_input_files() -> list[Path]:
    files = [V1_FILE, V2_FILE, POOLS_FILE, JUDGMENTS_DIR / "criteria.json"]
    files += sorted(JUDGMENTS_DIR.glob("q[0-9][0-9].txt"))
    return files


def build_manifest(documents: dict[str, dict]) -> dict[str, Any]:
    return {
        "version": "v2",
        "note": "Hashes of every input that produced eval_queries_v2.json. `verify` fails if any changes.",
        "files": {str(f.relative_to(config.DATASET_DIR)).replace("\\", "/"): _sha256(f) for f in frozen_input_files()},
        "catalogue": catalogue_snapshot(documents),
        "project_text_sha1": {pid: project_text_hash(documents[pid]) for pid in sorted(documents)},
    }


def verify_manifest(manifest: dict[str, Any], documents: dict[str, dict]) -> list[str]:
    """Problems found; an empty list means the v2 inputs and catalogue are exactly as released."""
    problems = []
    for rel, expected in manifest["files"].items():
        path = config.DATASET_DIR / rel
        if not path.exists():
            problems.append(f"missing frozen input: {rel}")
        elif _sha256(path) != expected:
            problems.append(f"frozen input changed: {rel}")
    snapshot = catalogue_snapshot(documents)
    if snapshot["sha256"] != manifest["catalogue"]["sha256"]:
        problems.append(
            f"catalogue changed since v2 was labelled ({manifest['catalogue']['project_count']} -> {snapshot['project_count']} projects): "
            "v2 numbers no longer apply; prepare a new dataset version"
        )
    return problems


# --- CLI ---------------------------------------------------------------------------------


def _retriever():
    from scripts import evaluate

    return evaluate.build_retriever()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build the v2 evaluation dataset.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("freeze")
    sub.add_parser("stats")
    sheet = sub.add_parser("sheet")
    sheet.add_argument("query_index", type=int)
    sub.add_parser("build")
    sub.add_parser("manifest")
    sub.add_parser("verify")
    args = parser.parse_args(argv)

    v1 = json.loads(V1_FILE.read_text(encoding="utf-8"))
    criteria = json.loads((JUDGMENTS_DIR / "criteria.json").read_text(encoding="utf-8"))

    if args.command == "freeze":
        if POOLS_FILE.exists():
            print(f"{POOLS_FILE} already exists; refusing to overwrite judged pools.", file=sys.stderr)
            return 1
        retriever = _retriever()
        frozen = {
            "depth": POOL_DEPTH,
            "snapshot": catalogue_snapshot(retriever.documents),
            "pools": [{"query": item["query"], "candidates": build_pool(retriever, item)} for item in v1],
        }
        POOLS_FILE.write_text(json.dumps(frozen, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Froze {sum(len(p['candidates']) for p in frozen['pools'])} candidates to {POOLS_FILE}")
        return 0

    if args.command == "manifest":
        if MANIFEST_FILE.exists():
            print(f"{MANIFEST_FILE} already exists; the v2 manifest is written once.", file=sys.stderr)
            return 1
        MANIFEST_FILE.write_text(json.dumps(build_manifest(load_documents()), indent=1) + chr(10), encoding="utf-8")
        print(f"Wrote {MANIFEST_FILE}")
        return 0

    if args.command == "verify":
        problems = verify_manifest(json.loads(MANIFEST_FILE.read_text(encoding="utf-8")), load_documents())
        print(chr(10).join(problems) if problems else "v2 inputs and catalogue match the manifest.")
        return 1 if problems else 0

    if not POOLS_FILE.exists():
        print("Run `freeze` first.", file=sys.stderr)
        return 1
    frozen = json.loads(POOLS_FILE.read_text(encoding="utf-8"))
    pools = [p["candidates"] for p in frozen["pools"]]
    documents = load_documents()

    if args.command == "stats":
        total = 0
        for i, (item, pool) in enumerate(zip(v1, pools), 1):
            new = sum(1 for p in pool if int(p.split("-")[1]) > 500)
            total += len(pool)
            print(f"{i:2} {item['query'][:50]:50} pool={len(pool):3} (new projects: {new:2}, v1-relevant: {len(item['relevant']):2})")
        print(f"total candidates to judge: {total}")
        return 0

    if args.command == "sheet":
        i = args.query_index
        print(sheet_lines(documents, pools[i - 1], i, v1[i - 1]["query"], criteria[v1[i - 1]["query"]]))
        return 0

    judgments = []
    for i in range(1, len(v1) + 1):
        path = JUDGMENTS_DIR / f"q{i:02d}.txt"
        if not path.exists():
            print(f"Missing judgments: {path}", file=sys.stderr)
            return 1
        judgments.append(parse_judgments(path.read_text(encoding="utf-8")))
    dataset = build_dataset(documents, v1, pools, judgments, criteria)
    V2_FILE.write_text(json.dumps(dataset, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {V2_FILE} ({sum(len(q['grades']) for q in dataset['queries'])} judgments, snapshot {dataset['catalogue']['sha256'][:12]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
