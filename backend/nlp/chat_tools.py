"""Tool implementations for the RAG-grounded chat assistant.

Each tool wraps a piece of this codebase that already exists and is already
deterministic (hybrid search, a Mongo project lookup, the roadmap generator).
The model never invents project data — everything it can say about a project
came from one of these calls, feeding it real catalogue data instead of a
hallucinated title or tech stack. See nlp/ai_assistant.py:general_reply for
the loop that calls these.
"""

from __future__ import annotations

from typing import Any, Optional

from db import client as db
from db.schema import DIFFICULTIES, DOMAINS
from nlp import generator, ideation, learning_path, recommend, timeline

MAX_SEARCH_RESULTS = 8
DEFAULT_SEARCH_RESULTS = 5
DESCRIPTION_PREVIEW_CHARS = 220
MAX_COMPARE_PROJECTS = 4

# --- Multi-factor decision weights ------------------------------------------
# Centralized so "overall fit" is always computed the same, transparent way —
# the model never sees or chooses these, it only explains the ranking they
# produce. A factor whose input wasn't given (no known_skills, no
# experience_level) contributes nothing rather than a guessed default; see
# recommend_decision() for how an "unavailable" factor is excluded from the
# average instead of defaulting to some fixed midpoint score.
SKILL_FIT_WEIGHT = 1.0
TIMELINE_FIT_WEIGHT = 0.25
DIFFICULTY_FIT_WEIGHT = 0.25
UNIQUENESS_WEIGHT_DEFAULT = 0.25
UNIQUENESS_WEIGHT_PREFERRED = 0.6  # when the student explicitly asked for something unique

# index gap between a student's stated experience level and a project's own
# difficulty -> a 0-100 fit score. Uses the same DIFFICULTIES ordering
# nlp/timeline.py's experience multiplier already uses, so the two signals
# never disagree about which direction is "ahead" vs "behind" — but it is its
# own small table, not a second copy of timeline's multiplier: that answers
# "how much faster/slower", this answers "how well does the level match".
_DIFFICULTY_FIT_BY_GAP = {0: 100, 1: 75}
_DIFFICULTY_FIT_FLOOR = 50

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_projects",
            "description": (
                "Search ProjectMind's EXISTING catalogue of real student project briefs using "
                "hybrid semantic + keyword search. Use for finding/recommending projects that "
                "already exist in the catalogue, or projects matching the student's skills. For "
                "'projects similar to X' about ONE specific project already shown, use "
                "find_similar_projects instead — it uses the real embedding similarity index "
                "rather than a re-typed query. Do NOT use this when the student asks for NEW, "
                "innovative, original, or fresh project ideas, or 'what can I build' / 'give me "
                "something different' — that is a request to invent something that isn't in the "
                "catalogue yet, which is generate_project_ideas' job, not this one. Never invent "
                "a project that isn't returned here. Pass known_skills/team_size/experience_level "
                "too whenever the student has already told you theirs (even earlier in the "
                "conversation) — it blends skill fit and timeline fit into the ranking instead of "
                "ranking on topic relevance alone, and each result comes back with its own "
                "matching_factors and skills_you_have/skills_to_learn so you never have to guess "
                "why something was recommended."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What the student is looking for, in natural language.",
                    },
                    "difficulty": {
                        "type": "string",
                        "enum": list(DIFFICULTIES),
                        "description": "Restrict to one difficulty level, only if the student asked for one.",
                    },
                    "domain": {
                        "type": "string",
                        "enum": list(DOMAINS),
                        "description": "Restrict to one domain, only if the student named one.",
                    },
                    "max_duration_weeks": {
                        # Accepts a numeral string too — Groq validates tool-call
                        # arguments strictly against this schema, and the model
                        # sometimes emits a quoted number ("12") rather than 12,
                        # which a plain "integer" type rejects outright (400).
                        "type": ["integer", "string"],
                        "description": "Only projects completable within this many weeks.",
                    },
                    "top_k": {
                        "type": ["integer", "string"],
                        "description": f"Number of results, default {DEFAULT_SEARCH_RESULTS}, max {MAX_SEARCH_RESULTS}.",
                    },
                    "known_skills": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Skills the student says they already have, if any — enables skill-fit ranking.",
                    },
                    "team_size": {
                        "type": ["integer", "string"],
                        "description": "Team size, if the student mentioned one — enables timeline-fit ranking.",
                    },
                    "experience_level": {
                        "type": "string",
                        "enum": list(DIFFICULTIES),
                        "description": "The student's own experience level, if mentioned — affects the timeline estimate.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_similar_projects",
            "description": (
                "Retrieve real catalogue projects most similar to ONE specific existing project, "
                "using ProjectMind's embedding similarity index directly — not a text search. Use "
                "this whenever the student names or references one specific project already "
                "shown/selected and asks for similar/related/alternative ones ('projects like "
                "this', 'anything similar to the chatbot one', 'what else is like project X'). "
                "Prefer this over search_projects for that case — it compares the two projects' "
                "full meaning, not just a re-typed description."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "top_k": {
                        "type": ["integer", "string"],
                        "description": f"Number of results, default {DEFAULT_SEARCH_RESULTS}, max {MAX_SEARCH_RESULTS}.",
                    },
                },
                "required": ["project_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_project_details",
            "description": (
                "Fetch full details (description, technologies, skills, duration) for one "
                "specific project by its project_id. Call this before answering a specific "
                "question — technologies used, duration, skills needed — about a project "
                "already shown in this conversation."
            ),
            "parameters": {
                "type": "object",
                "properties": {"project_id": {"type": "string"}},
                "required": ["project_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_roadmap",
            "description": (
                "Generate the official phase-by-phase development roadmap for one project, "
                "sized to its duration, by its project_id."
            ),
            "parameters": {
                "type": "object",
                "properties": {"project_id": {"type": "string"}},
                "required": ["project_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_synopsis",
            "description": "Generate the official first-draft synopsis (abstract, objectives, scope, methodology) for one project by its project_id.",
            "parameters": {
                "type": "object",
                "properties": {"project_id": {"type": "string"}},
                "required": ["project_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_milestones",
            "description": (
                "Generate measurable build milestones (M1, M2, ...) for one catalogue project by "
                "its project_id, one per roadmap phase with the week it should be done by — use "
                "for 'give me milestones', 'what are the checkpoints', or 'break this into "
                "deliverables'. Derived directly from the same roadmap generate_roadmap uses, so "
                "milestones always agree with the phases/timeline — never invent milestones "
                "yourself or make them up from generate_roadmap's own result."
            ),
            "parameters": {
                "type": "object",
                "properties": {"project_id": {"type": "string"}},
                "required": ["project_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_projects",
            "description": (
                "Compare two or more projects already shown in this conversation, side by side, "
                "using their real catalogue data (difficulty, duration, technologies, skills). "
                "Resolve references like 'the first and third one' to project_ids using the "
                "'[Context — projects shown above]' note before calling this."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": f"2 to {MAX_COMPARE_PROJECTS} project_ids to compare.",
                    },
                },
                "required": ["project_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_skill_gap",
            "description": (
                "Compare a student's own skills against one project's requirements — readiness %, "
                "skills they already have, and skills they're missing. If the student hasn't told "
                "you their skills yet in this conversation, ask them first instead of guessing or "
                "calling this with an empty list."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "known_skills": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Skills the student says they already have.",
                    },
                },
                "required": ["project_id", "known_skills"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "match_resume_projects",
            "description": (
                "Find and rank catalogue projects against the student's own uploaded-résumé "
                "skills — use for 'which project fits me best', 'recommend projects based on my "
                "résumé', or 'which project matches my experience/skills' once a "
                "'[Context — résumé skills already on file...]' note is present. Returns each "
                "match's real overall fit plus the skills the student already has and is missing "
                "for it, using the same skill-gap logic as check_skill_gap — never invent this "
                "breakdown yourself. If no résumé context note is present, do not call this — "
                "tell the student to upload their résumé on the Résumé Match page first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "known_skills": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "The résumé skills exactly as listed in the "
                            "'[Context — résumé skills already on file...]' note."
                        ),
                    },
                    "top_k": {
                        "type": ["integer", "string"],
                        "description": f"Number of results, default {DEFAULT_SEARCH_RESULTS}, max {MAX_SEARCH_RESULTS}.",
                    },
                },
                "required": ["known_skills"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "predict_timeline",
            "description": (
                "Estimate how long one project will actually take for a given team size and/or "
                "experience level — use for questions like 'can I finish this in 3 months' or "
                "'is this good for a team of 2'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "team_size": {"type": ["integer", "string"], "description": "Defaults to 1 (solo) if not mentioned."},
                    "experience_level": {"type": "string", "enum": list(DIFFICULTIES)},
                },
                "required": ["project_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_learning_path",
            "description": "Real tutorial/course/official-docs links for a list of skills — use after check_skill_gap to help with the skills a student is missing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "skills": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["skills"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "select_project",
            "description": (
                "Mark one project as the student's selected/active project for the rest of this "
                "conversation, so future questions (architecture, database choice, how to build X) "
                "are grounded in it automatically. Call this whenever the student says things like "
                "'select this one', 'I'll go with the second one', or 'let's build the chatbot'."
            ),
            "parameters": {
                "type": "object",
                "properties": {"project_id": {"type": "string"}},
                "required": ["project_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "select_idea",
            "description": (
                "Mark one previously generated idea (from generate_project_ideas or "
                "refine_project_idea) as the student's selected/active build target for the rest "
                "of this conversation, so future questions (architecture, database choice, how to "
                "build X) are grounded in it automatically — the idea-context mirror of "
                "select_project, for a GENERATED idea rather than a catalogue project. Call this "
                "whenever the student says things like 'let's build this one', 'I'll go with the "
                "second idea', or 'build the smart notes idea'. Use the idea's exact current "
                "fields from the '[Context — generated ideas shown above]' note. Selecting an idea "
                "replaces any previously selected catalogue project as the active build target, "
                "and vice versa for select_project — only one can be active at a time."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "The idea's id from the shown-ideas context, e.g. 'idea-2'."},
                    "name": {"type": "string"},
                    "problem": {"type": "string"},
                    "solution": {"type": "string"},
                    "unique_point": {"type": "string"},
                    "technologies": {"type": "array", "items": {"type": "string"}},
                    "domain": {"type": "string", "enum": list(DOMAINS)},
                    "difficulty": {"type": "string", "enum": list(DIFFICULTIES)},
                    "duration_weeks": {"type": ["integer", "string"]},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recommend_decision",
            "description": (
                "Help the student decide between project(s) already shown, searched, or compared "
                "in this conversation — call this for 'which one should I choose?', 'which is "
                "easiest?', 'which is most unique?', 'which fits my skills/resume best?', 'which "
                "can I finish in N weeks/months?', or 'give me your final recommendation'. "
                "Combines four real signals for each project into one ranked, explained result — "
                "Skill Fit (vs known_skills), Timeline Fit (vs target_weeks or the project's own "
                "duration), Difficulty Fit (vs experience_level), and catalogue Uniqueness — never "
                "re-derive or guess these judgements yourself, always call this. For a narrower "
                "question ('which is easiest', 'which fits my skills') just speak to that one "
                "factor from the result rather than the overall ranking. Works even with only one "
                "project_id (a straight suitability check) or with no known_skills/team_size/"
                "experience_level yet (don't block on asking first — use whatever the student has "
                "already said in this conversation; a factor with no input becomes explicitly "
                "unavailable rather than guessed, and the tool still works without it)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "1 to 4 project_ids to evaluate — from the projects shown, searched, or compared above.",
                    },
                    "known_skills": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Skills the student has mentioned they have, if any.",
                    },
                    "team_size": {"type": ["integer", "string"], "description": "Defaults to 1 (solo) if not mentioned."},
                    "experience_level": {"type": "string", "enum": list(DIFFICULTIES)},
                    "prefers_unique": {
                        "type": "boolean",
                        "description": "True if the student explicitly asked for something innovative/unique/original.",
                    },
                    "target_weeks": {
                        "type": ["integer", "string"],
                        "description": "The student's deadline in weeks, if they gave one — 'in 3 months' -> 12, 'in 6 weeks' -> 6. Omit if no deadline was mentioned.",
                    },
                },
                "required": ["project_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_project_uniqueness",
            "description": (
                "Check how original the student's OWN project idea is against ProjectMind's "
                "catalogue, by meaning (not just shared words). Call this when the student "
                "describes an idea of their own and asks things like 'is my idea unique?', "
                "'check this project idea', or 'is this too similar to existing projects?' — "
                "not for questions about a catalogue project they're already looking at."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "idea": {
                        "type": "string",
                        "description": "The student's project idea in their own words (title and/or description together is fine).",
                    }
                },
                "required": ["idea"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_project_ideas",
            "description": (
                "Invent NEW project concepts that do NOT exist in ProjectMind's catalogue yet — "
                "call this (never search_projects) when the student asks for new/innovative/"
                "original/fresh/unique project ideas, 'what can I build', 'suggest a project' "
                "with no catalogue qualifier, or explicitly says they want something different "
                "from what exists. Each idea is generated then automatically checked for real "
                "originality against the catalogue before being returned, so you never need to "
                "call check_project_uniqueness yourself right after this."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Theme/topic for the ideas in the student's own words, e.g. 'AI', 'NLP', 'sustainability'. Empty if unconstrained.",
                    },
                    "domain": {"type": "string", "enum": list(DOMAINS)},
                    "difficulty": {"type": "string", "enum": list(DIFFICULTIES)},
                    "count": {
                        "type": ["integer", "string"],
                        "description": f"Number of ideas, default {ideation.IDEA_COUNT_DEFAULT}, max {ideation.IDEA_COUNT_MAX}.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "refine_project_idea",
            "description": (
                "Regenerate ONE previously generated idea (from generate_project_ideas) against "
                "the student's follow-up instruction — 'make it more innovative', 'use a "
                "different tech stack', 'simplify it'. Use the idea's exact current fields from "
                "the '[Context — ideas shown above]' note; re-validated for originality "
                "automatically, same as a fresh idea."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "The idea's id from the shown-ideas context, e.g. 'idea-2'."},
                    "name": {"type": "string"},
                    "problem": {"type": "string"},
                    "solution": {"type": "string"},
                    "unique_point": {"type": "string"},
                    "technologies": {"type": "array", "items": {"type": "string"}},
                    "domain": {"type": "string", "enum": list(DOMAINS)},
                    "difficulty": {"type": "string", "enum": list(DIFFICULTIES)},
                    "duration_weeks": {"type": ["integer", "string"]},
                    "instruction": {"type": "string", "description": "What the student wants changed about this idea."},
                },
                "required": ["name", "instruction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_idea_roadmap",
            "description": (
                "Phase-by-phase development roadmap for a GENERATED idea (one with no catalogue "
                "project_id) — use this instead of generate_roadmap when the student asks for a "
                "roadmap, implementation plan, or phases for one of the ideas from "
                "generate_project_ideas rather than a catalogue project. Each phase comes back with "
                "objective/tasks/technologies/expected_output already filled in, grounded in the "
                "idea's own technologies where you pass them — always pass technologies from the "
                "idea's context so this is as grounded as a catalogue project's roadmap."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "domain": {"type": "string", "enum": list(DOMAINS)},
                    "duration_weeks": {"type": ["integer", "string"]},
                    "technologies": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "The idea's own technologies, from the shown-ideas/active-idea context.",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_idea_timeline",
            "description": (
                "Realistic completion estimate for a GENERATED idea (no catalogue project_id), "
                "given a team size and/or experience level — use this instead of predict_timeline "
                "when the student asks 'how long will this take' about one of the ideas from "
                "generate_project_ideas rather than a catalogue project."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "domain": {"type": "string", "enum": list(DOMAINS)},
                    "difficulty": {"type": "string", "enum": list(DIFFICULTIES)},
                    "duration_weeks": {"type": ["integer", "string"]},
                    "team_size": {"type": ["integer", "string"], "description": "Defaults to 1 (solo) if not mentioned."},
                    "experience_level": {"type": "string", "enum": list(DIFFICULTIES)},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_idea_milestones",
            "description": (
                "Measurable build milestones for a GENERATED idea (no catalogue project_id) — use "
                "this instead of generate_milestones when the student asks for milestones/"
                "checkpoints/deliverables for one of the ideas from generate_project_ideas rather "
                "than a catalogue project."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "domain": {"type": "string", "enum": list(DOMAINS)},
                    "duration_weeks": {"type": ["integer", "string"]},
                },
                "required": ["name"],
            },
        },
    },
]


def _card(doc: dict[str, Any], *, score: Optional[float] = None) -> dict[str, Any]:
    """The compact project shape stored in a project_recommendations block —
    enough for the frontend to render a card with no extra round trip.

    `score` is only ever known at search time (it's relative to a query, not
    an intrinsic project property), so it's an explicit optional rather than
    something a plain project lookup could ever produce on its own.
    """
    description = doc.get("description") or ""
    if len(description) > DESCRIPTION_PREVIEW_CHARS:
        description = description[:DESCRIPTION_PREVIEW_CHARS].rsplit(" ", 1)[0].rstrip(",;: ") + "…"
    card = {
        "project_id": doc["project_id"],
        "title": doc.get("title", ""),
        "domain": doc.get("domain", ""),
        "difficulty": doc.get("difficulty", ""),
        "duration_weeks": doc.get("duration_weeks"),
        "description": description,
        "technologies": doc.get("technologies", [])[:5],
    }
    if score is not None:
        card["match_score"] = round(float(score), 4)
    return card


def _lookup(project_id: str) -> Optional[dict[str, Any]]:
    return db.projects().find_one({"project_id": (project_id or "").strip()}, {"_id": 0})


def _recommendation_card(rec: dict[str, Any]) -> dict[str, Any]:
    """Card shape for one nlp/recommend.py:personalized_recommend() result —
    the multi-factor sibling of _card() above, carrying the extra fields a
    plain relevance search has no basis for (matching_factors, skill gap,
    timeline, and the reason string), so the model and frontend never have
    to re-derive why a personalized result ranked where it did."""
    description = rec.get("description") or ""
    if len(description) > DESCRIPTION_PREVIEW_CHARS:
        description = description[:DESCRIPTION_PREVIEW_CHARS].rsplit(" ", 1)[0].rstrip(",;: ") + "…"
    gap = rec.get("skill_gap") or {}
    return {
        "project_id": rec["project_id"],
        "title": rec.get("title", ""),
        "domain": rec.get("domain", ""),
        "difficulty": rec.get("difficulty", ""),
        "duration_weeks": rec.get("duration_weeks"),
        "description": description,
        "technologies": rec.get("technologies", [])[:5],
        "match_score": round(rec["overall_score"] / 100, 4),
        "matching_factors": rec.get("matching_factors", []),
        "skills_you_have": gap.get("skills_you_have", []),
        "skills_to_learn": gap.get("skills_to_learn", []),
        "estimated_weeks": (rec.get("timeline") or {}).get("predicted_weeks"),
        "recommendation_reason": rec.get("recommendation_reason", ""),
    }


def search_projects(
    query: str,
    difficulty: Optional[str] = None,
    domain: Optional[str] = None,
    max_duration_weeks: Optional[int] = None,
    top_k: Optional[int] = None,
    known_skills: Optional[list[str]] = None,
    team_size: Optional[int] = None,
    experience_level: Optional[str] = None,
) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    """Returns (result-for-the-model, project_recommendations block or None).

    Reuses the exact same hybrid retriever /api/search does — this is not a
    second ranking algorithm, just a second caller of the one that exists.
    When known_skills/team_size/experience_level carry a real signal, this
    delegates to nlp/recommend.py:personalized_recommend instead, which
    layers skill-gap and timeline fit onto that same retrieval rather than
    ranking on topic relevance alone — still one retrieval call either way.
    """
    filters: dict[str, Any] = {}
    if difficulty in DIFFICULTIES:
        filters["difficulty"] = difficulty
    if domain in DOMAINS:
        filters["domain"] = domain
    try:
        weeks = int(max_duration_weeks) if max_duration_weeks is not None else None
    except (TypeError, ValueError):
        weeks = None
    if weeks is not None and weeks > 0:
        filters["max_duration_weeks"] = weeks

    try:
        k = int(top_k) if top_k is not None else DEFAULT_SEARCH_RESULTS
    except (TypeError, ValueError):
        k = DEFAULT_SEARCH_RESULTS
    k = max(1, min(k, MAX_SEARCH_RESULTS))

    skills = [s.strip() for s in (known_skills or []) if isinstance(s, str) and s.strip()]
    try:
        size = int(team_size) if team_size is not None else None
    except (TypeError, ValueError):
        size = None
    level = experience_level if experience_level in DIFFICULTIES else None
    personalized = bool(skills or (size and size > 1) or level)

    query = (query or "").strip()
    if not query and not personalized:
        return {"count": 0, "projects": [], "note": "Empty query."}, None

    if personalized:
        recs = recommend.personalized_recommend(
            query=query,
            known_skills=skills,
            domain=filters.get("domain"),
            difficulty=filters.get("difficulty"),
            max_duration_weeks=filters.get("max_duration_weeks"),
            team_size=size or 1,
            experience_level=level,
            top_k=k,
        )
        cards = [_recommendation_card(r) for r in recs]
        for_model = {
            "count": len(cards),
            "personalized": True,
            "projects": [{key: value for key, value in c.items() if key != "description"} for c in cards],
        }
    else:
        results = recommend.search(query, filters=filters or None, top_k=k)
        cards = [_card(r.document, score=r.score) for r in results]
        for_model = {
            "count": len(cards),
            "personalized": False,
            "projects": [
                {
                    "project_id": c["project_id"],
                    "title": c["title"],
                    "domain": c["domain"],
                    "difficulty": c["difficulty"],
                    "duration_weeks": c["duration_weeks"],
                    "technologies": c["technologies"],
                }
                for c in cards
            ],
        }

    block = {"type": "project_recommendations", "projects": cards} if cards else None
    return for_model, block


def find_similar_projects(project_id: str, top_k: Optional[int] = None) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    """Wraps recommend.similar() — the same pure embedding nearest-neighbour
    lookup GET /api/similar/<id> already exposes, just reachable from chat.
    Deliberately not search_projects: this compares two full documents by
    meaning, not a hand-typed query against the corpus."""
    doc = _lookup(project_id)
    if doc is None:
        return {"error": f"No project with id '{project_id}'."}, None

    try:
        k = int(top_k) if top_k is not None else DEFAULT_SEARCH_RESULTS
    except (TypeError, ValueError):
        k = DEFAULT_SEARCH_RESULTS
    k = max(1, min(k, MAX_SEARCH_RESULTS))

    results = recommend.similar(project_id, top_k=k)
    cards = [_card(r.document, score=r.score) for r in results]

    for_model = {
        "reference_project_id": project_id,
        "reference_title": doc.get("title", ""),
        "count": len(cards),
        "projects": [
            {
                "project_id": c["project_id"],
                "title": c["title"],
                "domain": c["domain"],
                "difficulty": c["difficulty"],
                "duration_weeks": c["duration_weeks"],
                "technologies": c["technologies"],
            }
            for c in cards
        ],
    }
    block = {"type": "project_recommendations", "projects": cards} if cards else None
    return for_model, block


def get_project_details(project_id: str) -> dict[str, Any]:
    doc = _lookup(project_id)
    if doc is None:
        return {"error": f"No project with id '{project_id}'."}
    return {
        "project_id": doc["project_id"],
        "title": doc.get("title"),
        "description": doc.get("description"),
        "domain": doc.get("domain"),
        "difficulty": doc.get("difficulty"),
        "duration_weeks": doc.get("duration_weeks"),
        "technologies": doc.get("technologies", []),
        "skills": doc.get("skills", []),
    }


def generate_roadmap(project_id: str) -> dict[str, Any]:
    doc = _lookup(project_id)
    if doc is None:
        return {"error": f"No project with id '{project_id}'."}
    return generator.roadmap_for(doc)


def generate_synopsis(project_id: str) -> dict[str, Any]:
    doc = _lookup(project_id)
    if doc is None:
        return {"error": f"No project with id '{project_id}'."}
    return generator.synopsis_for(doc)


def generate_milestones(project_id: str) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    """Unlike generate_roadmap/generate_synopsis (prose-only — the model
    narrates them), milestones get a structured block: a short checkpoint
    list benefits from the same kind of dedicated rendering timeline/
    skill_gap already get, rather than a Markdown table for six lines."""
    doc = _lookup(project_id)
    if doc is None:
        return {"error": f"No project with id '{project_id}'."}, None
    result = generator.milestones_for(doc)
    return result, {"type": "milestones", **result}


def _uniqueness_percent(project_id: str) -> int:
    """How distinct one catalogue project is from its own nearest neighbour.

    Reuses recommend.similar() — the same nearest-neighbour search
    /api/similar/<id> already exposes — read as "1 - closest peer's score"
    rather than a ranked list. Shared by compare_projects() and
    recommend_decision() below so both ever report the exact same number for
    the same project; no second similarity computation.
    """
    peers = recommend.similar(project_id, top_k=1)
    return round((1 - peers[0].score) * 100) if peers else 100


def _difficulty_fit(project_difficulty: str, experience_level: Optional[str]) -> tuple[Optional[int], str]:
    """How well a student's stated experience level matches a project's own
    difficulty, as a 0-100 score — None (unavailable) when no
    experience_level was given, since that is genuinely unknown and must not
    be guessed (see module docstring / architecture rule on unavailable
    signals)."""
    if not experience_level:
        return None, "Experience level not given."
    try:
        project_idx = DIFFICULTIES.index(project_difficulty)
        student_idx = DIFFICULTIES.index(experience_level)
    except ValueError:
        return None, "Unrecognised difficulty level."

    gap = abs(student_idx - project_idx)
    score = _DIFFICULTY_FIT_BY_GAP.get(gap, _DIFFICULTY_FIT_FLOOR)

    if gap == 0:
        note = f"{experience_level} experience matches this project's {project_difficulty} difficulty."
    elif student_idx > project_idx:
        note = (
            f"{experience_level} experience is ahead of this project's {project_difficulty} "
            "difficulty — likely to feel easy."
        )
    else:
        note = (
            f"{experience_level} experience is behind this project's {project_difficulty} "
            "difficulty — likely to feel challenging."
        )
    return score, note


def compare_projects(project_ids: list[str]) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    """Side-by-side real data for 2+ projects — no invented fields (no
    'complexity'/'best suited for'/etc., since those aren't in the dataset;
    the model covers that qualitatively in its own reply, grounded in the
    real fields returned here). uniqueness_percent is the one derived signal
    included, reusing _uniqueness_percent() above rather than a second
    similarity computation."""
    ids: list[str] = []
    seen: set[str] = set()
    for raw in project_ids or []:
        pid = (raw or "").strip()
        if pid and pid not in seen:
            seen.add(pid)
            ids.append(pid)
    ids = ids[:MAX_COMPARE_PROJECTS]

    if len(ids) < 2:
        return {"error": "Need at least 2 distinct project_ids to compare."}, None

    docs = {d["project_id"]: d for d in db.projects().find({"project_id": {"$in": ids}}, {"_id": 0})}

    projects = []
    missing = []
    for pid in ids:
        doc = docs.get(pid)
        if doc is None:
            missing.append(pid)
            continue
        projects.append(
            {
                "project_id": doc["project_id"],
                "title": doc.get("title", ""),
                "domain": doc.get("domain", ""),
                "difficulty": doc.get("difficulty", ""),
                "duration_weeks": doc.get("duration_weeks"),
                "technologies": doc.get("technologies", []),
                "skills": doc.get("skills", []),
                "description": doc.get("description", ""),
                "uniqueness_percent": _uniqueness_percent(pid),
            }
        )

    for_model = {"projects": projects, "missing_ids": missing}
    block = {"type": "comparison", "projects": projects} if len(projects) >= 2 else None
    return for_model, block


def check_skill_gap(project_id: str, known_skills: list[str]) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    try:
        result = recommend.skill_gap(project_id, [s for s in (known_skills or []) if isinstance(s, str)])
    except KeyError:
        return {"error": f"No project with id '{project_id}'."}, None
    return result, {"type": "skill_gap", **result}


def match_resume_projects(
    known_skills: list[str], top_k: Optional[int] = None
) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    """Résumé-aware project ranking — wraps recommend.personalized_recommend()
    exactly the way search_projects' own personalized branch does (same
    _recommendation_card shape: matching_factors, skill gap, estimated
    weeks, recommendation_reason), so this is not a second ranking
    algorithm, just a second caller of the multi-factor engine /api/recommend
    and /api/resume-suggest both already use. `known_skills` here is the
    conversation's résumé skills (see the '[Context — résumé skills already
    on file...]' note in nlp/ai_assistant.py), copied through by the model
    rather than re-derived.
    """
    skills = [s for s in (known_skills or []) if isinstance(s, str) and s.strip()]
    if not skills:
        return {
            "error": (
                "No résumé skills on file for this conversation — the student needs to "
                "upload their résumé on the Résumé Match page first."
            )
        }, None

    try:
        k = int(top_k) if top_k is not None else DEFAULT_SEARCH_RESULTS
    except (TypeError, ValueError):
        k = DEFAULT_SEARCH_RESULTS
    k = max(1, min(k, MAX_SEARCH_RESULTS))

    recs = recommend.personalized_recommend(known_skills=skills, top_k=k)
    if not recs:
        return {"count": 0, "projects": [], "note": "No matching projects found for these skills."}, None

    cards = [_recommendation_card(r) for r in recs]
    for_model = {
        "count": len(cards),
        "projects": [{key: value for key, value in c.items() if key != "description"} for c in cards],
    }
    block = {"type": "project_recommendations", "projects": cards}
    return for_model, block


def predict_timeline(
    project_id: str, team_size: Optional[int] = None, experience_level: Optional[str] = None
) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    doc = _lookup(project_id)
    if doc is None:
        return {"error": f"No project with id '{project_id}'."}, None
    try:
        size = int(team_size) if team_size is not None else 1
    except (TypeError, ValueError):
        size = 1
    size = max(1, min(size, 20))
    level = experience_level if experience_level in DIFFICULTIES else None
    result = timeline.predict(doc, team_size=size, experience_level=level)
    return result, {"type": "timeline", **result}


def get_learning_path(skills: list[str]) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    """Resource bundles for a skill list, in a sensible learn-this-first
    order (nlp/learning_path.py:sequenced_learning_path) rather than
    whatever order the caller/model happened to list them in — each bundle
    also carries `reason`, so the model can explain the ordering instead of
    inventing its own justification."""
    clean = [s for s in (skills or []) if isinstance(s, str) and s.strip()][:20]
    if not clean:
        return {"error": "No skills given."}, None
    result = learning_path.sequenced_learning_path(clean)
    return {"skills": result}, {"type": "learning_path", "skills": result}


def select_project(project_id: str) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    doc = _lookup(project_id)
    if doc is None:
        return {"error": f"No project with id '{project_id}'."}, None
    project = {
        "project_id": doc["project_id"],
        "title": doc.get("title", ""),
        "domain": doc.get("domain", ""),
        "difficulty": doc.get("difficulty", ""),
        "duration_weeks": doc.get("duration_weeks"),
        "technologies": doc.get("technologies", []),
    }
    return project, {"type": "project_selected", "project": project}


def select_idea(
    id: Optional[str],
    name: str,
    problem: str = "",
    solution: str = "",
    unique_point: str = "",
    technologies: Optional[list[str]] = None,
    domain: Optional[str] = None,
    difficulty: Optional[str] = None,
    duration_weeks: Optional[int] = None,
) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    """The idea-context mirror of select_project — no DB lookup, since a
    generated idea has no catalogue record; the model supplies its current
    fields from the shown-ideas context, same as refine_project_idea does."""
    name = (name or "").strip()
    if not name:
        return {"error": "No idea name given."}, None
    try:
        weeks = int(duration_weeks) if duration_weeks is not None else None
    except (TypeError, ValueError):
        weeks = None
    idea = {
        "id": (id or "idea-1"),
        "name": name,
        "problem": (problem or "").strip(),
        "solution": (solution or "").strip(),
        "unique_point": (unique_point or "").strip(),
        "technologies": [t.strip() for t in (technologies or []) if isinstance(t, str) and t.strip()][:6],
        "domain": domain if domain in DOMAINS else "",
        "difficulty": difficulty if difficulty in DIFFICULTIES else "",
        "duration_weeks": weeks,
    }
    return idea, {"type": "idea_selected", "idea": idea}


def recommend_decision(
    project_ids: list[str],
    known_skills: Optional[list[str]] = None,
    team_size: Optional[int] = None,
    experience_level: Optional[str] = None,
    prefers_unique: bool = False,
    target_weeks: Optional[int] = None,
) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    """The Decision Engine: orchestrates existing signals into one ranked,
    explained decision — no new engine. skill_gap() and timeline.predict()
    are the same functions check_skill_gap/predict_timeline already wrap;
    uniqueness reuses _uniqueness_percent() above (recommend.similar(), the
    exact function /api/similar/<id> already exposes) rather than duplicating
    check_uniqueness's own idea-vs-catalogue logic, which answers a different
    question (a NEW idea's originality, not an existing catalogue project's
    own standing among its neighbours).

    Four factors, matching the product's own Skill Fit / Timeline Fit /
    Difficulty Fit / Uniqueness vocabulary:
      - skill_fit: skill_gap()'s readiness_percent, or None when no
        known_skills were given — never guessed.
      - timeline_fit: against `target_weeks` (the student's own deadline,
        e.g. "finish in 3 months" -> 12) when given, otherwise against this
        project's own baseline duration_weeks as a sanity check. Always
        available — every catalogue project has a duration_weeks.
      - difficulty_fit: _difficulty_fit() above, or None when no
        experience_level was given.
      - uniqueness_percent: always available (a property of the catalogue
        itself, not the student).

    Combined by a plain, readable weighted average (SKILL_FIT_WEIGHT etc.,
    defined once near the top of this module) — arithmetic, not a trained
    model, and a factor that is None/unavailable is excluded from the
    average rather than defaulting to a guessed midpoint. Every number in
    the result traces back to one of the existing functions named above.
    """
    ids: list[str] = []
    seen: set[str] = set()
    for raw in project_ids or []:
        pid = (raw or "").strip()
        if pid and pid not in seen:
            seen.add(pid)
            ids.append(pid)
    ids = ids[:MAX_COMPARE_PROJECTS]
    if not ids:
        return {"error": "Need at least 1 project_id to evaluate."}, None

    docs = {d["project_id"]: d for d in db.projects().find({"project_id": {"$in": ids}}, {"_id": 0})}
    ids = [pid for pid in ids if pid in docs]
    if not ids:
        return {"error": "None of the given project_ids exist."}, None

    skills = [s for s in (known_skills or []) if isinstance(s, str) and s.strip()]
    try:
        size = max(1, min(int(team_size), 20)) if team_size is not None else 1
    except (TypeError, ValueError):
        size = 1
    level = experience_level if experience_level in DIFFICULTIES else None
    try:
        target = max(1, min(int(target_weeks), 104)) if target_weeks is not None else None
    except (TypeError, ValueError):
        target = None

    candidates: list[dict[str, Any]] = []
    for pid in ids:
        doc = docs[pid]
        gap = recommend.skill_gap(pid, skills) if skills else None
        estimate = timeline.predict(doc, team_size=size, experience_level=level)
        uniqueness_percent = _uniqueness_percent(pid)
        difficulty_fit, difficulty_note = _difficulty_fit(doc.get("difficulty", ""), level)

        if target is not None:
            # Against the student's own stated deadline — answers "can I
            # finish this in N weeks/months?" directly, across candidates.
            if estimate["predicted_weeks"] <= target:
                timeline_fit = 100.0
            else:
                overrun = estimate["predicted_weeks"] - target
                timeline_fit = max(0.0, 100 - (overrun / target) * 100)
        else:
            # No deadline given — sanity-check the personalised estimate
            # against this project's own stated baseline duration instead.
            baseline = doc.get("duration_weeks") or estimate["predicted_weeks"]
            timeline_fit = max(0.0, 100 - abs(estimate["predicted_weeks"] - baseline) * 8)

        skill_fit = gap["readiness_percent"] if gap is not None else None

        strengths: list[str] = []
        risks: list[str] = []
        people_word = "person" if size == 1 else "people"

        if gap is not None:
            if gap["skills_you_have"]:
                strengths.append(f"{', '.join(gap['skills_you_have'][:3])} match your skills")
            if gap["skills_to_learn"]:
                risks.append(f"You'll need to learn {', '.join(gap['skills_to_learn'][:3])}")

        if timeline_fit >= 60:
            if target is not None:
                strengths.append(f"Fits your {target}-week timeline (~{estimate['predicted_weeks']:g} weeks estimated)")
            else:
                strengths.append(f"Suitable for {size} {people_word} in about {estimate['predicted_weeks']:g} weeks")
        else:
            if target is not None:
                risks.append(f"Won't comfortably fit your {target}-week timeline — estimated {estimate['predicted_weeks']:g} weeks")
            else:
                risks.append(f"Tight for {size} {people_word} — estimated {estimate['predicted_weeks']:g} weeks")

        if uniqueness_percent >= 60:
            strengths.append("Good uniqueness among the catalogue")
        elif uniqueness_percent < 35:
            risks.append("Very similar to other catalogue projects")

        if difficulty_fit is not None:
            (strengths if difficulty_fit >= 75 else risks).append(difficulty_note)
        elif doc.get("difficulty") == "Advanced":
            # No experience_level to judge against — fall back to the one
            # static fact we do know, same as before this signal existed.
            risks.append("Higher complexity")

        # Transparent weighted average — weights defined once, near the top
        # of this module, never invented per-call. Skill fit and difficulty
        # fit only count when their input was actually given.
        fit_total = 0.0
        weight_total = 0.0
        if skill_fit is not None:
            fit_total += skill_fit * SKILL_FIT_WEIGHT
            weight_total += SKILL_FIT_WEIGHT
        if difficulty_fit is not None:
            fit_total += difficulty_fit * DIFFICULTY_FIT_WEIGHT
            weight_total += DIFFICULTY_FIT_WEIGHT
        uniqueness_weight = UNIQUENESS_WEIGHT_PREFERRED if prefers_unique else UNIQUENESS_WEIGHT_DEFAULT
        fit_total += uniqueness_percent * uniqueness_weight
        weight_total += uniqueness_weight
        fit_total += timeline_fit * TIMELINE_FIT_WEIGHT
        weight_total += TIMELINE_FIT_WEIGHT
        overall_fit = round(fit_total / weight_total) if weight_total else 50

        candidates.append(
            {
                "project_id": pid,
                "title": doc.get("title", ""),
                "domain": doc.get("domain", ""),
                "difficulty": doc.get("difficulty", ""),
                "duration_weeks": doc.get("duration_weeks"),
                "technologies": doc.get("technologies", []),
                "overall_fit": overall_fit,
                "skill_fit": skill_fit,
                "timeline_fit": round(timeline_fit),
                "difficulty_fit": difficulty_fit,
                "target_weeks": target,
                "skills_you_have": gap["skills_you_have"] if gap else [],
                "skills_to_learn": gap["skills_to_learn"] if gap else [],
                "estimated_weeks": estimate["predicted_weeks"],
                "team_size": size,
                "uniqueness_percent": uniqueness_percent,
                "strengths": strengths,
                "risks": risks,
            }
        )

    candidates.sort(key=lambda c: c["overall_fit"], reverse=True)
    recommended = candidates[0]
    alternative = candidates[1] if len(candidates) > 1 else None

    for_model = {
        "candidates": candidates,
        "recommended_project_id": recommended["project_id"],
        "weights": {
            "skill_fit": SKILL_FIT_WEIGHT,
            "timeline_fit": TIMELINE_FIT_WEIGHT,
            "difficulty_fit": DIFFICULTY_FIT_WEIGHT,
            "uniqueness": UNIQUENESS_WEIGHT_PREFERRED if prefers_unique else UNIQUENESS_WEIGHT_DEFAULT,
        },
    }
    block = {
        "type": "decision",
        "recommended": recommended,
        "alternative": alternative,
        "candidates": candidates,
    }
    return for_model, block


def check_project_uniqueness(idea: str) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    """Wraps recommend.check_uniqueness() — same embedding index, same
    similarity engine /api/uniqueness already uses, just reachable from chat."""
    idea = (idea or "").strip()
    if not idea:
        return {"error": "No idea text given."}, None
    result = recommend.check_uniqueness(idea, "")
    block = {
        "type": "uniqueness",
        "is_unique": result["is_unique"],
        "originality_score": result["originality_score"],
        "similar_projects": result["similar_projects"],
        "overlapping_concepts": result["overlapping_concepts"],
        "suggestions": result["suggestions"],
    }
    return result, block


def generate_project_ideas(
    topic: str = "",
    domain: Optional[str] = None,
    difficulty: Optional[str] = None,
    count: Optional[int] = None,
) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    """Wraps nlp/ideation.py:generate_ideas — see there for the generate-then-
    validate pipeline. `block` uses the ideas' full fields (the model has no
    other way to remember them for a later refine/roadmap follow-up, since
    generated ideas are never written to Mongo)."""
    ideas = ideation.generate_ideas(topic=topic, domain=domain, difficulty=difficulty, count=count)
    if not ideas:
        return {"error": "Could not generate ideas right now — try again."}, None
    for_model = {
        "ideas": [
            {
                "id": i["id"],
                "name": i["name"],
                "unique_point": i["unique_point"],
                "domain": i["domain"],
                "difficulty": i["difficulty"],
                "duration_weeks": i["duration_weeks"],
                "originality_score": i["originality_score"],
                "closest_existing_project": i["similar_projects"][0]["title"] if i["similar_projects"] else None,
            }
            for i in ideas
        ]
    }
    block = {"type": "generated_project_ideas", "ideas": ideas}
    return for_model, block


def refine_project_idea(
    id: Optional[str],
    name: str,
    instruction: str,
    problem: str = "",
    solution: str = "",
    unique_point: str = "",
    technologies: Optional[list[str]] = None,
    domain: Optional[str] = None,
    difficulty: Optional[str] = None,
    duration_weeks: Optional[int] = None,
) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    instruction = (instruction or "").strip()
    if not instruction:
        return {"error": "No instruction given for what to change."}, None
    current = {
        "id": id,
        "name": name,
        "problem": problem,
        "solution": solution,
        "unique_point": unique_point,
        "technologies": technologies or [],
        "domain": domain,
        "difficulty": difficulty,
        "duration_weeks": duration_weeks,
    }
    refined = ideation.refine_idea(current, instruction)
    block = {"type": "generated_project_ideas", "ideas": [refined]}
    return refined, block


def _idea_weeks(duration_weeks: Optional[int]) -> int:
    try:
        return max(1, min(int(duration_weeks), 24)) if duration_weeks is not None else 8
    except (TypeError, ValueError):
        return 8


def _idea_doc(
    name: str,
    domain: Optional[str] = None,
    duration_weeks: Optional[int] = None,
    difficulty: Optional[str] = None,
    technologies: Optional[list[str]] = None,
) -> dict[str, Any]:
    """A synthetic project-shaped doc from a GENERATED idea's own fields, fed
    to the exact same generator/timeline functions a catalogue project's
    project_id would resolve to via Mongo — a generated idea just has no
    project_id to look up, so this stands in for the lookup. Shared by every
    generate_idea_* tool below so they all build the doc the same way."""
    return {
        "project_id": None,
        "title": name,
        "domain": domain if domain in DOMAINS else "",
        "difficulty": difficulty if difficulty in DIFFICULTIES else "",
        "duration_weeks": _idea_weeks(duration_weeks),
        "technologies": [t.strip() for t in (technologies or []) if isinstance(t, str) and t.strip()],
        "skills": [],
    }


def generate_idea_roadmap(
    name: str,
    domain: Optional[str] = None,
    duration_weeks: Optional[int] = None,
    technologies: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Same generator.roadmap_for() every catalogue project's roadmap uses
    (see generate_roadmap above), just fed a synthetic doc built from the
    idea's own fields instead of a Mongo lookup — a generated idea has no
    project_id to look up. Passing technologies grounds the phase tasks the
    same way a catalogue project's own technologies would."""
    doc = _idea_doc(name, domain=domain, duration_weeks=duration_weeks, technologies=technologies)
    return generator.roadmap_for(doc)


def generate_idea_timeline(
    name: str,
    domain: Optional[str] = None,
    difficulty: Optional[str] = None,
    duration_weeks: Optional[int] = None,
    team_size: Optional[int] = None,
    experience_level: Optional[str] = None,
) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    """Same nlp/timeline.py:predict() every catalogue project's timeline uses
    (see predict_timeline above), fed a synthetic idea doc — the idea-context
    mirror of generate_idea_roadmap, for "how long will this take" instead of
    "what are the phases"."""
    doc = _idea_doc(name, domain=domain, duration_weeks=duration_weeks, difficulty=difficulty)
    try:
        size = int(team_size) if team_size is not None else 1
    except (TypeError, ValueError):
        size = 1
    size = max(1, min(size, 20))
    level = experience_level if experience_level in DIFFICULTIES else None
    result = timeline.predict(doc, team_size=size, experience_level=level)
    return result, {"type": "timeline", **result}


def generate_idea_milestones(
    name: str, domain: Optional[str] = None, duration_weeks: Optional[int] = None
) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    """Same generator.milestones_for() a catalogue project's milestones use
    (see generate_milestones above), fed a synthetic idea doc."""
    doc = _idea_doc(name, domain=domain, duration_weeks=duration_weeks)
    result = generator.milestones_for(doc)
    return result, {"type": "milestones", **result}


def call_tool(name: str, arguments: dict[str, Any]) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    """Dispatch one model-requested tool call. Always returns (result, block) —
    `result` is what's fed back to the model; `block` (or None) is what the
    caller (nlp/ai_assistant.py:general_reply) surfaces to the frontend as
    structured, persisted UI alongside the model's own text."""
    if name == "search_projects":
        return search_projects(
            query=str(arguments.get("query", "")),
            difficulty=arguments.get("difficulty"),
            domain=arguments.get("domain"),
            max_duration_weeks=arguments.get("max_duration_weeks"),
            top_k=arguments.get("top_k"),
            known_skills=list(arguments.get("known_skills") or []),
            team_size=arguments.get("team_size"),
            experience_level=arguments.get("experience_level"),
        )
    if name == "find_similar_projects":
        return find_similar_projects(
            project_id=str(arguments.get("project_id", "")),
            top_k=arguments.get("top_k"),
        )
    if name == "get_project_details":
        return get_project_details(project_id=str(arguments.get("project_id", ""))), None
    if name == "generate_roadmap":
        return generate_roadmap(project_id=str(arguments.get("project_id", ""))), None
    if name == "generate_synopsis":
        return generate_synopsis(project_id=str(arguments.get("project_id", ""))), None
    if name == "generate_milestones":
        return generate_milestones(project_id=str(arguments.get("project_id", "")))
    if name == "compare_projects":
        return compare_projects(project_ids=list(arguments.get("project_ids") or []))
    if name == "check_skill_gap":
        return check_skill_gap(
            project_id=str(arguments.get("project_id", "")),
            known_skills=list(arguments.get("known_skills") or []),
        )
    if name == "match_resume_projects":
        return match_resume_projects(
            known_skills=list(arguments.get("known_skills") or []),
            top_k=arguments.get("top_k"),
        )
    if name == "predict_timeline":
        return predict_timeline(
            project_id=str(arguments.get("project_id", "")),
            team_size=arguments.get("team_size"),
            experience_level=arguments.get("experience_level"),
        )
    if name == "get_learning_path":
        return get_learning_path(skills=list(arguments.get("skills") or []))
    if name == "select_project":
        return select_project(project_id=str(arguments.get("project_id", "")))
    if name == "select_idea":
        return select_idea(
            id=arguments.get("id"),
            name=str(arguments.get("name", "")),
            problem=str(arguments.get("problem", "")),
            solution=str(arguments.get("solution", "")),
            unique_point=str(arguments.get("unique_point", "")),
            technologies=list(arguments.get("technologies") or []),
            domain=arguments.get("domain"),
            difficulty=arguments.get("difficulty"),
            duration_weeks=arguments.get("duration_weeks"),
        )
    if name == "check_project_uniqueness":
        return check_project_uniqueness(idea=str(arguments.get("idea", "")))
    if name == "recommend_decision":
        return recommend_decision(
            project_ids=list(arguments.get("project_ids") or []),
            known_skills=list(arguments.get("known_skills") or []),
            team_size=arguments.get("team_size"),
            experience_level=arguments.get("experience_level"),
            prefers_unique=bool(arguments.get("prefers_unique", False)),
            target_weeks=arguments.get("target_weeks"),
        )
    if name == "generate_project_ideas":
        return generate_project_ideas(
            topic=str(arguments.get("topic", "")),
            domain=arguments.get("domain"),
            difficulty=arguments.get("difficulty"),
            count=arguments.get("count"),
        )
    if name == "refine_project_idea":
        return refine_project_idea(
            id=arguments.get("id"),
            name=str(arguments.get("name", "")),
            instruction=str(arguments.get("instruction", "")),
            problem=str(arguments.get("problem", "")),
            solution=str(arguments.get("solution", "")),
            unique_point=str(arguments.get("unique_point", "")),
            technologies=list(arguments.get("technologies") or []),
            domain=arguments.get("domain"),
            difficulty=arguments.get("difficulty"),
            duration_weeks=arguments.get("duration_weeks"),
        )
    if name == "generate_idea_roadmap":
        return generate_idea_roadmap(
            name=str(arguments.get("name", "")),
            domain=arguments.get("domain"),
            duration_weeks=arguments.get("duration_weeks"),
            technologies=list(arguments.get("technologies") or []),
        ), None
    if name == "generate_idea_timeline":
        return generate_idea_timeline(
            name=str(arguments.get("name", "")),
            domain=arguments.get("domain"),
            difficulty=arguments.get("difficulty"),
            duration_weeks=arguments.get("duration_weeks"),
            team_size=arguments.get("team_size"),
            experience_level=arguments.get("experience_level"),
        )
    if name == "generate_idea_milestones":
        return generate_idea_milestones(
            name=str(arguments.get("name", "")),
            domain=arguments.get("domain"),
            duration_weeks=arguments.get("duration_weeks"),
        )
    return {"error": f"Unknown tool '{name}'."}, None
