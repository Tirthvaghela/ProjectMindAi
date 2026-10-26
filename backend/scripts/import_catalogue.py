"""Controlled catalogue expansion: validate -> dry-run plan -> reviewed apply.

    cd backend
    venv\\Scripts\\python -m scripts.import_catalogue --batch batch_001            # dry run (default)
    venv\\Scripts\\python -m scripts.import_catalogue --batch batch_001 --apply    # write, from the reviewed plan
    venv\\Scripts\\python -m scripts.import_catalogue --rollback batch_001         # dry run of an undo
    venv\\Scripts\\python -m scripts.import_catalogue --rollback batch_001 --apply

Candidate records live in `dataset/candidates/<batch>/*.json`, each file a JSON
array of project objects in the *existing* project format (see db/schema.py),
without `project_id` — ids are assigned here, continuing after the highest
existing `pm-NNN`, so an existing id is never reused or renumbered.

Nothing is written without `--apply`, and `--apply` only applies the plan the
last dry run produced (`dataset/reports/<batch>.plan.json`): it refuses if the
candidate files changed since, so what was reviewed is what is imported.

A candidate is rejected (with the specific reasons, exported to the plan) for:
unexpected fields, schema violations, placeholder/filler text, implausible
difficulty/duration pairs, malformed lists, an exact normalised-title match
with an existing or earlier candidate record, or embedding similarity at or
above REJECT_SIMILARITY with one. Similarity in [REVIEW_SIMILARITY,
REJECT_SIMILARITY) is *kept but listed for review* — closely related projects
can be legitimately distinct, so similarity is a signal, not a verdict.
Technology names not seen in the catalogue or alias table are warnings.

Apply is additive and reversible:
  * existing database documents are never modified (`$setOnInsert` upserts);
  * the seed file and embedding index are backed up first;
  * the seed file gets the new records appended, byte-for-byte in the format
    it already uses;
  * re-running is a no-op (records already present are skipped);
  * `--rollback` removes exactly the ids a batch manifest recorded.
Run `python -m scripts.build_index` afterwards so search can see the new records.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import config
from db import schema
from nlp import skills
from scripts import catalogue_audit

log = logging.getLogger("import_catalogue")

MIN_DESCRIPTION = 120  # characters; a batch may demand more (--min-description)
REJECT_SIMILARITY = 0.88  # existing catalogue's most similar pair is 0.81
REVIEW_SIMILARITY = 0.80

ID_PATTERN = re.compile(r"^pm-(\d+)$")
_FIELD_ORDER = (
    "project_id", "title", "description", "domain", "technologies", "difficulty",
    "duration_weeks", "skills", "keywords", "github_url", "learning_resources",
)
_ALLOWED_KEYS = set(_FIELD_ORDER) - {"project_id"}
_FILLER = re.compile(r"lorem ipsum|\btbd\b|\btodo\b|placeholder|coming soon|to be (added|decided)|insert .* here|n/a\b", re.I)
_GENERIC_OPENER = re.compile(r"^(this project|the project|a project) (is|aims|will|helps|focuses)", re.I)

# Difficulty -> plausible duration range, calibrated on the existing catalogue
# (Beginner 3-7, Intermediate 6-11, Advanced 8-14 weeks) with a little slack.
_DURATION_RANGE = {"Beginner": (3, 8), "Intermediate": (5, 12), "Advanced": (7, 14)}


# --- helpers -----------------------------------------------------------------


def norm_title(title: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(title).lower()).strip()


def read_seed(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_seed(path: Path, records: list[dict]) -> None:
    """Exactly the format the seed file already uses (indent 2, UTF-8,
    trailing newline) — verified byte-identical on the existing 500 records —
    written to a temp file and moved into place so a crash can't truncate it."""
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_candidates(batch_dir: Path) -> list[dict[str, Any]]:
    out = []
    for file in sorted(batch_dir.glob("*.json")):
        data = json.loads(file.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(f"{file.name} must contain a JSON array")
        for index, record in enumerate(data):
            out.append({"source": file.name, "index": index, "record": record})
    return out


def content_hash(candidates: list[dict[str, Any]]) -> str:
    blob = json.dumps([c["record"] for c in candidates], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def known_technology_keys(existing: list[dict]) -> set[str]:
    keys = {skills.normalize_key(t) for r in existing for t in r.get("technologies", []) if isinstance(t, str)}
    keys |= {skills.normalize_key(name) for name in skills._CANONICAL_ALIASES}  # noqa: SLF001 - the table's own names
    return keys


# --- per-record checks --------------------------------------------------------


def check_candidate(record: Any, tech_keys: set[str], min_description: int = MIN_DESCRIPTION) -> tuple[list[str], list[str]]:
    """(errors, warnings) for one candidate on its own, before any comparison
    with other records."""
    if not isinstance(record, dict):
        return ["record is not a JSON object"], []

    errors: list[str] = []
    warnings: list[str] = []

    if "project_id" in record:
        errors.append("candidates must not carry a project_id; ids are assigned by the importer")
    extra = sorted(set(record) - _ALLOWED_KEYS - {"project_id"})
    if extra:
        errors.append(f"unexpected field(s) {extra}: the catalogue format is fixed (db/schema.py)")

    errors.extend(schema.validate({"project_id": "pm-000", **record}))

    title = record.get("title")
    if isinstance(title, str) and not 8 <= len(title.strip()) <= 90:
        errors.append(f"title is {len(title.strip())} chars; expected 8-90")

    description = record.get("description")
    if isinstance(description, str):
        if not min_description <= len(description) <= 450:
            errors.append(f"description is {len(description)} chars; expected {min_description}-450")
        if _FILLER.search(description) or (isinstance(title, str) and _FILLER.search(title)):
            errors.append("placeholder/filler text detected")
        if _GENERIC_OPENER.match(description.strip()):
            warnings.append("description opens with generic filler ('This project aims to...')")

    for field, (lo, hi) in {"technologies": (2, 6), "skills": (3, 6), "keywords": (3, 6)}.items():
        values = record.get(field)
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            continue  # already reported by schema.validate
        if not lo <= len(values) <= hi:
            errors.append(f"'{field}' has {len(values)} items; expected {lo}-{hi}")
        keys = [skills.normalize_key(v) if field == "technologies" else v.strip().casefold() for v in values]
        if len(set(keys)) != len(keys):
            errors.append(f"'{field}' contains duplicates")
        if any(not v.strip() or len(v) > 60 for v in values):
            errors.append(f"'{field}' contains an empty or over-long item")
        if field == "keywords" and any(v != v.lower() for v in values):
            errors.append("keywords must be lowercase")

    difficulty, weeks = record.get("difficulty"), record.get("duration_weeks")
    if difficulty in _DURATION_RANGE and isinstance(weeks, int) and not isinstance(weeks, bool):
        lo, hi = _DURATION_RANGE[difficulty]
        if not lo <= weeks <= hi:
            errors.append(f"{difficulty} project with duration_weeks={weeks} is implausible (expected {lo}-{hi})")

    techs = record.get("technologies")
    if isinstance(techs, list):
        unknown = [t for t in techs if isinstance(t, str) and skills.normalize_key(t) not in tech_keys]
        if unknown:
            warnings.append(f"technology name(s) not seen in the catalogue or alias table: {unknown}")

    for url_field in ("github_url", "learning_resources"):
        if record.get(url_field):
            warnings.append(f"{url_field} supplied but this pipeline does not verify links (use validate_dataset --check-links)")

    return errors, warnings


# --- planning ------------------------------------------------------------------


def build_record(record: dict[str, Any], project_id: str) -> dict[str, Any]:
    merged = {"project_id": project_id, **{k: v for k, v in record.items()}}
    out = {k: merged[k] for k in _FIELD_ORDER if k in merged}
    for key in ("title", "description"):
        out[key] = out[key].strip()
    return out


def _default_encode(texts: list[str]):
    from nlp import embeddings

    return embeddings.encode(texts)


def plan_batch(
    candidates: list[dict[str, Any]],
    existing: list[dict],
    encode: Optional[Callable[[list[str]], Any]] = None,
    batch: str = "batch",
    min_description: int = MIN_DESCRIPTION,
) -> dict[str, Any]:
    """Pure planning step: classify every candidate and assign ids. Writes
    nothing."""
    import numpy as np

    encode = encode or _default_encode
    tech_keys = known_technology_keys(existing)
    existing_by_title = {norm_title(r["title"]): r for r in existing}
    numbers = [int(m.group(1)) for r in existing if (m := ID_PATTERN.match(str(r.get("project_id", ""))))]
    next_number = (max(numbers) if numbers else 0) + 1

    rejected: list[dict[str, Any]] = []
    already_present: list[dict[str, Any]] = []
    survivors: list[dict[str, Any]] = []
    seen_titles: dict[str, str] = {}

    for cand in candidates:
        record = cand["record"]
        errors, warnings = check_candidate(record, tech_keys, min_description)
        entry = {"source": cand["source"], "index": cand["index"], "record": record}
        if errors:
            rejected.append({**entry, "reasons": errors})
            continue

        key = norm_title(record["title"])
        match = existing_by_title.get(key)
        if match is not None:
            same = match.get("description", "").strip() == record["description"].strip()
            (already_present if same else rejected).append(
                {**entry, "matches": match["project_id"]}
                if same
                else {**entry, "reasons": [f"normalised title duplicates existing {match['project_id']} ('{match['title']}')"]}
            )
            continue
        if key in seen_titles:
            rejected.append({**entry, "reasons": [f"normalised title duplicates an earlier candidate ('{seen_titles[key]}')"]})
            continue
        seen_titles[key] = record["title"]
        survivors.append({**entry, "warnings": warnings})

    # Semantic comparison against the existing catalogue and earlier survivors.
    approved: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    if survivors:
        existing_texts = [schema.embedding_text(r) for r in existing]
        cand_texts = [schema.embedding_text(s["record"]) for s in survivors]
        matrix = np.asarray(encode(existing_texts + cand_texts), dtype=np.float32)
        base, cand_vecs = matrix[: len(existing)], matrix[len(existing):]
        accepted_idx: list[int] = []
        for i, s in enumerate(survivors):
            best_sim, best_label = -1.0, ""
            if len(existing):
                sims = base @ cand_vecs[i]
                j = int(np.argmax(sims))
                best_sim, best_label = float(sims[j]), f"{existing[j]['project_id']} '{existing[j]['title']}'"
            if accepted_idx:
                sims = cand_vecs[accepted_idx] @ cand_vecs[i]
                j = int(np.argmax(sims))
                if float(sims[j]) > best_sim:
                    other = survivors[accepted_idx[j]]["record"]
                    best_sim, best_label = float(sims[j]), f"earlier candidate '{other['title']}'"

            if best_sim >= REJECT_SIMILARITY:
                rejected.append(
                    {"source": s["source"], "index": s["index"], "record": s["record"],
                     "reasons": [f"semantic near-duplicate ({best_sim:.3f}) of {best_label}"]}
                )
                continue
            accepted_idx.append(i)
            if best_sim >= REVIEW_SIMILARITY:
                review.append({"title": s["record"]["title"], "similar_to": best_label, "similarity": round(best_sim, 3)})
            approved.append({**s, "max_similarity": round(best_sim, 3)})

    records = []
    for offset, s in enumerate(approved):
        records.append(build_record(s["record"], f"pm-{next_number + offset:03d}"))

    warnings_by_title = {s["record"]["title"]: s["warnings"] for s in approved if s["warnings"]}
    return {
        "batch": batch,
        "content_hash": content_hash(candidates),
        "thresholds": {"reject": REJECT_SIMILARITY, "review": REVIEW_SIMILARITY, "min_description": min_description},
        "counts": {
            "candidates": len(candidates),
            "approved": len(records),
            "rejected": len(rejected),
            "already_present": len(already_present),
            "review_flagged": len(review),
        },
        "first_id": records[0]["project_id"] if records else None,
        "last_id": records[-1]["project_id"] if records else None,
        "approved": records,
        "rejected": rejected,
        "already_present": already_present,
        "review": review,
        "warnings": warnings_by_title,
        "projected": catalogue_audit.audit_records([*existing, *records]),
    }


def summarise(plan: dict[str, Any]) -> str:
    c, p = plan["counts"], plan["projected"]
    lines = [
        f"Batch {plan['batch']}: {c['candidates']} candidates -> {c['approved']} approved "
        f"({plan['first_id']}..{plan['last_id']}), {c['rejected']} rejected, "
        f"{c['already_present']} already present, {c['review_flagged']} flagged for review",
        f"Projected catalogue: {p['unique_project_ids']} projects, {len(p['duplicate_project_ids'])} duplicate ids, "
        f"{len(p['duplicate_titles'])} duplicate titles, {len(p['schema_problems'])} schema problems, "
        f"{len(p['unknown_or_invalid_duration'])} unknown durations",
        f"By difficulty: {p['by_difficulty']}",
        f"By domain: {p['by_domain']}",
    ]
    reasons = Counter(r.split(":")[0].split("(")[0].strip()[:60] for rej in plan["rejected"] for r in rej["reasons"])
    if reasons:
        lines.append(f"Rejection reasons: {dict(reasons.most_common())}")
    return "\n".join(lines)


# --- apply / rollback -----------------------------------------------------------


def _backup(path: Path, backup_dir: Path, stamp: str) -> Optional[Path]:
    if not path.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"{path.stem}.{stamp}{path.suffix}"
    shutil.copy2(path, target)
    return target


def apply_plan(
    plan: dict[str, Any],
    seed_path: Path,
    projects_collection,
    reports_dir: Path,
    backup_dirs: tuple[Path, ...] = (),
    extra_backup_files: tuple[Path, ...] = (),
) -> dict[str, Any]:
    """Append the approved records to the seed file and insert-only upsert them
    into MongoDB. Idempotent: ids/titles already present are skipped."""
    from pymongo import UpdateOne

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    existing = read_seed(seed_path)
    present_ids = {r["project_id"] for r in existing}
    present_titles = {norm_title(r["title"]) for r in existing}

    to_add = []
    for record in plan["approved"]:
        if record["project_id"] in present_ids or norm_title(record["title"]) in present_titles:
            continue
        to_add.append(record)

    # Re-validate what is about to be written; the plan is a file and files change.
    problems = {r["project_id"]: schema.validate(r) for r in to_add if schema.validate(r)}
    if problems:
        raise ValueError(f"approved records no longer validate: {problems}")

    # Only back up when something is about to change, so a no-op re-run leaves
    # no clutter behind.
    backups: list[Optional[Path]] = []
    if to_add:
        backups.append(_backup(seed_path, seed_path.parent / "backups", stamp))
        for f in extra_backup_files:
            backups.append(_backup(f, f.parent / "backups", stamp))

    if to_add:
        write_seed(seed_path, [*existing, *to_add])

    before = projects_collection.count_documents({})
    # $setOnInsert: an existing document is never touched, even if a record
    # with the same id were somehow already in the database.
    inserted = 0
    if to_add:
        result = projects_collection.bulk_write(
            [UpdateOne({"project_id": r["project_id"]}, {"$setOnInsert": r}, upsert=True) for r in to_add]
        )
        inserted = result.upserted_count
    after = projects_collection.count_documents({})

    manifest = {
        "batch": plan["batch"],
        "applied_at": stamp,
        "content_hash": plan["content_hash"],
        "project_ids": [r["project_id"] for r in to_add],
        "skipped_already_present": len(plan["approved"]) - len(to_add),
        "database_count_before": before,
        "database_count_after": after,
        "backups": [str(b) for b in backups if b],
    }
    if to_add:
        (reports_dir.parent / "batches").mkdir(parents=True, exist_ok=True)
        (reports_dir.parent / "batches" / f"{plan['batch']}.manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
    manifest["inserted"] = inserted
    return manifest


def rollback_batch(manifest_path: Path, seed_path: Path, projects_collection, apply: bool) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ids = set(manifest["project_ids"])
    seed = read_seed(seed_path)
    in_seed = [r["project_id"] for r in seed if r["project_id"] in ids]
    in_db = [d["project_id"] for d in projects_collection.find({"project_id": {"$in": sorted(ids)}}, {"project_id": 1})]
    summary = {"batch": manifest["batch"], "ids": sorted(ids), "in_seed_file": len(in_seed), "in_database": len(in_db), "applied": False}
    if apply:
        write_seed(seed_path, [r for r in seed if r["project_id"] not in ids])
        projects_collection.delete_many({"project_id": {"$in": sorted(ids)}})
        summary["applied"] = True
    return summary


# --- CLI -------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Controlled catalogue expansion.")
    parser.add_argument("--batch", default="batch_001")
    parser.add_argument("--min-description", type=int, default=MIN_DESCRIPTION, help="Minimum description length in characters.")
    parser.add_argument("--apply", action="store_true", help="Write the reviewed plan (default: dry run).")
    parser.add_argument("--rollback", metavar="BATCH", help="Undo a previously applied batch (dry run unless --apply).")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    seed_path = config.SEED_FILE
    datasets = config.DATASET_DIR
    reports_dir = datasets / "reports"

    if args.rollback:
        from db import client as db

        manifest = datasets / "batches" / f"{args.rollback}.manifest.json"
        summary = rollback_batch(manifest, seed_path, db.projects(), apply=args.apply)
        print(json.dumps(summary, indent=2))
        if not args.apply:
            print("Dry run only. Pass --apply to remove exactly these ids from the seed file and database.")
        return 0

    batch_dir = datasets / "candidates" / args.batch
    if not batch_dir.is_dir():
        log.error("No candidate directory: %s", batch_dir)
        return 1
    reports_dir.mkdir(parents=True, exist_ok=True)
    plan_path = reports_dir / f"{args.batch}.plan.json"

    candidates = load_candidates(batch_dir)
    existing = read_seed(seed_path)

    if args.apply:
        if not plan_path.exists():
            log.error("No reviewed plan at %s. Run a dry run first.", plan_path)
            return 1
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        if plan["content_hash"] != content_hash(candidates):
            log.error("Candidate files changed since the plan was generated. Re-run the dry run and review it again.")
            return 1
        from db import client as db

        if not db.ping():
            log.error("Cannot reach MongoDB at %s", config.MONGO_URI)
            return 1
        db.ensure_indexes()
        manifest = apply_plan(
            plan, seed_path, db.projects(), reports_dir,
            extra_backup_files=(config.EMBEDDINGS_FILE, config.IDS_FILE),
        )
        ids = manifest.pop("project_ids")
        print(json.dumps({**manifest, "project_ids": f"{len(ids)} ids, {ids[0]}..{ids[-1]}" if ids else "none"}, indent=2))
        print("Next: venv\\Scripts\\python -m scripts.build_index   (search cannot see new projects until then)")
        return 0

    plan = plan_batch(candidates, existing, batch=args.batch, min_description=args.min_description)
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    print(summarise(plan))
    for item in plan["review"]:
        print(f"  REVIEW  {item['similarity']:.3f}  '{item['title']}'  ~  {item['similar_to']}")
    for title, notes in list(plan["warnings"].items())[:40]:
        print(f"  WARN    '{title}': {'; '.join(notes)}")
    print(f"\nDRY RUN: nothing was written. Plan saved to {plan_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
