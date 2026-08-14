"""HTTP-level auth/authorization tests — everything in tests/test_auth.py and
tests/test_teams.py already covers this at the function level; this file
exercises the same guarantees through the real Flask routes (headers, status
codes, cross-user isolation over the wire), since that is the layer a lot of
this actually lives in: current_user()'s 401, a route's own 403/404 mapping,
and whether a header is even read in the first place.
"""

from __future__ import annotations

from auth.service import AuthError
from db import client as db


def _signup(client, email, password="correcthorse1", name="Test User"):
    res = client.post("/api/auth/signup", json={"email": email, "password": password, "name": name})
    assert res.status_code == 201, res.get_json()
    body = res.get_json()
    return body["token"], body["data"]


def _auth(token):
    return {"X-Auth-Token": token}


# --- Registration / login (sections 1, 2, 13) -----------------------------


def test_signup_returns_token_and_user(client):
    res = client.post(
        "/api/auth/signup", json={"email": "alice@example.com", "password": "correcthorse1", "name": "Alice"}
    )
    assert res.status_code == 201
    body = res.get_json()
    assert body["token"]
    assert body["data"]["email"] == "alice@example.com"
    assert "password_hash" not in body["data"]


def test_duplicate_signup_is_rejected(client):
    _signup(client, "bob@example.com")
    res = client.post(
        "/api/auth/signup", json={"email": "bob@example.com", "password": "differentpass", "name": "Bob Two"}
    )
    assert res.status_code == 400
    assert "error" in res.get_json()


def test_signup_missing_fields_is_a_clean_400(client):
    res = client.post("/api/auth/signup", json={"email": "incomplete@example.com"})
    assert res.status_code == 400


def test_valid_login_returns_a_token(client):
    _signup(client, "carol@example.com", password="correcthorse2")
    res = client.post("/api/auth/login", json={"email": "carol@example.com", "password": "correcthorse2"})
    assert res.status_code == 200
    assert res.get_json()["token"]


def test_invalid_login_is_rejected_without_confirming_the_account_exists(client):
    _signup(client, "dana@example.com", password="correcthorse3")
    wrong_password = client.post("/api/auth/login", json={"email": "dana@example.com", "password": "wrong"})
    unknown_email = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "whatever1"})
    assert wrong_password.status_code == 401
    assert unknown_email.status_code == 401
    # Same message either way — a caller can't use it to enumerate accounts.
    assert wrong_password.get_json()["error"] == unknown_email.get_json()["error"]


# --- Authentication state / session management (sections 3, 4) -----------


def test_me_without_a_token_is_401(client):
    res = client.get("/api/auth/me")
    assert res.status_code == 401


def test_me_with_a_garbage_token_is_401(client):
    res = client.get("/api/auth/me", headers=_auth("not-a-real-token"))
    assert res.status_code == 401


def test_me_with_a_valid_token_returns_the_account(client):
    token, user = _signup(client, "erin@example.com")
    res = client.get("/api/auth/me", headers=_auth(token))
    assert res.status_code == 200
    assert res.get_json()["data"]["user_id"] == user["user_id"]


def test_session_survives_repeated_requests_page_refresh_style(client):
    # Each test-client call is its own request/response cycle — repeating the
    # same token across several of them is exactly what a page refresh does.
    token, user = _signup(client, "frank@example.com")
    for _ in range(3):
        res = client.get("/api/auth/me", headers=_auth(token))
        assert res.status_code == 200
        assert res.get_json()["data"]["user_id"] == user["user_id"]


def test_logout_invalidates_the_token(client):
    token, _ = _signup(client, "grace@example.com")
    assert client.get("/api/auth/me", headers=_auth(token)).status_code == 200

    logout_res = client.post("/api/auth/logout", headers=_auth(token))
    assert logout_res.status_code == 200

    assert client.get("/api/auth/me", headers=_auth(token)).status_code == 401


def test_logout_without_a_token_does_not_error(client):
    res = client.post("/api/auth/logout")
    assert res.status_code == 200


# --- Protected routes require authentication (sections 3, 6) --------------


def test_protected_team_route_without_authentication_is_401(client):
    res = client.post("/api/teams", json={"project_id": "does-not-matter", "name": "X"})
    assert res.status_code == 401


def test_notifications_route_without_authentication_is_401(client):
    assert client.get("/api/notifications").status_code == 401


def test_public_search_stays_public_without_authentication(client):
    # Discovery must never start requiring a token just because accounts now
    # exist elsewhere in the app (section 3's "do not add auth to public
    # features", section 14's "existing public discovery remains accessible").
    res = client.get("/api/projects", headers={"X-Device-Id": "dev-anonymous"})
    assert res.status_code == 200


# --- User-specific data isolation / authorization (sections 5, 8, 14) -----


def _seed_project(project_id="pm-auth-test"):
    db.projects().insert_one(
        {
            "project_id": project_id,
            "title": "Auth Test Project",
            "description": "A" * 100,
            "domain": "Artificial Intelligence",
            "difficulty": "Intermediate",
            "duration_weeks": 8,
            "technologies": ["Python"],
            "skills": ["ML"],
            "keywords": ["ai"],
        }
    )
    return project_id


def test_user_a_cannot_read_user_bs_team(client):
    project_id = _seed_project()
    token_a, _ = _signup(client, "team-owner@example.com")
    token_b, _ = _signup(client, "team-outsider@example.com")

    create_res = client.post("/api/teams", json={"project_id": project_id, "name": "A's Team"}, headers=_auth(token_a))
    assert create_res.status_code == 201
    team_id = create_res.get_json()["data"]["team_id"]

    outsider_res = client.get(f"/api/teams/{team_id}", headers=_auth(token_b))
    assert outsider_res.status_code == 404  # exists, but B is not told that


def test_user_b_cannot_rename_user_as_team(client):
    project_id = _seed_project("pm-auth-test-2")
    token_a, _ = _signup(client, "owner2@example.com")
    token_b, _ = _signup(client, "outsider2@example.com")

    team = client.post("/api/teams", json={"project_id": project_id, "name": "Team"}, headers=_auth(token_a)).get_json()["data"]

    # B must join before they're even a recognised member, matching the
    # existing "member vs non-member" distinction (non-member -> 404 either
    # way; a real member who isn't the owner -> 403).
    client.post("/api/teams/join", json={"invite_code": team["invite_code"]}, headers=_auth(token_b))
    rename_res = client.patch(f"/api/teams/{team['team_id']}", json={"name": "Hijacked"}, headers=_auth(token_b))
    assert rename_res.status_code == 403


def test_user_a_cannot_read_user_bs_notifications(client):
    # Notifications are created as a side effect of a real team join (see
    # notify.py + teams/service.py) — reuse that instead of writing directly
    # to the notifications collection, so this exercises the real path.
    project_id = _seed_project("pm-auth-test-3")
    token_a, user_a = _signup(client, "notif-owner@example.com")
    token_b, _ = _signup(client, "notif-joiner@example.com")

    team = client.post("/api/teams", json={"project_id": project_id, "name": "Team"}, headers=_auth(token_a)).get_json()["data"]
    client.post("/api/teams/join", json={"invite_code": team["invite_code"]}, headers=_auth(token_b))

    owner_notifications = client.get("/api/notifications", headers=_auth(token_a)).get_json()["data"]
    assert any(n["type"] == "team_join" for n in owner_notifications)

    # B has their own (empty) notification feed — never A's join notification.
    joiner_notifications = client.get("/api/notifications", headers=_auth(token_b)).get_json()["data"]
    assert all(n["user_id"] != user_a["user_id"] for n in joiner_notifications) if joiner_notifications else True
    assert not any(n["type"] == "team_join" and "joined" in n["title"] and user_a["name"] in n["title"] for n in joiner_notifications)


def test_user_a_cannot_mark_user_bs_notification_read(client):
    project_id = _seed_project("pm-auth-test-4")
    token_a, _ = _signup(client, "notif-owner2@example.com")
    token_b, _ = _signup(client, "notif-joiner2@example.com")

    team = client.post("/api/teams", json={"project_id": project_id, "name": "Team"}, headers=_auth(token_a)).get_json()["data"]
    client.post("/api/teams/join", json={"invite_code": team["invite_code"]}, headers=_auth(token_b))

    owner_notification = client.get("/api/notifications", headers=_auth(token_a)).get_json()["data"][0]

    # B "guessing" A's notification_id must not be able to mark it read.
    res = client.post(f"/api/notifications/{owner_notification['notification_id']}/read", headers=_auth(token_b))
    assert res.status_code == 200  # the route no-ops rather than erroring (matches its own filtered update_one)
    still_unread = client.get("/api/notifications", headers=_auth(token_a)).get_json()["data"][0]
    assert still_unread["read"] is False


# --- Profile management / authorization (sections 7, 8) -------------------


def test_user_cannot_modify_another_users_profile_by_supplying_their_id(client):
    token_a, user_a = _signup(client, "profile-a@example.com")
    token_b, user_b = _signup(client, "profile-b@example.com")

    # Identity comes from the token; a spoofed user_id field in the body is
    # simply not a field this endpoint reads at all.
    res = client.patch(
        "/api/auth/me",
        json={"user_id": user_b["user_id"], "name": "Hijacked By A"},
        headers=_auth(token_a),
    )
    assert res.status_code == 200
    assert res.get_json()["data"]["user_id"] == user_a["user_id"]

    b_profile = client.get("/api/auth/me", headers=_auth(token_b)).get_json()["data"]
    assert b_profile["name"] != "Hijacked By A"


def test_update_profile_without_authentication_is_401(client):
    res = client.patch("/api/auth/me", json={"name": "Nobody"})
    assert res.status_code == 401


def test_update_profile_rejects_taking_another_users_email(client):
    _signup(client, "taken@example.com")
    token_b, _ = _signup(client, "wants-taken@example.com")
    res = client.patch("/api/auth/me", json={"email": "taken@example.com"}, headers=_auth(token_b))
    assert res.status_code == 400


def test_update_profile_maps_a_vanished_account_to_404(client, monkeypatch):
    # The real trigger is a narrow race — the account gets deleted in the
    # gap between current_user()'s read (which already succeeded; the
    # session itself is genuinely valid) and update_profile()'s own — not
    # reproducible by simply deleting the account first, since current_user()
    # would already 401 before this route's own mapping is ever reached.
    # This tests routes/auth.py's mapping directly instead, the same way the
    # DuplicateKeyError tests mock the failure point rather than reproducing
    # genuine concurrency.
    import routes.auth as auth_routes

    def _account_vanished(*args, **kwargs):
        raise AuthError("Account not found.")

    token, _ = _signup(client, "vanishing@example.com")
    monkeypatch.setattr(auth_routes, "update_profile", _account_vanished)

    res = client.patch("/api/auth/me", json={"name": "Ghost"}, headers=_auth(token))
    assert res.status_code == 404


def test_update_profile_still_maps_ordinary_validation_errors_to_400(client, monkeypatch):
    import routes.auth as auth_routes

    def _bad_name(*args, **kwargs):
        raise AuthError("Name is required.")

    token, _ = _signup(client, "ordinary-error@example.com")
    monkeypatch.setattr(auth_routes, "update_profile", _bad_name)

    res = client.patch("/api/auth/me", json={"name": "x"}, headers=_auth(token))
    assert res.status_code == 400


def test_password_change_via_route_reissues_a_working_token_and_revokes_the_old_ones(client):
    token, user = _signup(client, "pwchange@example.com", password="correcthorse1")
    # A second session for the same account (e.g. another tab/device).
    other_login = client.post("/api/auth/login", json={"email": "pwchange@example.com", "password": "correcthorse1"})
    other_token = other_login.get_json()["token"]

    res = client.patch(
        "/api/auth/me",
        json={"current_password": "correcthorse1", "new_password": "newcorrecthorse2"},
        headers=_auth(token),
    )
    assert res.status_code == 200
    new_token = res.get_json()["token"]
    assert new_token

    # The old token used to make the change is now dead...
    assert client.get("/api/auth/me", headers=_auth(token)).status_code == 401
    # ...so is the other session's token...
    assert client.get("/api/auth/me", headers=_auth(other_token)).status_code == 401
    # ...but the freshly issued one works.
    assert client.get("/api/auth/me", headers=_auth(new_token)).status_code == 200

    # And the new password is what actually signs in now.
    relogin = client.post("/api/auth/login", json={"email": "pwchange@example.com", "password": "newcorrecthorse2"})
    assert relogin.status_code == 200


def test_password_change_rejects_the_wrong_current_password(client):
    token, _ = _signup(client, "pwreject@example.com", password="correcthorse1")
    res = client.patch(
        "/api/auth/me",
        json={"current_password": "totallywrong", "new_password": "newcorrecthorse2"},
        headers=_auth(token),
    )
    assert res.status_code == 400
    # Original credentials still work — nothing was changed.
    still_works = client.post("/api/auth/login", json={"email": "pwreject@example.com", "password": "correcthorse1"})
    assert still_works.status_code == 200


# --- AI Assistant private context isolation (sections 5, 10) --------------


def test_conversations_are_isolated_per_device_not_shared_globally(client):
    # The dashboard chat is intentionally device-scoped rather than
    # account-scoped (see nlp/ai_assistant.py / routes/assistant.py) —
    # isolation here is enforced by X-Device-Id, and that boundary must hold
    # regardless of which account (if any) is signed in on each device.
    device_a = {"X-Device-Id": "device-a-conv"}
    device_b = {"X-Device-Id": "device-b-conv"}

    created = client.post("/api/conversations", headers=device_a)
    assert created.status_code == 201
    conversation_id = created.get_json()["data"]["conversation_id"]

    # Device B cannot read device A's conversation by id.
    res = client.get(f"/api/conversations/{conversation_id}", headers=device_b)
    assert res.status_code == 404

    # Nor does device B see it in their own list.
    listing = client.get("/api/conversations", headers=device_b).get_json()["data"]
    assert all(c["conversation_id"] != conversation_id for c in listing)
