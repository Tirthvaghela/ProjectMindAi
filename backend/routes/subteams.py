"""Sub-team endpoints (module/workstream groups inside a parent team).

Same conventions as routes/teams.py: every route needs a signed-in account via
current_user(), identity is never read from the URL/query/body, and TeamError
carries the status to answer with. Authorisation (parent membership, owner,
sub-team membership) lives in teams/subteams.py and is evaluated on every call.
The parent team id in the URL is only ever a lookup key that the caller must
already belong to; a sub-team id is resolved UNDER that parent.
"""

from __future__ import annotations

from typing import Any, Callable

from flask import Blueprint, request

from extensions import limiter
from routes.helpers import ApiError, current_user, get_int, json_body, ok
from teams import subteams as svc

bp = Blueprint("subteams", __name__, url_prefix="/api/teams")


def _run(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except svc.TeamError as error:
        raise ApiError(str(error), status=error.status) from None


def _confirm() -> Any:
    body = request.get_json(silent=True)
    body = body if isinstance(body, dict) else {}
    return body.get("confirm", request.args.get("confirm"))


# --- sub-teams ------------------------------------------------------------------------------------------------


@bp.get("/<team_id>/sub-teams")
def list_sub_teams(team_id: str):
    user = current_user()
    rows = _run(svc.list_sub_teams, team_id, user["user_id"])
    return ok(rows, count=len(rows))


@bp.post("/<team_id>/sub-teams")
def create_sub_team(team_id: str):
    """Owner only. Body: {name, description?, module?, member_ids?}."""
    user = current_user()
    return ok(_run(svc.create_sub_team, team_id, user["user_id"], json_body())), 201


@bp.get("/<team_id>/sub-teams/<sub_team_id>")
def get_sub_team(team_id: str, sub_team_id: str):
    user = current_user()
    return ok(_run(svc.get_sub_team, team_id, sub_team_id, user["user_id"]))


@bp.patch("/<team_id>/sub-teams/<sub_team_id>")
def update_sub_team(team_id: str, sub_team_id: str):
    """Owner only. Body: any of {name, description, module, status: active|archived}."""
    user = current_user()
    return ok(_run(svc.update_sub_team, team_id, sub_team_id, user["user_id"], json_body()))


@bp.delete("/<team_id>/sub-teams/<sub_team_id>")
def delete_sub_team(team_id: str, sub_team_id: str):
    """Owner only; needs confirm=true (body or query) because chat and tasks go too."""
    user = current_user()
    return ok(_run(svc.delete_sub_team, team_id, sub_team_id, user["user_id"], _confirm()))


# --- members --------------------------------------------------------------------------------------------------


@bp.post("/<team_id>/sub-teams/<sub_team_id>/members")
def add_member(team_id: str, sub_team_id: str):
    """Owner only. Body: {user_id} - must already be on the parent team."""
    user = current_user()
    return ok(_run(svc.add_member, team_id, sub_team_id, user["user_id"], json_body().get("user_id")))


@bp.delete("/<team_id>/sub-teams/<sub_team_id>/members/<target_user_id>")
def remove_member(team_id: str, sub_team_id: str, target_user_id: str):
    user = current_user()
    return ok(_run(svc.remove_member, team_id, sub_team_id, user["user_id"], target_user_id))


# --- invitations -------------------------------------------------------------------------------------------------


@bp.post("/<team_id>/sub-teams/<sub_team_id>/invite")
@limiter.limit("30 per hour")
def create_invite(team_id: str, sub_team_id: str):
    """Owner only. Create or rotate the invitation; the code is in this response only.
    Body: {expires_in_days?: 1-30 (default 7)}."""
    user = current_user()
    body = request.get_json(silent=True)
    days = body.get("expires_in_days") if isinstance(body, dict) else None
    return ok(_run(svc.create_invite, team_id, sub_team_id, user["user_id"], days)), 201


@bp.delete("/<team_id>/sub-teams/<sub_team_id>/invite")
def revoke_invite(team_id: str, sub_team_id: str):
    user = current_user()
    return ok(_run(svc.revoke_invite, team_id, sub_team_id, user["user_id"]))


@bp.post("/sub-join")
# Same reasoning as POST /api/teams/join: the code is the credential, so guessing it
# is the attack. Every failure is one indistinguishable 404.
@limiter.limit("10 per minute")
@limiter.limit("60 per hour")
def join_sub_team():
    """Body: {invite_code}. Only works for someone already on the parent team."""
    user = current_user()
    code = json_body().get("invite_code")
    if not isinstance(code, str) or len(code) > 64:
        raise ApiError(svc.BAD_CODE, status=404)
    return ok(_run(svc.join_by_code, code, user))


# --- chat ---------------------------------------------------------------------------------------------------------


@bp.get("/<team_id>/sub-teams/<sub_team_id>/messages")
def list_messages(team_id: str, sub_team_id: str):
    """?limit=1-100 (default 50) returns the NEWEST messages, oldest first;
    ?before=<ISO timestamp> pages further back. Members only."""
    user = current_user()
    limit = get_int(request.args.to_dict(), "limit", 50, 1, 100)
    rows, has_more = _run(svc.list_messages, team_id, sub_team_id, user["user_id"], limit, request.args.get("before"))
    return ok(rows, count=len(rows), has_more=has_more)


@bp.post("/<team_id>/sub-teams/<sub_team_id>/messages")
# Matches the parent team's message limit: the cost is the notification fan-out.
@limiter.limit("30 per hour")
def post_message(team_id: str, sub_team_id: str):
    user = current_user()
    content = json_body().get("content")
    return ok(_run(svc.post_message, team_id, sub_team_id, user, content)), 201


# --- role suggestions ----------------------------------------------------------------------------------------------


@bp.get("/<team_id>/sub-teams/<sub_team_id>/roles")
def roles(team_id: str, sub_team_id: str):
    user = current_user()
    return ok(_run(svc.sub_team_roles, team_id, sub_team_id, user["user_id"]))


@bp.put("/<team_id>/sub-teams/<sub_team_id>/roles/mine")
def set_my_role_decision(team_id: str, sub_team_id: str):
    """Body: {status: accepted|rejected|custom, role?}. The caller's OWN decision only."""
    user = current_user()
    body = json_body()
    status, role = body.get("status"), body.get("role")
    if not isinstance(status, str) or (role is not None and not isinstance(role, str)):
        raise ApiError("'status' and 'role' must be text.", status=400)
    return ok(_run(svc.set_role_decision, team_id, sub_team_id, user["user_id"], status, role))


@bp.delete("/<team_id>/sub-teams/<sub_team_id>/roles/mine")
def clear_my_role_decision(team_id: str, sub_team_id: str):
    user = current_user()
    return ok(_run(svc.clear_role_decision, team_id, sub_team_id, user["user_id"]))


# --- tasks -------------------------------------------------------------------------------------------------------------


@bp.get("/<team_id>/sub-teams/<sub_team_id>/tasks")
def list_tasks(team_id: str, sub_team_id: str):
    user = current_user()
    rows = _run(svc.list_tasks, team_id, sub_team_id, user["user_id"])
    return ok(rows, count=len(rows))


@bp.post("/<team_id>/sub-teams/<sub_team_id>/tasks")
def create_task(team_id: str, sub_team_id: str):
    """Owner only. Body: {title, description?, assignee_id?, status?}."""
    user = current_user()
    return ok(_run(svc.create_task, team_id, sub_team_id, user["user_id"], json_body())), 201


@bp.patch("/<team_id>/sub-teams/<sub_team_id>/tasks/<task_id>")
def update_task(team_id: str, sub_team_id: str, task_id: str):
    """Owner: any of {title, description, assignee_id, status}. The assignee: {status} only."""
    user = current_user()
    return ok(_run(svc.update_task, team_id, sub_team_id, user["user_id"], task_id, json_body()))


@bp.delete("/<team_id>/sub-teams/<sub_team_id>/tasks/<task_id>")
def delete_task(team_id: str, sub_team_id: str, task_id: str):
    user = current_user()
    return ok(_run(svc.delete_task, team_id, sub_team_id, user["user_id"], task_id, _confirm()))
