"""Stage 1 security corrections to the existing Team API:

* member email addresses are never part of a team payload, and
* POST /api/teams/join is rate limited (and still behaves as before).
"""

from __future__ import annotations

import json
import logging

import pytest

from db import client as db

PROJECT = {
    "project_id": "pm-sec", "title": "Security Project", "domain": "Web Development", "difficulty": "Intermediate",
    "description": "A project.", "duration_weeks": 6, "technologies": ["React"], "skills": [],
}
EMAIL_A, EMAIL_B = "owner-secret@example.com", "member-secret@example.com"


def signup(client, email, name):
    res = client.post("/api/auth/signup", json={"email": email, "password": "correcthorse1", "name": name})
    assert res.status_code == 201, res.get_json()
    return {"X-Auth-Token": res.get_json()["token"]}, res.get_json()["data"]["user_id"]


@pytest.fixture
def team(client):
    db.projects().insert_one(dict(PROJECT))
    owner, owner_id = signup(client, EMAIL_A, "Olive")
    member, member_id = signup(client, EMAIL_B, "Mo")
    created = client.post("/api/teams", json={"project_id": "pm-sec", "name": "T"}, headers=owner).get_json()["data"]
    joined = client.post("/api/teams/join", json={"invite_code": created["invite_code"]}, headers=member)
    assert joined.status_code == 200
    return {"client": client, "owner": owner, "owner_id": owner_id, "member": member, "member_id": member_id, "team": created}


def assert_no_private(payload):
    raw = json.dumps(payload)
    for secret in (EMAIL_A, EMAIL_B, "@example.com", '"email"', "password", "role_decisions", '"_id"'):
        assert secret not in raw, secret


# --- C1: no email in team payloads ----------------------------------------------------------------------


def test_every_team_response_omits_member_emails(team):
    c, tid = team["client"], team["team"]["team_id"]
    responses = [
        c.post("/api/teams", json={"project_id": "pm-sec", "name": "Another"}, headers=team["owner"]),
        c.get("/api/teams/mine", headers=team["member"]),
        c.get(f"/api/teams/{tid}", headers=team["member"]),
        c.get(f"/api/teams/{tid}", headers=team["owner"]),
        c.patch(f"/api/teams/{tid}", json={"name": "Renamed"}, headers=team["owner"]),
        c.post(f"/api/teams/{tid}/skills", json={"skills": ["Python"]}, headers=team["member"]),
        c.get(f"/api/teams/{tid}/roles", headers=team["member"]),
    ]
    for res in responses:
        assert res.status_code in (200, 201), res.get_json()
        assert_no_private(res.get_json())


def test_join_and_remove_responses_omit_emails(client):
    db.projects().insert_one(dict(PROJECT))
    owner, _ = signup(client, EMAIL_A, "Olive")
    third, third_id = signup(client, "third-secret@example.com", "Thea")
    created = client.post("/api/teams", json={"project_id": "pm-sec"}, headers=owner).get_json()["data"]
    joined = client.post("/api/teams/join", json={"invite_code": created["invite_code"]}, headers=third)
    assert "@example.com" not in json.dumps(joined.get_json())
    removed = client.delete(f"/api/teams/{created['team_id']}/members/{third_id}", headers=owner)
    assert removed.status_code == 200 and "@example.com" not in json.dumps(removed.get_json())


def test_member_payload_keeps_only_what_collaboration_needs(team):
    c, tid = team["client"], team["team"]["team_id"]
    c.post(f"/api/teams/{tid}/skills", json={"skills": ["Python"]}, headers=team["member"])
    data = c.get(f"/api/teams/{tid}", headers=team["owner"]).get_json()["data"]
    by_id = {m["user_id"]: m for m in data["members"]}
    assert set(by_id) == {team["owner_id"], team["member_id"]}
    assert set(by_id[team["owner_id"]]) == {"user_id", "name"}
    assert set(by_id[team["member_id"]]) == {"user_id", "name", "skills"} and by_id[team["member_id"]]["skills"] == ["Python"]
    assert data["owner_user_id"] == team["owner_id"]


def test_team_payload_has_no_unlisted_fields(team):
    c, tid = team["client"], team["team"]["team_id"]
    db.teams().update_one({"team_id": tid}, {"$set": {"internal_note": "do-not-leak", "role_decisions": {"x": {"status": "accepted"}}}})
    data = c.get(f"/api/teams/{tid}", headers=team["owner"]).get_json()["data"]
    assert "internal_note" not in data and "role_decisions" not in data
    assert set(data) <= {"team_id", "project_id", "idea", "project_title", "name", "invite_code", "owner_user_id", "created_at", "members", "project", "domain"}


def test_only_the_owner_still_receives_the_invite_code(team):
    c, tid = team["client"], team["team"]["team_id"]
    assert "invite_code" in c.get(f"/api/teams/{tid}", headers=team["owner"]).get_json()["data"]
    assert "invite_code" not in c.get(f"/api/teams/{tid}", headers=team["member"]).get_json()["data"]
    assert "invite_code" not in c.get("/api/teams/mine", headers=team["member"]).get_json()["data"][0]


def test_legacy_member_documents_with_email_or_missing_fields_are_still_served(team):
    c, tid = team["client"], team["team"]["team_id"]
    db.teams().update_one({"team_id": tid}, {"$push": {"members": {"user_id": "legacy", "email": "legacy@example.com"}}})
    data = c.get(f"/api/teams/{tid}", headers=team["owner"]).get_json()["data"]
    legacy = next(m for m in data["members"] if m["user_id"] == "legacy")
    assert legacy == {"user_id": "legacy", "name": "legacy"}


def test_email_is_still_available_server_side_for_notifications(team, monkeypatch):
    import notify

    sent = []
    monkeypatch.setattr(notify.config, "SMTP_ENABLED", True)
    monkeypatch.setattr(notify, "_send_email", lambda user_id, title, body: sent.append(user_id))
    c, tid = team["client"], team["team"]["team_id"]
    c.post(f"/api/teams/{tid}/messages", json={"content": "hi"}, headers=team["owner"])
    assert sent == [team["member_id"]]  # looked up by id server-side; never put in a response


# --- C2: join-by-code rate limit -------------------------------------------------------------------------


def test_join_route_has_per_minute_and_hourly_limits(client):
    from tests.test_rate_limits import _configured_limits

    assert sorted(_configured_limits(client.application, "teams.join")) == ["10 per 1 minute", "60 per 1 hour"]


def test_join_still_works_and_bad_codes_answer_uniformly(team):
    c = team["client"]
    stranger, _ = signup(c, "stranger@example.com", "Sam")
    ok = c.post("/api/teams/join", json={"invite_code": team["team"]["invite_code"]}, headers=stranger)
    assert ok.status_code == 200
    bad = [c.post("/api/teams/join", json={"invite_code": code}, headers=stranger) for code in ("ZZZZZZ", "x", "a" * 300)]
    assert {r.status_code for r in bad} == {404}
    assert len({json.dumps(r.get_json()) for r in bad}) == 1  # nothing distinguishes a near miss


def test_join_is_rejected_with_429_after_repeated_attempts(team):
    c = team["client"]
    stranger, _ = signup(c, "stranger@example.com", "Sam")
    # The team fixture already spent one of this IP's 10 per-minute joins.
    statuses = [c.post("/api/teams/join", json={"invite_code": "ZZZZZZ"}, headers=stranger).status_code for _ in range(12)]
    assert statuses[:9] == [404] * 9
    assert set(statuses[9:]) == {429}
    limited = c.post("/api/teams/join", json={"invite_code": "ZZZZZZ"}, headers=stranger)
    assert limited.status_code == 429 and "error" in limited.get_json()


def test_invite_codes_are_not_logged(team, caplog):
    c = team["client"]
    stranger, _ = signup(c, "stranger@example.com", "Sam")
    with caplog.at_level(logging.DEBUG):
        c.post("/api/teams/join", json={"invite_code": "QWERTY"}, headers=stranger)
        c.post("/api/teams/join", json={"invite_code": team["team"]["invite_code"]}, headers=stranger)
    app_logs = " | ".join(r.getMessage() for r in caplog.records if not r.name.startswith("pymongo"))
    assert "QWERTY" not in app_logs and team["team"]["invite_code"] not in app_logs
