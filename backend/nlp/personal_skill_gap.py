"""Personalised skill-gap analysis: a saved profile against one project.

Deterministic and LLM-free. It adds no skill vocabulary of its own:

* names and aliases come from nlp/skills.py (same_skill / normalize_key),
* "related skill" detection is the token logic recommend.skill_gap_for_doc
  already uses (so this and /api/skill-gap never disagree about what counts as
  related),
* "builds on your X" and the project-module link reuse the Feature 3 role
  keyword table (nlp/team_builder.py) and module categories,
* learning order, prerequisites and resource links come from
  nlp/learning_path.py.

What it does NOT have: any per-skill proficiency requirement. The catalogue
records a project's difficulty and its skills/technologies, nothing finer, so
the "bar" a self-reported level is compared with is derived from difficulty
alone (see TARGET_LEVEL) and is stated in every response. All levels are
self-reported; none is treated as verified, and a skill missing from a profile
is "not on your profile", never proof the person lacks it.
"""

from __future__ import annotations

from typing import Any, Optional

from nlp import learning_path, preprocess, skills as skill_names, team_builder as tb
from nlp.generator import domain_profile
from nlp.recommend import GENERIC_SKILL_TOKENS

LEVELS = ("Beginner", "Intermediate", "Advanced")

# Project difficulty -> the self-reported level treated as "enough to start".
# Technologies in the project's own stack are held to a higher bar than the
# conceptual skills it lists, and nothing is ever held to Advanced: with no
# per-skill requirement data, demanding it would be invention.
TARGET_LEVEL = {
    "technology": {"Beginner": "Beginner", "Intermediate": "Intermediate", "Advanced": "Intermediate"},
    "skill": {"Beginner": "Beginner", "Intermediate": "Beginner", "Advanced": "Intermediate"},
}
DEFAULT_DIFFICULTY = "Intermediate"
MAX_NEXT_STEPS = 6

RULES = {
    "bar": (
        "The catalogue records a project's difficulty but no per-skill proficiency requirement, so the "
        "level a skill is compared with comes from difficulty alone: technologies in the project's own "
        "stack need Beginner / Intermediate / Intermediate for Beginner / Intermediate / Advanced "
        "projects, and listed skills need Beginner / Beginner / Intermediate. A skill you rate below "
        "that bar is 'needs improvement'; at or above it, 'have'. Levels are your own estimate."
    ),
    "classification": {
        "have": "Listed in your profile at or above the bar (or used in a past project on a Beginner-level project).",
        "needs_improvement": "Listed in your profile, but rated below the bar for this project's difficulty.",
        "unclear": "Evidence exists but cannot settle it: only used in a past project with no stated level on a harder project, or only a related skill is listed.",
        "missing": "Not found on your profile. This means 'not recorded', not that you lack the skill.",
    },
    "priority": {
        "high": "A technology in the project's own stack that you are missing or rate below the bar.",
        "medium": "A listed skill the project mentions more than once, or any gap that builds on a skill you already have.",
        "low": "Any other listed skill that is not yet covered.",
    },
}


def as_list(value: Any) -> list[Any]:
    """`value` if it is a list, else [] - malformed data is ignored, never iterated by character."""
    return value if isinstance(value, list) else []


def _level_rank(level: Optional[str]) -> int:
    return LEVELS.index(level) if level in LEVELS else -1


def _tokens(text: str) -> set[str]:
    return preprocess.keyword_set(text) - GENERIC_SKILL_TOKENS


def requirements_of(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """The project's own requirement entries, de-duplicated alias-aware.

    `kind` is 'technology' when the project lists it among its technologies
    (its core stack), else 'skill'. `mentions` counts the places the project
    names it (technologies, skills, keywords, title) - real catalogue data,
    used only as a prioritisation reason.
    """
    def strings(field: str) -> list[str]:
        value = doc.get(field)  # a malformed (non-list) field is ignored, never iterated character by character
        return [v.strip() for v in value if isinstance(v, str) and v.strip()] if isinstance(value, list) else []

    techs, skills, keywords = strings("technologies"), strings("skills"), strings("keywords")
    title = doc.get("title", "") if isinstance(doc.get("title"), str) else ""

    ordered: dict[str, dict[str, Any]] = {}
    for kind, names in (("technology", techs), ("skill", skills)):
        for name in names:
            key = skill_names.normalize_key(name)
            if not key:
                continue
            if key in ordered:
                ordered[key]["mentions"] += 1
                if kind == "technology":
                    ordered[key]["kind"] = "technology"
                continue
            ordered[key] = {"skill": skill_names.display_name(name), "kind": kind, "mentions": 1}

    for key, entry in ordered.items():
        extra = sum(1 for k in keywords if skill_names.normalize_key(k) == key)
        if skill_names.normalize_key(title) == key or (len(key) > 3 and key in skill_names.normalize_key(title)):
            extra += 1
        entry["mentions"] += extra
    return list(ordered.values())


def _evidence(requirement: str, profile_skills: list[dict[str, Any]], history: list[str]) -> dict[str, Any]:
    """The strongest evidence for one requirement: a profile skill (self-reported
    level), a past-project technology (no level), a related skill (inferred),
    or nothing. Explicit beats inferred; self-rated beats levelless."""
    for skill in profile_skills:
        if skill_names.same_skill(skill["name"], requirement):
            return {"source": "profile", "skill": skill["name"], "level": skill.get("level"), "self_reported": True}
    for tech in history:
        if skill_names.same_skill(tech, requirement):
            return {"source": "past_project", "skill": tech, "level": None, "self_reported": True}

    wanted = _tokens(requirement)
    if wanted:
        for name in [*(s["name"] for s in profile_skills), *history]:
            if wanted & _tokens(name):
                return {"source": "related", "skill": name, "level": None, "self_reported": False}
    return {"source": "none", "skill": None, "level": None, "self_reported": False}


def _classify(evidence: dict[str, Any], target: str, difficulty: str) -> str:
    source = evidence["source"]
    if source == "none":
        return "missing"
    if source == "related":
        return "unclear"
    if source == "past_project":
        # Used before, depth unknown: enough to begin an entry-level project,
        # not enough to judge against a harder one.
        return "have" if difficulty == "Beginner" else "unclear"
    level = evidence["level"]
    return "have" if _level_rank(level) >= _level_rank(target) else "needs_improvement"


def _builds_on(requirement: str, owned: list[str]) -> Optional[str]:
    """A skill the user already has in the same area as `requirement`: one that
    is strong evidence for a role the requirement is also strong evidence for."""
    roles = [r for r in tb.ROLE_ORDER if r != "Full-Stack Developer" and tb._keyword_weight(r, requirement) == tb._STRONG]
    for name in owned:
        if skill_names.same_skill(name, requirement):
            continue
        if any(tb._keyword_weight(r, name) == tb._STRONG for r in roles):
            return name
    return None


def _priority(item: dict[str, Any], builds_on: Optional[str], ranked: bool) -> Optional[dict[str, Any]]:
    if item["classification"] not in ("missing", "needs_improvement"):
        return None
    reasons = []
    if item["kind"] == "technology":
        level = "high"
        reasons.append("It is part of the project's own technology stack.")
    elif item["mentions"] > 1:
        level = "medium"
        reasons.append(f"The project names it in {item['mentions']} places.")
    else:
        level = "low"
        reasons.append("The project lists it as a required skill.")
    if builds_on:
        reasons.append(f"It builds on {builds_on}, which you already list.")
        if level == "low":
            level = "medium"
    if item["classification"] == "needs_improvement":
        reasons.append("You rate it below the level this project's difficulty suggests.")
    if not ranked:
        reasons.append("Too little evidence to rank these reliably; they are shown in learning order.")
    return {"level": level, "reasons": reasons}


def _module_for(doc: dict[str, Any], skill: str) -> Optional[str]:
    """The project module (from the domain's own breakdown) this skill most
    plausibly belongs to, via the role keyword table and module categories."""
    category_of_role = {role: cat for cat, role in tb._CATEGORY_ROLE.items()}
    for role in tb.ROLE_ORDER:
        if role == "Full-Stack Developer" or tb._keyword_weight(role, skill) != tb._STRONG:
            continue
        category = category_of_role.get(role)
        for module in domain_profile(doc.get("domain", ""))["modules"]:
            if role == "Database Engineer" and module in tb._DATABASE_MODULES:
                return module
            if category and tb._MODULE_CATEGORY.get(module) == category:
                return module
    return None


def _next_step(doc: dict[str, Any], item: dict[str, Any]) -> str:
    title, skill = doc.get("title", "this project"), item["skill"]
    module = _module_for(doc, skill)
    focus = f"the {module} part of “{title}”" if module else f"one small piece of “{title}”"
    if item["classification"] == "needs_improvement":
        return (
            f"You rate {skill} as {item['evidence']['level']}. Re-do {focus} as a throwaway "
            f"exercise using only {skill}, and note what you had to look up."
        )
    return f"Work through an official {skill} tutorial, then rebuild {focus} with {skill} as a short spike before starting the project."


def analyse(doc: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    """Skill-gap analysis of `profile` (API shape, profiles.service.get_profile)
    against catalogue project `doc`. Pure: same inputs, same output."""
    difficulty = doc.get("difficulty") if doc.get("difficulty") in LEVELS else DEFAULT_DIFFICULTY
    profile_skills = [s for s in as_list(profile.get("skills")) if isinstance(s, dict) and s.get("name")]
    history: list[str] = []
    seen = {skill_names.normalize_key(s["name"]) for s in profile_skills}
    for entry in as_list(profile.get("experience")):
        for tech in as_list(entry.get("technologies")) if isinstance(entry, dict) else []:
            key = skill_names.normalize_key(tech) if isinstance(tech, str) else ""
            if key and key not in seen:
                seen.add(key)
                history.append(tech)
    owned = [s["name"] for s in profile_skills] + history
    has_evidence = bool(owned)

    requirements = requirements_of(doc)
    limited = len(requirements) < 2
    notes: list[str] = []
    if not requirements:
        notes.append("This project lists no skills or technologies, so there is nothing to compare your profile with.")
    elif limited:
        notes.append("This project lists very few requirements, so the analysis is limited to what is listed.")
    if requirements and not doc.get("skills"):
        notes.append("This project lists technologies but no separate skills.")
    elif requirements and not doc.get("technologies"):
        notes.append("This project lists skills but no technologies.")
    if not has_evidence:
        notes.append("Your profile lists no skills or past-project technologies yet, so every requirement shows as not on your profile.")

    order = {e["skill"].lower(): i for i, e in enumerate(learning_path.sequence_technologies([r["skill"] for r in requirements]))}
    reasons = {e["skill"].lower(): e["reason"] for e in learning_path.sequence_technologies([r["skill"] for r in requirements])}

    items = []
    for req in requirements:
        target = TARGET_LEVEL[req["kind"]][difficulty]
        evidence = _evidence(req["skill"], profile_skills, history)
        classification = _classify(evidence, target, difficulty)
        item = {
            "skill": req["skill"],
            "kind": req["kind"],
            "mentions": req["mentions"],
            "classification": classification,
            "target_level": target,
            "evidence": evidence,
            "recognised": skill_names.canonical_name(req["skill"]) is not None,
        }
        item["priority"] = _priority(item, _builds_on(req["skill"], owned), ranked=has_evidence and not limited)
        item["why_it_matters"] = (
            f"“{doc.get('title', 'This project')}” is built with {req['skill']}."
            if req["kind"] == "technology"
            else f"“{doc.get('title', 'This project')}” lists {req['skill']} as a required skill."
        ) + (f" It is named in {req['mentions']} places on the project." if req["mentions"] > 1 else "")
        item["_order"] = order[req["skill"].lower()]
        item["_reason"] = reasons[req["skill"].lower()]
        items.append(item)

    # Prerequisite: only the one the existing learning sequence actually supports
    # (the programming language the rest of the stack is written in).
    language_gaps = [
        i["skill"] for i in items
        if i["classification"] in ("missing", "needs_improvement") and i["_reason"].startswith("Programming language")
    ]
    gap_rank = {"high": 0, "medium": 1, "low": 2}
    state_rank = {"missing": 0, "needs_improvement": 1, "unclear": 2, "have": 3}
    items.sort(key=lambda i: (
        state_rank[i["classification"]] >= 2,
        gap_rank[i["priority"]["level"]] if i["priority"] else 9,
        i["_order"],
        state_rank[i["classification"]],
        i["skill"].lower(),
    ))

    steps = 0
    for item in items:
        item["prerequisites"] = (
            [p for p in language_gaps if p != item["skill"]]
            if item["priority"] and not item["_reason"].startswith("Programming language") else []
        )
        wants_step = bool(item["priority"]) and (item["priority"]["level"] in ("high", "medium") or not has_evidence)
        if wants_step and steps < MAX_NEXT_STEPS:
            item["next_step"] = _next_step(doc, item)
            item["resources"] = learning_path.resources_for(item["skill"])
            steps += 1
        else:
            item["next_step"], item["resources"] = None, []
        del item["_order"], item["_reason"]

    counts = {k: sum(1 for i in items if i["classification"] == k) for k in RULES["classification"]}
    completion = profile.get("completion", {})
    return {
        "project": {k: doc.get(k) for k in ("project_id", "title", "domain", "difficulty")},
        "profile": {
            "status": completion.get("status", "not_started"),
            "percent": completion.get("percent", 0),
            "has_skills": has_evidence,
            "skills_listed": len(profile_skills),
            "past_project_technologies": len(history),
        },
        "requirements": {"total": len(requirements), "limited": limited},
        "summary": {**counts, "total": len(items)},
        "items": items,
        "rules": RULES,
        "ranking": {
            "basis": "rules",
            "reliable": has_evidence and not limited,
            "note": None if has_evidence and not limited else "Priorities are a simple ordering by learning sequence, not a reliable ranking.",
        },
        "notes": notes,
        "disclaimer": "Based on your self-reported profile and the project's listed requirements. It is not a verified assessment and does not predict how the project will go.",
    }
