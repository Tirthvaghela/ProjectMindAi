"""Prepare the next evaluation dataset version after the catalogue changes (e.g. v3 after Batch 2).

    cd backend
    venv\\Scripts\\python -m scripts.eval_next_version prepare --previous v2 --version v3
    venv\\Scripts\\python -m scripts.eval_next_version sheet --version v3 5
    venv\\Scripts\\python -m scripts.eval_next_version build --previous v2 --version v3 --annotator "Name or role"

Why this exists. A dataset version is only valid for the catalogue it was labelled
against (see dataset/eval/README.md). When projects are added, the old labels do
not cover them, so a new version is needed. This workflow keeps that cheap and
honest:

* it REFUSES to run while the catalogue is still the previous version's — there
  is nothing to prepare, and no labels are ever made up in advance;
* labels for projects whose searchable text is unchanged are CARRIED forward
  unchanged (recorded as carried, not re-claimed as newly judged);
* only candidates nobody has judged — chiefly the new projects — are put on a
  blinded sheet, with a fresh blinding salt so earlier sheets do not help;
* `build` refuses to finish until every candidate has a grade, and refuses
  without an explicit `--annotator`, so the dataset cannot claim an independence
  it does not have.

Carrying labels forward is NOT a claim that the new version is comparable with
the old one: the pool, the catalogue and (usually) the annotator differ. Compare
rankers by running both on the same version (scripts/evaluate.py --compare).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Optional

import config
from scripts import eval_dataset as ed

EVAL_DIR = ed.EVAL_DIR
MANIFEST_FOR = {"v2": ed.MANIFEST_FILE}  # a version's manifest records per-project text hashes


def paths(version: str) -> dict[str, Path]:
    folder = EVAL_DIR / f"judgments_{version}"
    return {
        "dir": folder,
        "pools": folder / "pools.json",
        "plan": folder / "plan.json",
        "criteria": folder / "criteria.json",
        "dataset": EVAL_DIR / f"eval_queries_{version}.json",
    }


def opaque_id(version: str, query_index: int, project_id: str) -> str:
    """Blinding ids with a per-version salt: ids from an earlier sheet reveal nothing here."""
    return hashlib.sha256(f"{ed.BLIND_SALT}:{version}:{query_index}:{project_id}".encode()).hexdigest()[:6]


# --- pure planning ---------------------------------------------------------------------------


def catalogue_unchanged(previous_snapshot: dict, documents: dict[str, dict]) -> bool:
    return ed.catalogue_snapshot(documents)["sha256"] == previous_snapshot["sha256"]


def plan_next_version(
    previous: dict,
    previous_text_hashes: dict[str, str],
    documents: dict[str, dict],
    pools: list[dict[str, list[str]]],
) -> dict[str, Any]:
    """Split each query's work into labels that can be carried and candidates
    that need a human. `pools` are the new candidate pools over the new catalogue."""
    queries = []
    for index, (old, pool) in enumerate(zip(previous["queries"], pools), 1):
        carried: dict[str, list] = {}
        text_changed, removed = [], []
        uncertain = set(old.get("uncertain", []))
        for pid, grade in old["grades"].items():
            if pid not in documents:
                removed.append(pid)
            elif ed.project_text_hash(documents[pid]) != previous_text_hashes.get(pid):
                text_changed.append(pid)
            else:
                carried[pid] = [grade, pid in uncertain]
        to_judge = sorted(p for p in pool if p not in carried)
        queries.append(
            {
                "query": old["query"],
                "carried": carried,
                "to_judge": to_judge,
                "text_changed": sorted(text_changed),
                "removed": sorted(removed),
                "pool": sorted(set(pool) | set(carried)),
            }
        )
    return {
        "previous_version": previous["version"],
        "queries": queries,
        "totals": {
            "carried": sum(len(q["carried"]) for q in queries),
            "to_judge": sum(len(q["to_judge"]) for q in queries),
            "text_changed": sum(len(q["text_changed"]) for q in queries),
            "removed": sum(len(q["removed"]) for q in queries),
        },
    }


def build_next_dataset(
    previous: dict,
    plan: dict,
    new_judgments: list[dict[str, tuple[int, bool]]],
    documents: dict[str, dict],
    criteria: dict,
    version: str,
    annotator: str,
) -> dict[str, Any]:
    """Merge carried labels with the newly judged ones. Raises unless every
    candidate has exactly one grade and the annotator is named."""
    if not annotator or not annotator.strip():
        raise ValueError("an annotator must be named; the dataset may not imply independence it does not have")
    queries = []
    for index, (pq, graded) in enumerate(zip(plan["queries"], new_judgments), 1):
        by_opaque = {opaque_id(version, index, pid): pid for pid in pq["to_judge"]}
        unknown, missing = set(graded) - set(by_opaque), set(by_opaque) - set(graded)
        if unknown or missing:
            raise ValueError(f"query {index}: {len(unknown)} unknown and {len(missing)} unjudged candidate id(s)")
        grades = {pid: g for pid, (g, _) in pq["carried"].items()}
        uncertain = [pid for pid, (_, u) in pq["carried"].items() if u]
        for key, (grade, flag) in graded.items():
            grades[by_opaque[key]] = grade
            if flag:
                uncertain.append(by_opaque[key])
        old = previous["queries"][index - 1]
        queries.append(
            {
                "query": old["query"],
                "v1_note": old.get("v1_note", ""),
                "criteria": criteria[old["query"]],
                "grades": dict(sorted(grades.items())),
                "uncertain": sorted(uncertain),
                "v1_relevant": old["v1_relevant"],
                "provenance": {
                    "carried_from": previous["version"],
                    "carried": len(pq["carried"]),
                    "newly_judged": len(pq["to_judge"]),
                    "dropped_text_changed": pq["text_changed"],
                    "dropped_removed": pq["removed"],
                },
            }
        )
    return {
        "version": version,
        "catalogue": ed.catalogue_snapshot(documents),
        "relevance_scale": previous["relevance_scale"],
        "pooling": previous["pooling"],
        "annotation": {
            "annotator_of_new_labels": annotator.strip(),
            "carried_labels": f"copied unchanged from {previous['version']} for projects whose searchable text is unchanged; "
            f"their annotation is that of {previous['version']}: {previous['annotation']['annotator']}",
            "comparability": f"NOT directly comparable with {previous['version']}: different catalogue, pool and possibly annotator",
        },
        "queries": queries,
    }


# --- CLI ------------------------------------------------------------------------------------------


def _load_previous(version: str) -> dict:
    return json.loads(paths(version)["dataset"].read_text(encoding="utf-8"))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare the next evaluation dataset version.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "build"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--previous", default="v2")
        cmd.add_argument("--version", required=True)
        if name == "build":
            cmd.add_argument("--annotator", required=True)
    sheet = sub.add_parser("sheet")
    sheet.add_argument("--version", required=True)
    sheet.add_argument("query_index", type=int)
    args = parser.parse_args(argv)

    documents = ed.load_documents()

    if args.command == "prepare":
        previous = _load_previous(args.previous)
        if catalogue_unchanged(previous["catalogue"], documents):
            print(f"The catalogue is still the one {args.previous} was labelled against ({previous['catalogue']['project_count']} projects). "
                  f"Nothing to prepare; no {args.version} labels exist or will be invented.", file=sys.stderr)
            return 3
        target = paths(args.version)
        if target["pools"].exists():
            print(f"{target['pools']} already exists; refusing to overwrite judged pools.", file=sys.stderr)
            return 1
        manifest = json.loads(MANIFEST_FOR[args.previous].read_text(encoding="utf-8"))
        from scripts import evaluate

        retriever = evaluate.build_retriever()
        if ed.catalogue_snapshot(retriever.documents)["sha256"] != ed.catalogue_snapshot(documents)["sha256"]:
            print("The database/index and the seed file disagree. Seed and run `python -m scripts.build_index` first.", file=sys.stderr)
            return 1
        pools = []
        for old in previous["queries"]:
            seeds_item = {"query": old["query"], "relevant": [p for p, g in old["grades"].items() if g >= 1 and p in documents]}
            pools.append(ed.build_pool(retriever, seeds_item))
        plan = plan_next_version(previous, manifest["project_text_sha1"], documents, pools)
        target["dir"].mkdir(parents=True, exist_ok=True)
        target["pools"].write_text(json.dumps({"depth": ed.POOL_DEPTH, "snapshot": ed.catalogue_snapshot(documents), "pools": [{"query": q["query"], "candidates": q["pool"]} for q in plan["queries"]]}, indent=1) + chr(10), encoding="utf-8")
        target["plan"].write_text(json.dumps(plan, indent=1) + chr(10), encoding="utf-8")
        target["criteria"].write_text((paths(args.previous)["dir"] / "criteria.json").read_text(encoding="utf-8"), encoding="utf-8")
        t = plan["totals"]
        print(f"{args.version}: {t['carried']} labels carried from {args.previous}, {t['to_judge']} candidates need judging, "
              f"{t['text_changed']} re-judge (text changed), {t['removed']} dropped (project removed).")
        print(f"Next: `sheet --version {args.version} N` per query; write q01.txt..q25.txt in {target['dir']}; then `build`.")
        return 0

    target = paths(args.version)
    plan = json.loads(target["plan"].read_text(encoding="utf-8"))
    if args.command == "sheet":
        i = args.query_index
        q = plan["queries"][i - 1]
        criteria = json.loads(target["criteria"].read_text(encoding="utf-8"))
        print(ed.sheet_lines(documents, {p: ["to_judge"] for p in q["to_judge"]}, i, q["query"], criteria[q["query"]], blind=lambda qi, pid: opaque_id(args.version, qi, pid)))
        return 0

    previous = _load_previous(args.previous)
    judgments = []
    for i in range(1, len(plan["queries"]) + 1):
        path = target["dir"] / f"q{i:02d}.txt"
        judgments.append(ed.parse_judgments(path.read_text(encoding="utf-8")) if path.exists() else {})
    criteria = json.loads(target["criteria"].read_text(encoding="utf-8"))
    try:
        dataset = build_next_dataset(previous, plan, judgments, documents, criteria, args.version, args.annotator)
    except ValueError as error:
        print(f"Cannot build {args.version}: {error}", file=sys.stderr)
        return 1
    target["dataset"].write_text(json.dumps(dataset, indent=2, ensure_ascii=False) + chr(10), encoding="utf-8")
    print(f"Wrote {target['dataset']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
