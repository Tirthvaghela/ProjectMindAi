"""The Project Decision / Action Center — a single, unified view combining

signals from ProjectMind's existing analyzers, for ONE catalogue project or
ONE generated idea. Like nlp/feasibility.py, this is an orchestrator, not a
new prediction engine: it computes nothing an existing module doesn't already
compute.

  - overall recommendation / recommendation_score
        catalogue -> chat_tools.recommend_decision's own overall_fit and
                     uniqueness_percent (the Decision Engine), called with a
                     single project_id — never re-implemented here.
        idea      -> recommend_decision has no idea mode (see its own
                     docstring), so the idea's feasibility_score stands in as
                     the best available comparable score, clearly labelled.
  - skill fit / timeline fit / difficulty fit / skill gap / estimated weeks
        -> nlp/feasibility.py:analyze_feasibility()'s own factors — the SAME
           underlying recommend.skill_gap_for_doc()/timeline.predict()/
           recommend.difficulty_fit() calls recommend_decision itself also
           uses, so these numbers are identical either way; sourced from
           analyze_feasibility() alone since it works uniformly for both a
           project and an idea (recommend_decision does not).
  - feasibility score / risk level / technical complexity / team fit
        -> nlp/feasibility.py:analyze_feasibility()
  - scope tiers / reduced-scope suggestion
        -> nlp/feasibility.py:analyze_scope()
  - required resources / cost estimate
        -> nlp/feasibility.py:estimate_resources()
  - originality / uniqueness
        catalogue -> recommend_decision's uniqueness_percent (the project's
                     own standing among its catalogue neighbours).
        idea      -> the idea's OWN already-computed originality_score/
                     is_unique (nlp/ideation.py validates every generated
                     idea against nlp/recommend.py:check_uniqueness() at
                     generation time) — passed straight through from
                     whatever the caller already has, never recomputed.

`recommended_next_step` is the one genuinely new piece of logic here — there
is no existing "what should the student do next" function anywhere in this
codebase — a small, rule-based pick (same threshold-table style as every
other rule-based note in feasibility.py), never a model call.
"""

from __future__ import annotations

from typing import Any, Optional

from db import client as db
from nlp import chat_tools, feasibility, generator

# overall_recommendation label bands, checked in order — same shape as
# feasibility.py's own _RISK_LEVEL_BANDS, phrased as a recommendation rather
# than a risk level since that's what this field is for.
_RECOMMENDATION_BANDS: tuple[tuple[int, str], ...] = (
    (75, "Recommended"),
    (50, "Worth considering"),
    (0, "High risk — reconsider or reduce scope"),
)


def _band(score: float, bands: tuple[tuple[int, str], ...]) -> str:
    for threshold, label in bands:
        if score >= threshold:
            return label
    return bands[-1][1]


def _factor_score(factors: list[dict[str, Any]], name: str) -> Optional[float]:
    for factor in factors:
        if factor.get("factor") == name:
            return factor.get("score")
    return None


def _resolve_doc(project_id: Optional[str], idea: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if project_id:
        return db.projects().find_one({"project_id": project_id}, {"_id": 0})
    if idea and idea.get("name"):
        return generator.idea_doc(
            idea["name"],
            domain=idea.get("domain"),
            duration_weeks=idea.get("duration_weeks"),
            difficulty=idea.get("difficulty"),
            technologies=idea.get("technologies"),
        )
    return None


def _recommended_next_step(
    *,
    has_known_skills: bool,
    skills_to_learn: list[str],
    reduced_scope: Optional[dict[str, Any]],
    feasibility_score: int,
) -> str:
    """One suggested next action, in priority order — the single most useful
    thing to do given what's already known, never a duplicate of an existing
    engine's own recommendations (those stay in `risks`/`strengths` from
    analyze_feasibility, this is only ever a POINTER to the next tool/action,
    not a second copy of that reasoning)."""
    if not has_known_skills:
        return "Check your skill gap — your fit scores are more accurate once we know what you already have."
    if skills_to_learn:
        return f"Review the learning path for {', '.join(skills_to_learn[:2])} before starting."
    if reduced_scope:
        return "Review the suggested scope reduction for your timeline before starting."
    if feasibility_score < 45:
        return "Review the risks below — this one needs real planning before you commit."
    return "Generate a roadmap to get started."


def build(
    *,
    project_id: Optional[str] = None,
    idea: Optional[dict[str, Any]] = None,
    known_skills: Optional[list[str]] = None,
    team_size: Optional[int] = None,
    experience_level: Optional[str] = None,
    target_weeks: Optional[int] = None,
) -> dict[str, Any]:
    """Build the unified Decision Center payload for ONE catalogue project
    (`project_id`) or ONE generated idea (`idea`, its own fields as already
    shown/selected — same shape select_idea/refine_project_idea already take).
    Exactly one of the two should be given, mirroring chat_tools.analyze_scope/
    estimate_project_resources's existing dual-mode pattern.
    """
    doc = _resolve_doc(project_id, idea)
    if doc is None:
        return {"error": "No project or idea to build a decision for."}

    skills = [s.strip() for s in (known_skills or []) if isinstance(s, str) and s.strip()]

    feasibility_result = feasibility.analyze_feasibility(
        doc,
        known_skills=skills,
        team_size=team_size,
        experience_level=experience_level,
        target_weeks=target_weeks,
    )
    scope_result = feasibility.analyze_scope(doc, target_weeks=target_weeks)
    resources_result = feasibility.estimate_resources(doc, team_size=team_size)

    skill_fit = _factor_score(feasibility_result["factors"], "Skill Fit")
    difficulty_fit = _factor_score(feasibility_result["factors"], "Difficulty Fit")
    timeline_fit = _factor_score(feasibility_result["factors"], "Timeline Fit")

    strengths = list(feasibility_result["strengths"])
    risks = list(feasibility_result["risks"])

    if project_id:
        # The Decision Engine — reused wholesale via its own existing tool
        # entry point, single project_id, never re-implemented here. Its
        # candidate carries the SAME skill/timeline/difficulty fit numbers
        # (same underlying recommend.py/timeline.py calls as analyze_feasibility
        # above), so only overall_fit/uniqueness_percent/its own strengths and
        # risks phrasing are pulled from it — everything else stays sourced
        # from feasibility_result so a project and an idea read consistently.
        decision_for_model, _block = chat_tools.recommend_decision(
            project_ids=[project_id],
            known_skills=skills,
            team_size=team_size,
            experience_level=experience_level,
            target_weeks=target_weeks,
        )
        candidate = (decision_for_model.get("candidates") or [None])[0]
        recommendation_score = candidate["overall_fit"] if candidate else feasibility_result["feasibility_score"]
        originality_score = candidate["uniqueness_percent"] if candidate else None
        is_unique = None
        originality_source = "catalogue_uniqueness"
        if candidate:
            # Deliberately NOT merging candidate["strengths"]/["risks"] wholesale
            # — both recommend_decision and analyze_feasibility independently
            # build their own skill/timeline/difficulty commentary from the
            # SAME underlying numbers, so merging both lists produced near-
            # duplicate lines (same fact, different phrasing/punctuation,
            # confirmed live) rather than new information. The one thing
            # recommend_decision computes that feasibility_result never does
            # is uniqueness — added here with the exact same threshold
            # recommend_decision itself uses, so the two never disagree.
            if originality_score is not None:
                if originality_score >= 60:
                    strengths.append("Good uniqueness among the catalogue")
                elif originality_score < 35:
                    risks.append("Very similar to other catalogue projects")
    else:
        # No Decision Engine equivalent exists for a generated idea (see its
        # own docstring) — the feasibility score is the best available
        # comparable "should I do this" number, clearly labelled as such
        # below rather than presented as if it were the same measurement.
        recommendation_score = feasibility_result["feasibility_score"]
        originality_score = idea.get("originality_score") if idea else None
        is_unique = idea.get("is_unique") if idea else None
        originality_source = "generated_idea_originality"

    recommendation_label = _band(recommendation_score, _RECOMMENDATION_BANDS)

    next_step = _recommended_next_step(
        has_known_skills=bool(skills),
        skills_to_learn=feasibility_result["skills_to_learn"],
        reduced_scope=scope_result["reduced_scope"],
        feasibility_score=feasibility_result["feasibility_score"],
    )

    return {
        "kind": "project" if project_id else "idea",
        "project_id": project_id,
        "name": doc.get("title", ""),
        "domain": doc.get("domain", ""),
        "difficulty": doc.get("difficulty", ""),
        "duration_weeks": doc.get("duration_weeks"),
        "technologies": doc.get("technologies", []),
        "overall_recommendation": {"label": recommendation_label, "score": recommendation_score},
        "skill_fit": skill_fit,
        "difficulty_fit": difficulty_fit,
        "timeline": {"estimated_weeks": feasibility_result["estimated_weeks"], "fit_score": timeline_fit},
        "feasibility": {"score": feasibility_result["feasibility_score"], "risk_level": feasibility_result["risk_level"]},
        "originality": {"score": originality_score, "is_unique": is_unique, "source": originality_source},
        "scope": {
            "mvp": scope_result["mvp"],
            "core": scope_result["core"],
            "advanced": scope_result["advanced"],
            "reduced_scope": scope_result["reduced_scope"],
        },
        "resources": {
            "team_recommended_size": resources_result["team"]["recommended_size"],
            "technology": resources_result["technology"],
            "cost_is_estimate": resources_result["cost"]["is_estimate"],
        },
        "strengths": strengths,
        "risks": risks,
        "skills_you_have": feasibility_result["skills_you_have"],
        "skills_to_learn": feasibility_result["skills_to_learn"],
        "known_skills_provided": bool(skills),
        "recommended_next_step": next_step,
    }
