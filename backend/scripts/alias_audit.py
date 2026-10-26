"""Audit the technology names in the catalogue against the shared alias table.

    cd backend
    venv\\Scripts\\python -m scripts.alias_audit
    venv\\Scripts\\python -m scripts.alias_audit --markdown dataset/reports/alias_audit.md

Read-only. For every distinct technology name a project lists it reports:

* covered      — a canonical name in nlp/skills.py (spelling variants resolve to it);
* sole spelling — not in the table, but still matched case/space/punctuation-
                  insensitively against itself, so it needs no alias to work;
* near variants — pairs of catalogue names that look like the same thing written
                  two ways, or one name contained in another. These are *candidates
                  for a human decision*, never mapped automatically: "Transformers"
                  versus "Sentence Transformers" are different libraries;
* ambiguous     — short names, plain English words, and names with a second reading.

Coverage is not a goal. A name earns an alias only when its variants are the same
thing in practice, and the decision (including every deliberate refusal) is
recorded in nlp/skills.py.
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import config
from nlp import skills
from nlp.similarity import _AMBIGUOUS_TECH_NAMES  # noqa: SLF001 - the audit reports the retriever's own list


def audit(records: list[dict]) -> dict[str, Any]:
    names = Counter(t for r in records for t in r.get("technologies", []) if isinstance(t, str))
    by_key: dict[str, list[str]] = {}
    for name in names:
        by_key.setdefault(skills.normalize_key(name), []).append(name)

    covered = sorted(n for n in names if skills.canonical_name(n) is not None)
    uncovered = sorted(n for n in names if skills.canonical_name(n) is None)

    # Same key, different spelling inside the catalogue: already unified by normalisation.
    unified = {k: sorted(v) for k, v in by_key.items() if len(v) > 1}

    keys = sorted(by_key)
    near: list[dict[str, Any]] = []
    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            ratio = difflib.SequenceMatcher(None, a, b).ratio()
            contained = (a in b or b in a) and min(len(a), len(b)) >= 4
            if ratio >= 0.84 or contained:
                near.append(
                    {
                        "a": by_key[a][0],
                        "b": by_key[b][0],
                        "similarity": round(ratio, 2),
                        "why": "one name contains the other" if contained and ratio < 0.84 else "similar spelling",
                    }
                )

    ambiguous = sorted(
        n
        for n in names
        if len(skills.normalize_key(n)) <= 2 or skills.normalize_key(n) in _AMBIGUOUS_TECH_NAMES or n.lower() in _AMBIGUOUS_TECH_NAMES
    )

    # An alias that is also a distinct catalogue technology would silently merge two things.
    alias_collisions = []
    for canonical, aliases in skills._CANONICAL_ALIASES.items():  # noqa: SLF001
        for alias in aliases:
            owners = by_key.get(skills._squash(alias), [])  # noqa: SLF001
            if owners and skills.canonical_name(owners[0]) != canonical:
                alias_collisions.append({"alias": alias, "canonical": canonical, "catalogue_name": owners[0]})

    return {
        "distinct_names": len(names),
        "covered": covered,
        "uncovered_count": len(uncovered),
        "uncovered": [{"name": n, "projects": names[n]} for n in sorted(uncovered, key=lambda n: (-names[n], n))],
        "spellings_already_unified": unified,
        "near_variants": near,
        "ambiguous": ambiguous,
        "alias_collisions": alias_collisions,
    }


def to_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Technology alias audit",
        "",
        f"{report['distinct_names']} distinct technology names; {len(report['covered'])} are canonical names in "
        f"`nlp/skills.py`, {report['uncovered_count']} are not. **Uncovered does not mean unmatched**: every name still "
        "matches itself case-, space- and punctuation-insensitively. An alias is only needed when two *different* "
        "spellings mean the same thing.",
        "",
        "## Covered by the table",
        ", ".join(report["covered"]),
        "",
        "## Spellings the catalogue already writes two ways (unified by normalisation)",
    ]
    lines += [f"- {k}: {', '.join(v)}" for k, v in report["spellings_already_unified"].items()] or ["- none"]
    lines += ["", "## Near variants — candidates for a human decision, never mapped automatically"]
    lines += [f"- `{p['a']}` ~ `{p['b']}` ({p['why']}, {p['similarity']})" for p in report["near_variants"]] or ["- none"]
    lines += ["", "## Ambiguous names (short, plain English, or a second reading)", ", ".join(report["ambiguous"]) or "none"]
    lines += ["", "## Alias collisions with a different catalogue technology (must be empty)"]
    lines += [f"- {c}" for c in report["alias_collisions"]] or ["- none"]
    lines += ["", "## Uncovered names (project count)"]
    lines += [", ".join(f"{u['name']} ({u['projects']})" for u in report["uncovered"])]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit catalogue technology names against the alias table.")
    parser.add_argument("--file", type=Path, default=config.SEED_FILE)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()

    report = audit(json.loads(args.file.read_text(encoding="utf-8")))
    text = to_markdown(report)
    print(text)
    if args.markdown:
        args.markdown.write_text(text, encoding="utf-8")
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 1 if report["alias_collisions"] else 0


if __name__ == "__main__":
    sys.exit(main())
