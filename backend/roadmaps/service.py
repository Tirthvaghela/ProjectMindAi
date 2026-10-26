"""Roadmap progress: one document per (account, project) in `roadmap_progress`.

Stores only what the user explicitly records - a status per step id, plus the
step's label at the time so a step the roadmap later drops can still be shown
as "earlier step". Statuses are never derived from the profile, and nothing here
writes to profiles, teams or the catalogue. Identity is always the
session-resolved user id passed in by the route; no function takes one from
request input.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from db import client as db
from nlp.learning_roadmap import build_roadmap

STATUSES = ("not_started", "in_progress", "completed")


class RoadmapError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _saved(user_id: str, project_id: str) -> dict[str, Any]:
    doc = db.roadmap_progress().find_one({"user_id": user_id, "project_id": project_id})
    return (doc or {}).get("steps", {})


def roadmap_with_progress(doc: dict[str, Any], profile: dict[str, Any], user_id: str) -> dict[str, Any]:
    """The generated roadmap with each step's saved status merged in.

    Steps with no saved status are `not_started` - progress is never inferred.
    Saved steps the current roadmap no longer contains (e.g. the user has since
    added the skill to their profile) are kept in storage and reported under
    `retired_steps` rather than silently dropped or counted as new progress.
    """
    roadmap = build_roadmap(doc, profile)
    saved = _saved(user_id, doc["project_id"])
    current = {s["id"] for s in roadmap["steps"]}
    for step in roadmap["steps"]:
        step["status"] = saved.get(step["id"], {}).get("status", "not_started")
    counts = {s: sum(1 for st in roadmap["steps"] if st["status"] == s) for s in STATUSES}
    roadmap["progress"] = {**counts, "total": len(roadmap["steps"])}
    roadmap["retired_steps"] = [
        {"id": sid, "label": entry.get("label", sid), "status": entry["status"]}
        for sid, entry in sorted(saved.items()) if sid not in current
    ]
    return roadmap


def set_step_status(doc: dict[str, Any], profile: dict[str, Any], user_id: str, step: Any, status: Any) -> dict[str, Any]:
    """Record the caller's status for one step of the CURRENT roadmap.

    The step id must exist in the roadmap as generated right now for this
    profile and project; anything else is rejected, so progress can only attach
    to real steps. `not_started` clears the entry.
    """
    if not isinstance(step, str) or not step:
        raise RoadmapError("'step_id' is required.")
    if status not in STATUSES:
        raise RoadmapError(f"'status' must be one of {', '.join(STATUSES)}.")
    roadmap = build_roadmap(doc, profile)
    match = next((s for s in roadmap["steps"] if s["id"] == step), None)
    if match is None:
        raise RoadmapError(f"No step '{step[:60]}' in this roadmap.", status=404)

    key = {"user_id": user_id, "project_id": doc["project_id"]}
    now = datetime.now(timezone.utc)
    if status == "not_started":
        db.roadmap_progress().update_one(key, {"$unset": {f"steps.{step}": ""}, "$set": {"updated_at": now}})
    else:
        db.roadmap_progress().update_one(
            key,
            {
                "$set": {f"steps.{step}": {"status": status, "label": match["skill"], "updated_at": now}, "updated_at": now},
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
    return roadmap_with_progress(doc, profile, user_id)


def reset_progress(user_id: str, project_id: str) -> bool:
    """Delete the caller's progress for one project. Profile skills are untouched."""
    return db.roadmap_progress().delete_one({"user_id": user_id, "project_id": project_id}).deleted_count > 0
