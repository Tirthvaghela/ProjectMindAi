"""Personalised learning roadmap for one project: an ordered, deterministic list
of steps built from the Feature 4 skill-gap analysis.

Nothing here extracts requirements or classifies skills itself:

* what is missing / below the bar / unclear comes from
  nlp/personal_skill_gap.analyse() (same requirements, same aliases, same rules),
* learning order comes from nlp/learning_path.py's tiers,
* resource links come from learning_path.resources_for().

What this module adds is (a) turning gaps into steps - grouping low-priority
concept phrases instead of making each its own step, (b) a small table of
well-established "built on" prerequisites, and (c) a cycle-safe topological
ordering. The ordering is a heuristic and says so. No time estimates, courses,
certifications or skill levels are invented; every "done" test is a self-check.
"""

from __future__ import annotations

import heapq
import re
from typing import Any, Optional

from nlp import learning_path, skills as skill_names
from nlp.personal_skill_gap import LEVELS, _module_for, _next_step, analyse, as_list

# dependent -> what it is built on. Only relationships that are plain facts about
# the technologies (a framework is written for its language / base library).
# Anything not listed has no prerequisite metadata and is ordered by the learning
# sequence alone - this table is deliberately conservative, not exhaustive.
KNOWN_PREREQUISITES: dict[str, tuple[str, ...]] = {
    "Flask": ("Python",),
    "Django": ("Python",),
    "FastAPI": ("Python",),
    "pandas": ("Python",),
    "NumPy": ("Python",),
    "scikit-learn": ("Python",),
    "TensorFlow": ("Python",),
    "PyTorch": ("Python",),
    "Streamlit": ("Python",),
    "Matplotlib": ("Python",),
    "pytest": ("Python",),
    "React": ("JavaScript",),
    "Vue": ("JavaScript",),
    "Angular": ("TypeScript",),
    "Node.js": ("JavaScript",),
    "Express.js": ("Node.js",),
    "TypeScript": ("JavaScript",),
    "Next.js": ("React",),
    "React Native": ("React",),
    "Redux": ("React",),
    "Tailwind CSS": ("CSS",),
    "CSS": ("HTML",),
    "Spring Boot": ("Java",),
    "Jetpack Compose": ("Kotlin",),
    "SwiftUI": ("Swift",),
    "Flutter": ("Dart",),
    "Hardhat": ("Solidity",),
    "Kubernetes": ("Docker",),
}

KINDS = ("learn", "improve", "confirm", "prerequisite", "concepts")
STATUS_RANK = {"high": 0, "medium": 1, "low": 2, None: 3}
MIN_GROUP = 2  # a single low-priority concept stays its own step

DISCLAIMER = (
    "A suggested order, not a guarantee of project success. Your skill levels are self-reported and "
    "nothing here is verified; 'done' tests are checks you make yourself."
)


def step_id(skill: str) -> str:
    return "s-" + skill_names.normalize_key(skill)


def _prereq_index(table: dict[str, tuple[str, ...]]) -> dict[str, list[str]]:
    return {skill_names.normalize_key(k): list(v) for k, v in table.items()}


def order_steps(keys: dict[str, tuple], edges: set[tuple[str, str]]) -> tuple[list[str], bool]:
    """Topological order of step ids (an edge is (prerequisite, dependent)),
    breaking ties by `keys`. Returns (order, had_cycle).

    A cycle can only come from bad metadata; rather than fail, the edges among
    the nodes that could not be ordered are dropped and those nodes are placed
    by key alone, so the caller still gets a complete, deterministic order.
    """
    incoming = {n: {a for a, b in edges if b == n and a in keys} for n in keys}
    ready = [(keys[n], n) for n in keys if not incoming[n]]
    heapq.heapify(ready)
    order: list[str] = []
    done: set[str] = set()
    while ready:
        _k, node = heapq.heappop(ready)
        order.append(node)
        done.add(node)
        for n in keys:
            if n not in done and node in incoming[n]:
                incoming[n].discard(node)
                if not incoming[n] and all(n != r[1] for r in ready):
                    heapq.heappush(ready, (keys[n], n))
    cycle = len(order) < len(keys)
    if cycle:
        order.extend(sorted((n for n in keys if n not in done), key=lambda n: (keys[n], n)))
    return order, cycle


def _goal_match(skill: str, goals: list[str]) -> Optional[str]:
    pattern = re.compile(r"(?<![a-z0-9+#])" + re.escape(skill.lower()) + r"(?![a-z0-9+#])")
    return next((g for g in goals if pattern.search(g.lower())), None)


def _owned(profile: dict[str, Any]) -> list[str]:
    names = [s["name"] for s in as_list(profile.get("skills")) if isinstance(s, dict) and s.get("name")]
    for entry in as_list(profile.get("experience")):
        if isinstance(entry, dict):
            names.extend(t for t in as_list(entry.get("technologies")) if isinstance(t, str))
    return names


def _on_profile(skill: str, owned: list[str]) -> bool:
    return any(skill_names.same_skill(skill, o) for o in owned)


def _evidence_sentence(item: dict[str, Any], difficulty: str, has_skills: bool) -> str:
    ev, skill = item["evidence"], item["skill"]
    if item["classification"] == "missing":
        return f"{skill} is not on your profile." + ("" if has_skills else " Your profile lists no skills yet.")
    if item["classification"] == "needs_improvement":
        return f"You rate {skill} {ev['level']}; a {difficulty} project suggests {item['target_level']}."
    if ev["source"] == "past_project":
        return f"You used {skill} in a past project, but no level is recorded."
    return f"Your profile lists {ev['skill']}, which looks related to {skill} but is not the same skill."


def build_roadmap(
    doc: dict[str, Any],
    profile: dict[str, Any],
    prerequisites: Optional[dict[str, tuple[str, ...]]] = None,
) -> dict[str, Any]:
    """Roadmap for `profile` (API shape) on catalogue project `doc`. Pure."""
    analysis = analyse(doc, profile)
    table = _prereq_index(KNOWN_PREREQUISITES if prerequisites is None else prerequisites)
    title = doc.get("title", "this project")
    difficulty = analysis["project"]["difficulty"] if analysis["project"]["difficulty"] in LEVELS else "Intermediate"
    has_skills = analysis["profile"]["has_skills"]
    owned = _owned(profile)
    goals = [g for g in as_list(profile.get("learning_goals")) if isinstance(g, str)]
    items = analysis["items"]
    by_key = {skill_names.normalize_key(i["skill"]): i for i in items}

    work = [i for i in items if i["classification"] != "have"]
    concept_pool = [
        i for i in work
        if i["kind"] == "skill" and i["classification"] == "missing" and (i["priority"] or {}).get("level") == "low"
    ]
    grouped = concept_pool if len(concept_pool) >= MIN_GROUP else []
    grouped_keys = {skill_names.normalize_key(i["skill"]) for i in grouped}

    steps: dict[str, dict[str, Any]] = {}
    for item in work:
        key = skill_names.normalize_key(item["skill"])
        if key in grouped_keys:
            continue
        kind = {"missing": "learn", "needs_improvement": "improve", "unclear": "confirm"}[item["classification"]]
        focus = _focus(doc, item["skill"])
        practice, criterion = _practice(kind, item, doc, focus)
        steps[step_id(item["skill"])] = {
            "id": step_id(item["skill"]),
            "kind": kind,
            "skill": item["skill"],
            "skills": [item["skill"]],
            "classification": item["classification"],
            "evidence": item["evidence"],
            "from_project_requirements": True,
            "priority": item["priority"],
            "why_it_matters": item["why_it_matters"],
            "why_for_you": _evidence_sentence(item, difficulty, has_skills),
            "practice_task": practice,
            "completion_criterion": criterion,
            "resources": learning_path.resources_for(item["skill"]),
            "matches_your_goal": _goal_match(item["skill"], goals),
            "_tier": learning_path.learning_tier(item["skill"])[0],
        }

    if grouped:
        names = [i["skill"] for i in grouped]
        steps["concepts"] = {
            "id": "concepts",
            "kind": "concepts",
            "skill": "Project concepts",
            "skills": names,
            "classification": "missing",
            "evidence": {"source": "none", "skill": None, "level": None, "self_reported": False},
            "from_project_requirements": True,
            "priority": {"level": "low", "reasons": [f"The project lists {len(names)} concept skills that do not each need a separate study step."]},
            "why_it_matters": f"“{title}” lists these as required skills: {', '.join(names)}.",
            "why_for_you": "None of them is on your profile; they are best picked up while building.",
            "practice_task": f"While building “{title}”, write a short note with a small working example of each: {', '.join(names)}.",
            "completion_criterion": "Each concept appears in your notes with an example you wrote yourself and could explain.",
            "resources": [],
            "matches_your_goal": next((m for m in (_goal_match(n, goals) for n in names) if m), None),
            "_tier": max(learning_path.learning_tier(n)[0] for n in names),
        }

    # Prerequisites: Feature 4's language prerequisite plus the known-table
    # entries. A prerequisite becomes its own step only when it is not already a
    # step, the project does not already have it covered, and the profile shows
    # no evidence of it.
    edges: set[tuple[str, str]] = set()
    prereq_info: dict[str, list[dict[str, str]]] = {sid: [] for sid in steps}
    queue = [sid for sid in steps if sid != "concepts"]
    visited: set[str] = set()
    while queue:
        sid = queue.pop(0)
        if sid in visited:
            continue
        visited.add(sid)
        step = steps[sid]
        item = by_key.get(skill_names.normalize_key(step["skill"]))
        wanted = list(table.get(skill_names.normalize_key(step["skill"]), []))
        wanted += [p for p in (item["prerequisites"] if item else []) if p not in wanted]
        for pre in wanted:
            pre_key = skill_names.normalize_key(pre)
            pre_id = step_id(pre)
            if pre_key == skill_names.normalize_key(step["skill"]):
                continue
            if pre_id in steps:
                edges.add((pre_id, sid))
                prereq_info[sid].append({"skill": steps[pre_id]["skill"], "status": "in_roadmap"})
            elif _on_profile(pre, owned) or (pre_key in by_key and by_key[pre_key]["classification"] == "have"):
                prereq_info[sid].append({"skill": skill_names.display_name(pre), "status": "on_profile"})
            else:
                name = skill_names.display_name(pre)
                steps[pre_id] = {
                    "id": pre_id,
                    "kind": "prerequisite",
                    "skill": name,
                    "skills": [name],
                    "classification": "missing",
                    "evidence": {"source": "none", "skill": None, "level": None, "self_reported": False},
                    "from_project_requirements": False,
                    "priority": None,
                    "why_it_matters": f"{step['skill']} is built on {name}.",
                    "why_for_you": f"{name} is not on your profile, and {step['skill']} builds on it.",
                    "practice_task": f"Complete an official {name} tutorial, then write a small working example on your own.",
                    "completion_criterion": f"You can write a small working {name} example without copying, enough to start {step['skill']}.",
                    "resources": learning_path.resources_for(name),
                    "matches_your_goal": _goal_match(name, goals),
                    "_tier": learning_path.learning_tier(name)[0],
                }
                prereq_info[pre_id] = []
                edges.add((pre_id, sid))
                prereq_info[sid].append({"skill": name, "status": "in_roadmap"})
                queue.append(pre_id)

    keys = {
        sid: (s["_tier"], STATUS_RANK[(s["priority"] or {}).get("level")], list(steps).index(sid))
        for sid, s in steps.items()
    }
    order, cycle = order_steps(keys, edges)

    ordered = []
    for number, sid in enumerate(order, start=1):
        step = {k: v for k, v in steps[sid].items() if not k.startswith("_")}
        step["number"] = number
        step["prerequisites"] = prereq_info.get(sid, [])
        ordered.append(step)
    for current, following in zip(ordered, ordered[1:]):
        current["after"] = {"id": following["id"], "skill": following["skill"]}
    for step in ordered[-1:]:
        step["after"] = None
    for step in ordered:
        step.setdefault("after", None)

    notes = list(analysis["notes"])
    if cycle:
        notes.append("The prerequisite information contained a loop, so part of the order falls back to the standard learning sequence.")
    if not ordered and analysis["requirements"]["total"] and not notes:
        notes.append("Everything this project lists is already covered by your profile.")

    return {
        "project": analysis["project"],
        "profile": analysis["profile"],
        "requirements": analysis["requirements"],
        "overview": {
            "steps": len(ordered),
            "by_kind": {k: sum(1 for s in ordered if s["kind"] == k) for k in KINDS},
            "already_covered": [i["skill"] for i in items if i["classification"] == "have"],
            "domain_interest": doc.get("domain") in as_list(profile.get("interests")),
            "finish": f"When these steps feel solid, start building “{title}”." if ordered else f"You can start building “{title}” on what your profile lists.",
        },
        "steps": ordered,
        "ordering": {
            "basis": "learning-sequence heuristic plus known prerequisites",
            "known_prerequisite_edges": len(edges),
            "cycle_detected": cycle,
            "reliable": analysis["ranking"]["reliable"],
            "note": "Steps follow the standard order (languages, concepts, frameworks, backend, frontend, data, deployment) and the "
                    "prerequisites listed above. Skills with no prerequisite information are ordered by that sequence alone, so treat "
                    "the order as a sensible suggestion, not a requirement.",
        },
        "notes": notes,
        "disclaimer": DISCLAIMER,
    }


def _focus(doc: dict[str, Any], skill: str) -> str:
    module = _module_for(doc, skill)
    title = doc.get("title", "this project")
    return f"the {module} part of “{title}”" if module else f"one small piece of “{title}”"


def _practice(kind: str, item: dict[str, Any], doc: dict[str, Any], focus: str) -> tuple[str, str]:
    skill = item["skill"]
    if kind == "learn":
        return (
            _next_step(doc, item),
            f"You have built {focus} with {skill} yourself and can explain how it works without copying a tutorial.",
        )
    if kind == "improve":
        return (
            _next_step(doc, item),
            f"You can repeat the exercise using only {skill} and its official docs, without a step-by-step guide. "
            "This is a self-check; update your profile level yourself if you choose.",
        )
    ev = item["evidence"]
    if ev["source"] == "past_project":
        return (
            f"Rebuild {focus} with {skill} from scratch, without looking at your old code.",
            f"If you can do it without help, add or update your {skill} level in your profile. If not, treat it as a learning step.",
        )
    return (
        f"Check whether your {ev['skill']} experience really covers {skill}: try {focus} using only what you already know.",
        f"If it works, add {skill} to your profile yourself; otherwise treat {skill} as a learning step.",
    )
