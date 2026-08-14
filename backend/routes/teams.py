"""Team endpoints — create/join a team for a project, and its async message board.

Every route here requires a signed-in account (current_user()), unlike the
rest of the app which only ever needs an anonymous device id.
"""

from __future__ import annotations

from flask import Blueprint

from routes.helpers import ApiError, current_user, json_body, ok
from teams.service import (
    TeamError,
    create_team,
    get_team,
    join_team,
    list_messages,
    list_my_teams,
    post_message,
    remove_member,
    set_member_skills,
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


@bp.get("/<team_id>/messages")
def messages(team_id: str):
    user = current_user()
    try:
        rows = list_messages(team_id, user["user_id"])
    except TeamError as error:
        raise ApiError(str(error), status=error.status) from None
    return ok(rows, count=len(rows))


@bp.post("/<team_id>/messages")
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
