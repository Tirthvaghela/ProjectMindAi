"""Validate the dataset before it reaches the database.

    cd backend
    venv\\Scripts\\python -m scripts.validate_dataset
    venv\\Scripts\\python -m scripts.validate_dataset --check-links

Three independent checks:

1. Schema     — every record has required fields with sane values.
2. Duplicates — near-identical records, found by embedding similarity rather
                than string matching, so a reworded copy is still caught.
3. Links      — GitHub and resource URLs still resolve (opt-in; it makes one
                network request per URL).

The duplicate check is the one that matters most for recommendation quality: a
corpus containing the same project three times wastes the user's top-3 slots on
what is effectively one result.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter

import numpy as np

import config
from db import schema
from nlp import embeddings

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
log = logging.getLogger("validate")


def check_schema(records: list[dict]) -> int:
    failures = 0
    seen: Counter[str] = Counter()

    for index, record in enumerate(records):
        problems = schema.validate(record)
        pid = record.get("project_id", f"<index {index}>")
        seen[pid] += 1

        if problems:
            failures += 1
            log.error("%s:", pid)
            for problem in problems:
                log.error("    - %s", problem)

    for pid, count in seen.items():
        if count > 1:
            failures += 1
            log.error("project_id '%s' appears %d times", pid, count)

    if not failures:
        log.info("Schema: all %d records valid", len(records))
    return failures


def check_duplicates(records: list[dict], threshold: float) -> int:
    """Find near-identical records via embedding similarity."""
    log.info("Encoding %d records for duplicate detection...", len(records))
    texts = [schema.embedding_text(r) for r in records]
    matrix = embeddings.encode(texts)

    similarity = matrix @ matrix.T
    # Zero the diagonal and lower triangle so each pair is reported once and
    # no record is compared against itself.
    similarity = np.triu(similarity, k=1)

    pairs = np.argwhere(similarity >= threshold)
    for i, j in pairs:
        log.warning(
            "Possible duplicate (%.3f):\n    %s  %s\n    %s  %s",
            similarity[i, j],
            records[i]["project_id"],
            records[i]["title"],
            records[j]["project_id"],
            records[j]["title"],
        )

    if len(pairs) == 0:
        log.info("Duplicates: none above %.2f similarity", threshold)
    return len(pairs)


def _probe(url: str, timeout: int = 10) -> tuple[bool, str]:
    """Return (reachable, detail) for a single URL.

    Tries HEAD first (cheap), falling back to GET when a host rejects HEAD.
    Distinguishes "this URL is dead" from "this host is throttling or blocking
    an automated client", because only the former is a dataset defect.
    """
    import urllib.error
    import urllib.request

    headers = {"User-Agent": "Mozilla/5.0 (compatible; ProjectMind/1.0)"}

    for method in ("HEAD", "GET"):
        request = urllib.request.Request(url, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status < 400:
                    return True, f"HTTP {response.status}"
                return False, f"HTTP {response.status}"
        except urllib.error.HTTPError as error:
            # 429 = rate limited, 403 = bot-blocked, 405 = HEAD unsupported.
            # None of these mean the page is missing, and treating them as
            # broken produces false failures that train you to ignore the
            # validator — the worst possible outcome for a checking tool.
            if error.code in (403, 429):
                return True, f"HTTP {error.code} (throttled/blocked, not dead)"
            if error.code == 405 and method == "HEAD":
                continue  # retry the same URL with GET
            return False, f"HTTP {error.code}"
        except Exception as error:  # noqa: BLE001
            if method == "HEAD":
                continue  # some hosts mishandle HEAD at the TLS layer
            return False, type(error).__name__

    return False, "unreachable"


def check_links(records: list[dict]) -> int:
    """Check every URL for link rot. Opt-in — this hits the network."""
    import time

    urls: list[tuple[str, str]] = []
    for record in records:
        pid = record["project_id"]
        if record.get("github_url"):
            urls.append((pid, record["github_url"]))
        for resource in record.get("learning_resources", []):
            urls.append((pid, resource))

    if not urls:
        log.info("Links: no URLs to check")
        return 0

    # De-duplicate: the same official docs URL is cited by several projects,
    # and requesting it once per citation is what triggered rate limiting.
    unique_urls = sorted({url for _, url in urls})
    owners: dict[str, list[str]] = {}
    for pid, url in urls:
        owners.setdefault(url, []).append(pid)

    log.info(
        "Checking %d unique URL(s) from %d citation(s)...", len(unique_urls), len(urls)
    )

    broken = 0
    for index, url in enumerate(unique_urls):
        reachable, detail = _probe(url)
        if not reachable:
            broken += 1
            log.error("%s  %s  (cited by %s)", detail, url, ", ".join(owners[url]))

        # Politeness delay. Without it, docs hosts return 429 and the run
        # reports healthy links as broken.
        if index < len(unique_urls) - 1:
            time.sleep(0.4)

    if not broken:
        log.info("Links: all %d reachable", len(unique_urls))
    return broken


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the project dataset.")
    parser.add_argument("--check-links", action="store_true", help="Verify URLs resolve.")
    parser.add_argument(
        "--threshold",
        type=float,
        default=config.DUPLICATE_THRESHOLD,
        help=f"Duplicate similarity threshold (default {config.DUPLICATE_THRESHOLD}).",
    )
    args = parser.parse_args()

    if not config.SEED_FILE.exists():
        log.error("Seed file not found: %s", config.SEED_FILE)
        return 1

    records = json.loads(config.SEED_FILE.read_text(encoding="utf-8"))
    log.info("Validating %d records from %s\n", len(records), config.SEED_FILE.name)

    schema_failures = check_schema(records)
    duplicate_count = check_duplicates(records, args.threshold)
    link_failures = check_links(records) if args.check_links else 0

    print()
    log.info("--- Summary ---")
    log.info("  schema failures : %d", schema_failures)
    log.info("  duplicate pairs : %d", duplicate_count)
    if args.check_links:
        log.info("  broken links    : %d", link_failures)
    else:
        log.info("  broken links    : not checked (pass --check-links)")

    # Duplicates are a warning, not a failure: two genuinely different projects
    # can be legitimately similar, and a human should make that call.
    return 1 if (schema_failures or link_failures) else 0


if __name__ == "__main__":
    sys.exit(main())
