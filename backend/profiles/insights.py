"""Skill progress & profile insights: a read-only, current-state summary.

Derived entirely from two things that already exist - the caller's profile
(`user_profiles`) and the roadmap steps they explicitly marked
(`roadmap_progress`) - plus the roadmap/skill-gap engines (nlp/learning_roadmap,
which wraps nlp/personal_skill_gap). Nothing here writes, and no new collection
or index is needed: the single progress query is by `user_id`, the prefix of the
existing unique (user_id, project_id) index.

Three things are kept strictly apart in the result:

* `profile`      - what the student SAID about themselves (self-reported levels).
* `learning`     - what they RECORDED: roadmap steps they set to in progress or
                   completed. Completing a step never changes a declared level.
* `next_steps`   - suggestions from their saved roadmap state and profile gaps.

History: the store keeps ONE status and its last-changed time per step, not a
log of changes. So this reports the current state (and when each step's current
status was set) and says plainly that earlier changes are not recoverable. No
dates, levels or achievements are inferred or invented.

Identity is the session-resolved user id passed in by the route; no function
here takes one from request input.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from db import client as db
from nlp import recommend, skills as skill_names
from nlp.learning_roadmap import build_roadmap
from profiles import service as profile_service

MAX_PROJECTS = 12  # most recently updated roadmaps considered
MAX_RECENT = 8
MAX_NEXT_STEPS = 6
MAX_SKILLS = 60

RECORDED = ("in_progress", "completed")

HISTORY_NOTE = (
    "ProjectMind keeps the current status of each roadmap step and when that status was last set. "
    "It does not keep a log of earlier changes, so past progress and level changes cannot be shown."
)
PROVENANCE = {
    "profile": "What you entered on your profile. Levels are self-reported and not verified.",
    "learning": "Roadmap steps you marked as in progress or completed. Viewing a page or generating a roadmap records nothing.",
    "next_steps": "Taken from your saved roadmaps and the gaps between your profile and each project's requirements.",
}


def _iso(value: Any) -> Optional[str]:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _key(name: str) -> str:
    return skill_names.normalize_key(name)


def _recorded_steps(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The stored steps that are well-formed AND carry a recorded status.
    Legacy or hand-edited documents (non-dict steps, unknown statuses) are
    skipped rather than trusted."""
    steps = doc.get("steps")
    if not isinstance(steps, dict):
        return {}
    out = {}
    for step_id, entry in steps.items():
        if isinstance(entry, dict) and entry.get("status") in RECORDED and isinstance(step_id, str):
            out[step_id] = entry
    return out


def _profile_section(profile: dict[str, Any]) -> dict[str, Any]:
    levels = {level: 0 for level in profile_service.PROFICIENCY_LEVELS}
    unspecified = 0
    for skill in profile["skills"]:
        if skill.get("level") in levels:
            levels[skill["level"]] += 1
        else:
            unspecified += 1
    completion = profile["completion"]
    return {
        "provenance": PROVENANCE["profile"],
        "status": completion["status"],
        "completion_percent": completion["percent"],
        "missing_sections": [m["label"] for m in completion["missing"]],
        "skill_count": len(profile["skills"]),
        "level_counts": {**levels, "Unspecified": unspecified} if unspecified else levels,
        "updated_at": profile.get("updated_at"),
    }


def build_insights(user_id: str) -> dict[str, Any]:
    profile = profile_service.get_profile(user_id)
    declared = {_key(s["name"]): s for s in profile["skills"] if isinstance(s.get("name"), str)}

    # One query for all of this account's progress; roadmaps are rebuilt in memory
    # from the same profile (no per-project database reads).
    docs = list(db.roadmap_progress().find({"user_id": user_id}).sort("updated_at", -1).limit(MAX_PROJECTS + 1))
    truncated = len(docs) > MAX_PROJECTS
    docs = docs[:MAX_PROJECTS]
    catalogue = recommend.get_retriever().documents

    totals = {"completed": 0, "in_progress": 0, "remaining": 0, "total_steps": 0}
    projects: list[dict[str, Any]] = []
    unavailable = 0
    retired_recorded = 0
    activity: list[dict[str, Any]] = []
    worked: dict[str, dict[str, Any]] = {}  # skill key -> aggregated recorded activity
    next_steps: list[dict[str, Any]] = []

    for doc in docs:
        project_id = doc.get("project_id")
        recorded = _recorded_steps(doc)
        project_doc = catalogue.get(project_id) if isinstance(project_id, str) else None
        roadmap = None
        if project_doc is not None:
            try:
                roadmap = build_roadmap(project_doc, profile)
            except Exception:  # noqa: BLE001 - one odd project must not break the whole summary
                roadmap = None
        if roadmap is None:
            unavailable += 1
            continue

        title = project_doc.get("title", "Untitled project")
        current = {s["id"]: s for s in roadmap["steps"]}
        counts = {"completed": 0, "in_progress": 0}
        for step in roadmap["steps"]:
            status = recorded.get(step["id"], {}).get("status", "not_started")
            step["status"] = status
            if status in counts:
                counts[status] += 1
        remaining = len(roadmap["steps"]) - counts["completed"] - counts["in_progress"]
        retired = [sid for sid in recorded if sid not in current]
        retired_recorded += len(retired)
        for key in ("completed", "in_progress"):
            totals[key] += counts[key]
        totals["remaining"] += remaining
        totals["total_steps"] += len(roadmap["steps"])
        projects.append({
            "project_id": project_id, "title": title, "total_steps": len(roadmap["steps"]),
            "completed": counts["completed"], "in_progress": counts["in_progress"], "remaining": remaining,
            "retired_recorded_steps": len(retired),
            "last_updated": _iso(doc.get("updated_at")),
        })

        for sid, entry in recorded.items():
            step = current.get(sid)
            names = step["skills"] if step else [entry.get("label") if isinstance(entry.get("label"), str) else sid]
            when = _iso(entry.get("updated_at"))
            activity.append({
                "skill": names[0] if len(names) == 1 else step["skill"], "status": entry["status"],
                "project_id": project_id, "project_title": title, "status_set_at": when,
                "earlier_step": step is None,
            })
            for name in names:
                if not isinstance(name, str) or not name.strip():
                    continue
                agg = worked.setdefault(_key(name), {"skill": name, "recognised": skill_names.canonical_name(name) is not None,
                                                     "completed": 0, "in_progress": 0, "projects": set()})
                agg[entry["status"]] += 1
                agg["projects"].add(project_id)

        # Next step in this roadmap: continue what is in progress, else the first
        # step not yet started, in roadmap order. Nothing is marked done for them.
        pick = next((s for s in roadmap["steps"] if s["status"] == "in_progress"), None)
        reason = "You marked this step in progress."
        if pick is None:
            pick = next((s for s in roadmap["steps"] if s["status"] == "not_started"), None)
            reason = "The first step in this roadmap you have not started."
        if pick is not None and len(next_steps) < MAX_NEXT_STEPS:
            next_steps.append({
                "type": "roadmap_step", "project_id": project_id, "project_title": title, "step_id": pick["id"],
                "skill": pick["skill"], "kind": pick["kind"], "classification": pick["classification"],
                "status": pick["status"], "reason": reason, "link": f"/project/{project_id}",
            })

    # Profile skills: self-reported level next to what (if anything) was recorded.
    profile_skills = []
    for key, skill in list(declared.items())[:MAX_SKILLS]:
        agg = worked.get(key)
        recorded_state = "none" if agg is None else ("completed" if agg["completed"] else "in_progress")
        profile_skills.append({
            "name": skill["name"], "declared_level": skill.get("level"),
            "recognised": skill_names.canonical_name(skill["name"]) is not None, "recorded_progress": recorded_state,
        })

    worked_out = [
        {
            "skill": a["skill"], "recognised": a["recognised"], "recorded_status": "completed" if a["completed"] else "in_progress",
            "completed_steps": a["completed"], "in_progress_steps": a["in_progress"], "projects": len(a["projects"]),
            "on_profile": key in declared, "declared_level": (declared[key].get("level") if key in declared else None),
        }
        for key, a in sorted(worked.items(), key=lambda kv: (-kv[1]["completed"], kv[1]["skill"].lower()))
    ][:MAX_SKILLS]

    # Prompts to look at the profile - phrased as a question, never as a level change.
    review = [
        {"skill": w["skill"], "declared_level": w["declared_level"],
         "reason": "You completed a step for this skill but it is not on your profile." if not w["on_profile"]
         else "You completed a step for this skill; your profile still lists it as Beginner."}
        for w in worked_out
        if w["recorded_status"] == "completed" and (not w["on_profile"] or w["declared_level"] == "Beginner")
    ]

    profile_section = _profile_section(profile)
    if profile_section["status"] != "complete" and len(next_steps) < MAX_NEXT_STEPS:
        next_steps.append({
            "type": "profile", "reason": "Your profile is missing sections, which limits how well ProjectMind can personalise.",
            "missing_sections": profile_section["missing_sections"], "link": "/profile",
        })

    activity.sort(key=lambda a: a["status_set_at"] or "", reverse=True)
    started = totals["completed"] + totals["in_progress"] + retired_recorded > 0

    return {
        "profile": profile_section,
        "profile_skills": profile_skills,
        "learning": {
            "provenance": PROVENANCE["learning"],
            "started": started,
            "projects_with_progress": len(projects),
            "projects_unavailable": unavailable,
            "projects_truncated": truncated,
            "totals": totals,
            "retired_recorded_steps": retired_recorded,
            "projects": projects,
            "skills_worked_on": worked_out,
            "recent_activity": activity[:MAX_RECENT],
        },
        "profile_review": review[:MAX_RECENT],
        "next_steps": {"provenance": PROVENANCE["next_steps"], "items": next_steps},
        "history": {"available": False, "note": HISTORY_NOTE},
        "disclaimer": "Declared levels are self-reported. Recorded progress shows steps you marked yourself; "
                      "neither is a verified measure of skill, and marking a step complete does not change your profile.",
    }
