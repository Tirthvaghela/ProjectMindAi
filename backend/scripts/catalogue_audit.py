"""Read-only audit of a project catalogue file — run this before any import.

    cd backend
    venv\\Scripts\\python -m scripts.catalogue_audit
    venv\\Scripts\\python -m scripts.catalogue_audit --file path\\to\\candidates.json
    venv\\Scripts\\python -m scripts.catalogue_audit --semantic --json report.json

It never touches MongoDB, the embedding index or the file it reads. It
reports what a catalogue expansion has to get right:

* stable IDs   - duplicate ids, ids that break the `pm-NNN` convention, gaps,
                 and the next free id (existing ids must never be renumbered);
* duplicates   - identical normalised titles always; near-identical meaning
                 with `--semantic` (embedding similarity, a review signal and
                 not a verdict, same as scripts.validate_dataset);
* metadata     - records with a missing/invalid duration, difficulty,
                 technologies, skills or keywords, using db/schema.py's own
                 rules plus a duration check that mirrors the deadline logic;
* distribution - domain, difficulty, duration and technology counts, and how
                 many technology names the shared alias table recognises.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import config
from db import schema
from nlp import skills

log = logging.getLogger("catalogue_audit")

ID_PATTERN = re.compile(r"^pm-(\d+)$")


def _norm_title(title: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(title).lower()).strip()


def audit_records(records: list[Any], semantic_pairs: list[tuple[str, str, float]] | None = None) -> dict[str, Any]:
    """Pure function over parsed records, so it can be tested on fixtures."""
    docs = [r for r in records if isinstance(r, dict)]
    not_objects = len(records) - len(docs)

    ids = [d.get("project_id") for d in docs]
    id_counts = Counter(i for i in ids if i is not None)
    numbers = sorted(int(m.group(1)) for i in id_counts if isinstance(i, str) and (m := ID_PATTERN.match(i)))
    off_pattern = sorted(str(i) for i in id_counts if not (isinstance(i, str) and ID_PATTERN.match(i)))
    gaps = sorted(set(range(numbers[0], numbers[-1] + 1)) - set(numbers)) if numbers else []

    by_title: dict[str, list[str]] = {}
    for d in docs:
        by_title.setdefault(_norm_title(d.get("title", "")), []).append(str(d.get("project_id")))

    schema_problems = {}
    for d in docs:
        problems = schema.validate(d)
        if problems:
            schema_problems[str(d.get("project_id"))] = problems

    def missing(field: str) -> list[str]:
        out = []
        for d in docs:
            value = d.get(field)
            if value is None or value == [] or value == "":
                out.append(str(d.get("project_id")))
        return out

    unknown_duration = [str(d.get("project_id")) for d in docs if schema.known_duration(d) is None]
    technologies = Counter(t for d in docs for t in d.get("technologies", []) if isinstance(t, str))
    recognised = {t for t in technologies if skills.canonical_name(t) is not None}
    durations = Counter(d["duration_weeks"] for d in docs if schema.known_duration(d) is not None)

    return {
        "total_records": len(records),
        "non_object_records": not_objects,
        "unique_project_ids": len(id_counts),
        "duplicate_project_ids": sorted(i for i, n in id_counts.items() if n > 1),
        "records_without_id": sum(1 for i in ids if i is None),
        "ids_off_convention": off_pattern,
        "id_number_range": [numbers[0], numbers[-1]] if numbers else None,
        "id_gaps": gaps,
        "next_free_id": f"pm-{(numbers[-1] + 1) if numbers else 1:03d}",
        "duplicate_titles": {t: pids for t, pids in by_title.items() if t and len(pids) > 1},
        "schema_problems": schema_problems,
        "missing": {f: missing(f) for f in ("difficulty", "technologies", "skills", "keywords", "description")},
        "unknown_or_invalid_duration": unknown_duration,
        "by_domain": dict(Counter(d.get("domain") for d in docs).most_common()),
        "by_difficulty": dict(Counter(d.get("difficulty") for d in docs).most_common()),
        "by_duration_weeks": dict(sorted(durations.items())),
        "technology_names": len(technologies),
        "technology_names_in_alias_table": len(recognised),
        "top_technologies": technologies.most_common(15),
        "semantic_duplicate_pairs": semantic_pairs,
    }


def semantic_pairs(records: list[dict], threshold: float) -> list[tuple[str, str, float]]:
    """Near-identical pairs by embedding similarity (loads the encoder)."""
    import numpy as np

    from nlp import embeddings

    matrix = embeddings.encode([schema.embedding_text(r) for r in records])
    sim = np.triu(matrix @ matrix.T, k=1)
    return [
        (records[i]["project_id"], records[j]["project_id"], round(float(sim[i, j]), 3))
        for i, j in np.argwhere(sim >= threshold)
    ]


def format_report(report: dict[str, Any]) -> str:
    r = report
    lines = [
        f"Records            : {r['total_records']} ({r['unique_project_ids']} unique ids)",
        f"Next free id       : {r['next_free_id']}   (range {r['id_number_range']}, {len(r['id_gaps'])} gap(s))",
        f"Duplicate ids      : {len(r['duplicate_project_ids'])}   {r['duplicate_project_ids'][:5]}",
        f"Ids off convention : {len(r['ids_off_convention'])}   {r['ids_off_convention'][:5]}",
        f"Duplicate titles   : {len(r['duplicate_titles'])}",
        f"Schema problems    : {len(r['schema_problems'])} record(s)",
        f"Unknown duration   : {len(r['unknown_or_invalid_duration'])} record(s)",
    ]
    for field, pids in r["missing"].items():
        lines.append(f"Missing {field:<12}: {len(pids)}")
    lines.append(f"Domains            : {r['by_domain']}")
    lines.append(f"Difficulty         : {r['by_difficulty']}")
    lines.append(f"Duration (weeks)   : {r['by_duration_weeks']}")
    lines.append(
        f"Technology names   : {r['technology_names']} distinct, "
        f"{r['technology_names_in_alias_table']} recognised by nlp/skills.py"
    )
    lines.append(f"Top technologies   : {r['top_technologies']}")
    pairs = r["semantic_duplicate_pairs"]
    lines.append(
        "Semantic duplicates: not run (pass --semantic)"
        if pairs is None
        else f"Semantic duplicates: {len(pairs)} pair(s) for review {pairs[:5]}"
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only catalogue audit.")
    parser.add_argument("--file", type=Path, default=config.SEED_FILE, help="Catalogue JSON (default: the seed file).")
    parser.add_argument("--semantic", action="store_true", help="Also find near-duplicates by embedding similarity.")
    parser.add_argument("--threshold", type=float, default=config.DUPLICATE_THRESHOLD)
    parser.add_argument("--json", type=Path, help="Write the full report as JSON to this path.")
    parser.add_argument("--strict", action="store_true", help="Exit 1 if any duplicate id/title or schema problem exists.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    records = json.loads(args.file.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        log.error("%s must contain a JSON array.", args.file)
        return 1

    pairs = semantic_pairs([r for r in records if isinstance(r, dict)], args.threshold) if args.semantic else None
    report = audit_records(records, pairs)
    print(format_report(report))
    if args.json:
        args.json.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(f"\nFull report written to {args.json}")

    bad = report["duplicate_project_ids"] or report["duplicate_titles"] or report["schema_problems"]
    return 1 if (args.strict and bad) else 0


if __name__ == "__main__":
    sys.exit(main())
