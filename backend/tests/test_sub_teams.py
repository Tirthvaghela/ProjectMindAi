"""Module-based sub-teams (teams/subteams.py, routes/subteams.py): lifecycle,
membership invariants, invitations, chat, consent-aware role suggestions and tasks.

Everything runs against the throwaway per-process test database (conftest.py)."""

from __future__ import annotations

import json
import logging
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from db import client as db
from teams import subteams

PROJECT = {
    "project_id": "pm-sub", "title": "Campus Marketplace", "domain": "Web Development", "difficulty": "Intermediate",
    "description": "A marketplace.", "duration_weeks": 8, "technologies": ["React", "Node.js", "PostgreSQL"], "skills": [],
}
SECRET_SKILL = "Zebra Wrangling"
SECRET_GOAL = "Become a zebra whisperer"


def signup(client, email, name):
    res = client.post("/api/auth/signup", json={"email": email, "password": "correcthorse1", "name": name})
    assert res.status_code == 201, res.get_json()
    return {"X-Auth-Token": res.get_json()["token"]}, res.get_json()["data"]["user_id"]


class World:
    """Parent team T (owner O; members A, B) plus an outsider X who is not on T."""

    def __init__(self, client):
        self.c = client
        db.projects().insert_one(dict(PROJECT))
        self.O, self.o = signup(client, "owner@example.com", "Olive")
        self.A, self.a = signup(client, "ann@example.com", "Ann")
        self.B, self.b = signup(client, "bob@example.com", "Bob")
        self.X, self.x = signup(client, "xena@example.com", "Xena")
        team = client.post("/api/teams", json={"project_id": "pm-sub", "name": "Parent"}, headers=self.O).get_json()["data"]
        self.tid, self.code = team["team_id"], team["invite_code"]
        for h in (self.A, self.B):
            assert client.post("/api/teams/join", json={"invite_code": self.code}, headers=h).status_code == 200
        client.application.config["TESTING"] = True

    # --- thin HTTP helpers -------------------------------------------------------------------------------
    def url(self, sid=None, tail=""):
        base = f"/api/teams/{self.tid}/sub-teams"
        return base + (f"/{sid}" if sid else "") + tail

    def create(self, h=None, **body):
        body.setdefault("name", "Backend")
        return self.c.post(self.url(), json=body, headers=h or self.O)

    def sub(self, h=None, **body):
        res = self.create(h, **body)
        assert res.status_code == 201, res.get_json()
        return res.get_json()["data"]["sub_team_id"]

    def invite(self, sid, **body):
        res = self.c.post(self.url(sid, "/invite"), json=body, headers=self.O)
        assert res.status_code == 201, res.get_json()
        return res.get_json()["data"]["invite"]["code"]

    def get(self, path, h=None):
        return self.c.get(path, headers=h or {})

    def post(self, path, h, **body):
        return self.c.post(path, json=body, headers=h)

    def patch(self, path, h, **body):
        return self.c.patch(path, json=body, headers=h)


@pytest.fixture
def w(client):
    return World(client)


def raw(res):
    return json.dumps(res.get_json())


# =============================== STAGE 2: foundation =====================================================


def test_only_the_parent_owner_can_create_sub_teams(w):
    assert w.create(w.O, name="Backend", module="API", description="Server side").status_code == 201
    assert w.create(w.A, name="Sneaky").status_code == 403  # a member cannot elevate themselves
    assert w.create(w.X, name="Outsider").status_code == 404  # reveals nothing about the team
    assert w.c.post(w.url(), json={"name": "Anon"}).status_code == 401
    assert db.sub_teams().count_documents({}) == 1


def test_create_validates_input_and_requires_members_to_be_on_the_parent(w):
    assert w.create(name="").status_code == 400
    assert w.create(name="   ").status_code == 400
    assert w.create(name="x" * 81).status_code == 400
    assert w.create(name=5).status_code == 400
    assert w.create(description="d" * 501).status_code == 400
    assert w.create(module="m" * 81).status_code == 400
    assert w.create(member_ids="notalist").status_code == 400
    assert w.create(member_ids=[w.x]).status_code == 400  # not on the parent team
    assert w.create(member_ids=[w.a, 7]).status_code == 400
    assert w.c.post(w.url(), data="nope", headers=w.O).status_code == 400
    ok = w.create(name="Frontend", member_ids=[w.a, w.a, w.b])
    assert ok.status_code == 201
    assert [m["user_id"] for m in ok.get_json()["data"]["members"]] == [w.a, w.b]  # deduplicated
    assert db.sub_teams().count_documents({}) == 1


def test_names_are_unique_per_parent_case_insensitively_and_the_number_is_capped(w, monkeypatch):
    from tests.conftest import ensure_indexes_for_test

    ensure_indexes_for_test()
    assert w.create(name="Backend").status_code == 201
    assert w.create(name="backend").status_code == 409
    monkeypatch.setattr(subteams, "MAX_SUB_TEAMS", 2)
    assert w.create(name="Two").status_code == 201
    assert w.create(name="Three").status_code == 400


def test_a_parent_can_have_several_sub_teams_and_a_member_can_be_in_more_than_one(w):
    s1, s2 = w.sub(name="API", member_ids=[w.a]), w.sub(name="UI", member_ids=[w.a, w.b])
    for sid in (s1, s2):
        assert w.get(w.url(sid), w.A).status_code == 200
    listing = w.get(w.url(), w.O).get_json()["data"]
    assert {s["name"] for s in listing} == {"API", "UI"}


def test_list_shows_non_members_only_a_summary(w):
    sid = w.sub(name="Secret ops", module="Payments", member_ids=[w.a])
    for_b = w.get(w.url(), w.B).get_json()["data"][0]
    assert for_b["name"] == "Secret ops" and for_b["module"] == "Payments"
    assert for_b["is_member"] is False and for_b["can_manage"] is False
    assert "members" not in for_b and "invite" not in for_b
    assert w.get(w.url(sid), w.B).status_code == 404  # detail is members/owner only
    assert w.get(w.url(), w.X).status_code == 404 and w.get(w.url()).status_code == 401


def test_payloads_never_carry_emails_hashes_or_internals(w):
    sid = w.sub(member_ids=[w.a])
    code = w.invite(sid)
    texts = [
        raw(w.get(w.url(), w.O)), raw(w.get(w.url(sid), w.O)), raw(w.get(w.url(sid), w.A)), raw(w.get(w.url(), w.B)),
        raw(w.post(w.url(sid, "/members"), w.O, user_id=w.b)),
    ]
    for text in texts:
        for secret in ("@example.com", "code_hash", code, '"_id"', "password"):
            assert secret not in text, secret


def test_foreign_and_malformed_ids_never_resolve(w):
    sid = w.sub()
    other = w.c.post("/api/teams", json={"project_id": "pm-sub", "name": "Other parent"}, headers=w.O).get_json()["data"]["team_id"]
    # The same sub-team id under a DIFFERENT parent the caller owns is not found.
    assert w.get(f"/api/teams/{other}/sub-teams/{sid}", w.O).status_code == 404
    for bad in ("nope", "x" * 200, "..", "%00"):
        assert w.get(w.url(bad), w.O).status_code == 404
    assert w.get(f"/api/teams/{'z' * 50}/sub-teams", w.O).status_code == 404


def test_owner_can_rename_describe_archive_and_reactivate(w):
    sid = w.sub(name="Old", module="m")
    res = w.patch(w.url(sid), w.O, name="New", description="d", module="Payments")
    assert res.status_code == 200 and res.get_json()["data"]["name"] == "New"
    assert w.patch(w.url(sid), w.O, status="archived").get_json()["data"]["status"] == "archived"
    assert w.patch(w.url(sid), w.O, status="active").get_json()["data"]["status"] == "active"
    assert w.patch(w.url(sid), w.O, status="deleted").status_code == 400
    assert w.patch(w.url(sid), w.O).status_code == 400
    assert w.patch(w.url(sid), w.O, name="").status_code == 400


def test_members_and_outsiders_cannot_configure_a_sub_team(w):
    sid = w.sub(member_ids=[w.a])
    assert w.patch(w.url(sid), w.A, name="Hijacked").status_code == 403
    assert w.patch(w.url(sid), w.B, name="Hijacked").status_code == 404
    assert w.patch(w.url(sid), w.X, name="Hijacked").status_code == 404
    assert w.c.delete(w.url(sid) + "?confirm=true", headers=w.A).status_code == 403
    assert w.post(w.url(sid, "/members"), w.A, user_id=w.b).status_code == 403
    assert w.c.delete(w.url(sid, f"/members/{w.a}"), headers=w.A).status_code == 403
    assert db.sub_teams().find_one()["name"] == "Backend"


def test_delete_needs_confirmation_and_removes_chat_and_tasks(w):
    sid = w.sub(member_ids=[w.a])
    w.post(w.url(sid, "/messages"), w.A, content="hello")
    w.post(w.url(sid, "/tasks"), w.O, title="Do it")
    assert w.c.delete(w.url(sid), headers=w.O).status_code == 400
    assert db.sub_teams().count_documents({}) == 1
    res = w.c.delete(w.url(sid), json={"confirm": True}, headers=w.O)
    assert res.status_code == 200 and res.get_json()["data"]["deleted"] is True
    assert db.sub_teams().count_documents({}) == db.sub_team_messages().count_documents({}) == db.sub_team_tasks().count_documents({}) == 0
    assert w.get(w.url(sid), w.O).status_code == 404
    assert db.teams().count_documents({"team_id": w.tid}) == 1  # the parent is untouched


def test_members_must_already_be_on_the_parent(w):
    sid = w.sub()
    assert w.post(w.url(sid, "/members"), w.O, user_id=w.x).status_code == 400
    assert w.post(w.url(sid, "/members"), w.O, user_id="nobody").status_code == 400
    assert w.post(w.url(sid, "/members"), w.O, user_id=5).status_code == 400
    assert w.post(w.url(sid, "/members"), w.O).status_code == 400
    assert w.post(w.url(sid, "/members"), w.O, user_id=w.a).status_code == 200
    again = w.post(w.url(sid, "/members"), w.O, user_id=w.a)  # idempotent
    assert again.status_code == 200 and again.get_json()["data"]["member_count"] == 1
    assert w.c.delete(w.url(sid, f"/members/{w.a}"), headers=w.O).get_json()["data"]["member_count"] == 0
    assert w.c.delete(w.url(sid, f"/members/{w.a}"), headers=w.O).status_code == 404
    assert db.teams().find_one({"team_id": w.tid})["members"].__len__() == 3  # parent roster unchanged


def test_removed_parent_member_loses_every_sub_team_surface_immediately(w, monkeypatch):
    # Even if the tidy-up never ran, authorisation reads the parent roster.
    monkeypatch.setattr(subteams, "on_parent_member_removed", lambda *a, **k: None)
    sid = w.sub(member_ids=[w.a, w.b])
    w.post(w.url(sid, "/messages"), w.A, content="before")
    task = w.post(w.url(sid, "/tasks"), w.O, title="T", assignee_id=w.a).get_json()["data"]["task_id"]
    assert w.c.delete(f"/api/teams/{w.tid}/members/{w.a}", headers=w.O).status_code == 200

    stale = db.sub_teams().find_one()
    assert any(m["user_id"] == w.a for m in stale["members"])  # the stale row is still there...
    for res in (
        w.get(w.url(sid), w.A), w.get(w.url(sid, "/messages"), w.A), w.post(w.url(sid, "/messages"), w.A, content="x"),
        w.get(w.url(sid, "/tasks"), w.A), w.get(w.url(sid, "/roles"), w.A), w.get(w.url(), w.A),
        w.patch(w.url(sid, f"/tasks/{task}"), w.A, status="done"),
    ):
        assert res.status_code == 404  # ...and grants nothing
    owner_view = w.get(w.url(sid), w.O).get_json()["data"]
    assert [m["user_id"] for m in owner_view["members"]] == [w.b] and owner_view["member_count"] == 1
    task_view = w.get(w.url(sid, "/tasks"), w.O).get_json()["data"][0]
    assert task_view["assignee"] is None and task_view["needs_reassignment"] is True


def test_parent_removal_tidies_rows_and_unassigns_tasks_but_keeps_history(w):
    sid = w.sub(member_ids=[w.a, w.b])
    w.post(w.url(sid, "/messages"), w.A, content="hello from ann")
    w.post(w.url(sid, "/tasks"), w.O, title="T", assignee_id=w.a)
    w.c.put(w.url(sid, "/roles/mine"), json={"status": "rejected"}, headers=w.A)
    w.c.delete(f"/api/teams/{w.tid}/members/{w.a}", headers=w.O)
    doc = db.sub_teams().find_one()
    assert [m["user_id"] for m in doc["members"]] == [w.b] and w.a not in (doc.get("role_decisions") or {})
    assert db.sub_team_tasks().find_one()["assignee_id"] is None
    messages = w.get(w.url(sid, "/messages"), w.B).get_json()["data"]
    assert [m["content"] for m in messages] == ["hello from ann"]  # history preserved for authorised members


def test_leaving_the_parent_has_the_same_effect(w):
    sid = w.sub(member_ids=[w.a])
    assert w.c.delete(f"/api/teams/{w.tid}/members/{w.a}", headers=w.A).status_code == 200
    assert w.get(w.url(sid, "/messages"), w.A).status_code == 404
    assert [m["user_id"] for m in db.sub_teams().find_one()["members"]] == []


def test_rejoining_the_parent_does_not_restore_sub_team_access(w):
    sid = w.sub(member_ids=[w.a])
    w.c.delete(f"/api/teams/{w.tid}/members/{w.a}", headers=w.A)
    w.c.post("/api/teams/join", json={"invite_code": w.code}, headers=w.A)
    assert w.get(w.url(sid), w.A).status_code == 404


def test_injected_stale_or_foreign_member_rows_grant_nothing(w):
    sid = w.sub(member_ids=[w.a])
    db.sub_teams().update_one({"sub_team_id": sid}, {"$push": {"members": {"user_id": w.x}}})  # outsider sneaks in
    assert w.get(w.url(sid), w.X).status_code == 404
    assert w.get(w.url(sid, "/messages"), w.X).status_code == 404
    seen = w.get(w.url(sid), w.O).get_json()["data"]
    assert [m["user_id"] for m in seen["members"]] == [w.a]
    # Reads never write: the inert row stays (and stays inert) until a write path or the
    # parent-removal cleanup clears it.
    w.get(w.url(), w.O)
    assert w.x in [m["user_id"] for m in db.sub_teams().find_one()["members"]]
    assert w.get(w.url(sid), w.X).status_code == 404


def test_malformed_legacy_documents_are_handled(w):
    sid = w.sub(member_ids=[w.a])
    db.sub_teams().update_one({"sub_team_id": sid}, {"$set": {"members": [None, "x", {"nouser": 1}, {"user_id": w.a}, {"user_id": 5}], "invite": "junk", "status": None}})
    assert w.get(w.url(sid), w.A).status_code == 200
    assert w.get(w.url(), w.O).status_code == 200
    db.sub_teams().update_one({"sub_team_id": sid}, {"$unset": {"members": ""}})
    assert w.get(w.url(sid), w.O).get_json()["data"]["member_count"] == 0
    db.sub_teams().insert_one({"sub_team_id": 42, "parent_team_id": w.tid})  # no usable id at all
    assert w.get(w.url(), w.O).status_code == 200


# --- invitations ---------------------------------------------------------------------------------------------------


def test_only_the_owner_manages_invitations_and_the_code_is_shown_once(w):
    sid = w.sub(member_ids=[w.a])
    assert w.post(w.url(sid, "/invite"), w.A).status_code == 403
    assert w.post(w.url(sid, "/invite"), w.B).status_code == 404
    assert w.c.delete(w.url(sid, "/invite"), headers=w.A).status_code == 403
    code = w.invite(sid)
    assert len(code) == subteams.INVITE_LENGTH and set(code) <= set(subteams.INVITE_ALPHABET)
    assert code != w.code  # separate from the parent's code
    for res in (w.get(w.url(sid), w.O), w.get(w.url(), w.O), w.get(w.url(sid), w.A), w.get(w.url(), w.B)):
        assert code not in raw(res)
    owner = w.get(w.url(sid), w.O).get_json()["data"]["invite"]
    assert owner["active"] is True and "code" not in owner and owner["expires_at"]
    assert "invite" not in w.get(w.url(sid), w.A).get_json()["data"]


def test_only_a_hash_of_the_code_is_stored(w):
    sid = w.sub()
    code = w.invite(sid)
    stored = json.dumps(db.sub_teams().find_one(), default=str)
    assert code not in stored and "code_hash" in stored


def test_invite_expiry_days_are_validated(w):
    sid = w.sub()
    for bad in (0, 31, -1, "7", 1.5, True):
        assert w.post(w.url(sid, "/invite"), w.O, expires_in_days=bad).status_code == 400
    res = w.post(w.url(sid, "/invite"), w.O, expires_in_days=1)
    expires = datetime.fromisoformat(res.get_json()["data"]["invite"]["expires_at"])
    assert timedelta(hours=20) < expires - datetime.now(timezone.utc) < timedelta(hours=25)
    default = w.post(w.url(sid, "/invite"), w.O).get_json()["data"]["invite"]["expires_at"]
    assert timedelta(days=6) < datetime.fromisoformat(default) - datetime.now(timezone.utc) < timedelta(days=8)


def test_a_parent_member_joins_with_a_valid_code(w):
    sid = w.sub()
    code = w.invite(sid)
    res = w.post("/api/teams/sub-join", w.A, invite_code=code.lower())  # case-insensitive
    assert res.status_code == 200 and res.get_json()["data"]["is_member"] is True
    assert res.get_json()["data"]["sub_team_id"] == sid
    assert w.get(w.url(sid, "/messages"), w.A).status_code == 200
    again = w.post("/api/teams/sub-join", w.A, invite_code=code)
    assert again.status_code == 200 and again.get_json()["data"]["member_count"] == 1  # no duplicate


def test_a_sub_team_code_never_adds_anyone_to_the_parent(w):
    sid = w.sub()
    code = w.invite(sid)
    res = w.post("/api/teams/sub-join", w.X, invite_code=code)
    assert res.status_code == 404
    assert w.get(f"/api/teams/{w.tid}", w.X).status_code == 404
    assert {m["user_id"] for m in db.teams().find_one({"team_id": w.tid})["members"]} == {w.o, w.a, w.b}
    assert db.sub_teams().find_one()["members"] == []
    # And the parent code does not work as a sub-team code.
    assert w.post("/api/teams/sub-join", w.A, invite_code=w.code).status_code == 404


def test_every_failed_join_looks_identical(w):
    sid = w.sub()
    good = w.invite(sid)
    expired = w.sub(name="Expired")
    ecode = w.invite(expired)
    db.sub_teams().update_one({"sub_team_id": expired}, {"$set": {"invite.expires_at": datetime.now(timezone.utc) - timedelta(minutes=1)}})
    revoked = w.sub(name="Revoked")
    rcode = w.invite(revoked)
    w.c.delete(w.url(revoked, "/invite"), headers=w.O)
    archived = w.sub(name="Archived")
    acode = w.invite(archived)
    w.patch(w.url(archived), w.O, status="archived")

    attempts = [
        w.post("/api/teams/sub-join", w.A, invite_code=c) for c in ("ZZZZZZZZZZ", ecode, rcode, acode, "x", "!!bad!!", "a" * 70, "")
    ] + [w.post("/api/teams/sub-join", w.X, invite_code=good), w.c.post("/api/teams/sub-join", json={"invite_code": 5}, headers=w.A)]
    assert {r.status_code for r in attempts} == {404}
    assert len({raw(r) for r in attempts}) == 1  # nothing reveals expired vs unknown vs wrong team
    assert "Invalid or expired" in raw(attempts[0])
    from extensions import limiter

    limiter.reset()  # the 10/min per-IP cap is tested separately; this checks the 401 path
    assert w.c.post("/api/teams/sub-join", json={"invite_code": good}).status_code == 401


def test_rotation_invalidates_the_previous_code_and_revocation_stops_joins(w):
    sid = w.sub()
    old = w.invite(sid)
    new = w.invite(sid)
    assert old != new
    assert w.post("/api/teams/sub-join", w.A, invite_code=old).status_code == 404
    assert w.post("/api/teams/sub-join", w.A, invite_code=new).status_code == 200
    assert w.c.delete(w.url(sid, "/invite"), headers=w.O).get_json()["data"]["invite"]["active"] is False
    assert w.post("/api/teams/sub-join", w.B, invite_code=new).status_code == 404


def test_parent_membership_is_rechecked_at_join_time(w):
    sid = w.sub()
    code = w.invite(sid)
    w.c.delete(f"/api/teams/{w.tid}/members/{w.b}", headers=w.O)  # removed AFTER the code was made
    assert w.post("/api/teams/sub-join", w.B, invite_code=code).status_code == 404
    assert db.sub_teams().find_one()["members"] == []


def test_concurrent_joins_leave_exactly_one_membership(w):
    from app import app as flask_app

    sid = w.sub()
    code = w.invite(sid)
    token = w.A["X-Auth-Token"]

    def attempt(_):
        return flask_app.test_client().post("/api/teams/sub-join", json={"invite_code": code}, headers={"X-Auth-Token": token}).status_code

    with ThreadPoolExecutor(6) as pool:
        statuses = list(pool.map(attempt, range(6)))
    assert set(statuses) <= {200, 429} and 200 in statuses
    assert [m["user_id"] for m in db.sub_teams().find_one()["members"]] == [w.a]


def test_concurrent_duplicate_creates_resolve_to_one_winner(w):
    from tests.conftest import ensure_indexes_for_test
    from app import app as flask_app

    ensure_indexes_for_test()
    token = w.O["X-Auth-Token"]

    def attempt(_):
        return flask_app.test_client().post(w.url(), json={"name": "Race"}, headers={"X-Auth-Token": token}).status_code

    with ThreadPoolExecutor(5) as pool:
        statuses = list(pool.map(attempt, range(5)))
    assert statuses.count(201) == 1 and set(statuses) <= {201, 409}
    assert db.sub_teams().count_documents({"name": "Race"}) == 1


def test_sub_team_routes_have_the_intended_rate_limits(client):
    from tests.test_rate_limits import _configured_limits

    app = client.application
    assert sorted(_configured_limits(app, "subteams.join_sub_team")) == ["10 per 1 minute", "60 per 1 hour"]
    assert _configured_limits(app, "subteams.post_message") == ["30 per 1 hour"]
    assert _configured_limits(app, "subteams.create_invite") == ["30 per 1 hour"]


def test_repeated_bad_sub_team_codes_are_rate_limited_with_the_standard_429(w):
    w.sub()
    codes = [w.post("/api/teams/sub-join", w.A, invite_code="ZZZZZZZZZZ").status_code for _ in range(12)]
    assert codes[:10] == [404] * 10 and set(codes[10:]) == {429}


def test_invitation_codes_are_not_logged(w, caplog):
    sid = w.sub()
    code = w.invite(sid)
    with caplog.at_level(logging.DEBUG):
        w.post("/api/teams/sub-join", w.A, invite_code=code)
        w.post("/api/teams/sub-join", w.B, invite_code="QWERTYUIOP")
    logs = " | ".join(r.getMessage() for r in caplog.records if not r.name.startswith("pymongo"))
    assert code not in logs and "QWERTYUIOP" not in logs


# =============================== STAGE 3: chat + roles ====================================================


def test_chat_is_per_sub_team_and_separate_from_the_parent_chat(w):
    s1, s2 = w.sub(name="API", member_ids=[w.a]), w.sub(name="UI", member_ids=[w.b])
    assert w.post(w.url(s1, "/messages"), w.A, content="api secret plan").status_code == 201
    w.c.post(f"/api/teams/{w.tid}/messages", json={"content": "parent hello"}, headers=w.B)
    assert [m["content"] for m in w.get(w.url(s1, "/messages"), w.A).get_json()["data"]] == ["api secret plan"]
    assert w.get(w.url(s2, "/messages"), w.B).get_json()["data"] == []
    parent = w.c.get(f"/api/teams/{w.tid}/messages", headers=w.O).get_json()["data"]
    assert [m["content"] for m in parent] == ["parent hello"]  # nothing leaks up


def test_a_member_of_one_sub_team_cannot_read_or_post_in_another(w):
    s1, s2 = w.sub(name="API", member_ids=[w.a]), w.sub(name="UI", member_ids=[w.b])
    w.post(w.url(s2, "/messages"), w.B, content="ui only")
    assert w.get(w.url(s2, "/messages"), w.A).status_code == 404
    assert w.post(w.url(s2, "/messages"), w.A, content="intrusion").status_code == 404
    assert db.sub_team_messages().count_documents({"sub_team_id": s2}) == 1
    # Using sub-team 1's id under a different parent does not help either.
    other = w.c.post("/api/teams", json={"project_id": "pm-sub", "name": "P2"}, headers=w.A).get_json()["data"]["team_id"]
    assert w.get(f"/api/teams/{other}/sub-teams/{s2}/messages", w.A).status_code == 404


def test_the_owner_does_not_read_chat_unless_they_are_a_member(w):
    sid = w.sub(member_ids=[w.a])
    w.post(w.url(sid, "/messages"), w.A, content="private to the sub-team")
    res = w.get(w.url(sid, "/messages"), w.O)
    assert res.status_code == 403 and "private" not in raw(res)
    assert w.post(w.url(sid, "/messages"), w.O, content="hi").status_code == 403
    w.post(w.url(sid, "/members"), w.O, user_id=w.o)
    assert w.get(w.url(sid, "/messages"), w.O).status_code == 200


def test_message_validation_pagination_and_archive(w):
    sid = w.sub(member_ids=[w.a])
    for bad in ("", "   ", None, 5, "x" * 2001):
        assert w.post(w.url(sid, "/messages"), w.A, content=bad).status_code == 400
    for i in range(7):
        w.post(w.url(sid, "/messages"), w.A, content=f"m{i}")
    page = w.get(w.url(sid, "/messages") + "?limit=3", w.A).get_json()
    assert [m["content"] for m in page["data"]] == ["m4", "m5", "m6"] and page["has_more"] is True
    older = w.get(w.url(sid, "/messages") + f"?limit=3&before={quote(page['data'][0]['created_at'])}", w.A).get_json()
    assert [m["content"] for m in older["data"]] == ["m1", "m2", "m3"]
    assert w.get(w.url(sid, "/messages") + "?limit=9999", w.A).status_code == 200
    assert w.get(w.url(sid, "/messages") + "?before=garbage", w.A).status_code == 400
    assert w.get(w.url(sid, "/messages") + "?limit=abc", w.A).status_code == 200
    w.patch(w.url(sid), w.O, status="archived")
    assert w.post(w.url(sid, "/messages"), w.A, content="late").status_code == 400
    assert w.get(w.url(sid, "/messages"), w.A).status_code == 200  # history stays readable


def test_chat_notifications_go_only_to_sub_team_members_and_message_text_is_not_logged(w, caplog):
    sid = w.sub(member_ids=[w.a, w.b])
    w.c.delete(w.url(sid, f"/members/{w.b}"), headers=w.O)
    before = db.notifications().count_documents({})
    with caplog.at_level(logging.DEBUG):
        w.post(w.url(sid, "/messages"), w.A, content="SENSITIVE-TEXT-123")
    types = [n["type"] for n in db.notifications().find({"type": "subteam_message"})]
    assert types == [] and db.notifications().count_documents({}) == before  # the only other member left
    w.post(w.url(sid, "/members"), w.O, user_id=w.b)
    w.post(w.url(sid, "/messages"), w.A, content="hello again")
    recipients = {n["user_id"] for n in db.notifications().find({"type": "subteam_message"})}
    assert recipients == {w.b}
    logs = " | ".join(r.getMessage() for r in caplog.records if not r.name.startswith("pymongo"))
    assert "SENSITIVE-TEXT-123" not in logs


def _profile(client, h, **fields):
    assert client.put("/api/profile", json=fields, headers=h).status_code == 200


def test_roles_are_computed_for_the_sub_team_roster_only(w):
    _profile(w.c, w.A, skills=[{"name": "React", "level": "Advanced"}], share_with_teams=True)
    _profile(w.c, w.B, skills=[{"name": "PostgreSQL", "level": "Advanced"}], share_with_teams=True)
    sid = w.sub(member_ids=[w.a])
    roles = w.get(w.url(sid, "/roles"), w.A).get_json()["data"]
    assert roles["scope"]["member_count"] == 1
    names = {f["name"] for f in roles["role_fit"]["members"]}
    assert names == {"Ann"}
    assert "Bob" not in raw(w.get(w.url(sid, "/roles"), w.A)) and "PostgreSQL" not in raw(w.get(w.url(sid, "/roles"), w.A))
    parent = w.c.get(f"/api/teams/{w.tid}/roles", headers=w.A).get_json()["data"]
    assert {f["name"] for f in parent["role_fit"]["members"]} == {"Olive", "Ann", "Bob"}  # parent endpoint unchanged


def test_an_empty_sub_team_does_not_fall_back_to_the_parent_roster(w):
    sid = w.sub()
    roles = w.get(w.url(sid, "/roles"), w.O).get_json()["data"]
    assert roles["scope"]["member_count"] == 0 and roles["role_fit"]["members"] == []
    assert roles["assignments"] == []


def test_non_members_and_signed_out_callers_get_no_sub_team_roles(w):
    sid = w.sub(member_ids=[w.a])
    assert w.get(w.url(sid, "/roles"), w.B).status_code == 404
    assert w.get(w.url(sid, "/roles"), w.X).status_code == 404
    assert w.c.get(w.url(sid, "/roles")).status_code == 401


def _private_profile(client, h, shared):
    _profile(client, h, skills=[{"name": SECRET_SKILL, "level": "Advanced"}, {"name": "React", "level": "Advanced"}],
             learning_goals=[SECRET_GOAL], education="Zebra University", share_with_teams=shared)


def test_consent_disabled_missing_and_switched_off_keep_a_profile_private(w):
    sid = w.sub(member_ids=[w.a, w.b])
    _private_profile(w.c, w.A, False)  # explicitly not shared
    _profile(w.c, w.B, skills=[{"name": SECRET_SKILL, "level": "Advanced"}], learning_goals=[SECRET_GOAL])  # field never set
    for h in (w.O, w.B):
        res = w.get(w.url(sid, "/roles"), h)
        assert res.status_code == 200
        if h is w.O:
            assert SECRET_SKILL not in raw(res) and SECRET_GOAL not in raw(res) and "Zebra University" not in raw(res)
    owner = w.get(w.url(sid, "/roles"), w.O).get_json()["data"]
    ann = next(f for f in owner["role_fit"]["members"] if f["name"] == "Ann")
    assert ann.get("info_unavailable") is True and ann["suggested"] is None
    # Opt in: now her role-relevant skills count, but not goals/education.
    _private_profile(w.c, w.A, True)
    shared = w.get(w.url(sid, "/roles"), w.O)
    assert "React" in raw(shared) and SECRET_GOAL not in raw(shared) and "Zebra University" not in raw(shared)
    # Switched off again: effective on the very next request.
    _private_profile(w.c, w.A, False)
    off = w.get(w.url(sid, "/roles"), w.O)
    assert "React" not in raw(off) and SECRET_SKILL not in raw(off)


def test_manual_team_skills_still_count_and_are_labelled_when_the_profile_is_withheld(w):
    sid = w.sub(member_ids=[w.a])
    _private_profile(w.c, w.A, False)
    w.c.post(f"/api/teams/{w.tid}/skills", json={"skills": ["React"]}, headers=w.A)
    res = w.get(w.url(sid, "/roles"), w.O)
    ann = next(f for f in res.get_json()["data"]["role_fit"]["members"] if f["name"] == "Ann")
    assert ann["source"] == "manual" and SECRET_SKILL not in raw(res)


def test_a_viewer_always_sees_their_own_profile_based_result(w):
    sid = w.sub(member_ids=[w.a])
    _private_profile(w.c, w.A, False)
    ann = next(f for f in w.get(w.url(sid, "/roles"), w.A).get_json()["data"]["role_fit"]["members"] if f["name"] == "Ann")
    assert ann["source"] in ("profile", "profile+manual") and ann["profile_shared"] is False


def test_role_decisions_are_personal_and_scoped_to_the_sub_team(w):
    sid = w.sub(member_ids=[w.a, w.b])
    other = w.sub(name="Other", member_ids=[w.a])
    put = lambda h, s, **b: w.c.put(w.url(s, "/roles/mine"), json=b, headers=h)  # noqa: E731
    assert put(w.A, sid, status="accepted", role="Frontend Developer").status_code == 200
    assert put(w.O, sid, status="accepted", role="Frontend Developer").status_code == 403  # the owner has no personal decision here
    assert put(w.X, sid, status="rejected").status_code == 404
    assert put(w.A, sid, status="maybe").status_code == 400
    assert put(w.A, sid, status="accepted", role="Wizard").status_code == 400
    assert put(w.A, sid, status="accepted").status_code == 400
    decisions = w.get(w.url(sid, "/roles"), w.B).get_json()["data"]["decisions"]
    assert decisions == [{"user_id": w.a, "name": "Ann", "status": "accepted", "role": "Frontend Developer"}]
    assert w.get(w.url(other, "/roles"), w.A).get_json()["data"]["decisions"] == []  # per sub-team
    assert w.c.get(f"/api/teams/{w.tid}/roles", headers=w.A).get_json()["data"]["decisions"] == []  # not the parent's
    assert w.c.delete(w.url(sid, "/roles/mine"), headers=w.A).get_json()["data"] == []
    assert db.teams().find_one({"team_id": w.tid}).get("role_decisions") is None


# =============================== STAGE 4: tasks =============================================================


def test_only_the_owner_manages_tasks(w):
    sid = w.sub(member_ids=[w.a, w.b])
    created = w.post(w.url(sid, "/tasks"), w.O, title="Build API", description="REST", assignee_id=w.a)
    assert created.status_code == 201
    task = created.get_json()["data"]
    assert task["status"] == "todo" and task["assignee"]["user_id"] == w.a and task["needs_reassignment"] is False
    tid = task["task_id"]
    for res in (
        w.post(w.url(sid, "/tasks"), w.A, title="Mine"), w.post(w.url(sid, "/tasks"), w.X, title="X"),
        w.patch(w.url(sid, f"/tasks/{tid}"), w.B, title="Hijack"), w.patch(w.url(sid, f"/tasks/{tid}"), w.A, title="Rename"),
        w.patch(w.url(sid, f"/tasks/{tid}"), w.A, assignee_id=w.a, status="done"),
        w.c.delete(w.url(sid, f"/tasks/{tid}") + "?confirm=true", headers=w.A),
    ):
        assert res.status_code in (403, 404)
    assert db.sub_team_tasks().find_one()["title"] == "Build API"
    assert w.c.post(w.url(sid, "/tasks"), json={"title": "x"}).status_code == 401


def test_task_visibility_is_for_sub_team_members_and_the_owner(w):
    sid = w.sub(member_ids=[w.a])
    w.post(w.url(sid, "/tasks"), w.O, title="Visible")
    assert [t["title"] for t in w.get(w.url(sid, "/tasks"), w.A).get_json()["data"]] == ["Visible"]
    assert len(w.get(w.url(sid, "/tasks"), w.O).get_json()["data"]) == 1
    assert w.get(w.url(sid, "/tasks"), w.B).status_code == 404 and w.get(w.url(sid, "/tasks"), w.X).status_code == 404


def test_task_input_is_validated_on_the_server(w):
    sid = w.sub(member_ids=[w.a])
    bad_bodies = [
        {}, {"title": ""}, {"title": "x" * 121}, {"title": 5}, {"title": "ok", "description": "d" * 1001},
        {"title": "ok", "status": "finished"}, {"title": "ok", "assignee_id": w.b},  # b is on the parent but not the sub-team
        {"title": "ok", "assignee_id": w.x}, {"title": "ok", "assignee_id": 7}, {"title": "ok", "assignee_id": "nobody"},
    ]
    for body in bad_bodies:
        assert w.post(w.url(sid, "/tasks"), w.O, **body).status_code == 400, body
    assert db.sub_team_tasks().count_documents({}) == 0
    ok = w.post(w.url(sid, "/tasks"), w.O, title="Fine", status="blocked", assignee_id=None)
    assert ok.status_code == 201 and ok.get_json()["data"]["status"] == "blocked"


def test_owner_edits_assigns_and_reassigns(w):
    sid = w.sub(member_ids=[w.a, w.b])
    tid = w.post(w.url(sid, "/tasks"), w.O, title="T").get_json()["data"]["task_id"]
    res = w.patch(w.url(sid, f"/tasks/{tid}"), w.O, title="T2", description="more", assignee_id=w.a, status="in_progress")
    assert res.status_code == 200 and res.get_json()["data"]["assignee"]["name"] == "Ann"
    assert w.patch(w.url(sid, f"/tasks/{tid}"), w.O, assignee_id=w.b).get_json()["data"]["assignee"]["user_id"] == w.b
    assert w.patch(w.url(sid, f"/tasks/{tid}"), w.O, assignee_id=None).get_json()["data"]["assignee"] is None
    assert w.patch(w.url(sid, f"/tasks/{tid}"), w.O, assignee_id=w.x).status_code == 400
    assert w.patch(w.url(sid, f"/tasks/{tid}"), w.O, bogus=1).status_code == 400
    assert w.patch(w.url(sid, f"/tasks/{tid}"), w.O).status_code == 400
    assert {n["user_id"] for n in db.notifications().find({"type": "subteam_task"})} == {w.a, w.b}


def test_an_assignee_can_change_only_the_status_of_their_own_task(w):
    sid = w.sub(member_ids=[w.a, w.b])
    mine = w.post(w.url(sid, "/tasks"), w.O, title="Mine", assignee_id=w.a).get_json()["data"]["task_id"]
    theirs = w.post(w.url(sid, "/tasks"), w.O, title="Bob's", assignee_id=w.b).get_json()["data"]["task_id"]
    unassigned = w.post(w.url(sid, "/tasks"), w.O, title="Open").get_json()["data"]["task_id"]
    for status in ("in_progress", "blocked", "done", "todo"):
        assert w.patch(w.url(sid, f"/tasks/{mine}"), w.A, status=status).get_json()["data"]["status"] == status
    assert w.patch(w.url(sid, f"/tasks/{mine}"), w.A, status="finished").status_code == 400
    assert w.patch(w.url(sid, f"/tasks/{theirs}"), w.A, status="done").status_code == 403
    assert w.patch(w.url(sid, f"/tasks/{unassigned}"), w.A, status="done").status_code == 403
    assert w.patch(w.url(sid, f"/tasks/{mine}"), w.A, status="done", title="Renamed").status_code == 403
    assert w.patch(w.url(sid, f"/tasks/{mine}"), w.A, assignee_id=w.b).status_code == 403
    assert db.sub_team_tasks().find_one({"task_id": mine})["assignee_id"] == w.a
    assert db.sub_team_tasks().find_one({"task_id": mine})["title"] == "Mine"


def test_removing_an_assignee_from_the_sub_team_or_parent_revokes_their_task_access(w):
    sid = w.sub(member_ids=[w.a, w.b])
    tid = w.post(w.url(sid, "/tasks"), w.O, title="T", assignee_id=w.a).get_json()["data"]["task_id"]
    w.c.delete(w.url(sid, f"/members/{w.a}"), headers=w.O)  # off the sub-team, still on the parent
    assert w.patch(w.url(sid, f"/tasks/{tid}"), w.A, status="done").status_code == 404
    task = w.get(w.url(sid, "/tasks"), w.O).get_json()["data"][0]
    assert task["assignee"] is None and db.sub_team_tasks().find_one()["assignee_id"] is None
    assert w.patch(w.url(sid, f"/tasks/{tid}"), w.O, assignee_id=w.b).status_code == 200  # owner can reassign

    sid2 = w.sub(name="Second", member_ids=[w.b])
    t2 = w.post(w.url(sid2, "/tasks"), w.O, title="T2", assignee_id=w.b).get_json()["data"]["task_id"]
    w.c.delete(f"/api/teams/{w.tid}/members/{w.b}", headers=w.O)  # off the parent
    assert w.patch(w.url(sid2, f"/tasks/{t2}"), w.B, status="done").status_code == 404
    assert db.sub_team_tasks().find_one({"task_id": t2})["status"] == "todo"


def test_a_stale_assignment_to_a_removed_member_cannot_be_used(w, monkeypatch):
    monkeypatch.setattr(subteams, "on_parent_member_removed", lambda *a, **k: None)
    sid = w.sub(member_ids=[w.a])
    tid = w.post(w.url(sid, "/tasks"), w.O, title="T", assignee_id=w.a).get_json()["data"]["task_id"]
    w.c.delete(f"/api/teams/{w.tid}/members/{w.a}", headers=w.O)
    assert db.sub_team_tasks().find_one()["assignee_id"] == w.a  # stale
    assert w.patch(w.url(sid, f"/tasks/{tid}"), w.A, status="done").status_code == 404
    assert w.get(w.url(sid, "/tasks"), w.O).get_json()["data"][0]["needs_reassignment"] is True


def test_tasks_are_isolated_between_sub_teams_and_parents(w):
    s1, s2 = w.sub(name="One", member_ids=[w.a]), w.sub(name="Two", member_ids=[w.a])
    tid = w.post(w.url(s1, "/tasks"), w.O, title="Only in One", assignee_id=w.a).get_json()["data"]["task_id"]
    assert w.get(w.url(s2, "/tasks"), w.A).get_json()["data"] == []
    assert w.patch(w.url(s2, f"/tasks/{tid}"), w.A, status="done").status_code == 404  # right id, wrong sub-team
    assert w.patch(w.url(s2, f"/tasks/{tid}"), w.O, title="x").status_code == 404
    assert w.c.delete(w.url(s2, f"/tasks/{tid}") + "?confirm=true", headers=w.O).status_code == 404
    other = w.c.post("/api/teams", json={"project_id": "pm-sub", "name": "P2"}, headers=w.O).get_json()["data"]["team_id"]
    assert w.patch(f"/api/teams/{other}/sub-teams/{s1}/tasks/{tid}", w.O, title="x").status_code == 404
    assert db.sub_team_tasks().find_one()["title"] == "Only in One"
    for bad in ("nope", "x" * 200):
        assert w.patch(w.url(s1, f"/tasks/{bad}"), w.O, title="x").status_code == 404


def test_deleting_a_task_needs_confirmation(w):
    sid = w.sub(member_ids=[w.a])
    tid = w.post(w.url(sid, "/tasks"), w.O, title="T").get_json()["data"]["task_id"]
    assert w.c.delete(w.url(sid, f"/tasks/{tid}"), headers=w.O).status_code == 400
    assert db.sub_team_tasks().count_documents({}) == 1
    assert w.c.delete(w.url(sid, f"/tasks/{tid}"), json={"confirm": True}, headers=w.O).status_code == 200
    assert db.sub_team_tasks().count_documents({}) == 0
    assert w.c.delete(w.url(sid, f"/tasks/{tid}") + "?confirm=true", headers=w.O).status_code == 404


def test_archived_sub_teams_are_read_only_for_tasks(w):
    sid = w.sub(member_ids=[w.a])
    tid = w.post(w.url(sid, "/tasks"), w.O, title="T", assignee_id=w.a).get_json()["data"]["task_id"]
    w.patch(w.url(sid), w.O, status="archived")
    assert w.post(w.url(sid, "/tasks"), w.O, title="New").status_code == 400
    assert w.patch(w.url(sid, f"/tasks/{tid}"), w.A, status="done").status_code == 400
    assert w.patch(w.url(sid, f"/tasks/{tid}"), w.O, status="done").status_code == 400
    assert w.get(w.url(sid, "/tasks"), w.A).get_json()["data"][0]["can_update_status"] is False


def test_task_count_is_capped(w, monkeypatch):
    sid = w.sub()
    monkeypatch.setattr(subteams, "MAX_TASKS", 2)
    assert w.post(w.url(sid, "/tasks"), w.O, title="1").status_code == 201
    assert w.post(w.url(sid, "/tasks"), w.O, title="2").status_code == 201
    assert w.post(w.url(sid, "/tasks"), w.O, title="3").status_code == 400


# =============================== no unrelated writes ==========================================================


def _snapshot():
    return {
        n: sorted(json.dumps(d, default=str, sort_keys=True) for d in getattr(db, n)().find({}, {"_id": 0}))
        for n in ("users", "profiles", "projects", "roadmap_progress", "sessions")
    }


def test_sub_team_activity_writes_nothing_outside_its_own_collections(w):
    _profile(w.c, w.A, skills=[{"name": "React", "level": "Beginner"}], share_with_teams=True)
    before = _snapshot()
    parent_before = json.dumps(db.teams().find_one({"team_id": w.tid}), default=str, sort_keys=True)
    sid = w.sub(member_ids=[w.a, w.b])
    code = w.invite(sid)
    w.post("/api/teams/sub-join", w.B, invite_code=code)
    w.post(w.url(sid, "/messages"), w.A, content="hi")
    w.get(w.url(sid, "/roles"), w.O)
    tid = w.post(w.url(sid, "/tasks"), w.O, title="T", assignee_id=w.a).get_json()["data"]["task_id"]
    w.patch(w.url(sid, f"/tasks/{tid}"), w.A, status="done")
    w.c.delete(w.url(sid), json={"confirm": True}, headers=w.O)
    assert _snapshot() == before
    assert json.dumps(db.teams().find_one({"team_id": w.tid}), default=str, sort_keys=True) == parent_before
