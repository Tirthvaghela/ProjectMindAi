"""Personalised learning roadmap endpoints.

Every route is account-scoped: the profile and the progress are always the ones
the session token resolves to (routes/helpers.py:current_user). No route reads a
user id from the URL, query or body. The roadmap itself is generated
deterministically from the saved profile and the catalogue project
(nlp/learning_roadmap.py) - no LLM, no network.
"""

from __future__ import annotations

from flask import Blueprint, request

from extensions import limiter
from nlp import recommend
from profiles import service as profile_service
from roadmaps import service
from routes.helpers import ApiError, current_user, json_body, ok

bp = Blueprint("roadmap", __name__, url_prefix="/api/roadmap")


def _project(project_id) -> dict:
    if not isinstance(project_id, str) or not project_id.strip():
        raise ApiError("'project_id' is required.", status=400)
    project_id = project_id.strip()
    if len(project_id) > 64:
        raise ApiError("'project_id' is too long.", status=400)
    doc = recommend.get_retriever().documents.get(project_id)
    if doc is None:
        raise ApiError(f"No project with id '{project_id}'.", status=404)
    return doc


@bp.get("/me")
@limiter.limit("60 per minute")
def get_roadmap():
    """?project_id=<id> -> the caller's roadmap for that project, with saved step statuses."""
    user = current_user()
    doc = _project(request.args.get("project_id"))
    profile = profile_service.get_profile(user["user_id"])
    return ok(service.roadmap_with_progress(doc, profile, user["user_id"]))


@bp.put("/me/progress")
@limiter.limit("120 per hour")
def set_progress():
    """Body: {project_id, step_id, status: not_started|in_progress|completed}."""
    user = current_user()
    body = json_body()
    doc = _project(body.get("project_id"))
    profile = profile_service.get_profile(user["user_id"])
    try:
        roadmap = service.set_step_status(doc, profile, user["user_id"], body.get("step_id"), body.get("status"))
    except service.RoadmapError as error:
        raise ApiError(str(error), status=error.status) from None
    return ok(roadmap)


@bp.delete("/me/progress")
def reset_progress():
    """Body or query: {project_id, confirm: true}. Deleting recorded progress
    cannot be undone, so it requires an explicit confirmation flag."""
    user = current_user()
    body = request.get_json(silent=True)
    body = body if isinstance(body, dict) else {}
    project_id = body.get("project_id", request.args.get("project_id"))
    confirm = body.get("confirm", request.args.get("confirm"))
    doc = _project(project_id)
    if confirm not in (True, "true"):
        raise ApiError("Resetting progress cannot be undone; send confirm=true to proceed.", status=400)
    removed = service.reset_progress(user["user_id"], doc["project_id"])
    profile = profile_service.get_profile(user["user_id"])
    return ok({"reset": removed, "roadmap": service.roadmap_with_progress(doc, profile, user["user_id"])})
