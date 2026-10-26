"""Identity-bound, READ-ONLY tools for the signed-in student's assistant.

These are the only tools that touch the student's own saved data (profile, skill
gap, roadmap progress, teams). Each one wraps an existing service rather than
re-deriving anything - Features 2-6:

* recommend_for_me      -> nlp/recommend.personalized_recommend (+ profile context)
* get_my_skill_gap      -> nlp/personal_skill_gap.analyse
* get_my_roadmap        -> roadmaps/service.roadmap_with_progress (real saved statuses)
* get_my_team_roles     -> teams/service.team_roles
* suggest_team          -> teams/service.team_formation
* get_my_progress       -> profiles/insights.build_insights (profile vs recorded roadmap progress)
* list_my_teams, get_my_profile

Identity and authorisation:

* The user comes from the server-side session (routes/assistant.py) and is passed
  in by the caller. NO tool schema has a user, email or account parameter, and an
  argument that is not in a tool's schema is rejected, so the model - and any text
  it was shown - cannot name another account.
* Teammate data is reached ONLY through teams/service.py, which re-checks team
  membership and every teammate's `share_with_teams` consent on each call. Nothing
  here caches consent or reads another person's profile directly.
* Nothing here writes. There is no tool to edit a profile, invite, change a role
  decision, change roadmap progress or reset anything, so the assistant cannot
  claim to have done those things through a tool.

Results are trimmed to what an answer needs; free-text profile fields (education,
experience descriptions) are never included.
"""

from __future__ import annotations

from typing import Any, Optional

from nlp import personal_skill_gap, recommend
from profiles import insights as insights_service, personalization, service as profile_service
from roadmaps import service as roadmap_service
from teams import service as team_service

MAX_ITEMS = 15
MAX_ID_CHARS = 64
MAX_QUERY_CHARS = 500
MAX_CANDIDATES = 12
MAX_RECOMMENDATIONS = 6

PROVENANCE = "Retrieved from this student's own ProjectMind AI data. Report it as such."
WITHHELD_NOTE = (
    "Information a teammate has not shared (or has not added) is unavailable for matching. "
    "It is not evidence that they lack a skill, and must never be guessed."
)

_STR = {"type": "string"}


def _tool(name: str, description: str, properties: dict[str, Any], required: Optional[list[str]] = None) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False},
        },
    }


PERSONAL_TOOL_SCHEMAS: list[dict[str, Any]] = [
    _tool(
        "get_my_profile",
        "The signed-in student's OWN saved profile summary: skills with self-reported levels, interests, preferred roles, "
        "goals, time available and completion. Use when you need to know what they have told ProjectMind about themselves. "
        "Never guess their skills; if the profile is empty, say so.",
        {},
    ),
    _tool(
        "recommend_for_me",
        "Recommend EXISTING catalogue projects using the student's saved profile (skills, interests, time limits) on top of "
        "an optional query. Use for 'what should I build', 'projects that fit me'. Results carry why each matches and which "
        "skills they have or still need.",
        {
            "query": {**_STR, "description": "Optional topic, e.g. 'computer vision'."},
            "max_duration_weeks": {"type": ["integer", "null"], "description": "Optional hard deadline in weeks."},
            "top_k": {"type": ["integer", "null"], "description": f"How many projects (1-{MAX_RECOMMENDATIONS})."},
        },
    ),
    _tool(
        "get_my_skill_gap",
        "The student's personal skill-gap for ONE catalogue project, from their saved profile: which required skills they "
        "have, which need improvement, which are not on their profile, priorities and next steps. Use for 'am I ready for X', "
        "'what am I missing'. Needs a catalogue project_id.",
        {"project_id": {**_STR, "description": "A catalogue project id such as 'pm-123'."}},
        ["project_id"],
    ),
    _tool(
        "get_my_roadmap",
        "The student's personalised learning roadmap for ONE catalogue project with their REAL saved step progress "
        "(not started / in progress / completed). Use for 'what should I learn next', 'how far along am I'. Report statuses "
        "exactly as returned; never infer completion.",
        {"project_id": {**_STR, "description": "A catalogue project id such as 'pm-123'."}},
        ["project_id"],
    ),
    _tool(
        "get_my_progress",
        "The student's current learning progress across ALL their saved roadmaps: roadmap steps they recorded as in progress or "
        "completed, which skills those relate to, how that sits next to the levels they declared on their profile, and suggested "
        "next steps. Use for 'what have I learned', 'how am I progressing', 'what should I work on next'. Declared levels are "
        "self-reported; recorded progress is only what the student marked. No history is kept.",
        {},
    ),
    _tool(
        "list_my_teams",
        "The teams the student belongs to (id, name, project). Use to find a team_id before get_my_team_roles or suggest_team.",
        {},
    ),
    _tool(
        "get_my_team_roles",
        "Role suggestions and team role coverage for a team the student belongs to, honouring each teammate's profile-sharing "
        "choice. Use for 'who should do what on my team', 'what role suits me'. Needs a team_id from list_my_teams.",
        {"team_id": {**_STR, "description": "A team id from list_my_teams."}},
        ["team_id"],
    ),
    _tool(
        "suggest_team",
        "Recommend balanced team combinations for a catalogue project from an AUTHORISED pool only: the student, optionally the "
        "roster of one of their teams, and people THE STUDENT TYPED in this conversation (name + skills). Read-only: it never "
        "invites or adds anyone.",
        {
            "project_id": {**_STR, "description": "A catalogue project id."},
            "team_id": {"type": ["string", "null"], "description": "Optional: one of the student's teams, to include its roster."},
            "team_size": {"type": ["integer", "null"], "description": "Optional, 1-8."},
            "candidates": {
                "type": ["array", "null"],
                "description": "Optional people the student described in this conversation.",
                "items": {
                    "type": "object",
                    "properties": {"name": _STR, "skills": {"type": "array", "items": _STR}},
                    "required": ["name"],
                    "additionalProperties": False,
                },
            },
        },
        ["project_id"],
    ),
]

PERSONAL_TOOL_NAMES = frozenset(t["function"]["name"] for t in PERSONAL_TOOL_SCHEMAS)
_ALLOWED = {t["function"]["name"]: set(t["function"]["parameters"]["properties"]) for t in PERSONAL_TOOL_SCHEMAS}
_REQUIRED = {t["function"]["name"]: set(t["function"]["parameters"]["required"]) for t in PERSONAL_TOOL_SCHEMAS}


class ToolArgumentError(ValueError):
    pass


def is_personal_tool(name: str) -> bool:
    return name in PERSONAL_TOOL_NAMES


# --- argument validation ---------------------------------------------------------------------------


def _clean_args(name: str, arguments: Any) -> dict[str, Any]:
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ToolArgumentError("Arguments must be an object.")
    unknown = set(arguments) - _ALLOWED[name]
    if unknown:
        # Includes any attempt to pass user_id / email / account: not in the schema, so refused.
        raise ToolArgumentError(f"Unexpected argument(s): {', '.join(sorted(str(k)[:30] for k in unknown))}.")
    missing = {k for k in _REQUIRED[name] if arguments.get(k) in (None, "")}
    if missing:
        raise ToolArgumentError(f"Missing argument(s): {', '.join(sorted(missing))}.")
    return arguments


def _id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > MAX_ID_CHARS:
        raise ToolArgumentError(f"'{label}' must be a short id string.")
    return value.strip()


def _int(value: Any, label: str, lo: int, hi: int) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ToolArgumentError(f"'{label}' must be a whole number from {lo} to {hi}.")
    return value


def _project(project_id: Any) -> dict[str, Any]:
    pid = _id(project_id, "project_id")
    doc = recommend.get_retriever().documents.get(pid)
    if doc is None:
        raise LookupError(f"No catalogue project with id '{pid}'.")
    return doc


def _candidates(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_CANDIDATES:
        raise ToolArgumentError(f"'candidates' must be a list of at most {MAX_CANDIDATES} people.")
    out = []
    for entry in raw:
        if not isinstance(entry, dict) or set(entry) - {"name", "skills"}:
            raise ToolArgumentError("Each candidate needs only a 'name' and a 'skills' list.")
        name, skills = entry.get("name"), entry.get("skills", [])
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 60:
            raise ToolArgumentError("Each candidate needs a name of 60 characters or fewer.")
        if not isinstance(skills, list) or len(skills) > 30 or not all(isinstance(s, str) and len(s) <= 60 for s in skills):
            raise ToolArgumentError("Candidate 'skills' must be a list of at most 30 short strings.")
        out.append({"name": name.strip(), "skills": [s.strip() for s in skills if s.strip()]})
    return out


# --- grounding block -------------------------------------------------------------------------------------------


def _grounding(kind: str, label: str, follow_ups: list[str]) -> dict[str, Any]:
    return {"type": "grounding", "sources": [{"kind": kind, "label": label}], "follow_ups": follow_ups}


# --- tools ---------------------------------------------------------------------------------------------------------


def get_my_profile(user: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    profile = profile_service.get_profile(user["user_id"])
    status = profile["completion"]
    techs = []
    for entry in profile["experience"]:
        for tech in entry.get("technologies", []):
            if tech not in techs:
                techs.append(tech)
    result = {
        "provenance": PROVENANCE,
        "profile_status": status["status"],
        "completion_percent": status["percent"],
        "skills": [{"name": s["name"], "level": s["level"], "self_reported": True} for s in profile["skills"]][:MAX_ITEMS * 3],
        "past_project_technologies": techs[:MAX_ITEMS],
        "interests": profile["interests"],
        "preferred_roles": profile["preferred_roles"],
        "learning_goals": profile["learning_goals"][:5],
        "career_interests": profile["career_interests"][:5],
        "availability": profile["availability"],
        "shares_role_relevant_skills_with_teammates": profile["share_with_teams"],
    }
    if status["status"] == "not_started":
        result["note"] = "The student has not added any profile information yet. Do not assume any skills."
    return result, _grounding("profile", "Your saved profile", ["Which projects fit my skills?"])


def recommend_for_me(user: dict[str, Any], args: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    query = args.get("query") or ""
    if not isinstance(query, str) or len(query) > MAX_QUERY_CHARS:
        raise ToolArgumentError(f"'query' must be text of at most {MAX_QUERY_CHARS} characters.")
    weeks = _int(args.get("max_duration_weeks"), "max_duration_weeks", 1, 52)
    k = _int(args.get("top_k"), "top_k", 1, MAX_RECOMMENDATIONS) or 5
    context = personalization.build_context(profile_service.get_profile(user["user_id"]))
    usable = bool(context["usable"])
    if not usable and not query.strip():
        return {
            "provenance": PROVENANCE, "count": 0, "projects": [], "profile_used": False,
            "note": "The saved profile has nothing usable yet and no topic was given. Ask what they are interested in, or suggest adding skills to their profile.",
        }, []
    from nlp import chat_tools  # local: chat_tools imports this module's schemas

    recs = recommend.personalized_recommend(
        query=query.strip(), max_duration_weeks=weeks, top_k=k, profile_context=context if usable else None
    )
    cards = [chat_tools._recommendation_card(r) for r in recs]
    result = {
        "provenance": PROVENANCE, "count": len(cards), "profile_used": usable,
        "projects": [{k_: v for k_, v in c.items() if k_ != "description"} for c in cards],
    }
    if not cards:
        result["note"] = "No catalogue project matched. Say so plainly and suggest relaxing the deadline or changing the topic."
    sources = _grounding("projects", "Catalogue projects ranked with your profile" if usable else "Catalogue search", ["What would I need to learn for the top match?"])
    if usable:
        sources["sources"].insert(0, {"kind": "profile", "label": "Your saved profile"})
    blocks = ([{"type": "project_recommendations", "projects": cards}] if cards else []) + [sources]
    return result, blocks


def get_my_skill_gap(user: dict[str, Any], args: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    doc = _project(args["project_id"])
    analysis = personal_skill_gap.analyse(doc, profile_service.get_profile(user["user_id"]))
    items = [
        {
            "skill": i["skill"], "kind": i["kind"], "classification": i["classification"], "needed_level": i["target_level"],
            "evidence": i["evidence"], "priority": i["priority"], "why_it_matters": i["why_it_matters"],
            "next_step": i["next_step"], "prerequisites": i["prerequisites"],
        }
        for i in analysis["items"][:MAX_ITEMS]
    ]
    result = {
        "provenance": PROVENANCE, "project": analysis["project"], "profile": analysis["profile"],
        "summary": analysis["summary"], "requirements": analysis["requirements"], "items": items,
        "notes": analysis["notes"], "ranking": analysis["ranking"],
        "how_to_read": "'missing' means not recorded on the profile, not that the student lacks the skill. Levels are self-reported.",
    }
    return result, _grounding("skill_gap", f"Your skill gap for “{doc.get('title', 'this project')}”", ["Show my learning roadmap for this project."])


def get_my_roadmap(user: dict[str, Any], args: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    doc = _project(args["project_id"])
    road = roadmap_service.roadmap_with_progress(doc, profile_service.get_profile(user["user_id"]), user["user_id"])
    steps = [
        {
            "number": s["number"], "skill": s["skill"], "kind": s["kind"], "classification": s["classification"],
            "why_for_you": s["why_for_you"], "practice_task": s["practice_task"],
            "completion_criterion": s["completion_criterion"], "prerequisites": s["prerequisites"], "status": s["status"],
        }
        for s in road["steps"][:MAX_ITEMS]
    ]
    result = {
        "provenance": PROVENANCE, "project": road["project"], "profile": road["profile"], "steps": steps,
        "progress": road["progress"], "retired_steps": road["retired_steps"][:MAX_ITEMS],
        "already_covered": road["overview"]["already_covered"][:MAX_ITEMS], "notes": road["notes"],
        "ordering_note": road["ordering"]["note"],
        "how_to_read": "Statuses are what the student recorded. A step is completed only if status says so.",
    }
    return result, _grounding("roadmap", f"Your roadmap and saved progress for “{doc.get('title', 'this project')}”", ["What should I do first?", "Which step should I tackle next?"])


def get_my_progress(user: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    data = insights_service.build_insights(user["user_id"])
    learning = data["learning"]
    result = {
        "provenance": PROVENANCE,
        "profile": data["profile"],
        "declared_skills_self_reported": data["profile_skills"][:MAX_ITEMS * 2],
        "recorded_learning_progress": {
            "started": learning["started"],
            "totals": learning["totals"],
            "projects": learning["projects"][:MAX_ITEMS],
            "skills_worked_on": learning["skills_worked_on"][:MAX_ITEMS],
            "recent_activity": learning["recent_activity"][:5],
        },
        "profile_review": data["profile_review"][:5],
        "suggested_next_steps": data["next_steps"]["items"][:5],
        "history_available": False,
        "how_to_read": (
            "Declared levels are the student's own claims and are never changed by recorded progress. A step counts as completed only "
            "if its recorded status says so; suggested next steps are NOT done. " + data["history"]["note"]
        ),
    }
    if not learning["started"]:
        result["note"] = "The student has not recorded any roadmap progress yet. Do not describe any skill as learned or improved."
    return result, _grounding("progress", "Your saved profile and roadmap progress", ["What should I work on next?"])


def list_my_teams(user: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    teams = team_service.list_my_teams(user["user_id"])
    rows = [
        {
            "team_id": t["team_id"], "name": t["name"], "project_id": t.get("project_id"),
            "project_title": t.get("project_title"), "members": len(t["members"]),
            "your_role_in_team": "owner" if t.get("owner_user_id") == user["user_id"] else "member",
        }
        for t in teams[:MAX_ITEMS]
    ]
    result = {"provenance": PROVENANCE, "count": len(rows), "teams": rows}
    if not rows:
        result["note"] = "The student is not on any team yet."
    return result, _grounding("teams", "Your teams", ["Who should do what on my team?"])


def get_my_team_roles(user: dict[str, Any], args: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    team_id = _id(args["team_id"], "team_id")
    data = team_service.team_roles(team_id, user["user_id"])  # membership + teammate consent re-checked inside
    fit = data["role_fit"]
    members = []
    for m in fit["members"][:MAX_ITEMS]:
        top = m["suggested"]
        members.append({
            "name": m["name"], "source": m["source"], "info_unavailable": bool(m.get("info_unavailable")), "message": m["message"],
            "suggested": None if not top else {
                "role": top["role"], "confidence": top["confidence"], "score_0_to_100_heuristic": top["score"],
                "supporting_skills": top["supporting_skills"], "missing_skills": top["missing_skills"], "explanation": top["explanation"],
            },
            "alternatives": [a["role"] for a in m["alternatives"]],
        })
    team = fit["team"]
    result = {
        "provenance": PROVENANCE, "privacy_note": WITHHELD_NOTE, "score_meaning": fit["score_meaning"], "members": members,
        "covered_roles": [c["role"] for c in team["covered"] if c["priority"]],
        "uncovered_roles": [{"role": g["role"], "note": g["note"]} for g in team["gaps"]],
        "overlaps": [o["note"] for o in team["overlaps"]],
        "suggested_split": [{"member": p["member"], "role": p["role"], "differs_from_own_best": p["differs"]} for p in team["plan"]],
        "confirmed_or_chosen_roles": data["decisions"],
        "note": "Suggestions are advice. Only a role in confirmed_or_chosen_roles has been accepted or chosen by that person.",
    }
    return result, _grounding("team_roles", "Role suggestions for your team (teammate sharing choices respected)", ["Suggest a balanced team for this project."])


def suggest_team(user: dict[str, Any], args: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    doc = _project(args["project_id"])
    team_id = args.get("team_id")
    team_id = _id(team_id, "team_id") if team_id else None
    size = _int(args.get("team_size"), "team_size", 1, 8)
    out = team_service.team_formation(user, doc, team_id=team_id, include_self=True, manual=_candidates(args.get("candidates")), team_size=size)
    teams = []
    for t in out["teams"][:4]:
        req = t["requirements"]
        teams.append({
            "label": t["label"], "recommended": t["recommended"], "size": t["size"],
            "members": [
                {
                    "name": m["name"], "source": m["source"],
                    "contributes": [{"requirement": c["skill"], "strength": c["strength"], "level": c["level"]} for c in m["contributes"]],
                    "best_fit_role": (m["suggested_role"] or {}).get("role"),
                }
                for m in t["members"]
            ],
            "requirements": {"solid": req["solid"], "partial": req["partial"], "uncovered": req["uncovered"], "total": req["total"],
                             "uncovered_skills": [i["skill"] for i in req["items"] if i["status"] == "uncovered"]},
            "dependencies": [b["note"] for b in t["bottlenecks"]],
            "explanation": t["explanation"],
        })
    result = {
        "provenance": PROVENANCE, "privacy_note": WITHHELD_NOTE, "project": out["project"], "teams": teams,
        "not_matched": out["pool"]["not_matched"], "notes": out["notes"], "limitations": out["limitations"][:4],
        "team_size_used": out.get("inputs", {}).get("team_size"),
        "action_note": "Nothing was created, invited or changed. The student must use the Team page to do that.",
    }
    return result, _grounding("team_formation", "Team suggestions from the people you can compare", ["Explain why this team was chosen."])


# --- dispatch --------------------------------------------------------------------------------------------------------------


def call_personal_tool(name: str, arguments: Any, user: Optional[dict[str, Any]]) -> tuple[dict[str, Any], Any]:
    """Run one personal tool for `user` (the server-resolved account) and return
    (result for the model, block(s) for the UI). Never raises for bad input or
    missing data: the model gets a plain error string it can relay."""
    if name not in PERSONAL_TOOL_NAMES:
        return {"error": f"Unknown tool '{name}'."}, None
    if not user or not user.get("user_id"):
        return {"error": "The student is not signed in, so their saved data is unavailable. Suggest signing in."}, None
    try:
        args = _clean_args(name, arguments)
        if name == "get_my_profile":
            return get_my_profile(user)
        if name == "list_my_teams":
            return list_my_teams(user)
        if name == "get_my_progress":
            return get_my_progress(user)
        if name == "recommend_for_me":
            return recommend_for_me(user, args)
        if name == "get_my_skill_gap":
            return get_my_skill_gap(user, args)
        if name == "get_my_roadmap":
            return get_my_roadmap(user, args)
        if name == "get_my_team_roles":
            return get_my_team_roles(user, args)
        return suggest_team(user, args)
    except ToolArgumentError as error:
        return {"error": f"Invalid request: {error}"}, None
    except LookupError as error:
        return {"error": str(error)}, None
    except team_service.TeamError as error:
        return {"error": str(error)}, None  # generic by construction ("No team found, or you are not a member.")
