"""Learner profile endpoints (skills, interests, goals, roles, availability).

Every route is account-scoped: the profile is always the one the session token
resolves to (routes/helpers.py:current_user). No route reads a user id from the
URL or body, so there is no way to address another account's profile — the
privacy guarantee is structural, not a check that could be forgotten.
"""

from __future__ import annotations

from flask import Blueprint

from extensions import limiter
from profiles import service
from routes.helpers import ApiError, current_user, json_body, ok

bp = Blueprint("profile", __name__, url_prefix="/api/profile")


@bp.get("/options")
def profile_options():
    """The form's fixed choices. Contains no user data, so no sign-in needed."""
    return ok(service.options())


@bp.get("")
def get_profile():
    user = current_user()
    return ok(service.get_profile(user["user_id"]))


@bp.put("")
@limiter.limit("120 per hour")
def save_profile():
    """Body: any subset of the profile sections. Sections not sent are kept."""
    user = current_user()
    try:
        profile = service.save_profile(user["user_id"], json_body())
    except service.ProfileError as error:
        raise ApiError(str(error), status=400, details={"field": error.field} if error.field else None) from None
    return ok(profile)


@bp.delete("")
def delete_profile():
    user = current_user()
    removed = service.delete_profile(user["user_id"])
    return ok({"deleted": removed})
