"""Turn a saved learner profile into the inputs nlp/recommend.py already takes.

This is deliberately a translation layer, not a second ranking engine: it
produces a small `context` dict that personalized_recommend() merges into the
inputs it already understands (known skills, experience level, a soft duration
preference) plus one new, small signal (declared domain interests). Everything
else — retrieval, skill-fit, timeline-fit, difficulty-fit — is the existing
code, so a skill is never scored twice through two different paths.

Nothing here reads the database; callers pass in the profile that
profiles.service.get_profile() returned for the *signed-in* account.
"""

from __future__ import annotations

from typing import Any, Optional

import config
from db.schema import DIFFICULTIES
from nlp import skills as skill_names

_LEVEL_INDEX = {"Beginner": 0, "Intermediate": 1, "Advanced": 2}
# Fewer skills than this say too little about overall experience to infer a
# level from; a single "Advanced" Python entry must not make every project
# look Advanced-appropriate.
MIN_SKILLS_TO_INFER_LEVEL = 3


def merge_skills(explicit: list[str], extra: list[str]) -> list[str]:
    """`explicit` first, then `extra`, one entry per real skill (alias-aware),
    so a skill typed in the form and also saved in the profile counts once."""
    seen: set[str] = set()
    merged: list[str] = []
    for name in [*explicit, *extra]:
        if not isinstance(name, str) or not name.strip():
            continue
        key = skill_names.normalize_key(name)
        if key and key not in seen:
            seen.add(key)
            merged.append(name.strip())
    return merged


def infer_experience_level(skills: list[dict[str, str]]) -> Optional[str]:
    """Mean of the self-reported levels, rounded — or None with too few skills.

    A rough summary of how the person rates themselves, never a verified
    ability; the response says where the value came from so the UI can too.
    """
    levels = [_LEVEL_INDEX[s["level"]] for s in skills if s.get("level") in _LEVEL_INDEX]
    if len(levels) < MIN_SKILLS_TO_INFER_LEVEL:
        return None
    return DIFFICULTIES[min(len(DIFFICULTIES) - 1, round(sum(levels) / len(levels)))]


def build_context(profile: dict[str, Any]) -> dict[str, Any]:
    """The usable signals in a profile (API shape from profiles.service).

    `usable` is False when the profile holds nothing the recommender can act on
    (e.g. only an onboarding dismissal), so the caller can fall back to exactly
    the un-personalised behaviour instead of pretending to personalise.
    Missing sections simply contribute nothing — they never count against the
    user.
    """
    skills = [s for s in profile.get("skills", []) if isinstance(s, dict) and s.get("name")]
    levels = {skill_names.normalize_key(s["name"]): s.get("level") for s in skills}

    # Technologies from past projects are evidence of having used something, so
    # they count as known skills — but with no self-rated level, and never
    # overriding a level the user did state for the same skill.
    project_techs: list[str] = []
    for entry in profile.get("experience", []):
        for tech in entry.get("technologies", []):
            key = skill_names.normalize_key(tech)
            if key and key not in levels:
                levels[key] = None
                project_techs.append(tech)

    interests = [d for d in profile.get("interests", []) if isinstance(d, str)]
    availability = profile.get("availability") or {}
    hours = availability.get("hours_per_week")
    preferred_weeks = availability.get("max_project_weeks")

    skill_list = merge_skills([s["name"] for s in skills], project_techs)
    inferred = infer_experience_level(skills)

    usable = bool(skill_list or interests or preferred_weeks or hours)
    return {
        "usable": usable,
        "skills": skill_list,
        "skill_levels": levels,  # normalised key -> level, or None for past-project tech
        "interests": interests,
        "experience_level": inferred,
        "preferred_weeks": preferred_weeks,
        "hours_per_week": hours,
        "reference_hours_per_week": config.REFERENCE_HOURS_PER_WEEK,
    }


def pace_adjusted_weeks(predicted_weeks: float, hours_per_week: Optional[int]) -> float:
    """Estimated weeks at the user's own weekly hours.

    The catalogue's durations are for no stated pace, so this scales them by an
    explicitly *assumed* reference commitment (config.REFERENCE_HOURS_PER_WEEK)
    — fewer hours stretches the plan, more shortens it, clamped to 0.5x-3x so a
    single field cannot swing an estimate wildly. It is advice, not a measured
    prediction, and is only used for the soft duration preference and notes;
    explicit deadlines are checked against the unscaled estimate as before.
    """
    if not hours_per_week:
        return predicted_weeks
    factor = max(0.5, min(3.0, config.REFERENCE_HOURS_PER_WEEK / hours_per_week))
    return max(1.0, round(predicted_weeks * factor * 2) / 2)


def describe_skill(name: str, level: Optional[str]) -> str:
    return f"{name} ({level})" if level else name


def summary(context: dict[str, Any], explicit_skills: int, experience_source: str) -> dict[str, Any]:
    """What was used, for the response and UI: counts and names, no free text."""
    return {
        "skills_from_profile": len(context["skills"]),
        "skills_from_request": explicit_skills,
        "interests": context["interests"],
        "experience_level": context["experience_level"],
        "experience_level_source": experience_source,
        "preferred_weeks": context["preferred_weeks"],
        "hours_per_week": context["hours_per_week"],
    }
