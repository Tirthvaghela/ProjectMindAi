from datetime import datetime, timedelta, timezone

import pytest

from auth.service import (
    AuthError,
    create_session,
    login,
    revoke_all_sessions,
    signup,
    update_profile,
    user_from_token,
)
from db import client as db


def test_signup_then_login_round_trip(mongo_test_db):
    created = signup("alice@example.com", "correcthorse1", "Alice")
    assert created["email"] == "alice@example.com"
    assert created["name"] == "Alice"
    assert "password_hash" not in created  # never leaks the hash to a caller

    logged_in = login("alice@example.com", "correcthorse1")
    assert logged_in["user_id"] == created["user_id"]


def test_signup_normalises_email_case_and_whitespace(mongo_test_db):
    signup("  Bob@Example.com  ", "correcthorse2", "Bob")
    logged_in = login("bob@example.com", "correcthorse2")
    assert logged_in["email"] == "bob@example.com"


def test_signup_rejects_duplicate_email(mongo_test_db):
    signup("carol@example.com", "correcthorse3", "Carol")
    with pytest.raises(AuthError, match="already exists"):
        signup("carol@example.com", "differentpassword", "Carol Two")


def test_signup_rejects_short_password(mongo_test_db):
    with pytest.raises(AuthError, match="8 characters"):
        signup("dana@example.com", "short", "Dana")


def test_signup_rejects_invalid_email(mongo_test_db):
    with pytest.raises(AuthError, match="valid email"):
        signup("not-an-email", "correcthorse4", "Eve")


def test_login_rejects_wrong_password(mongo_test_db):
    signup("frank@example.com", "correcthorse5", "Frank")
    with pytest.raises(AuthError, match="Incorrect"):
        login("frank@example.com", "wrongpassword")


def test_login_rejects_unknown_email(mongo_test_db):
    with pytest.raises(AuthError, match="Incorrect"):
        login("nobody@example.com", "whatever123")


# Regression tests for the NoSQL-injection-shaped bug found and fixed
# alongside routes/helpers.py's device_id(): a non-string value here must
# never reach a raw string operation unguarded, since the failure mode for
# that class of bug is exactly "crashes instead of validating cleanly".
def test_signup_rejects_non_string_email(mongo_test_db):
    with pytest.raises(AuthError, match="text"):
        signup({"$ne": None}, "correcthorse6", "Mallory")


def test_login_rejects_non_string_email(mongo_test_db):
    with pytest.raises(AuthError, match="Incorrect"):
        login({"$ne": None}, "whatever")


def test_user_from_token_returns_none_for_unknown_token(mongo_test_db):
    assert user_from_token("not-a-real-token") is None


def test_user_from_token_returns_none_for_empty_token(mongo_test_db):
    assert user_from_token("") is None


def test_create_session_then_resolve_it_back_to_the_user(mongo_test_db):
    user = signup("grace@example.com", "correcthorse7", "Grace")
    token = create_session(user["user_id"])

    resolved = user_from_token(token)
    assert resolved["user_id"] == user["user_id"]


def test_expired_session_is_rejected_and_self_cleans(mongo_test_db):
    # A session past its own expires_at must stop authenticating immediately —
    # not wait on the TTL index's own background sweep (see
    # auth/service.py:user_from_token) — and the stale document should be
    # gone afterward, not merely ignored on every future lookup.
    user = signup("hana@example.com", "correcthorse7b", "Hana")
    token = create_session(user["user_id"])
    db.sessions().update_one(
        {"token": token},
        {"$set": {"expires_at": datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)}},
    )

    assert user_from_token(token) is None
    assert db.sessions().find_one({"token": token}) is None


# --- Profile management (section 7) ---------------------------------------


def test_update_profile_changes_the_display_name(mongo_test_db):
    user = signup("henry@example.com", "correcthorse8", "Henry")
    updated = update_profile(user["user_id"], name="Henry Jr.")
    assert updated["name"] == "Henry Jr."
    assert updated["email"] == "henry@example.com"  # untouched


def test_update_profile_changes_the_email(mongo_test_db):
    user = signup("iris@example.com", "correcthorse9", "Iris")
    updated = update_profile(user["user_id"], email="iris.new@example.com")
    assert updated["email"] == "iris.new@example.com"
    assert login("iris.new@example.com", "correcthorse9")["user_id"] == user["user_id"]


def test_update_profile_rejects_an_email_already_taken_by_someone_else(mongo_test_db):
    signup("jack@example.com", "correcthorse10", "Jack")
    kate = signup("kate@example.com", "correcthorse11", "Kate")
    with pytest.raises(AuthError, match="already exists"):
        update_profile(kate["user_id"], email="jack@example.com")


def test_update_profile_allows_keeping_your_own_current_email(mongo_test_db):
    # Re-saving the same email must not trip the "already taken" check
    # against yourself.
    user = signup("leo@example.com", "correcthorse12", "Leo")
    updated = update_profile(user["user_id"], name="Leo Two", email="leo@example.com")
    assert updated["email"] == "leo@example.com"
    assert updated["name"] == "Leo Two"


def test_update_profile_rejects_an_invalid_email(mongo_test_db):
    user = signup("mia@example.com", "correcthorse13", "Mia")
    with pytest.raises(AuthError, match="valid email"):
        update_profile(user["user_id"], email="not-an-email")


def test_update_profile_rejects_an_empty_name(mongo_test_db):
    user = signup("nora@example.com", "correcthorse14", "Nora")
    with pytest.raises(AuthError, match="required"):
        update_profile(user["user_id"], name="   ")


def test_update_profile_with_nothing_to_change_is_rejected(mongo_test_db):
    user = signup("oscar@example.com", "correcthorse15", "Oscar")
    with pytest.raises(AuthError, match="Nothing to update"):
        update_profile(user["user_id"])


def test_update_profile_changes_the_password_given_the_correct_current_one(mongo_test_db):
    user = signup("paula@example.com", "correcthorse16", "Paula")
    update_profile(user["user_id"], current_password="correcthorse16", new_password="newpassword1")
    assert login("paula@example.com", "newpassword1")["user_id"] == user["user_id"]
    with pytest.raises(AuthError, match="Incorrect"):
        login("paula@example.com", "correcthorse16")


def test_update_profile_rejects_a_password_change_with_the_wrong_current_password(mongo_test_db):
    user = signup("quinn@example.com", "correcthorse17", "Quinn")
    with pytest.raises(AuthError, match="Current password is incorrect"):
        update_profile(user["user_id"], current_password="wrongpassword", new_password="newpassword2")
    # The password must be unchanged.
    assert login("quinn@example.com", "correcthorse17")["user_id"] == user["user_id"]


def test_update_profile_rejects_a_short_new_password(mongo_test_db):
    user = signup("ruth@example.com", "correcthorse18", "Ruth")
    with pytest.raises(AuthError, match="8 characters"):
        update_profile(user["user_id"], current_password="correcthorse18", new_password="short")


def test_update_profile_for_unknown_user_fails(mongo_test_db):
    with pytest.raises(AuthError, match="Account not found"):
        update_profile("no-such-user", name="Ghost")


def test_revoke_all_sessions_invalidates_every_token_for_that_account(mongo_test_db):
    user = signup("sam@example.com", "correcthorse19", "Sam")
    token_a = create_session(user["user_id"])
    token_b = create_session(user["user_id"])

    revoke_all_sessions(user["user_id"])

    assert user_from_token(token_a) is None
    assert user_from_token(token_b) is None


# --- Duplicate-email race handling (reliability section 12: "duplicate
# record") --------------------------------------------------------------
#
# signup()/update_profile() both pre-check "is this email taken?" before
# writing — a TOCTOU gap in principle (two concurrent calls for the same new
# email could both pass the check). db/client.py's unique index on `email`
# is the actual backstop; these tests simulate that backstop firing by
# proxying db.users() so insert_one/update_one raise DuplicateKeyError
# exactly as Mongo would once two racing writers hit the real index —
# without needing genuinely concurrent threads to reproduce it.


class _DuplicateKeyOnInsert:
    """Passes every read through to the real collection; insert_one always
    raises, as if the unique email index had just rejected a racing write."""

    def __init__(self, real):
        self._real = real

    def find_one(self, *args, **kwargs):
        return self._real.find_one(*args, **kwargs)

    def insert_one(self, *args, **kwargs):
        from pymongo.errors import DuplicateKeyError

        raise DuplicateKeyError("E11000 duplicate key error collection: test.users index: uq_email")


class _DuplicateKeyOnUpdate:
    """Same idea, for update_profile()'s write instead of signup()'s insert."""

    def __init__(self, real):
        self._real = real

    def find_one(self, *args, **kwargs):
        return self._real.find_one(*args, **kwargs)

    def update_one(self, *args, **kwargs):
        from pymongo.errors import DuplicateKeyError

        raise DuplicateKeyError("E11000 duplicate key error collection: test.users index: uq_email")


def test_signup_converts_a_racing_duplicate_key_error_into_a_clean_auth_error(monkeypatch, mongo_test_db):
    # The pre-check (find_one) sees no existing user and passes — the
    # collision only surfaces when the write itself hits the unique index,
    # exactly like two real concurrent signups for the same email would.
    real_collection = db.users()
    monkeypatch.setattr(db, "users", lambda: _DuplicateKeyOnInsert(real_collection))

    with pytest.raises(AuthError, match="already exists"):
        signup("racer@example.com", "correcthorse20", "Racer")


def test_update_profile_converts_a_racing_duplicate_key_error_into_a_clean_auth_error(monkeypatch, mongo_test_db):
    user = signup("tina@example.com", "correcthorse21", "Tina")
    real_collection = db.users()
    monkeypatch.setattr(db, "users", lambda: _DuplicateKeyOnUpdate(real_collection))

    with pytest.raises(AuthError, match="already exists"):
        update_profile(user["user_id"], email="new-address@example.com")
