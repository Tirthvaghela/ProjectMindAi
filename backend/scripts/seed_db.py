"""Load the curated dataset into MongoDB.

    cd backend
    venv\\Scripts\\python -m scripts.seed_db

Idempotent: re-running updates existing projects by project_id rather than
creating duplicates, so it is safe to run after every dataset edit.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from pymongo import UpdateOne

import config
from db import client as db
from db import schema

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
log = logging.getLogger("seed")


def load_seed() -> list[dict]:
    if not config.SEED_FILE.exists():
        log.error("Seed file not found: %s", config.SEED_FILE)
        sys.exit(1)

    try:
        data = json.loads(config.SEED_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        log.error("Seed file is not valid JSON: %s", error)
        sys.exit(1)

    if not isinstance(data, list):
        log.error("Seed file must contain a JSON array of project objects.")
        sys.exit(1)
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed MongoDB with project data.")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete all existing projects before inserting.",
    )
    args = parser.parse_args()

    if not db.ping():
        log.error("Cannot reach MongoDB at %s", config.MONGO_URI)
        log.error("Is mongod running? Check the MongoDB service or Compass.")
        return 1

    records = load_seed()
    log.info("Read %d records from %s", len(records), config.SEED_FILE.name)

    # Validate everything before writing anything — a partial seed is worse
    # than no seed, because the failure is silent until search returns junk.
    invalid = 0
    seen_ids: set[str] = set()
    for index, record in enumerate(records):
        problems = schema.validate(record)

        pid = record.get("project_id")
        if pid in seen_ids:
            problems.append(f"duplicate project_id '{pid}' within the seed file")
        seen_ids.add(pid)

        if problems:
            invalid += 1
            log.error("Record %d (%s):", index, pid or "no id")
            for problem in problems:
                log.error("    - %s", problem)

    if invalid:
        log.error("%d invalid record(s). Nothing was written.", invalid)
        return 1

    db.ensure_indexes()

    if args.replace:
        deleted = db.projects().delete_many({}).deleted_count
        log.info("Deleted %d existing project(s)", deleted)

    operations = [
        UpdateOne({"project_id": r["project_id"]}, {"$set": r}, upsert=True)
        for r in records
    ]
    result = db.projects().bulk_write(operations)

    log.info(
        "Seed complete: %d inserted, %d updated, %d total in database",
        result.upserted_count,
        result.modified_count,
        db.projects().count_documents({}),
    )
    log.info("Next: venv\\Scripts\\python -m scripts.build_index")
    return 0


if __name__ == "__main__":
    sys.exit(main())
