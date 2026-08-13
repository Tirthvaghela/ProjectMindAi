"""Personalised project-timeline prediction.

`duration_weeks` on a project is a baseline for one student working solo at
the project's own stated difficulty. This module adjusts that baseline for
the two things that actually vary per team: how experienced the student is
relative to the project's difficulty, and how many people are splitting the
work. Both are named, transparent multipliers rather than a trained model —
there is no historical completion-time data in this dataset to train one on,
and a formula a student can read and sanity-check beats a black-box number.
"""

from __future__ import annotations

from typing import Any, Optional

from db.schema import DIFFICULTIES
from nlp.generator import phase_plan

# Each extra team member contributes this fraction of an ideal additional
# worker — coordination overhead means team size never divides time linearly
# (Brooks's-law territory, kept modest rather than punitive).
_TEAM_COORDINATION_FACTOR = 0.6

# A team can never be modelled as finishing in less than this fraction of the
# solo baseline — some phases (integration, documentation) don't parallelise.
_MIN_TEAM_MULTIPLIER = 0.4

# index gap (student's level - project's level) -> time multiplier.
_EXPERIENCE_MULTIPLIERS = {-2: 1.5, -1: 1.25, 0: 1.0, 1: 0.85, 2: 0.75}


def _level_index(difficulty: str) -> Optional[int]:
    try:
        return DIFFICULTIES.index(difficulty)
    except ValueError:
        return None


def _experience_multiplier(project_difficulty: str, experience_level: Optional[str]) -> tuple[float, str]:
    if not experience_level:
        return 1.0, f"Assumed to match this project's own {project_difficulty} difficulty."

    project_idx = _level_index(project_difficulty)
    student_idx = _level_index(experience_level)
    if project_idx is None or student_idx is None:
        return 1.0, "Unrecognised difficulty level; used the project's baseline."

    gap = max(-2, min(2, student_idx - project_idx))
    multiplier = _EXPERIENCE_MULTIPLIERS[gap]

    if gap == 0:
        note = f"{experience_level} experience matches this project's {project_difficulty} difficulty."
    elif gap > 0:
        note = (
            f"{experience_level} experience is ahead of this project's {project_difficulty} "
            "difficulty — faster than the baseline."
        )
    else:
        note = (
            f"{experience_level} experience is behind this project's {project_difficulty} "
            "difficulty — slower than the baseline."
        )
    return multiplier, note


def _team_multiplier(team_size: int) -> tuple[float, str]:
    team_size = max(1, team_size)
    if team_size == 1:
        return 1.0, "Solo — full baseline duration."

    effective_workers = 1 + (team_size - 1) * _TEAM_COORDINATION_FACTOR
    multiplier = max(_MIN_TEAM_MULTIPLIER, 1 / effective_workers)
    return multiplier, (
        f"{team_size} people splitting the work, with coordination overhead — "
        f"not a straight {team_size}x speed-up."
    )


def predict(doc: dict[str, Any], team_size: int = 1, experience_level: Optional[str] = None) -> dict[str, Any]:
    base_weeks = doc.get("duration_weeks") or 1
    project_difficulty = doc.get("difficulty", "")

    exp_multiplier, exp_note = _experience_multiplier(project_difficulty, experience_level)
    team_multiplier, team_note = _team_multiplier(team_size)

    raw_weeks = base_weeks * exp_multiplier * team_multiplier
    predicted_weeks = max(1.0, round(raw_weeks * 2) / 2)

    return {
        "project_id": doc.get("project_id"),
        "title": doc.get("title"),
        "base_weeks": base_weeks,
        "predicted_weeks": predicted_weeks,
        "team_size": max(1, team_size),
        "experience_level": experience_level or project_difficulty,
        "factors": [
            {"factor": "Experience level", "multiplier": round(exp_multiplier, 2), "note": exp_note},
            {"factor": "Team size", "multiplier": round(team_multiplier, 2), "note": team_note},
        ],
        "phases": phase_plan(predicted_weeks, doc.get("domain", "")),
    }
