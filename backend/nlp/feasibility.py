"""Deterministic project feasibility scoring.

The Feasibility Analyzer is an orchestrator, not a new prediction engine — it
computes nothing an existing module doesn't already compute:

  - skill fit          -> nlp/recommend.py:skill_gap_for_doc()
  - timeline fit        -> nlp/timeline.py:predict()
  - difficulty fit      -> nlp/recommend.py:difficulty_fit() (shared with
                            chat_tools.recommend_decision — one implementation)
  - team-size guidance   -> nlp/generator.py:domain_profile() modules, mapped
                            to categories via nlp/team_builder.py:category_for()
  - infrastructure/dataset guidance -> nlp/generator.py:domain_profile()'s
                            infra_hint/dataset_hint (static domain facts,
                            always returned flagged as an estimate, never a
                            fact about the specific project/idea)

The only genuinely new arithmetic here is `_technical_complexity()` — there is
no existing "how complex is this build" number anywhere else in the codebase
— and the weighted-average combination below, which mirrors
chat_tools.recommend_decision's own pattern exactly (a factor whose input
wasn't given contributes nothing, rather than a guessed default). Every
number in the result traces back to one of the functions named above; an LLM
calling analyze_project_feasibility/analyze_idea_feasibility (see
nlp/chat_tools.py) only narrates this result, it never invents a score.
"""

from __future__ import annotations

from typing import Any, Optional

from db.schema import DIFFICULTIES
from nlp import generator, recommend, team_builder, timeline

# --- Weighted-average factors ------------------------------------------------
# Same transparent-average pattern as chat_tools.recommend_decision: weights
# are fixed constants, never chosen by the model, and a factor with no input
# (no known_skills, no experience_level, no team_size) is excluded from the
# average rather than defaulting to a guessed midpoint.
SKILL_FEASIBILITY_WEIGHT = 1.0
TIMELINE_FEASIBILITY_WEIGHT = 1.0
DIFFICULTY_FEASIBILITY_WEIGHT = 0.5
COMPLEXITY_FEASIBILITY_WEIGHT = 0.5
TEAM_SIZE_FEASIBILITY_WEIGHT = 0.4
_DEFAULT_SCORE_WHEN_NO_FACTORS = 50

# overall_score lower bound (inclusive) -> risk label, checked in order.
_RISK_LEVEL_BANDS: tuple[tuple[int, str], ...] = ((70, "Low"), (45, "Medium"), (0, "High"))

# --- Technical complexity ----------------------------------------------------
# A transparent, formula-based 0-100 complexity score — not a trained model,
# same philosophy as nlp/timeline.py's own multiplier tables. Difficulty
# supplies the base (a project's own stated difficulty is the strongest single
# signal of build complexity); the technology count adds a bounded penalty for
# how many distinct pieces have to be integrated, since a 2-technology project
# and an 8-technology project at the same "Intermediate" label are not
# equally complex to actually build.
_COMPLEXITY_BASE_BY_DIFFICULTY = {"Beginner": 25, "Intermediate": 50, "Advanced": 75}
_COMPLEXITY_BASE_UNKNOWN = 50
_COMPLEXITY_TECH_BASELINE = 3  # technologies up to this count add no penalty
_COMPLEXITY_TECH_STEP = 4  # points added per technology beyond the baseline
_COMPLEXITY_TECH_MAX_POINTS = 20  # ceiling on how much tech count alone can add

# complexity score lower bound (inclusive) -> label, checked in order.
_COMPLEXITY_LEVEL_BANDS: tuple[tuple[int, str], ...] = ((70, "High"), (40, "Medium"), (0, "Low"))

# --- Team size ----------------------------------------------------------------
# recommended_size is clamped into this range — a domain profile with a
# single module still suggests at least a solo builder (1), and even a
# module-heavy domain profile is capped so the number stays a sane team size
# rather than "one person per module" for an 8-module domain.
_TEAM_SIZE_MIN = 1
_TEAM_SIZE_MAX = 6
# |given - recommended| -> fit score, same shape as timeline/experience
# multiplier tables elsewhere in nlp/ — a fixed, readable table rather than a
# formula, since the meaningful cases (exact match, off-by-one, off-by-more)
# don't need continuous precision.
_TEAM_SIZE_FIT_FLOOR = 40
_TEAM_SIZE_FIT_STEP = 20

# Domains where a from-scratch model is the main complexity/infrastructure
# driver — used only to phrase a "consider a pretrained model" recommendation
# when complexity is genuinely high, never to change any score.
_MODEL_HEAVY_DOMAINS = {
    "Artificial Intelligence", "Machine Learning", "Deep Learning",
    "Natural Language Processing", "Computer Vision",
}
# Domains where a live/production-scale requirement is the most common scope
# risk — used only to phrase a "drop the real-time requirement" recommendation.
_REAL_TIME_SENSITIVE_DOMAINS = {"Computer Vision", "Augmented & Virtual Reality", "Robotics", "Internet of Things"}


def _band(score: float, bands: tuple[tuple[int, str], ...]) -> str:
    for threshold, label in bands:
        if score >= threshold:
            return label
    return bands[-1][1]


def _technical_complexity(doc: dict[str, Any]) -> dict[str, Any]:
    difficulty = doc.get("difficulty") or ""
    base = _COMPLEXITY_BASE_BY_DIFFICULTY.get(difficulty, _COMPLEXITY_BASE_UNKNOWN)

    tech_count = len(doc.get("technologies") or [])
    extra = max(0, tech_count - _COMPLEXITY_TECH_BASELINE)
    tech_points = min(extra * _COMPLEXITY_TECH_STEP, _COMPLEXITY_TECH_MAX_POINTS)

    score = max(0, min(100, base + tech_points))
    level = _band(score, _COMPLEXITY_LEVEL_BANDS)
    note = (
        f"{level} technical complexity — {difficulty or 'unspecified'} difficulty"
        f"{f', integrating {tech_count} technologies' if tech_count > _COMPLEXITY_TECH_BASELINE else ''}."
    )
    return {"score": score, "level": level, "note": note}


def _timeline_feasibility(
    doc: dict[str, Any], team_size: int, experience_level: Optional[str], target_weeks: Optional[int]
) -> dict[str, Any]:
    """Timeline FIT score against either the student's own deadline or this
    project's own baseline duration — the same two-branch scoring
    chat_tools.recommend_decision uses, kept here as this module's own small
    piece of orchestration glue. The estimate itself always comes from
    timeline.predict() (the real engine); nothing here recomputes it."""
    estimate = timeline.predict(doc, team_size=team_size, experience_level=experience_level)
    predicted = estimate["predicted_weeks"]

    if target_weeks is not None:
        if predicted <= target_weeks:
            score = 100.0
        else:
            overrun = predicted - target_weeks
            score = max(0.0, 100 - (overrun / target_weeks) * 100)
        basis = "target"
    else:
        baseline = doc.get("duration_weeks") or predicted
        score = max(0.0, 100 - abs(predicted - baseline) * 8)
        basis = "baseline"

    return {"score": round(score), "estimate": estimate, "basis": basis, "target_weeks": target_weeks}


def _team_size_guidance(doc: dict[str, Any], team_size: Optional[int]) -> dict[str, Any]:
    """recommended_size is the number of distinct role CATEGORIES this
    project's own domain modules span (nlp/team_builder.py's exact category
    table, via category_for()) — the same categories a real team_builder
    assignment would fill, not a separate guess. Always returned; `score` is
    only populated when the caller actually gave a team_size to compare
    against — an unavailable signal, never a guessed one."""
    profile = generator.domain_profile(doc.get("domain", ""))
    categories = {team_builder.category_for(module) for module in profile["modules"]}
    recommended = max(_TEAM_SIZE_MIN, min(_TEAM_SIZE_MAX, len(categories)))

    result: dict[str, Any] = {"recommended_size": recommended, "given_size": team_size, "score": None, "note": ""}
    if team_size is None:
        result["note"] = f"No team size given — this domain's roles typically span {recommended} categories."
        return result

    gap = abs(team_size - recommended)
    score = max(_TEAM_SIZE_FIT_FLOOR, 100 - gap * _TEAM_SIZE_FIT_STEP) if gap else 100
    if gap == 0:
        note = f"{team_size} matches the {recommended} role categories this project's domain typically has."
    elif team_size < recommended:
        note = f"{team_size} is fewer than the {recommended} role categories this project's domain typically has — expect overlap."
    else:
        note = f"{team_size} is more than the {recommended} role categories this project's domain typically needs."
    result["score"], result["note"] = score, note
    return result


def analyze_feasibility(
    doc: dict[str, Any],
    known_skills: Optional[list[str]] = None,
    team_size: Optional[int] = None,
    experience_level: Optional[str] = None,
    target_weeks: Optional[int] = None,
) -> dict[str, Any]:
    """The Feasibility Analyzer — one project/idea-shaped `doc` (a real
    catalogue project or a synthetic nlp/generator.py:idea_doc()), scored
    against the student's own stated skills/team/experience/deadline.

    Returns a dict with `feasibility_score` (0-100), `risk_level`, a `factors`
    list, plus the informational (never-scored) `technical_complexity`,
    `infrastructure`, `dataset`, and `team` sections, and rule-based
    `strengths`/`risks`/`recommendations` — every bullet traces back to one of
    the real numbers/hints computed above, never free text the caller invents.
    """
    skills = [s.strip() for s in (known_skills or []) if isinstance(s, str) and s.strip()]
    try:
        size = max(1, min(int(team_size), 20)) if team_size is not None else None
    except (TypeError, ValueError):
        size = None
    level = experience_level if experience_level in DIFFICULTIES else None
    try:
        target = max(1, min(int(target_weeks), 104)) if target_weeks is not None else None
    except (TypeError, ValueError):
        target = None

    gap = recommend.skill_gap_for_doc(doc, skills) if skills else None
    skill_score = gap["readiness_percent"] if gap is not None else None

    timeline_result = _timeline_feasibility(doc, size or 1, level, target)
    timeline_score = timeline_result["score"]

    difficulty_score, difficulty_note = recommend.difficulty_fit(doc.get("difficulty", ""), level)

    complexity = _technical_complexity(doc)
    complexity_score = 100 - complexity["score"]  # higher complexity -> lower feasibility contribution

    team = _team_size_guidance(doc, size)

    profile = generator.domain_profile(doc.get("domain", ""))
    infra_hint = profile.get("infra_hint", "")
    dataset_hint = profile.get("dataset_hint", "")

    factors = [
        {"factor": "Skill Fit", "score": skill_score, "note": ("Based on the skills you listed." if gap else "No skills given.")},
        {"factor": "Timeline Fit", "score": timeline_score, "note": f"Estimated {timeline_result['estimate']['predicted_weeks']:g} weeks."},
        {"factor": "Difficulty Fit", "score": difficulty_score, "note": difficulty_note},
        {"factor": "Technical Complexity", "score": complexity_score, "note": complexity["note"]},
        {"factor": "Team Size Fit", "score": team["score"], "note": team["note"]},
    ]

    weighted = (
        (skill_score, SKILL_FEASIBILITY_WEIGHT),
        (timeline_score, TIMELINE_FEASIBILITY_WEIGHT),
        (difficulty_score, DIFFICULTY_FEASIBILITY_WEIGHT),
        (complexity_score, COMPLEXITY_FEASIBILITY_WEIGHT),
        (team["score"], TEAM_SIZE_FEASIBILITY_WEIGHT),
    )
    score_total = sum(value * weight for value, weight in weighted if value is not None)
    weight_total = sum(weight for value, weight in weighted if value is not None)
    feasibility_score = round(score_total / weight_total) if weight_total else _DEFAULT_SCORE_WHEN_NO_FACTORS
    risk_level = _band(feasibility_score, _RISK_LEVEL_BANDS)

    strengths: list[str] = []
    risks: list[str] = []
    recommendations: list[str] = []

    if gap is not None:
        if gap["skills_you_have"]:
            strengths.append(f"You already have {', '.join(gap['skills_you_have'][:3])}.")
        if gap["skills_to_learn"]:
            risks.append(f"You'll need to learn {', '.join(gap['skills_to_learn'][:3])}.")
            if gap["readiness_percent"] < 50:
                recommendations.append(
                    f"Learn {', '.join(gap['skills_to_learn'][:2])} first, or partner with a teammate who "
                    "already knows them."
                )

    if timeline_score >= 70:
        strengths.append(f"Estimated {timeline_result['estimate']['predicted_weeks']:g} weeks fits comfortably.")
    else:
        risks.append(
            f"Timeline is tight — estimated {timeline_result['estimate']['predicted_weeks']:g} weeks"
            + (f" against your {target}-week target." if target else ".")
        )
        recommendations.append("Reduce scope to fit the timeline.")

    if difficulty_score is not None:
        (strengths if difficulty_score >= 75 else risks).append(difficulty_note)

    if complexity["level"] == "High":
        risks.append(complexity["note"])
        if doc.get("domain") in _MODEL_HEAVY_DOMAINS:
            recommendations.append("Consider using a pretrained model instead of training one from scratch.")
        if doc.get("domain") in _REAL_TIME_SENSITIVE_DOMAINS:
            recommendations.append("Simplify by dropping real-time/live-inference requirements if they aren't essential.")
    elif complexity["level"] == "Low":
        strengths.append("Technology stack is straightforward to pick up.")

    if infra_hint:
        (risks if "GPU" in infra_hint or "physical hardware" in infra_hint or "headset" in infra_hint else strengths).append(infra_hint)
    if dataset_hint:
        (risks if "Needs" in dataset_hint or "Typically needs" in dataset_hint or "May need" in dataset_hint else strengths).append(f"{dataset_hint} (estimate)")

    if team["score"] is not None:
        if team["score"] >= 80:
            strengths.append(team["note"])
        else:
            risks.append(team["note"])
            if team["given_size"] is not None and team["given_size"] < team["recommended_size"]:
                recommendations.append(f"Consider a team of about {team['recommended_size']} to comfortably cover every role.")

    return {
        "project_id": doc.get("project_id"),
        "title": doc.get("title", ""),
        "domain": doc.get("domain", ""),
        "feasibility_score": feasibility_score,
        "risk_level": risk_level,
        "factors": factors,
        "technical_complexity": complexity,
        "infrastructure": {"note": infra_hint, "is_estimate": True},
        "dataset": {"note": dataset_hint, "is_estimate": True},
        "team": team,
        "estimated_weeks": timeline_result["estimate"]["predicted_weeks"],
        "team_size": size or 1,
        "experience_level": level or doc.get("difficulty", ""),
        "target_weeks": target,
        "skills_you_have": gap["skills_you_have"] if gap else [],
        "skills_to_learn": gap["skills_to_learn"] if gap else [],
        "strengths": strengths,
        "risks": risks,
        "recommendations": recommendations,
    }


# --- Scope Analyzer ------------------------------------------------------------
# Same orchestration-only philosophy as analyze_feasibility() above — every
# tier is a real, already-existing piece of data, never an invented feature:
#
#   - mvp/core/advanced  -> nlp/generator.py:domain_profile()'s own `modules`
#                            list, re-sliced by its existing order (see
#                            _split_into_tiers()'s docstring for why that
#                            order is a real fact, not something invented here)
#   - future              -> nlp/generator.py:synopsis_for()'s own future_scope
#                            (already exists, already means "deferred")
#   - dependencies         -> the project/idea's own real `technologies`
#   - technical_constraints -> the same domain_profile() infra_hint/
#                            dataset_hint analyze_feasibility() already uses
#
# target_weeks only ever produces an advisory remove/keep recommendation
# (reduced_scope) — it never mutates `doc` or anything the caller passed in.

# A domain profile's `modules` list is already authored in build-dependency
# order (foundational work first — verified against every entry in
# nlp/generator.py's _DOMAIN_PROFILES, e.g. AI: "Data Collection" before
# "Model Training" before "User Interface"; the same order team_builder.py's
# suggest_roles() and generator.py's own roadmap core-phase task list already
# rely on). Slicing by that existing order is a re-presentation of real,
# already-meaningful data — not a fabricated split. MVP gets the first (larger)
# half, CORE and ADVANCED split what's left, each tier keeping at least one
# module whenever there is one left to give it.
def _split_into_tiers(modules: list[str]) -> tuple[list[str], list[str], list[str]]:
    n = len(modules)
    if n == 0:
        return [], [], []
    mvp_n = max(1, -(-n // 2))  # ceil(n / 2)
    remaining = n - mvp_n
    core_n = max(1, -(-remaining // 2)) if remaining else 0  # ceil(remaining / 2)
    mvp = modules[:mvp_n]
    core = modules[mvp_n : mvp_n + core_n]
    advanced = modules[mvp_n + core_n :]
    return mvp, core, advanced


def analyze_scope(doc: dict[str, Any], target_weeks: Optional[int] = None) -> dict[str, Any]:
    """The Scope Analyzer — MVP/CORE/ADVANCED/FUTURE tiers, in/out-of-scope,
    dependencies and technical constraints for one project/idea-shaped `doc`,
    plus (only when `target_weeks` is given and tighter than the baseline
    duration) a remove/keep scope-reduction recommendation.
    """
    try:
        target = max(1, min(int(target_weeks), 104)) if target_weeks is not None else None
    except (TypeError, ValueError):
        target = None

    profile = generator.domain_profile(doc.get("domain", ""))
    mvp, core, advanced = _split_into_tiers(profile["modules"])

    synopsis = generator.synopsis_for(doc)
    future = synopsis["future_scope"]

    infra_hint = profile.get("infra_hint", "")
    dataset_hint = profile.get("dataset_hint", "")
    constraints = [hint for hint in (infra_hint, dataset_hint) if hint]

    duration_weeks = doc.get("duration_weeks")
    reduced_scope = None
    if target is not None and duration_weeks and target < duration_weeks:
        if advanced:
            reduced_scope = {
                "remove": advanced,
                "keep": mvp + core,
                "reason": (
                    f"Your {target}-week target is {duration_weeks - target} week"
                    f"{'s' if duration_weeks - target != 1 else ''} short of the {duration_weeks}-week "
                    f"baseline — dropping {', '.join(advanced)} keeps the core system achievable."
                ),
            }
        else:
            reduced_scope = {
                "remove": [],
                "keep": mvp + core,
                "reason": (
                    f"Your {target}-week target is short of the {duration_weeks}-week baseline, but "
                    "there are no optional modules left to drop — consider simplifying within the "
                    "core modules instead, or extending the timeline."
                ),
            }

    return {
        "project_id": doc.get("project_id"),
        "title": doc.get("title", ""),
        "domain": doc.get("domain", ""),
        "mvp": mvp,
        "core": core,
        "advanced": advanced,
        "future": future,
        "in_scope": mvp + core + advanced,
        "out_of_scope": future,
        "dependencies": doc.get("technologies", []),
        "technical_constraints": constraints,
        "target_weeks": target,
        "duration_weeks": duration_weeks,
        "reduced_scope": reduced_scope,
    }


# --- Resource Estimator ---------------------------------------------------
# Same orchestration-only rule as the two analyzers above:
#   - team recommended_size  -> _team_size_guidance() above (the exact same
#                                helper analyze_feasibility() uses — not a
#                                second team-size computation)
#   - roles/categories        -> domain_profile()'s own `modules`, mapped
#                                through team_builder.category_for() (the
#                                same table suggest_roles() uses)
#   - required_skills          -> the project/idea's own real `skills`
#   - technology breakdown     -> the project/idea's own real `technologies`,
#                                bucketed by _TECH_STACK_KEYWORDS below
#   - dataset/compute guidance -> the same domain_profile() infra_hint/
#                                dataset_hint the other two analyzers use,
#                                always returned flagged as an estimate
#   - cost                     -> a static, free-tier-first bracket table,
#                                never a specific invented price; every
#                                figure is a round number or "$0", always
#                                under an explicit is_estimate flag
#
# _TECH_STACK_KEYWORDS is a NEW small table (this codebase has no existing
# "which stack layer is this technology" classifier) — deliberately not
# reused from team_builder._CATEGORY_KEYWORDS, which answers a different
# question (which team ROLE fits a skill) and has no separate "database"
# bucket; forcing that table to serve both purposes would blur two genuinely
# different taxonomies rather than reuse one.
_TECH_STACK_KEYWORDS: dict[str, list[str]] = {
    "ai_ml": [
        "tensorflow", "pytorch", "scikit", "sklearn", "keras", "opencv", "transformers",
        "spacy", "nltk", "huggingface", "yolo", "mediapipe", "machine learning", "deep learning", "nlp",
    ],
    "frontend": [
        "react", "vue", "angular", "flutter", "react native", "swiftui", "html", "css",
        "tailwind", "next.js", "javascript", "typescript",
    ],
    "backend": ["flask", "django", "fastapi", "express", "node", "spring", "rest api", "graphql", "microservice"],
    "database": [
        "mongodb", "postgresql", "postgres", "mysql", "sqlite", "redis", "firebase",
        "firestore", "dynamodb", "cassandra", "database", "sql",
    ],
    "infrastructure": ["docker", "kubernetes", "aws", "azure", "gcp", "ci/cd", "cicd", "terraform", "cloud", "deployment"],
}

# Substring match against a technology's own name — a project's own real
# `technologies` list filtered, never a separate invented list.
_API_KEYWORDS = ("api",)
_EXTERNAL_SERVICE_KEYWORDS = ("aws", "azure", "gcp", "firebase", "cloud", "stripe", "twilio", "auth0")

# Static, free-tier-first bracket text — deliberately never a specific
# dollar figure beyond "$0", and every claim names a real, stable free tier
# rather than a guessed number. Cost of running THIS app is the same shape
# of claim (see config.py's own GROQ_API_KEY comment: "free key").
_COST_NOTES = {
    "development": "Typically $0 — a solo/team academic project using your own time, no paid development cost expected.",
    "infrastructure": "Roughly $0 on free-tier hosting/database plans for a project this size; costs only appear past those free limits.",
    "api": "$0 on free-tier APIs (e.g. Groq, Hugging Face Inference); paid usage varies by provider and volume — check current pricing before committing.",
    "hosting": "$0/month achievable on a free-tier host (Render, Vercel, Netlify, or Railway) for a student-scale deployment.",
}
_STORAGE_NOTE = "Local storage is sufficient for a student-scale project; cloud storage only becomes worth it if the dataset or user base grows large."


def _technology_stack(technologies: list[str]) -> dict[str, list[str]]:
    stack: dict[str, list[str]] = {"frontend": [], "backend": [], "database": [], "ai_ml": [], "infrastructure": []}
    for tech in technologies:
        tech_lower = tech.lower()
        for category, keywords in _TECH_STACK_KEYWORDS.items():
            if any(keyword in tech_lower for keyword in keywords):
                stack[category].append(tech)
                break
    return stack


def _free_alternatives(technologies: list[str], infra_hint: str, dataset_hint: str) -> list[str]:
    """Real, stable free tiers — only ever suggested when the project's own
    domain data (infra_hint/dataset_hint) or technologies actually implies a
    need for them, never a blanket list unrelated to this project."""
    alternatives = ["Free-tier hosting: Render, Vercel, Netlify, or Railway free plans."]
    if "GPU" in infra_hint:
        alternatives.append("Free GPU compute: Google Colab or Kaggle Notebooks free tier.")
    if "dataset" in dataset_hint.lower():
        alternatives.append("Free public datasets: Kaggle, Hugging Face Datasets, or the UCI Machine Learning Repository.")
    if any("mongodb" in t.lower() for t in technologies):
        alternatives.append("Free-tier database: MongoDB Atlas free cluster (M0).")
    alternatives.append("Free/low-cost AI API: Groq's free tier or Hugging Face Inference's free tier.")
    return alternatives


def estimate_resources(doc: dict[str, Any], team_size: Optional[int] = None) -> dict[str, Any]:
    """The Resource Estimator — team size/roles, a technology-stack
    breakdown, dataset/compute/storage/API guidance, and a free-tier-first
    cost estimate for one project/idea-shaped `doc`. Every cost figure is a
    round bracket under `cost.is_estimate: true`, never an LLM-invented exact
    price — see the module docstring above for what each section reuses.
    """
    try:
        size = max(1, min(int(team_size), 20)) if team_size is not None else None
    except (TypeError, ValueError):
        size = None

    profile = generator.domain_profile(doc.get("domain", ""))
    infra_hint = profile.get("infra_hint", "")
    dataset_hint = profile.get("dataset_hint", "")
    technologies = doc.get("technologies", [])

    team_guidance = _team_size_guidance(doc, size)
    roles = [{"role": module, "category": team_builder.category_for(module)} for module in profile["modules"]]

    return {
        "project_id": doc.get("project_id"),
        "title": doc.get("title", ""),
        "domain": doc.get("domain", ""),
        "duration_weeks": doc.get("duration_weeks"),
        "difficulty": doc.get("difficulty", ""),
        "team": {
            "recommended_size": team_guidance["recommended_size"],
            "given_size": team_guidance["given_size"],
            "roles": roles,
            "required_skills": doc.get("skills", []),
        },
        "technology": _technology_stack(technologies),
        "resources": {
            "dataset": {"note": dataset_hint, "is_estimate": True},
            "compute": {"note": infra_hint, "is_estimate": True},
            "storage": {"note": _STORAGE_NOTE, "is_estimate": True},
            "apis": [t for t in technologies if any(k in t.lower() for k in _API_KEYWORDS)],
            "external_services": [t for t in technologies if any(k in t.lower() for k in _EXTERNAL_SERVICE_KEYWORDS)],
        },
        "cost": {
            **_COST_NOTES,
            "free_alternatives": _free_alternatives(technologies, infra_hint, dataset_hint),
            "is_estimate": True,
        },
    }
