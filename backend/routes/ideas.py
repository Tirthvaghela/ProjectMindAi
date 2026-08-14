"""Workspace endpoints for AI-GENERATED ideas — the idea-scoped mirror of
routes/projects.py's synopsis/roadmap/milestones and routes/search.py's
skill-gap/team-builder/timeline-predict/chat, for the "Idea Workspace" page
(frontend/src/pages/IdeaDetail.jsx).

A generated idea is deliberately never written to Mongo (see
nlp/ai_assistant.py's module docstring), so there is no project_id to look
one up by — every route here takes the idea's own fields directly in the
request body instead, builds a synthetic project-shaped doc via
nlp/generator.py:idea_doc() (the same builder nlp/chat_tools.py's
generate_idea_roadmap/timeline/milestones tools already use), and feeds it
into the exact same deterministic generators a catalogue project's own
routes use. Nothing here is a second implementation of skill-gap, roadmap,
synopsis, milestones, team-building, or chat — it is the same functions,
minus the Mongo lookup.
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint

from extensions import limiter
from nlp import ai_assistant, generator, recommend, timeline
from nlp.team_builder import suggest_roles
from routes.assistant import _raise_for_llm_failure, _validate_message
from routes.helpers import ApiError, get_int, json_body, ok

bp = Blueprint("ideas", __name__, url_prefix="/api/idea")


def _idea_doc_from_body(body: dict[str, Any], *, description: str = "") -> dict[str, Any]:
    """Shared field extraction + validation for every route below — an
    idea's name is the only thing that's actually required; domain/
    difficulty/duration_weeks/technologies all degrade gracefully inside
    generator.idea_doc() itself (invalid/missing values normalise rather
    than error), exactly as they already do for the chat-tool callers.
    """
    name = (body.get("name") or "").strip()
    if not name:
        raise ApiError("'name' is required.", status=400)

    technologies = body.get("technologies") or []
    if not isinstance(technologies, list) or not all(isinstance(t, str) for t in technologies):
        raise ApiError("'technologies' must be a list of strings.", status=400)

    return generator.idea_doc(
        name,
        domain=body.get("domain"),
        duration_weeks=body.get("duration_weeks"),
        difficulty=body.get("difficulty"),
        technologies=technologies,
        description=description,
    )


@bp.post("/skill-gap")
def idea_skill_gap():
    """Body: {name, domain?, difficulty?, duration_weeks?, technologies?, skills}."""
    body = json_body()
    skills = body.get("skills") or []
    if not isinstance(skills, list) or not all(isinstance(s, str) for s in skills):
        raise ApiError("'skills' must be a list of strings.", status=400)

    doc = _idea_doc_from_body(body)
    return ok(recommend.skill_gap_for_doc(doc, skills))


@bp.post("/synopsis")
def idea_synopsis():
    """Body: {name, domain?, difficulty?, duration_weeks?, technologies?, problem?, solution?}."""
    body = json_body()
    description = f"{body.get('problem') or ''} {body.get('solution') or ''}".strip()
    doc = _idea_doc_from_body(body, description=description)
    return ok(generator.synopsis_for(doc))


@bp.post("/roadmap")
def idea_roadmap():
    """Body: {name, domain?, difficulty?, duration_weeks?, technologies?}."""
    doc = _idea_doc_from_body(json_body())
    return ok(generator.roadmap_for(doc))


@bp.post("/milestones")
def idea_milestones():
    """Body: {name, domain?, difficulty?, duration_weeks?, technologies?}."""
    doc = _idea_doc_from_body(json_body())
    return ok(generator.milestones_for(doc))


@bp.post("/timeline")
def idea_timeline():
    """Body: {name, domain?, difficulty?, duration_weeks?, technologies?, team_size?, experience_level?}.

    Mirrors POST /api/timeline-predict — used by the Roadmap tab's
    "personalize estimate" control to re-plan against a team size/experience
    level instead of the flat baseline duration_weeks.
    """
    body = json_body()
    team_size = get_int(body, "team_size", 1, 1, 20)
    doc = _idea_doc_from_body(body)
    return ok(timeline.predict(doc, team_size=team_size, experience_level=body.get("experience_level") or None))


@bp.post("/team-builder")
def idea_team_builder():
    """Body: {domain?, technologies?, members: [{name?, skills: [str]}]}.

    Only `domain` actually drives the role list (generator.domain_profile),
    so unlike the other routes here `name` isn't required.
    """
    body = json_body()
    members = body.get("members") or []
    if not isinstance(members, list) or not members:
        raise ApiError("'members' must be a non-empty list.", status=400)
    if len(members) > 20:
        raise ApiError("'members' must be 20 or fewer.", status=400)
    for member in members:
        if not isinstance(member, dict) or not isinstance(member.get("skills", []), list):
            raise ApiError("Each member must be an object with a 'skills' list.", status=400)

    technologies = body.get("technologies") or []
    if not isinstance(technologies, list) or not all(isinstance(t, str) for t in technologies):
        raise ApiError("'technologies' must be a list of strings.", status=400)

    doc = generator.idea_doc(body.get("name") or "", domain=body.get("domain"), technologies=technologies)
    return ok(suggest_roles(doc, members))


@bp.post("/chat")
@limiter.limit("20 per hour")
def idea_chat():
    """Body: {idea: {name, problem?, solution?, domain?, difficulty?, technologies?}, message, history?}.

    The idea-scoped mirror of POST /project/<id>/chat — adapts the idea's
    own fields into the same {title, domain, difficulty, description,
    technologies, skills} shape ai_assistant.reply() already expects for a
    catalogue project's doc, so reply() itself needs no changes.
    """
    body = json_body()
    message = _validate_message(body)
    history = body.get("history") or []
    if not isinstance(history, list):
        raise ApiError("'history' must be a list.", status=400)

    idea = body.get("idea")
    if not isinstance(idea, dict):
        raise ApiError("'idea' must be an object.", status=400)
    description = f"{idea.get('problem') or ''} {idea.get('solution') or ''}".strip()
    doc = _idea_doc_from_body(idea, description=description)

    try:
        answer = ai_assistant.reply(doc, message, history)
    except Exception as error:  # noqa: BLE001
        _raise_for_llm_failure(error)

    return ok({"reply": answer})
