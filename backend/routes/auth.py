"""Signup / login / current-user endpoints.

This is the only place accounts are created or verified. Nothing else in
this app requires one — favourites, history and search all still work
purely off the anonymous X-Device-Id, unchanged. Accounts exist only so
teams and notifications have someone to identify across devices.
"""

from __future__ import annotations

from flask import Blueprint, request

from auth.service import (
    AuthError,
    create_session,
    login,
    revoke_all_sessions,
    revoke_session,
    signup,
    update_profile,
)
from extensions import limiter
from routes.helpers import ApiError, current_user, json_body, ok

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@bp.post("/signup")
@limiter.limit("10 per hour")
def signup_route():
    body = json_body()
    try:
        user = signup(body.get("email", ""), body.get("password", ""), body.get("name", ""))
    except AuthError as error:
        raise ApiError(str(error), status=400) from None

    token = create_session(user["user_id"])
    return ok(user, token=token), 201


@bp.post("/login")
@limiter.limit("20 per hour")
def login_route():
    body = json_body()
    try:
        user = login(body.get("email", ""), body.get("password", ""))
    except AuthError as error:
        raise ApiError(str(error), status=401) from None

    token = create_session(user["user_id"])
    return ok(user, token=token)


@bp.get("/me")
def me():
    return ok(current_user())


@bp.patch("/me")
def update_profile_route():
    """Body: {name?, email?, current_password?, new_password?}. The account
    being updated is always the one the session token resolves to — there is
    no user_id field this endpoint reads from the body, so a caller cannot
    edit another account by supplying a different id.
    """
    user = current_user()
    body = json_body()

    name = body.get("name")
    email = body.get("email")
    current_password = body.get("current_password")
    new_password = body.get("new_password")
    for field, value in (("name", name), ("email", email), ("new_password", new_password)):
        if value is not None and not isinstance(value, str):
            raise ApiError(f"'{field}' must be text.", status=400)

    try:
        updated = update_profile(
            user["user_id"],
            name=name,
            email=email,
            current_password=current_password,
            new_password=new_password,
        )
    except AuthError as error:
        raise ApiError(str(error), status=400) from None

    if new_password is not None:
        # A password change invalidates every session for this account,
        # including the one making this very request — mint a fresh token so
        # the caller stays signed in instead of being logged out by their
        # own request; any other device/tab must sign in again.
        revoke_all_sessions(user["user_id"])
        token = create_session(updated["user_id"])
        return ok(updated, token=token)

    return ok(updated)


@bp.post("/logout")
def logout():
    token = request.headers.get("X-Auth-Token")
    if token:
        revoke_session(token)
    return ok({"logged_out": True})
