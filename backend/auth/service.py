"""Lightweight email/password accounts and bearer-token sessions.

No Flask-Login, no JWT library, no cookies: a session is a random opaque
token stored in Mongo and looked up per request via an X-Auth-Token header —
the same shape as every other identity in this app (X-Device-Id), just for a
verified person instead of an anonymous browser. Passwords are hashed with
Werkzeug's built-in PBKDF2 implementation, already a dependency via Flask.

Accounts exist only to make teams and notifications possible. Favourites,
history, search and personalisation all still run purely off the anonymous
device id — signing in changes nothing about them.
"""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from pymongo.errors import DuplicateKeyError
from werkzeug.security import check_password_hash, generate_password_hash

from db import client as db

SESSION_LIFETIME = timedelta(days=30)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MAX_NAME_CHARS = 80


class AuthError(Exception):
    """Signup/login failure with a message safe to show the caller."""


def _normalise_email(email: str) -> str:
    return email.strip().lower()


def signup(email: str, password: str, name: str) -> dict[str, Any]:
    if not all(isinstance(v, str) for v in (email, password, name)):
        raise AuthError("Email, password and name must all be text.")

    email = _normalise_email(email)
    name = name.strip()

    if not _EMAIL_RE.match(email):
        raise AuthError("Enter a valid email address.")
    if len(password) < 8:
        raise AuthError("Password must be at least 8 characters.")
    if not name:
        raise AuthError("Name is required.")
    if db.users().find_one({"email": email}):
        raise AuthError("An account with that email already exists.")

    user = {
        "user_id": str(uuid.uuid4()),
        "email": email,
        "name": name,
        "password_hash": generate_password_hash(password),
        "created_at": datetime.now(timezone.utc),
    }
    try:
        db.users().insert_one(user)
    except DuplicateKeyError:
        # Backstops the narrow race the pre-check above can't close: two
        # signups for the same email landing between "check" and "insert".
        # db/client.py's unique index on email is the actual source of
        # truth here; this just turns its failure into the same clean error
        # everyone else gets from the pre-check, not a raw 500.
        raise AuthError("An account with that email already exists.") from None
    return _public_user(user)


def login(email: str, password: str) -> dict[str, Any]:
    if not isinstance(email, str) or not isinstance(password, str):
        raise AuthError("Incorrect email or password.")

    email = _normalise_email(email)
    user = db.users().find_one({"email": email})
    if not user or not check_password_hash(user["password_hash"], password):
        raise AuthError("Incorrect email or password.")
    return _public_user(user)


def create_session(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    db.sessions().insert_one(
        {
            "token": token,
            "user_id": user_id,
            "created_at": now,
            "expires_at": now + SESSION_LIFETIME,
        }
    )
    return token


def user_from_token(token: str) -> Optional[dict[str, Any]]:
    if not token:
        return None
    session = db.sessions().find_one({"token": token})
    if not session:
        return None

    # pymongo hands back naive datetimes on read even though we wrote an
    # aware one (see routes/user.py's history serialisation for the same
    # quirk elsewhere in this app) — compare naive-to-naive.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if session["expires_at"] < now:
        # The TTL index will also clean this up, but not sending them a stale
        # "yes, still signed in" answer shouldn't wait on that background pass.
        db.sessions().delete_one({"token": token})
        return None

    user = db.users().find_one({"user_id": session["user_id"]})
    return _public_user(user) if user else None


def revoke_session(token: str) -> None:
    db.sessions().delete_one({"token": token})


def revoke_all_sessions(user_id: str) -> None:
    """Sign this account out everywhere — used after a password change, so a
    credential rotation actually invalidates any session issued under the
    old password rather than leaving them all valid until they expire."""
    db.sessions().delete_many({"user_id": user_id})


def update_profile(
    user_id: str,
    name: Optional[str] = None,
    email: Optional[str] = None,
    current_password: Optional[str] = None,
    new_password: Optional[str] = None,
) -> dict[str, Any]:
    """Update the caller's own profile. `user_id` must come from the
    session-resolved account (see routes/helpers.py:current_user), never
    from a request field — that is what makes it impossible for one account
    to edit another's profile by supplying a different id.

    Every argument is optional and independent: pass only what actually
    changed. Changing the password requires proving the current one first,
    same as any real account settings page — knowing a valid session token
    is not sufficient on its own to set a brand new password.
    """
    user = db.users().find_one({"user_id": user_id})
    if user is None:
        raise AuthError("Account not found.")

    updates: dict[str, Any] = {}

    if name is not None:
        name = name.strip()
        if not name:
            raise AuthError("Name is required.")
        if len(name) > _MAX_NAME_CHARS:
            raise AuthError(f"Name must be {_MAX_NAME_CHARS} characters or fewer.")
        updates["name"] = name

    if email is not None:
        email = _normalise_email(email)
        if not _EMAIL_RE.match(email):
            raise AuthError("Enter a valid email address.")
        if email != user["email"] and db.users().find_one({"email": email}):
            raise AuthError("An account with that email already exists.")
        updates["email"] = email

    if new_password is not None:
        if not isinstance(current_password, str) or not check_password_hash(user["password_hash"], current_password):
            raise AuthError("Current password is incorrect.")
        if len(new_password) < 8:
            raise AuthError("Password must be at least 8 characters.")
        updates["password_hash"] = generate_password_hash(new_password)

    if not updates:
        raise AuthError("Nothing to update — provide 'name', 'email' and/or 'new_password'.")

    try:
        db.users().update_one({"user_id": user_id}, {"$set": updates})
    except DuplicateKeyError:
        # Same race as signup's, one layer later: two profile updates racing
        # to claim the same new email between the pre-check above and this write.
        raise AuthError("An account with that email already exists.") from None
    updated = db.users().find_one({"user_id": user_id})
    return _public_user(updated)


def _public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {"user_id": user["user_id"], "email": user["email"], "name": user["name"]}
