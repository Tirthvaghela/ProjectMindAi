"""Independent human review of the v2 evaluation labels.

    cd backend
    venv\\Scripts\\python -m scripts.eval_review export                    # sheet for reviewers + private key
    venv\\Scripts\\python -m scripts.eval_review validate A.csv B.csv      # check filled sheets; never reads AI grades
    venv\\Scripts\\python -m scripts.eval_review agreement --reviewer anna=A.csv --reviewer ben=B.csv

The v2 grades were assigned by one AI assistant that also authored most of the
new projects, so they are not independent. This module turns a few hours of
real human review into a measured answer to "how far can these labels be
trusted?" — and says nothing until real reviewers have filled the sheet.

What a reviewer receives (review/review_sheet_v2.csv), and only that file:
the query, the 0/1/2 rubric for it, and each project's title, domain, difficulty,
technologies and description, with blank `reviewer_grade`, `reviewer_uncertain`
and `reviewer_comment` columns. Row ids are sequential (R001, R002, ...) and carry
no information. The mapping from a row to its project, the AI grade, whether the
AI was uncertain, and which sampling stratum it came from live in
review/PRIVATE_review_key_v2.json, which must not be shared; the AI grades
themselves are read only by `agreement`, after the reviewers are done.

Sampling is stratified, because a convenience sample would mislead:
  * stratum `uncertain` — every item the AI itself marked uncertain;
  * stratum `sampled`   — a seeded random sample of the rest, with at least
                          MIN_PER_QUERY items per query.
Agreement on `sampled` estimates how reliable the AI's confident labels are.
Agreement on `uncertain` is expected to be lower by construction, and the two are
reported separately; neither is pooled, because `uncertain` is deliberately
over-represented.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import random
import re
import sys
from pathlib import Path
from typing import Any, Optional

import config
from scripts.eval_dataset import V2_FILE, load_documents

REVIEW_DIR = config.DATASET_DIR / "eval" / "review"
SHEET_FILE = REVIEW_DIR / "review_sheet_v2.csv"
KEY_FILE = REVIEW_DIR / "PRIVATE_review_key_v2.json"

SAMPLE_SEED = 11
MIN_PER_QUERY = 4
CERTAIN_SAMPLE = 95  # AI-confident items drawn in addition to every uncertain one

SHEET_COLUMNS = [
    "row_id", "query", "grade_2_means", "grade_1_means",
    "title", "domain", "difficulty", "technologies", "description",
    "reviewer_grade", "reviewer_uncertain", "reviewer_comment",
]
STATIC_COLUMNS = SHEET_COLUMNS[:9]  # everything the organiser wrote; reviewers must not edit these
REVIEWER_COLUMNS = SHEET_COLUMNS[9:]
YES = {"y", "yes", "1", "true", "u", "x"}


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(row: dict) -> str:
    """Fingerprint of everything the organiser wrote in a row (the rubric and the
    project text), computed from the row itself so that a reviewer's edit to any
    of those cells is caught when their file comes back."""
    return hashlib.sha1("\x1f".join(row.get(c, "") or "" for c in STATIC_COLUMNS[1:]).encode("utf-8")).hexdigest()[:12]


# --- export ------------------------------------------------------------------------------


def select_items(dataset: dict, everything: bool = False, seed: int = SAMPLE_SEED) -> list[dict[str, Any]]:
    """The (query, project, stratum) triples to be reviewed."""
    rng = random.Random(seed)
    chosen: list[dict[str, Any]] = []
    for index, query in enumerate(dataset["queries"], 1):
        uncertain = sorted(query["uncertain"])
        certain = sorted(p for p in query["grades"] if p not in set(uncertain))
        rng.shuffle(certain)
        keep = certain if everything else certain[:MIN_PER_QUERY]
        chosen += [{"query_index": index, "project_id": p, "stratum": "uncertain"} for p in uncertain]
        chosen += [{"query_index": index, "project_id": p, "stratum": "sampled"} for p in keep]
    if not everything:
        taken = {(c["query_index"], c["project_id"]) for c in chosen}
        extra = [
            (i, p)
            for i, q in enumerate(dataset["queries"], 1)
            for p in sorted(q["grades"])
            if p not in set(q["uncertain"]) and (i, p) not in taken
        ]
        rng.shuffle(extra)
        for i, p in extra[: max(0, CERTAIN_SAMPLE - sum(1 for c in chosen if c["stratum"] == "sampled"))]:
            chosen.append({"query_index": i, "project_id": p, "stratum": "sampled"})
    return chosen


def build_export(dataset: dict, documents: dict[str, dict], dataset_sha256: str, everything: bool = False, seed: int = SAMPLE_SEED):
    """(sheet_rows, key). Rows are grouped by query for context but shuffled
    within it, then numbered, so neither the id nor the position says anything."""
    rng = random.Random(seed + 1)
    items = select_items(dataset, everything, seed)
    items.sort(key=lambda c: c["query_index"])
    rows, key_rows = [], {}
    number = 0
    for _, group in itertools.groupby(items, key=lambda c: c["query_index"]):
        group = list(group)
        rng.shuffle(group)
        for item in group:
            number += 1
            row_id = f"R{number:03d}"
            query = dataset["queries"][item["query_index"] - 1]
            doc = documents[item["project_id"]]
            rows.append(
                {
                    "row_id": row_id,
                    "query": query["query"],
                    "grade_2_means": query["criteria"]["2"],
                    "grade_1_means": query["criteria"]["1"],
                    "title": doc["title"],
                    "domain": doc["domain"],
                    "difficulty": doc["difficulty"],
                    "technologies": ", ".join(doc["technologies"]),
                    "description": doc["description"],
                    **{c: "" for c in REVIEWER_COLUMNS},
                }
            )
            key_rows[row_id] = {**item, "content": _content_hash(rows[-1])}
    key = {
        "dataset": "v2",
        "dataset_sha256": dataset_sha256,
        "seed": seed,
        "strata": {s: sum(1 for r in key_rows.values() if r["stratum"] == s) for s in ("uncertain", "sampled")},
        "rows": key_rows,
        "warning": "PRIVATE. Maps review rows to projects and strata. Never send this file to a reviewer.",
    }
    return rows, key


def write_export(rows: list[dict], key: dict, sheet: Path = SHEET_FILE, key_file: Path = KEY_FILE) -> None:
    sheet.parent.mkdir(parents=True, exist_ok=True)
    with sheet.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SHEET_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    key_file.write_text(json.dumps(key, indent=1) + "\n", encoding="utf-8")


# --- reading a reviewer's sheet -------------------------------------------------------------


class ReviewerData:
    def __init__(self, name: str):
        self.name = name
        self.grades: dict[str, int] = {}
        self.uncertain: set[str] = set()
        self.comments = 0
        self.problems: list[str] = []

    @property
    def ok(self) -> bool:
        return not self.problems


def read_reviewer(name: str, path: Path, key: dict) -> ReviewerData:
    """Parse and validate one reviewer's filled sheet against the private key.
    Needs neither the dataset nor any AI grade. Problems are collected, never
    silently dropped."""
    data = ReviewerData(name)
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != SHEET_COLUMNS:
                data.problems.append(f"columns differ from the sheet that was sent: {reader.fieldnames}")
                return data
            rows = list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as error:
        data.problems.append(f"cannot read the file: {error}")
        return data

    seen: set[str] = set()
    for number, row in enumerate(rows, start=2):
        row_id = (row.get("row_id") or "").strip()
        where = f"line {number} ({row_id or 'no id'})"
        entry = key["rows"].get(row_id)
        if entry is None:
            data.problems.append(f"{where}: unknown row id")
            continue
        if row_id in seen:
            data.problems.append(f"{where}: row appears twice")
            continue
        seen.add(row_id)
        if _content_hash(row) != entry["content"]:
            data.problems.append(f"{where}: the rubric or project text was edited, or this sheet is from a different export")
            continue

        grade = (row.get("reviewer_grade") or "").strip()
        if grade:
            if grade not in {"0", "1", "2"}:
                data.problems.append(f"{where}: reviewer_grade must be 0, 1 or 2, got {grade!r}")
            else:
                data.grades[row_id] = int(grade)
        flag = (row.get("reviewer_uncertain") or "").strip().lower()
        if flag and flag in YES:
            data.uncertain.add(row_id)
        elif flag and flag not in {"n", "no", "0", "false"}:
            data.problems.append(f"{where}: reviewer_uncertain should be y or blank, got {flag!r}")
        if (row.get("reviewer_comment") or "").strip():
            data.comments += 1
    missing = set(key["rows"]) - seen
    if missing:
        data.problems.append(f"{len(missing)} row(s) of the original sheet are absent")
    return data


# --- statistics --------------------------------------------------------------------------------


def weighted_kappa(pairs: list[tuple[int, int]], levels: int = 3) -> Optional[float]:
    """Quadratic-weighted Cohen's kappa; None when chance agreement is total
    (e.g. one grade used throughout), where kappa is undefined."""
    n = len(pairs)
    if not n:
        return None
    observed = [[0.0] * levels for _ in range(levels)]
    for a, b in pairs:
        observed[a][b] += 1
    rows = [sum(observed[i]) for i in range(levels)]
    cols = [sum(observed[i][j] for i in range(levels)) for j in range(levels)]
    weight = lambda i, j: (i - j) ** 2 / (levels - 1) ** 2  # noqa: E731
    disagree = sum(weight(i, j) * observed[i][j] / n for i in range(levels) for j in range(levels))
    chance = sum(weight(i, j) * rows[i] * cols[j] / n**2 for i in range(levels) for j in range(levels))
    return None if chance == 0 else 1 - disagree / chance


def summarise_pairs(pairs: list[tuple[int, int]]) -> dict[str, Any]:
    n = len(pairs)
    if not n:
        return {"n": 0}
    lenient = [(int(a >= 1), int(b >= 1)) for a, b in pairs]
    return {
        "n": n,
        "exact_agreement": round(sum(1 for a, b in pairs if a == b) / n, 3),
        "lenient_agreement": round(sum(1 for a, b in lenient if a == b) / n, 3),
        "weighted_kappa": _r(weighted_kappa(pairs)),
        "lenient_kappa": _r(weighted_kappa(lenient, levels=2)),
        "disagreements_by_two_grades": sum(1 for a, b in pairs if abs(a - b) == 2),
    }


def _r(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 3)


def _ai_grade(dataset: dict, entry: dict) -> int:
    return dataset["queries"][entry["query_index"] - 1]["grades"][entry["project_id"]]


def compare(dataset: dict, key: dict, reviewers: list[ReviewerData]) -> dict[str, Any]:
    """Human-vs-AI and human-vs-human agreement. This is the only function that
    reads the AI grades; call it after the reviewers are finished."""
    report: dict[str, Any] = {"rows_sent": len(key["rows"]), "strata": key["strata"], "reviewers": {}, "inter_reviewer": {}}

    def stratum_pairs(data: ReviewerData, stratum: Optional[str] = None, new_only: Optional[bool] = None):
        pairs = []
        for row_id, grade in data.grades.items():
            entry = key["rows"][row_id]
            if stratum and entry["stratum"] != stratum:
                continue
            is_new = int(entry["project_id"].split("-")[1]) > 500
            if new_only is not None and is_new != new_only:
                continue
            pairs.append((_ai_grade(dataset, entry), grade))
        return pairs

    for data in reviewers:
        graded = len(data.grades)
        report["reviewers"][data.name] = {
            "valid": data.ok,
            "problems": data.problems[:10],
            "graded": graded,
            "coverage": round(graded / max(1, len(key["rows"])), 3),
            "marked_uncertain": len(data.uncertain),
            "comments": data.comments,
            "vs_ai_confident_items": summarise_pairs(stratum_pairs(data, "sampled")),
            "vs_ai_uncertain_items": summarise_pairs(stratum_pairs(data, "uncertain")),
            "vs_ai_on_original_500_projects": summarise_pairs(stratum_pairs(data, "sampled", new_only=False)),
            "vs_ai_on_new_projects": summarise_pairs(stratum_pairs(data, "sampled", new_only=True)),
        }

    usable = [r for r in reviewers if r.ok and r.grades]
    for a, b in itertools.combinations(usable, 2):
        common = sorted(set(a.grades) & set(b.grades))
        report["inter_reviewer"][f"{a.name} vs {b.name}"] = summarise_pairs([(a.grades[r], b.grades[r]) for r in common])

    if len(usable) >= 2:
        consensus: dict[str, int] = {}
        for row_id in key["rows"]:
            votes = [r.grades[row_id] for r in usable if row_id in r.grades]
            if len(votes) >= 2:
                top = max(set(votes), key=votes.count)
                if votes.count(top) * 2 > len(votes):
                    consensus[row_id] = top
        report["consensus_vs_ai"] = {
            "rows_with_a_majority": len(consensus),
            "confident_items": summarise_pairs([(_ai_grade(dataset, key["rows"][r]), g) for r, g in consensus.items() if key["rows"][r]["stratum"] == "sampled"]),
            "uncertain_items": summarise_pairs([(_ai_grade(dataset, key["rows"][r]), g) for r, g in consensus.items() if key["rows"][r]["stratum"] == "uncertain"]),
        }
    elif not usable:
        report["note"] = "No completed reviewer sheet supplied: nothing to report, and the labels remain single-annotator."
    else:
        report["note"] = "Only one reviewer: human-vs-AI agreement is reported, but inter-reviewer agreement needs at least two."
    return report


def interpretation(report: dict[str, Any]) -> list[str]:
    """Plain-language reading, with the caveats a number alone would hide."""
    lines = []
    for name, r in report["reviewers"].items():
        c = r["vs_ai_confident_items"]
        if c.get("n", 0) >= 30 and c.get("weighted_kappa") is not None:
            band = "substantial" if c["weighted_kappa"] >= 0.6 else "moderate" if c["weighted_kappa"] >= 0.4 else "weak"
            lines.append(f"{name}: {band} agreement with the AI's confident labels (weighted kappa {c['weighted_kappa']}, n={c['n']}).")
        elif c.get("n", 0):
            lines.append(f"{name}: only {c['n']} confident items graded; too few to say anything reliable (aim for 60+).")
    for pair, r in report["inter_reviewer"].items():
        if r.get("n", 0) and r.get("weighted_kappa") is not None:
            lines.append(f"{pair}: weighted kappa {r['weighted_kappa']} on {r['n']} shared rows; human-vs-AI agreement cannot be expected to exceed this ceiling.")
    return lines or ["No interpretation available yet."]


# --- CLI ----------------------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Independent human review of the v2 labels.")
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export")
    export.add_argument("--all", action="store_true", help="Every judged item instead of a stratified sample.")
    check = sub.add_parser("validate", help="Check filled sheets against the private key; does not use the AI grades.")
    check.add_argument("files", nargs="+", type=Path)
    agree = sub.add_parser("agreement")
    agree.add_argument("--reviewer", action="append", required=True, metavar="NAME=FILE")
    agree.add_argument("--json", type=Path)
    args = parser.parse_args(argv)

    documents = load_documents()
    dataset = json.loads(V2_FILE.read_text(encoding="utf-8"))

    if args.command == "export":
        rows, key = build_export(dataset, documents, file_sha256(V2_FILE), everything=args.all)
        write_export(rows, key)
        print(f"Wrote {len(rows)} rows to {SHEET_FILE} (strata: {key['strata']})")
        print(f"Wrote the PRIVATE mapping to {KEY_FILE}. Send reviewers {SHEET_FILE.name} and REVIEWER_INSTRUCTIONS.md only.")
        return 0

    key = json.loads(KEY_FILE.read_text(encoding="utf-8"))
    if key["dataset_sha256"] != file_sha256(V2_FILE):
        print("The v2 dataset changed after this sheet was exported; export a new sheet.", file=sys.stderr)
        return 2

    if args.command == "validate":
        status = 0
        for path in args.files:
            data = read_reviewer(path.stem, path, key)
            state = "OK" if data.ok else "PROBLEMS"
            print(f"{path.name}: {state} — graded {len(data.grades)}/{len(key['rows'])}, uncertain {len(data.uncertain)}, comments {data.comments}")
            for problem in data.problems[:15]:
                print("   -", problem)
            status |= 0 if data.ok else 1
        return status

    reviewers = []
    for spec in args.reviewer:
        name, _, file = spec.partition("=")
        if not file:
            print(f"--reviewer expects NAME=FILE, got {spec!r}", file=sys.stderr)
            return 1
        reviewers.append(read_reviewer(name, Path(file), key))
    report = compare(dataset, key, reviewers)
    report["interpretation"] = interpretation(report)
    print(json.dumps(report, indent=2))
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if all(r.ok for r in reviewers) else 1


if __name__ == "__main__":
    sys.exit(main())
