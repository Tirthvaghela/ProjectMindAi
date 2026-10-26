"""Smart team formation: choose a subset of an authorised candidate pool whose
COMBINED skills best cover a project - not simply the people with the highest
individual scores.

Nothing here knows about accounts, teams or invitations; it receives candidates
already resolved and authorised by teams/service.py and returns advice. It
reuses, rather than reimplements:

* requirement extraction and matching - nlp/personal_skill_gap (Feature 4):
  the same requirements, aliases, evidence rules and difficulty bar,
* role evidence, needed roles and team role coverage - nlp/team_builder
  (Feature 3): member_role_fit, needed_roles, team_coverage, role_fit.

Selection is deterministic. The objective is documented in OBJECTIVE and every
number it uses is shown to the user as a count, not a percentage or a
probability. Self-reported skills only; availability and willingness are
unknown and never assumed.
"""

from __future__ import annotations

from itertools import combinations
from math import comb
from typing import Any, Optional

from nlp import team_builder as tb
from nlp.personal_skill_gap import (
    DEFAULT_DIFFICULTY,
    LEVELS,
    TARGET_LEVEL,
    _classify,
    _evidence,
    requirements_of,
)

MAX_TEAM_SIZE = 8
MIN_DEFAULT_SIZE, MAX_DEFAULT_SIZE = 2, 4
EXHAUSTIVE_LIMIT = 20_000  # above this many subsets, fall back to greedy selection
ACCEPTABLE_FRACTION = 0.9  # a smaller team is offered if it keeps >= this share of the best coverage
BALANCE_TOLERANCE = 0.95   # a "balanced" team may give up at most this much coverage for less concentration
CONCENTRATED_SHARE = 0.5   # one person solely holding more than this share of solid coverage is a bottleneck

WEIGHT = {"technology": 2, "skill": 1}
VALUE = {"have": 1.0, "needs_improvement": 0.5, "unclear": 0.5, "missing": 0.0}

OBJECTIVE = (
    "Teams are compared first by how much of the project's weighted requirements (a stack technology counts 2, a "
    "listed skill 1) the members cover - solidly counts fully, partially counts half, related-only skills not at all - "
    "then by how many of the project's priority roles someone could fill, then by how little of the solid coverage "
    "rests on a single person, then by name for a stable order."
)
DEFAULT_SIZE_RULE = (
    f"With no team size given, one person per main role the project's module breakdown calls for, between "
    f"{MIN_DEFAULT_SIZE} and {MAX_DEFAULT_SIZE} (the app's timeline model treats bigger teams as increasingly "
    "inefficient), limited by how many candidates have skills on file."
)


def _split_skills(skills: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Levelled skills (self-rated) vs unlevelled ones (past projects or typed
    without a level) - the two kinds of evidence Feature 4 distinguishes."""
    levelled = [s for s in skills if s.get("level") in LEVELS]
    unlevelled = [s["name"] for s in skills if s.get("level") not in LEVELS]
    return levelled, unlevelled


def requirement_values(candidate: dict[str, Any], requirements: list[dict[str, Any]], difficulty: str) -> list[dict[str, Any]]:
    """Per requirement: how well this candidate covers it (Feature 4's rules)."""
    levelled, unlevelled = _split_skills(candidate["skills"])
    out = []
    for req in requirements:
        evidence = _evidence(req["skill"], levelled, unlevelled)
        status = _classify(evidence, TARGET_LEVEL[req["kind"]][difficulty], difficulty)
        # An inferred "related skill" is classified unclear by Feature 4, but it
        # is not evidence the person has THIS skill, so it earns no coverage.
        value = 0.0 if evidence["source"] == "related" else VALUE[status]
        out.append({"skill": req["skill"], "kind": req["kind"], "status": status, "value": value, "evidence": evidence})
    return out


def _evaluate(subset: tuple[int, ...], values: list[list[dict[str, Any]]], weights: list[int], role_ok: list[set[str]], priority: list[str]) -> dict[str, Any]:
    total = sum(weights)
    covered = solid_total = 0.0
    sole: dict[int, float] = {i: 0.0 for i in subset}
    for r, w in enumerate(weights):
        best = max((values[i][r]["value"] for i in subset), default=0.0)
        covered += w * best
        if best == 1.0:
            solid_total += w
            holders = [i for i in subset if values[i][r]["value"] == 1.0]
            if len(holders) == 1:
                sole[holders[0]] += w
    concentration = (max(sole.values()) / solid_total) if solid_total and len(subset) > 1 else 0.0
    roles = sum(1 for role in priority if any(role in role_ok[i] for i in subset))
    return {"coverage": covered / total if total else 0.0, "roles": roles, "concentration": concentration, "sole": sole}


def _key(metrics: dict[str, Any], subset: tuple[int, ...], names: list[str]) -> tuple:
    return (-round(metrics["coverage"], 9), -metrics["roles"], round(metrics["concentration"], 9), tuple(names[i] for i in subset))


def _best(size: int, n: int, score) -> tuple[Optional[tuple[int, ...]], bool]:
    """Best subset of `size` (exhaustive when small, greedy otherwise)."""
    if size < 1 or size > n:
        return None, False
    if comb(n, size) <= EXHAUSTIVE_LIMIT:
        return min(combinations(range(n), size), key=score), True
    chosen: list[int] = []
    for _ in range(size):
        remaining = [i for i in range(n) if i not in chosen]
        chosen.append(min(remaining, key=lambda i: score(tuple(sorted([*chosen, i])))))
    return tuple(sorted(chosen)), False


def form_teams(doc: dict[str, Any], candidates: list[dict[str, Any]], team_size: Optional[int] = None) -> dict[str, Any]:
    """Recommend teams for catalogue project `doc` from `candidates`.

    candidates: [{id, name (unique), source, skills: [{name, level|None}],
    preferred_roles, interests, profile_status}] - the shape
    nlp/team_builder.role_fit takes. Pure and deterministic.
    """
    difficulty = doc.get("difficulty") if doc.get("difficulty") in LEVELS else DEFAULT_DIFFICULTY
    requirements = requirements_of(doc)
    names_all = [r["skill"] for r in requirements]
    informative = [c for c in candidates if c["skills"]]
    uninformative = [c for c in candidates if not c["skills"]]

    limitations = [
        "Based on self-reported skills and the project's listed requirements; nothing is verified.",
        "Availability, willingness and working style are unknown, so no one is assumed to be free or interested.",
        "Selection is a heuristic over the candidates you supplied, not a claim that a team is objectively optimal.",
    ]
    base: dict[str, Any] = {
        "project": {k: doc.get(k) for k in ("project_id", "title", "domain", "difficulty")},
        "requirements": {"total": len(requirements), "limited": len(requirements) < 2},
        "pool": {
            "size": len(candidates),
            "matchable": len(informative),
            "not_matched": [
                {
                    "name": c["name"], "source": c["source"],
                    "reason": (
                        "No profile information is available for matching (it has not been shared with the team, or has not been added). "
                        "That says nothing about what this person can do."
                        if c.get("info_unavailable") else "No skills on file for this person. That says nothing about what they can do."
                    ),
                }
                for c in uninformative
            ],
        },
        "objective": OBJECTIVE,
        "teams": [],
        "limitations": limitations,
        "notes": [],
    }

    if not requirements:
        base["notes"].append("This project lists no skills or technologies, so there is nothing to optimise a team against.")
        return base
    if len(requirements) < 2:
        limitations.append("This project lists very few requirements, so the recommendation is only loosely project-specific.")
    if not informative:
        base["notes"].append("None of the candidates has skills on file, so no team can be recommended. Add skills to a profile or type them in.")
        return base

    n = len(informative)
    names = [c["name"] for c in informative]
    values = [requirement_values(c, requirements, difficulty) for c in informative]
    weights = [WEIGHT[r["kind"]] for r in requirements]
    fits = [tb.member_role_fit(c, names_all, doc.get("domain", "")) for c in informative]

    explicit = team_size is not None
    needs_default = [x for x in tb.needed_roles(doc, names_all, MAX_DEFAULT_SIZE) if x["priority"]]
    default_size = max(MIN_DEFAULT_SIZE, min(MAX_DEFAULT_SIZE, len(needs_default)))
    wanted = team_size if explicit else default_size
    size = min(wanted, n)
    if size < wanted:
        base["notes"].append(f"Only {n} candidate{'s have' if n != 1 else ' has'} skills on file, so the team is {size} rather than {wanted}.")
    priority = [x["role"] for x in tb.needed_roles(doc, names_all, size) if x["priority"]]
    role_ok = [{role for role, f in fit["fits"].items() if f["score"] >= tb.MIN_SUGGEST_SCORE} if fit["fits"] else set() for fit in fits]

    def metrics(subset):
        return _evaluate(subset, values, weights, role_ok, priority)

    def score(subset):
        return _key(metrics(subset), subset, names)

    primary, exhaustive = _best(size, n, score)
    if not exhaustive:
        limitations.append("The candidate pool is large, so teams were built greedily rather than by trying every combination.")
    primary_metrics = metrics(primary)
    chosen: list[tuple[str, str, tuple[int, ...], bool]] = [
        ("best_coverage", "Best overall coverage", primary, True)
    ]

    if exhaustive and size < n:
        near = [
            s for s in combinations(range(n), size)
            if metrics(s)["coverage"] >= primary_metrics["coverage"] * BALANCE_TOLERANCE
        ]
        balanced = min(near, key=lambda s: (round(metrics(s)["concentration"], 9), *score(s)))
        if set(balanced) != set(primary) and metrics(balanced)["concentration"] < primary_metrics["concentration"]:
            chosen.append(("balanced", "More evenly shared responsibilities", balanced, True))

    if not explicit and size > 1:
        for smaller_size in range(1, size):
            candidate, _ = _best(smaller_size, n, score)
            if candidate and metrics(candidate)["coverage"] >= primary_metrics["coverage"] * ACCEPTABLE_FRACTION:
                if all(set(candidate) != set(c[2]) for c in chosen):
                    chosen.append(("smaller", f"Smaller team of {smaller_size}", candidate, True))
                break

    top_individual = tuple(sorted(sorted(range(n), key=lambda i: (-(fits[i]["suggested"] or {"score": 0})["score"], names[i]))[:size]))
    if all(set(top_individual) != set(c[2]) for c in chosen):
        chosen.append(("top_individuals", "Highest individual role scores (for comparison)", top_individual, False))

    reference = metrics(top_individual)

    def render(key: str, label: str, subset: tuple[int, ...], recommended: bool) -> dict[str, Any]:
        m = metrics(subset)
        members = [informative[i] for i in subset]
        items = []
        for r, req in enumerate(requirements):
            holders = [(i, values[i][r]) for i in subset if values[i][r]["value"] > 0]
            solid = [names[i] for i, v in holders if v["value"] == 1.0]
            partial = [names[i] for i, v in holders if v["value"] < 1.0]
            items.append({
                "skill": req["skill"], "kind": req["kind"],
                "status": "solid" if solid else "partial" if partial else "uncovered",
                "solid_by": solid, "partial_by": partial,
            })
        counts = {s: sum(1 for it in items if it["status"] == s) for s in ("solid", "partial", "uncovered")}
        fit = tb.role_fit(doc, members)
        by_name = {mm["name"]: mm for mm in fit["members"]}
        out_members = []
        for i in subset:
            contributes = [
                {"skill": v["skill"], "kind": v["kind"], "strength": "solid" if v["value"] == 1.0 else "partial",
                 "level": v["evidence"]["level"], "source": v["evidence"]["source"]}
                for v in values[i] if v["value"] > 0
            ]
            role = by_name[names[i]]["suggested"]
            out_members.append({
                "user_id": informative[i].get("id"),
                "name": names[i],
                "source": informative[i]["source"],
                "profile_status": informative[i].get("profile_status"),
                **({"info_unavailable": True} if informative[i].get("info_unavailable") else {}),
                "contributes": contributes,
                "sole_holder_of": [it["skill"] for r, it in enumerate(items) if it["solid_by"] == [names[i]]],
                "suggested_role": {"role": role["role"], "confidence": role["confidence"], "score": role["score"]} if role else None,
            })
        bottlenecks = []
        if len(subset) > 1:
            solid_weight = sum(weights[r] for r, it in enumerate(items) if it["status"] == "solid")
            for mem in out_members:
                held = [it for it in items if it["solid_by"] == [mem["name"]]]
                share = sum(WEIGHT[it["kind"]] for it in held) / solid_weight if solid_weight else 0
                if held and share > CONCENTRATED_SHARE:
                    bottlenecks.append({
                        "member": mem["name"],
                        "requirements": [it["skill"] for it in held],
                        "note": f"{mem['name']} is the only person with solid evidence for {len(held)} of the {counts['solid']} solidly covered requirements.",
                    })
        uncovered = [it["skill"] for it in items if it["status"] == "uncovered"]
        explanation = (
            f"Covers {counts['solid']} of {len(items)} requirements solidly and {counts['partial']} partially"
            + (f"; not covered: {', '.join(uncovered)}." if uncovered else ".")
            + " " + " ".join(
                f"{mm['name']} brings {', '.join(c['skill'] for c in mm['contributes'][:3])}." for mm in out_members if mm["contributes"]
            )
        )
        if not recommended:
            explanation += " Shown only to compare with the recommended teams: it ranks people by individual role score instead of by how their skills combine."
        return {
            "key": key, "label": label, "recommended": recommended, "size": len(subset),
            "members": out_members,
            "requirements": {**counts, "total": len(items), "items": items},
            "roles": {k: fit["team"][k] for k in ("needed_roles", "covered", "gaps", "overlaps", "plan", "optional_roles")},
            "bottlenecks": bottlenecks,
            "explanation": explanation,
            "vs_individual_ranking": None if key == "top_individuals" else {
                "covers_more": m["coverage"] > reference["coverage"] + 1e-9,
                "covers_same": abs(m["coverage"] - reference["coverage"]) <= 1e-9,
            },
        }

    base["teams"] = [render(*c) for c in chosen]
    base["inputs"] = {
        "team_size": size, "requested": team_size, "source": "requested" if explicit else "default",
        "default_rule": None if explicit else DEFAULT_SIZE_RULE,
    }
    all_values = [max((values[i][r]["value"] for i in range(n)), default=0.0) for r in range(len(requirements))]
    base["pool"]["coverage"] = {
        "solid": sum(1 for v in all_values if v == 1.0),
        "partial": sum(1 for v in all_values if 0 < v < 1.0),
        "uncovered": [requirements[r]["skill"] for r, v in enumerate(all_values) if v == 0],
        "total": len(requirements),
    }
    if base["pool"]["coverage"]["uncovered"]:
        base["notes"].append(
            "No one in this pool covers: " + ", ".join(base["pool"]["coverage"]["uncovered"]) + ". Consider recruiting someone with those skills."
        )
    if n < 2:
        base["notes"].append("With one matchable candidate there are no alternative teams to compare.")
    return base
