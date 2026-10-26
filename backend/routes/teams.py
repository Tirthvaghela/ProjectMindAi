"""Team endpoints — create/join a team for a project, and its async message board.

Every route here requires a signed-in account (current_user()), unlike the
rest of the app which only ever needs an anonymous device id.
"""

from __future__ import annotations

from flask import Blueprint

from extensions import limiter
from nlp import recommend
from routes.helpers import ApiError, current_user, json_body, ok
from teams.service import (
    TeamError,
    clear_role_decision,
    create_team,
    get_team,
    join_team,
    list_messages,
    list_my_teams,
    post_message,
    remove_member,
    set_member_skills,
    set_role_decision,
    team_formation,
    team_roles,
    update_team,
)

bp = Blueprint("teams", __name__, url_prefix="/api/teams")

MAX_TEAM_NAME_CHARS = 80


@bp.post("")
def create():
    """Body: {name, project_id} for a catalogue project, or {name, idea} for
    a generated idea (that idea's own fields — see routes/ideas.py) — a
    generated idea has no project_id to key a team on (nlp/ai_assistant.py's
    module docstring: never written to Mongo), so this is the one place a
    team can be grounded in one directly instead."""
    user = current_user()
    body = json_body()
    project_id = (body.get("project_id") or "").strip() or None
    idea = body.get("idea")
    name = (body.get("name") or "").strip()

    if not project_id and not idea:
        raise ApiError("Provide either 'project_id' or 'idea'.", status=400)
    if project_id and idea:
        raise ApiError("Provide only one of 'project_id' or 'idea'.", status=400)
    if idea is not None and not isinstance(idea, dict):
        raise ApiError("'idea' must be an object.", status=400)
    if len(name) > MAX_TEAM_NAME_CHARS:
        raise ApiError(f"'name' must be {MAX_TEAM_NAME_CHARS} characters or fewer.", status=400)

    try:
        team = create_team(name, user, project_id=project_id, idea=idea)
    except TeamError as error:
        raise ApiError(str(error), status=error.status) from None

    return ok(team), 201


@bp.post("/join")
def join():
    user = current_user()
    body = json_body()
    invite_code = (body.get("invite_code") or "").strip()

    if not invite_code:
        raise ApiError("'invite_code' is required.", status=400)

    try:
        team = join_team(invite_code, user)
    except TeamError as error:
        raise ApiError(str(error), status=error.status) from None

    return ok(team)


@bp.get("/mine")
def mine():
    user = current_user()
    teams = list_my_teams(user["user_id"])
    return ok(teams, count=len(teams))


@bp.get("/<team_id>")
def get_one(team_id: str):
    user = current_user()
    try:
        team = get_team(team_id, user["user_id"])
    except TeamError as error:
        raise ApiError(str(error), status=error.status) from None
    return ok(team)


@bp.patch("/<team_id>")
def update(team_id: str):
    """Body: {name}. Owner-only — teams.service.update_team enforces it."""
    user = current_user()
    body = json_body()
    name = body.get("name")
    if not isinstance(name, str):
        raise ApiError("'name' is required.", status=400)
    if len(name.strip()) > MAX_TEAM_NAME_CHARS:
        raise ApiError(f"'name' must be {MAX_TEAM_NAME_CHARS} characters or fewer.", status=400)

    try:
        team = update_team(team_id, user["user_id"], name)
    except TeamError as error:
        raise ApiError(str(error), status=error.status) from None

    return ok(team)


@bp.delete("/<team_id>/members/<target_user_id>")
def remove_member_route(team_id: str, target_user_id: str):
    """The owner removing someone else (kick) or a member removing
    themselves (leave) — teams.service.remove_member tells the two apart
    and enforces who's allowed to do which."""
    user = current_user()
    try:
        team = remove_member(team_id, user["user_id"], target_user_id)
    except TeamError as error:
        raise ApiError(str(error), status=error.status) from None

    return ok(team)


@bp.post("/<team_id>/skills")
def set_my_skills(team_id: str):
    """Body: {skills: [str, ...]}. Self-service — a member records only their
    own skills, which GET /<team_id>/roles below then uses to ground role
    suggestions in this team's real roster."""
    user = current_user()
    body = json_body()
    skills = body.get("skills")
    if not isinstance(skills, list) or not all(isinstance(s, str) for s in skills):
        raise ApiError("'skills' must be a list of strings.", status=400)

    try:
        team = set_member_skills(team_id, user["user_id"], skills)
    except TeamError as error:
        raise ApiError(str(error), status=error.status) from None

    return ok(team)


@bp.get("/<team_id>/roles")
def roles(team_id: str):
    """Who should work on what, for this team's real roster and project —
    the persisted-team counterpart of POST /api/team-builder, reusing
    nlp/team_builder.py:suggest_roles rather than a second role-assignment
    algorithm."""
    user = current_user()
    try:
        result = team_roles(team_id, user["user_id"])
    except TeamError as error:
        raise ApiError(str(error), status=error.status) from None

    return ok(result)


@bp.put("/<team_id>/roles/mine")
def set_my_role_decision(team_id: str):
    """Body: {status: accepted|rejected|custom, role?}. The caller records their
    OWN decision about their suggested role; there is no route for deciding for
    someone else. Suggestions in GET /roles stay advice until this is called."""
    user = current_user()
    body = json_body()
    status, role = body.get("status"), body.get("role")
    if not isinstance(status, str) or (role is not None and not isinstance(role, str)):
        raise ApiError("'status' and 'role' must be text.", status=400)
    try:
        decisions = set_role_decision(team_id, user["user_id"], status, role)
    except TeamError as error:
        raise ApiError(str(error), status=error.status) from None
    return ok(decisions)


@bp.delete("/<team_id>/roles/mine")
def clear_my_role_decision(team_id: str):
    user = current_user()
    try:
        decisions = clear_role_decision(team_id, user["user_id"])
    except TeamError as error:
        raise ApiError(str(error), status=error.status) from None
    return ok(decisions)


@bp.post("/formation")
@limiter.limit("30 per minute")
def formation():
    """Recommend balanced teams for a catalogue project. READ-ONLY: it never
    invites anyone, creates a team or changes membership.

    Body: {project_id, team_id?, include_self? (default true), team_size? (1-8),
           candidates?: [{name, skills: [str]}]}
    Candidates are limited to the caller, the roster of a team the caller
    belongs to, and people the caller types in; there is no way to name another
    account. See nlp/team_formation.py for the selection logic.
    """
    user = current_user()
    body = json_body()
    project_id = body.get("project_id")
    if not isinstance(project_id, str) or not project_id.strip() or len(project_id.strip()) > 64:
        raise ApiError("'project_id' is required.", status=400)
    doc = recommend.get_retriever().documents.get(project_id.strip())
    if doc is None:
        raise ApiError(f"No project with id '{project_id.strip()}'.", status=404)

    team_id = body.get("team_id")
    if team_id is not None and (not isinstance(team_id, str) or not team_id.strip() or len(team_id) > 64):
        raise ApiError("'team_id' must be a team id.", status=400)
    include_self = body.get("include_self", True)
    if not isinstance(include_self, bool):
        raise ApiError("'include_self' must be true or false.", status=400)
    team_size = body.get("team_size")
    if team_size is not None and (isinstance(team_size, bool) or not isinstance(team_size, int) or not 1 <= team_size <= 8):
        raise ApiError("'team_size' must be a whole number from 1 to 8.", status=400)

    raw = body.get("candidates", [])
    if not isinstance(raw, list) or len(raw) > 12:
        raise ApiError("'candidates' must be a list of at most 12 people.", status=400)
    manual = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ApiError("Each candidate must be an object with a 'name' and a 'skills' list.", status=400)
        name, skills = entry.get("name"), entry.get("skills", [])
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 60:
            raise ApiError("Each candidate needs a name of 60 characters or fewer.", status=400)
        if not isinstance(skills, list) or len(skills) > 30 or not all(isinstance(s, str) and len(s) <= 60 for s in skills):
            raise ApiError("Candidate 'skills' must be a list of at most 30 short strings.", status=400)
        manual.append({"name": name.strip(), "skills": [s.strip() for s in skills if s.strip()]})

    try:
        result = team_formation(
            user, doc, team_id=team_id.strip() if team_id else None, include_self=include_self, manual=manual, team_size=team_size
        )
    except TeamError as error:
        raise ApiError(str(error), status=error.status) from None
    return ok(result)


@bp.get("/<team_id>/messages")
def messages(team_id: str):
    user = current_user()
    try:
        rows = list_messages(team_id, user["user_id"])
    except TeamError as error:
        raise ApiError(str(error), status=error.status) from None
    return ok(rows, count=len(rows))


@bp.post("/<team_id>/messages")
# Matches POST /api/conversations/<id>/messages' own rate (routes/assistant.py)
# — the closest existing analog: a persisted, human-typed message-send route.
# Real cost here isn't an LLM call, it's the notification/email fan-out to
# every other team member (notify.py, teams/service.py:post_message) — the
# same "expensive/external side effect" bar every other limited route meets.
@limiter.limit("30 per hour")
def post_message_route(team_id: str):
    user = current_user()
    body = json_body()
    content = (body.get("content") or "").strip()

    if not content:
        raise ApiError("'content' is required.", status=400)
    if len(content) > 2000:
        raise ApiError("'content' must be 2000 characters or fewer.", status=400)

    try:
        message = post_message(team_id, user, content)
    except TeamError as error:
        raise ApiError(str(error), status=error.status) from None

    return ok(message), 201
