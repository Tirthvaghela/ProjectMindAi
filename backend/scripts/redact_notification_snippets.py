"""Replace stored chat/task text in team notifications with generic wording.

    cd backend
    venv\\Scripts\\python -m scripts.redact_notification_snippets                         # DRY RUN: counts only
    venv\\Scripts\\python -m scripts.redact_notification_snippets --apply                 # throwaway databases only
    venv\\Scripts\\python -m scripts.redact_notification_snippets --apply --confirm-database <exact name>

Why: before the change that made them generic, `team_message` notifications stored
"<author>: <first 120 characters of the message>" and early `subteam_message` /
`subteam_task` notifications stored message text / a task title. A notification belongs to
its recipient, not to the team, so that text outlives the recipient's membership (and is
emailed when SMTP is on). New notifications no longer carry it; this cleans up what is
already stored.

Safety
------
* Dry run by default; prints the database name and counts per type, never record contents.
* Touches ONLY the `body` of notifications of the three types below, and only where the body
  is not already the generic text - so it is idempotent and changes nothing else (not titles,
  recipients, read flags, timestamps, or any other collection). It sends no email and creates
  no notification.
* FAIL CLOSED: --apply is allowed without further confirmation ONLY on a database whose name
  starts with a throwaway prefix (projectmind_test / projectmind_e2e). Any other database -
  "projectmind", or one with any other name - needs --confirm-database <the exact configured
  name>, i.e. the operator must type the name of the database they mean. There is no boolean
  "I approve" flag and no environment-variable override; nothing in the repository or the
  tests supplies a real confirmation.
* The script cannot verify that a backup exists - see the operator procedure that accompanies
  it. Interruption is safe: each type is one update_many whose per-document writes are atomic
  and idempotent, so re-running after a crash simply finishes what is left.
* It cannot recall emails already sent.
"""

from __future__ import annotations

import argparse
import sys

import config
from db import client as db

THROWAWAY_PREFIXES = ("projectmind_test", "projectmind_e2e")

# Must stay identical to the wording the code now writes (teams/service.py:
# TEAM_MESSAGE_NOTIFICATION_BODY); a test enforces that.
GENERIC_BODY = {
    "team_message": "A new message was posted in your team.",
    "subteam_message": "A new message was posted in your sub-team.",
    "subteam_task": "A task was assigned to you in your sub-team.",
}


def is_throwaway(name: str) -> bool:
    return isinstance(name, str) and name.startswith(THROWAWAY_PREFIXES)


def _pending_filter(type_: str) -> dict:
    return {"type": type_, "body": {"$ne": GENERIC_BODY[type_]}}


def plan() -> dict[str, int]:
    """How many records of each type would change. Read-only; counts, never contents."""
    return {t: db.notifications().count_documents(_pending_filter(t)) for t in GENERIC_BODY}


def apply() -> dict[str, int]:
    """Redact the bodies; returns how many records changed per type."""
    changed = {}
    for type_, text in GENERIC_BODY.items():
        result = db.notifications().update_many(_pending_filter(type_), {"$set": {"body": text}})
        changed[type_] = result.modified_count
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--apply", action="store_true", help="write the change (default is a dry run)")
    parser.add_argument(
        "--confirm-database", metavar="NAME", default=None,
        help="the exact name of the (non-throwaway) database to modify; must equal the configured name",
    )
    args = parser.parse_args(argv)

    print(f"database: {config.MONGO_DB}")
    # Decide BEFORE touching the database at all, so a refusal never even counts records.
    confirmed = bool(args.confirm_database) and args.confirm_database == config.MONGO_DB
    if args.apply and not is_throwaway(config.MONGO_DB) and not confirmed:
        print("refusing to modify a non-throwaway database without --confirm-database <exact name>", file=sys.stderr)
        return 2
    pending = plan()
    for type_, count in pending.items():
        print(f"  {type_}: {count} record(s) with text to replace")
    if not args.apply:
        print("dry run - nothing changed. Re-run with --apply to redact.")
        return 0
    for type_, count in apply().items():
        print(f"  {type_}: redacted {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
