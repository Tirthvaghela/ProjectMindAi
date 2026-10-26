"""Structured learner profile: skills, interests, goals, roles, availability.

One document per account in `user_profiles`, keyed by the session-resolved
`user_id` — no function here takes a user id from a request body, so one
account cannot read or write another's profile. The `users` collection is
untouched: an account with no profile document is simply "not started", which
is what keeps every pre-existing account working without a migration.

Validation is strict on shape (unknown fields are rejected so nothing
unintended — contact details, free-form blobs — can be stored) and lenient on
completeness: every section is optional so a profile can be filled in over
time. Skill names go through nlp/skills.py, the same alias layer retrieval and
the résumé matcher use, so "reactjs" and "React" are one skill everywhere.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

from db import client as db
from db.schema import DOMAINS
from nlp import skills as skill_names

PROFICIENCY_LEVELS = ("Beginner", "Intermediate", "Advanced")

# Roles a person might want on a team. Deliberately the same vocabulary Team
# Role Suggestions will use later (nlp/team_builder.py categories map onto
# these), so a stated preference can be compared with a suggestion.
TEAM_ROLES = (
    "Frontend Developer",
    "Backend Developer",
    "Full-Stack Developer",
    "AI / ML Engineer",
    "Data Engineer",
    "Database Engineer",
    "QA / Test Engineer",
    "DevOps Engineer",
    "Mobile Developer",
    "Embedded / IoT Engineer",
    "Security Engineer",
    "Blockchain Developer",
    "UI / UX Designer",
    "Project Coordinator",
    "Researcher / Documentation",
)

EDITABLE_FIELDS = (
    "skills",
    "interests",
    "experience",
    "learning_goals",
    "career_interests",
    "preferred_roles",
    "availability",
    "education",
    "onboarding_dismissed",
    "share_with_teams",
)

MAX_SKILLS = 50
MAX_SKILL_CHARS = 60
MAX_EXPERIENCE = 10
MAX_EXPERIENCE_TITLE = 100
MAX_EXPERIENCE_TEXT = 500
MAX_EXPERIENCE_TECH = 10
MAX_GOALS = 10
MAX_GOAL_CHARS = 200
MAX_CAREER = 10
MAX_CAREER_CHARS = 80
MAX_EDUCATION_CHARS = 200
MAX_HOURS_PER_WEEK = 80
MAX_DURATION_WEEKS = 52

# Control characters (including newlines) have no place in a skill or title and
# are how stray terminal/HTML payloads get smuggled into a "name" field.
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_SPACE_RE = re.compile(r"\s+")


class ProfileError(ValueError):
    """Invalid profile input. `field` names the offending field for the UI."""

    def __init__(self, message: str, field: Optional[str] = None):
        super().__init__(message)
        self.field = field


# --- field cleaning ---------------------------------------------------------


def _clean_text(value: Any, field: str, max_chars: int, *, allow_newlines: bool = False) -> str:
    if not isinstance(value, str):
        raise ProfileError(f"'{field}' must be text.", field)
    text = value.replace("\r\n", "\n") if allow_newlines else value
    pattern = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]") if allow_newlines else _CONTROL_RE
    text = pattern.sub(" ", text)
    text = text.strip() if allow_newlines else _SPACE_RE.sub(" ", text).strip()
    if len(text) > max_chars:
        raise ProfileError(f"'{field}' must be {max_chars} characters or fewer.", field)
    return text


def _clean_list(value: Any, field: str, max_items: int) -> list[Any]:
    if not isinstance(value, list):
        raise ProfileError(f"'{field}' must be a list.", field)
    if len(value) > max_items:
        raise ProfileError(f"'{field}' can have at most {max_items} entries.", field)
    return value


def _clean_skills(value: Any) -> list[dict[str, str]]:
    """[{name, level}] with names canonicalised and duplicates merged.

    Two spellings of one skill collapse to a single entry; when they disagree
    on level the later one wins (the user's most recent statement). A level is
    required to be one of PROFICIENCY_LEVELS but defaults to Beginner when
    omitted, so a quick "just list my skills" flow still validates.
    """
    items = _clean_list(value, "skills", MAX_SKILLS * 2)
    merged: dict[str, dict[str, str]] = {}
    for item in items:
        if isinstance(item, str):
            item = {"name": item}
        if not isinstance(item, dict):
            raise ProfileError("Each skill must be a name or {name, level}.", "skills")
        extra = set(item) - {"name", "level"}
        if extra:
            raise ProfileError(f"Unknown skill field(s): {', '.join(sorted(extra))}.", "skills")

        name = _clean_text(item.get("name", ""), "skills", MAX_SKILL_CHARS)
        if not name:
            continue
        level = item.get("level", "Beginner")
        if level is None or level == "":
            level = "Beginner"
        if level not in PROFICIENCY_LEVELS:
            raise ProfileError(f"Proficiency must be one of {', '.join(PROFICIENCY_LEVELS)}.", "skills")

        key = skill_names.normalize_key(name)
        if not key:
            raise ProfileError(f"'{name}' is not a usable skill name.", "skills")
        merged.pop(key, None)  # re-insert so the latest statement is also last
        merged[key] = {"name": skill_names.display_name(name), "level": level}

    if len(merged) > MAX_SKILLS:
        raise ProfileError(f"A profile can list at most {MAX_SKILLS} skills.", "skills")
    return list(merged.values())


def _clean_strings(value: Any, field: str, max_items: int, max_chars: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in _clean_list(value, field, max_items * 2):
        text = _clean_text(item, field, max_chars)
        if text and text.casefold() not in seen:
            seen.add(text.casefold())
            out.append(text)
    if len(out) > max_items:
        raise ProfileError(f"'{field}' can have at most {max_items} entries.", field)
    return out


def _clean_choices(value: Any, field: str, allowed: tuple[str, ...]) -> list[str]:
    items = _clean_list(value, field, len(allowed))
    out: list[str] = []
    for item in items:
        if item not in allowed:  # also rejects non-strings and unhashables safely
            raise ProfileError(f"'{item}' is not a valid option for '{field}'.", field)
        if item not in out:
            out.append(item)
    return out


def _clean_experience(value: Any) -> list[dict[str, Any]]:
    out = []
    for item in _clean_list(value, "experience", MAX_EXPERIENCE):
        if not isinstance(item, dict):
            raise ProfileError("Each experience entry must be an object.", "experience")
        extra = set(item) - {"title", "description", "technologies"}
        if extra:
            raise ProfileError(f"Unknown experience field(s): {', '.join(sorted(extra))}.", "experience")
        title = _clean_text(item.get("title", ""), "experience", MAX_EXPERIENCE_TITLE)
        if not title:
            raise ProfileError("Each experience entry needs a title.", "experience")
        description = _clean_text(item.get("description", ""), "experience", MAX_EXPERIENCE_TEXT, allow_newlines=True)
        techs = []
        for tech in _clean_list(item.get("technologies", []), "experience", MAX_EXPERIENCE_TECH):
            name = _clean_text(tech, "experience", MAX_SKILL_CHARS)
            shown = skill_names.display_name(name)
            if shown and skill_names.normalize_key(shown) not in {skill_names.normalize_key(t) for t in techs}:
                techs.append(shown)
        out.append({"title": title, "description": description, "technologies": techs})
    return out


def _clean_availability(value: Any) -> dict[str, Optional[int]]:
    if not isinstance(value, dict):
        raise ProfileError("'availability' must be an object.", "availability")
    extra = set(value) - {"hours_per_week", "max_project_weeks"}
    if extra:
        raise ProfileError(f"Unknown availability field(s): {', '.join(sorted(extra))}.", "availability")

    def whole(key: str, upper: int, label: str) -> Optional[int]:
        raw = value.get(key)
        if raw is None or raw == "":
            return None
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw != int(raw):
            raise ProfileError(f"{label} must be a whole number.", "availability")
        number = int(raw)
        if not 1 <= number <= upper:
            raise ProfileError(f"{label} must be between 1 and {upper}.", "availability")
        return number

    return {
        "hours_per_week": whole("hours_per_week", MAX_HOURS_PER_WEEK, "Hours per week"),
        "max_project_weeks": whole("max_project_weeks", MAX_DURATION_WEEKS, "Preferred project length (weeks)"),
    }


def validate_fields(payload: Any) -> dict[str, Any]:
    """Validate and normalise a (possibly partial) profile payload.

    Only the sections present are returned, so a PUT that sends `skills` alone
    leaves every other section as it was.
    """
    if not isinstance(payload, dict):
        raise ProfileError("Profile must be a JSON object.")
    unknown = set(payload) - set(EDITABLE_FIELDS)
    if unknown:
        raise ProfileError(f"Unknown profile field(s): {', '.join(sorted(unknown))}.")

    cleaned: dict[str, Any] = {}
    if "skills" in payload:
        cleaned["skills"] = _clean_skills(payload["skills"])
    if "interests" in payload:
        cleaned["interests"] = _clean_choices(payload["interests"], "interests", DOMAINS)
    if "experience" in payload:
        cleaned["experience"] = _clean_experience(payload["experience"])
    if "learning_goals" in payload:
        cleaned["learning_goals"] = _clean_strings(payload["learning_goals"], "learning_goals", MAX_GOALS, MAX_GOAL_CHARS)
    if "career_interests" in payload:
        cleaned["career_interests"] = _clean_strings(payload["career_interests"], "career_interests", MAX_CAREER, MAX_CAREER_CHARS)
    if "preferred_roles" in payload:
        cleaned["preferred_roles"] = _clean_choices(payload["preferred_roles"], "preferred_roles", TEAM_ROLES)
    if "availability" in payload:
        cleaned["availability"] = _clean_availability(payload["availability"])
    if "education" in payload:
        cleaned["education"] = _clean_text(payload["education"], "education", MAX_EDUCATION_CHARS)
    if "onboarding_dismissed" in payload:
        if not isinstance(payload["onboarding_dismissed"], bool):
            raise ProfileError("'onboarding_dismissed' must be true or false.", "onboarding_dismissed")
        cleaned["onboarding_dismissed"] = payload["onboarding_dismissed"]
    if "share_with_teams" in payload:
        if not isinstance(payload["share_with_teams"], bool):
            raise ProfileError("'share_with_teams' must be true or false.", "share_with_teams")
        cleaned["share_with_teams"] = payload["share_with_teams"]
    return cleaned


# --- completion -------------------------------------------------------------

# (key, label, core). Core sections decide "complete"; experience and
# education improve the picture but are never required.
_SECTIONS = (
    ("skills", "Skills", True),
    ("interests", "Project interests", True),
    ("goals", "Learning or career goals", True),
    ("roles", "Preferred team roles", True),
    ("availability", "Time available", True),
    ("experience", "Past projects", False),
)


def _section_done(profile: dict[str, Any], key: str) -> bool:
    if key == "goals":
        return bool(profile.get("learning_goals") or profile.get("career_interests"))
    if key == "roles":
        return bool(profile.get("preferred_roles"))
    if key == "availability":
        availability = profile.get("availability") or {}
        return bool(availability.get("hours_per_week"))
    return bool(profile.get(key))


def completion(profile: dict[str, Any]) -> dict[str, Any]:
    """Percent filled, which sections are missing, and an overall status.

    Status is "not_started" (nothing saved), "in_progress", or "complete" (all
    core sections present). It is derived from the stored data every time, never
    stored, so it cannot drift from what the profile actually contains.
    """
    done = {key: _section_done(profile, key) for key, _label, _core in _SECTIONS}
    missing = [{"key": key, "label": label, "core": core} for key, label, core in _SECTIONS if not done[key]]
    core_done = all(done[key] for key, _label, core in _SECTIONS if core)
    percent = round(100 * sum(done.values()) / len(_SECTIONS))
    if not any(done.values()):
        status = "not_started"
    elif core_done:
        status = "complete"
    else:
        status = "in_progress"
    return {"status": status, "percent": percent, "missing": missing}


# --- persistence ------------------------------------------------------------


def _empty() -> dict[str, Any]:
    return {
        "skills": [],
        "interests": [],
        "experience": [],
        "learning_goals": [],
        "career_interests": [],
        "preferred_roles": [],
        "availability": {"hours_per_week": None, "max_project_weeks": None},
        "education": "",
        "onboarding_dismissed": False,
        # Opt-in. Absent (every profile saved before this existed) means NOT shared.
        "share_with_teams": False,
    }


def _present(doc: Optional[dict[str, Any]]) -> dict[str, Any]:
    """The API shape: every section present (so the UI never null-checks),
    plus derived completion and a per-skill `recognised` flag. Mongo internals
    and the owner id are not echoed back."""
    profile = _empty()
    if doc:
        for key in EDITABLE_FIELDS:
            if key in doc:
                profile[key] = doc[key]
        profile["share_with_teams"] = doc.get("share_with_teams") is True  # only an explicit true counts
        profile["created_at"] = doc["created_at"].isoformat() if doc.get("created_at") else None
        profile["updated_at"] = doc["updated_at"].isoformat() if doc.get("updated_at") else None
    else:
        profile["created_at"] = profile["updated_at"] = None
    profile["skills"] = [
        {**skill, "recognised": skill_names.canonical_name(skill["name"]) is not None} for skill in profile["skills"]
    ]
    profile["completion"] = completion(profile)
    return profile


def get_profile(user_id: str) -> dict[str, Any]:
    """The caller's profile. Never writes: a user who has not started simply
    gets an empty profile back, so merely opening the page creates no data."""
    return _present(db.profiles().find_one({"user_id": user_id}))


def shares_with_teams(profile: Optional[dict[str, Any]]) -> bool:
    """True only when the person explicitly opted in. A missing profile, a profile
    saved before the setting existed, or any non-True value all mean no."""
    return bool(profile) and profile.get("share_with_teams") is True


def get_profiles(user_ids: list[str]) -> dict[str, dict[str, Any]]:
    """API-shaped profiles for the given accounts that have one saved, one query.

    For callers that have ALREADY established the right to see these accounts
    (e.g. teammates of a team the caller belongs to). It takes ids from the
    caller's own authorisation, never from request input, and returns the full
    profile - the caller is responsible for exposing only what it needs."""
    ids = [u for u in user_ids if isinstance(u, str)]
    if not ids:
        return {}
    return {doc["user_id"]: _present(doc) for doc in db.profiles().find({"user_id": {"$in": ids}})}


def save_profile(user_id: str, payload: Any) -> dict[str, Any]:
    """Merge the validated sections into this account's profile (upsert).

    Sections not in the payload are left alone. An empty payload is rejected
    rather than silently creating an empty document.
    """
    fields = validate_fields(payload)
    if not fields:
        raise ProfileError("Nothing to update — send at least one profile section.")
    now = datetime.now(timezone.utc)
    db.profiles().update_one(
        {"user_id": user_id},
        {"$set": {**fields, "updated_at": now}, "$setOnInsert": {"user_id": user_id, "created_at": now}},
        upsert=True,
    )
    return get_profile(user_id)


def delete_profile(user_id: str) -> bool:
    """Remove the caller's profile. The account itself is untouched."""
    return db.profiles().delete_one({"user_id": user_id}).deleted_count > 0


def options() -> dict[str, Any]:
    """Static choices the form offers; no user data."""
    return {
        "proficiency_levels": list(PROFICIENCY_LEVELS),
        "domains": list(DOMAINS),
        "team_roles": list(TEAM_ROLES),
        "limits": {
            "skills": MAX_SKILLS,
            "skill_chars": MAX_SKILL_CHARS,
            "experience": MAX_EXPERIENCE,
            "goals": MAX_GOALS,
            "goal_chars": MAX_GOAL_CHARS,
            "career": MAX_CAREER,
            "hours_per_week": MAX_HOURS_PER_WEEK,
            "max_project_weeks": MAX_DURATION_WEEKS,
        },
    }
