"""Post-implementation audit of sub-teams: deterministic races, archived behaviour,
owner self-membership, non-revealing denials and notification content.

Races are made deterministic by running the competing write INSIDE the window
between a request's parent-membership check and its own write (the wrapper below
fires once, right after the first parent-membership lookup)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import pytest

from db import client as db
from teams import service as team_service
from tests.test_sub_teams import World, raw

SUB_TYPES = ("subteam_added", "subteam_join", "subteam_message", "subteam_task")


@pytest.fixture
def w(client):
    return World(client)


def race_after_first_membership_check(monkeypatch, action):
    """Run `action()` immediately after the first parent-membership lookup of the
    request under test, i.e. between its check and its write."""
    real = team_service._member_team_or_none
    state = {"calls": 0}

    def wrapper(team_id, user_id):
        result = real(team_id, user_id)
        state["calls"] += 1
        if state["calls"] == 1:
            action()
        return result

    monkeypatch.setattr(team_service, "_member_team_or_none", wrapper)


def remove_from_parent(w, uid):
    db.teams().update_one({"team_id": w.tid}, {"$pull": {"members": {"user_id": uid}}})


# --- races -----------------------------------------------------------------------------------------------------------


def test_join_racing_a_parent_removal_is_refused_and_leaves_no_row(w, monkeypatch):
    sid = w.sub()
    code = w.invite(sid)
    race_after_first_membership_check(monkeypatch, lambda: remove_from_parent(w, w.b))
    res = w.post("/api/teams/sub-join", w.B, invite_code=code)
    assert res.status_code == 404 and "Backend" not in raw(res)  # no sub-team data handed to a removed user
    assert db.sub_teams().find_one()["members"] == []
    assert db.notifications().count_documents({"type": "subteam_join"}) == 0


def test_owner_add_racing_a_parent_removal_leaves_no_row(w, monkeypatch):
    sid = w.sub()
    race_after_first_membership_check(monkeypatch, lambda: remove_from_parent(w, w.b))
    res = w.post(w.url(sid, "/members"), w.O, user_id=w.b)
    assert res.status_code in (400, 404)
    assert db.sub_teams().find_one()["members"] == []
    assert db.notifications().count_documents({"type": "subteam_added"}) == 0


def test_join_racing_a_revocation_is_refused(w, monkeypatch):
    sid = w.sub()
    code = w.invite(sid)
    race_after_first_membership_check(monkeypatch, lambda: db.sub_teams().update_one({"sub_team_id": sid}, {"$unset": {"invite": ""}}))
    assert w.post("/api/teams/sub-join", w.A, invite_code=code).status_code == 404
    assert db.sub_teams().find_one()["members"] == []


def test_join_racing_expiry_is_refused(w, monkeypatch):
    sid = w.sub()
    code = w.invite(sid)
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    race_after_first_membership_check(monkeypatch, lambda: db.sub_teams().update_one({"sub_team_id": sid}, {"$set": {"invite.expires_at": past}}))
    assert w.post("/api/teams/sub-join", w.A, invite_code=code).status_code == 404
    assert db.sub_teams().find_one()["members"] == []


def test_join_racing_rotation_or_archiving_is_refused(w, monkeypatch):
    sid = w.sub()
    code = w.invite(sid)
    race_after_first_membership_check(monkeypatch, lambda: db.sub_teams().update_one({"sub_team_id": sid}, {"$set": {"status": "archived"}}))
    assert w.post("/api/teams/sub-join", w.A, invite_code=code).status_code == 404
    assert db.sub_teams().find_one()["members"] == []


def test_a_member_removed_from_the_parent_mid_assignment_cannot_use_the_task(w, monkeypatch):
    sid = w.sub(member_ids=[w.a])
    tid = w.post(w.url(sid, "/tasks"), w.O, title="T").get_json()["data"]["task_id"]
    real_lookup = team_service._member_team_or_none
    race_after_first_membership_check(monkeypatch, lambda: remove_from_parent(w, w.a))
    w.patch(w.url(sid, f"/tasks/{tid}"), w.O, assignee_id=w.a)  # may land: the assignee row is stale but inert
    monkeypatch.setattr(team_service, "_member_team_or_none", real_lookup)
    assert w.patch(w.url(sid, f"/tasks/{tid}"), w.A, status="done").status_code == 404
    shown = w.get(w.url(sid, "/tasks"), w.O).get_json()["data"][0]
    assert shown["assignee"] is None and (shown["needs_reassignment"] or db.sub_team_tasks().find_one()["assignee_id"] is None)
    w.post(w.url(sid, "/members"), w.O, user_id=w.b)
    assert w.patch(w.url(sid, f"/tasks/{tid}"), w.O, assignee_id=w.b).status_code == 200  # owner can reassign


def test_reading_a_sub_team_never_writes(w):
    sid = w.sub(member_ids=[w.a])
    db.sub_teams().update_one({"sub_team_id": sid}, {"$push": {"members": {"user_id": "ghost"}}})
    before = json.dumps(db.sub_teams().find_one(), default=str, sort_keys=True)
    for h in (w.O, w.A, w.B):
        w.get(w.url(), h)
        w.get(w.url(sid), h)
    assert json.dumps(db.sub_teams().find_one(), default=str, sort_keys=True) == before


# --- archived ---------------------------------------------------------------------------------------------------------


def test_archived_sub_teams_refuse_every_write_but_stay_readable(w):
    sid = w.sub(member_ids=[w.a])
    tid = w.post(w.url(sid, "/tasks"), w.O, title="T", assignee_id=w.a).get_json()["data"]["task_id"]
    w.post(w.url(sid, "/messages"), w.A, content="before")
    code = w.invite(sid)
    w.patch(w.url(sid), w.O, status="archived")

    writes = [
        w.post(w.url(sid, "/messages"), w.A, content="x"),
        w.post(w.url(sid, "/tasks"), w.O, title="x"),
        w.patch(w.url(sid, f"/tasks/{tid}"), w.O, title="x"),
        w.patch(w.url(sid, f"/tasks/{tid}"), w.A, status="done"),
        w.post(w.url(sid, "/members"), w.O, user_id=w.b),
        w.post(w.url(sid, "/invite"), w.O),
        w.c.put(w.url(sid, "/roles/mine"), json={"status": "rejected"}, headers=w.A),
        w.c.delete(w.url(sid, "/roles/mine"), headers=w.A),
        w.post("/api/teams/sub-join", w.B, invite_code=code),
    ]
    assert [r.status_code for r in writes] == [400, 400, 400, 400, 400, 400, 400, 400, 404]
    reads = [w.get(w.url(sid), w.A), w.get(w.url(sid, "/messages"), w.A), w.get(w.url(sid, "/tasks"), w.A), w.get(w.url(sid, "/roles"), w.A)]
    assert [r.status_code for r in reads] == [200, 200, 200, 200]
    assert db.sub_team_tasks().find_one()["status"] == "todo" and db.sub_team_messages().count_documents({}) == 1
    # The owner can still remove members, revoke the code, and delete.
    assert w.c.delete(w.url(sid, f"/members/{w.a}"), headers=w.O).status_code == 200
    assert w.c.delete(w.url(sid, "/invite"), headers=w.O).status_code == 200
    assert w.c.delete(w.url(sid), json={"confirm": True}, headers=w.O).status_code == 200


# --- owner self-membership -------------------------------------------------------------------------------------------


def test_the_owner_reads_chat_only_while_a_member_and_can_join_by_code(w):
    sid = w.sub(member_ids=[w.a])
    assert w.get(w.url(sid, "/messages"), w.O).status_code == 403
    w.post(w.url(sid, "/members"), w.O, user_id=w.o)
    assert w.get(w.url(sid, "/messages"), w.O).status_code == 200
    assert w.post(w.url(sid, "/messages"), w.O, content="hi").status_code == 201
    w.c.delete(w.url(sid, f"/members/{w.o}"), headers=w.O)
    assert w.get(w.url(sid, "/messages"), w.O).status_code == 403
    assert w.get(w.url(sid), w.O).status_code == 200  # still administers it
    code = w.invite(sid)
    assert w.post("/api/teams/sub-join", w.O, invite_code=code).status_code == 200
    assert w.get(w.url(sid, "/messages"), w.O).status_code == 200


# --- non-revealing denials ----------------------------------------------------------------------------------------------


def _probe(w, h, team_id, sid, task="task-x"):
    base = f"/api/teams/{team_id}/sub-teams"
    s = f"{base}/{sid}"
    calls = [
        w.c.get(s, headers=h), w.c.patch(s, json={"name": "x"}, headers=h), w.c.delete(s + "?confirm=true", headers=h),
        w.c.post(s + "/members", json={"user_id": w.a}, headers=h), w.c.delete(s + f"/members/{w.a}", headers=h),
        w.c.post(s + "/invite", json={}, headers=h), w.c.delete(s + "/invite", headers=h),
        w.c.get(s + "/messages", headers=h), w.c.post(s + "/messages", json={"content": "x"}, headers=h),
        w.c.get(s + "/roles", headers=h), w.c.put(s + "/roles/mine", json={"status": "rejected"}, headers=h),
        w.c.delete(s + "/roles/mine", headers=h), w.c.get(s + "/tasks", headers=h),
        w.c.post(s + "/tasks", json={"title": "x"}, headers=h), w.c.patch(s + f"/tasks/{task}", json={"status": "done"}, headers=h),
        w.c.delete(s + f"/tasks/{task}?confirm=true", headers=h),
    ]
    return [(r.status_code, json.dumps(r.get_json(), sort_keys=True)) for r in calls]


def test_a_parent_member_outside_the_sub_team_cannot_tell_it_from_one_that_does_not_exist(w):
    real = w.sub(member_ids=[w.a])
    w.post(w.url(real, "/tasks"), w.O, title="T")
    real_probe = _probe(w, w.B, w.tid, real)
    fake_probe = _probe(w, w.B, w.tid, "00000000-0000-0000-0000-000000000000")
    assert real_probe == fake_probe
    assert {status for status, _ in real_probe} == {404}


def test_an_outsider_cannot_tell_a_real_team_from_a_fake_one(w):
    real = w.sub()
    assert _probe(w, w.X, w.tid, real) == _probe(w, w.X, "no-such-team", real)
    assert {status for status, _ in _probe(w, w.X, w.tid, real)} == {404}


def test_denials_never_echo_the_submitted_invite_code(w, caplog):
    secret = "SECRETCODE"
    sid = w.sub()
    with caplog.at_level(logging.DEBUG):
        bad = w.post("/api/teams/sub-join", w.A, invite_code=secret)
        bad2 = w.c.post("/api/teams/join", json={"invite_code": secret}, headers=w.A)
    assert secret not in raw(bad) and secret not in raw(bad2)
    assert secret not in " | ".join(r.getMessage() for r in caplog.records if not r.name.startswith("pymongo"))


# --- notifications -----------------------------------------------------------------------------------------------------------


def _sub_notifications():
    return list(db.notifications().find({"type": {"$in": list(SUB_TYPES)}}, {"_id": 0}))


def test_notification_text_never_contains_chat_bodies_task_titles_or_invite_codes(w):
    sid = w.sub(member_ids=[w.a, w.b])
    code = w.invite(sid)
    w.post("/api/teams/sub-join", w.A, invite_code=code)
    w.post(w.url(sid, "/messages"), w.A, content="PRIVATE-CHAT-BODY-42")
    w.post(w.url(sid, "/tasks"), w.O, title="PRIVATE-TASK-TITLE", assignee_id=w.b)
    w.post(w.url(sid, "/members"), w.O, user_id=w.a)
    found = _sub_notifications()
    assert {n["type"] for n in found} >= {"subteam_added", "subteam_message", "subteam_task"}
    blob = json.dumps(found, default=str)
    for secret in ("PRIVATE-CHAT-BODY-42", "PRIVATE-TASK-TITLE", code, "code_hash", "@example.com"):
        assert secret not in blob, secret


def test_notification_recipients_are_only_currently_authorised_people(w):
    sid = w.sub(member_ids=[w.a, w.b])
    w.c.delete(w.url(sid, f"/members/{w.b}"), headers=w.O)  # off the sub-team
    w.post(w.url(sid, "/messages"), w.A, content="hello")
    w.c.delete(f"/api/teams/{w.tid}/members/{w.a}", headers=w.O)  # off the parent
    w.post(w.url(sid, "/members"), w.O, user_id=w.o)
    w.post(w.url(sid, "/messages"), w.O, content="owner here")
    recipients = [(n["type"], n["user_id"]) for n in _sub_notifications() if n["type"] == "subteam_message"]
    assert recipients == []  # the only members at message time were the sender (and, later, the owner alone)
    assert not [n for n in _sub_notifications() if n["user_id"] in (w.x,)]


def test_failed_membership_changes_send_no_notifications(w):
    sid = w.sub()
    assert w.post(w.url(sid, "/members"), w.O, user_id=w.x).status_code == 400  # outsider
    assert w.post(w.url(sid, "/tasks"), w.O, title="T", assignee_id=w.x).status_code == 400
    assert w.post("/api/teams/sub-join", w.X, invite_code="ZZZZZZZZZZ").status_code == 404
    assert _sub_notifications() == []


def test_notifications_carry_no_access_the_list_is_per_user(w):
    sid = w.sub(member_ids=[w.a, w.b])
    w.post(w.url(sid, "/messages"), w.A, content="hello")
    seen_b = w.get("/api/notifications", w.B).get_json()["data"]
    assert any(n["type"] == "subteam_message" for n in seen_b)
    assert not any(n["type"].startswith("subteam") for n in w.get("/api/notifications", w.X).get_json()["data"])
    assert not any(n["type"] == "subteam_message" for n in w.get("/api/notifications", w.A).get_json()["data"])  # not the sender
    # Having one gives no access once membership is gone.
    w.c.delete(f"/api/teams/{w.tid}/members/{w.b}", headers=w.O)
    assert w.get(w.url(sid, "/messages"), w.B).status_code == 404


# --- task assignment races (stale assignment vs. actual authorisation) --------------------------------------------------


def remove_from_sub_team(w, sid, uid):
    db.sub_teams().update_one({"sub_team_id": sid}, {"$pull": {"members": {"user_id": uid}}})


def test_creating_an_assigned_task_while_the_assignee_is_removed_from_the_parent(w, monkeypatch):
    sid = w.sub(member_ids=[w.a, w.b])
    race_after_first_membership_check(monkeypatch, lambda: remove_from_parent(w, w.b))
    res = w.post(w.url(sid, "/tasks"), w.O, title="Doomed", assignee_id=w.b)
    assert res.status_code == 400
    assert db.sub_team_tasks().count_documents({}) == 0  # no half-assigned task is left behind
    assert db.notifications().count_documents({"type": "subteam_task"}) == 0


def test_reassigning_while_the_new_assignee_is_removed_from_the_parent(w, monkeypatch):
    sid = w.sub(member_ids=[w.a, w.b])
    tid = w.post(w.url(sid, "/tasks"), w.O, title="Original", assignee_id=w.a).get_json()["data"]["task_id"]
    race_after_first_membership_check(monkeypatch, lambda: remove_from_parent(w, w.b))
    res = w.patch(w.url(sid, f"/tasks/{tid}"), w.O, assignee_id=w.b, title="Changed", status="blocked")
    assert res.status_code == 400
    task = db.sub_team_tasks().find_one()
    assert (task["assignee_id"], task["title"], task["status"]) == (w.a, "Original", "todo")  # the whole call is undone
    assert db.notifications().count_documents({"type": "subteam_task", "user_id": w.b}) == 0


def test_reassigning_while_the_new_assignee_is_removed_from_the_sub_team(w, monkeypatch):
    sid = w.sub(member_ids=[w.a, w.b])
    tid = w.post(w.url(sid, "/tasks"), w.O, title="T", assignee_id=w.a).get_json()["data"]["task_id"]
    from teams import subteams

    real_check = subteams._assignee

    def check_then_remove(value, acc):
        result = real_check(value, acc)  # the request's own membership check passes...
        remove_from_sub_team(w, sid, w.b)  # ...then the owner removes them from the sub-team
        return result

    monkeypatch.setattr(subteams, "_assignee", check_then_remove)
    assert w.patch(w.url(sid, f"/tasks/{tid}"), w.O, assignee_id=w.b).status_code == 400
    assert db.sub_team_tasks().find_one()["assignee_id"] == w.a


def test_a_valid_assignment_is_unaffected_by_the_recheck(w):
    sid = w.sub(member_ids=[w.a, w.b])
    tid = w.post(w.url(sid, "/tasks"), w.O, title="T", assignee_id=w.a).get_json()["data"]["task_id"]
    res = w.patch(w.url(sid, f"/tasks/{tid}"), w.O, assignee_id=w.b, status="in_progress")
    assert res.status_code == 200 and res.get_json()["data"]["assignee"]["user_id"] == w.b
    assert db.notifications().count_documents({"type": "subteam_task", "user_id": w.b}) == 1


def test_a_stale_assignment_is_inert_for_reads_updates_and_everyone_else(w, monkeypatch):
    """Even with every cleanup path disabled, a stale assignee_id grants nothing, other
    members keep full access, and the owner can reassign to a valid current member."""
    from teams import subteams

    monkeypatch.setattr(subteams, "on_parent_member_removed", lambda *a, **k: None)
    sid = w.sub(member_ids=[w.a, w.b])
    stale = w.post(w.url(sid, "/tasks"), w.O, title="Stale", assignee_id=w.a).get_json()["data"]["task_id"]
    other = w.post(w.url(sid, "/tasks"), w.O, title="Bobs", assignee_id=w.b).get_json()["data"]["task_id"]
    w.c.delete(f"/api/teams/{w.tid}/members/{w.a}", headers=w.O)
    assert db.sub_team_tasks().find_one({"task_id": stale})["assignee_id"] == w.a  # genuinely stale

    # The removed user: no read, no update, no delete, no chat, no sub-team detail.
    assert w.get(w.url(sid, "/tasks"), w.A).status_code == 404
    assert w.patch(w.url(sid, f"/tasks/{stale}"), w.A, status="done").status_code == 404
    assert w.c.delete(w.url(sid, f"/tasks/{stale}") + "?confirm=true", headers=w.A).status_code == 404
    assert w.get(w.url(sid), w.A).status_code == 404
    # An authorised member still sees both tasks (the stale one flagged) and can update their own.
    shown = {t["title"]: t for t in w.get(w.url(sid, "/tasks"), w.B).get_json()["data"]}
    assert set(shown) == {"Stale", "Bobs"} and shown["Stale"]["needs_reassignment"] is True and shown["Stale"]["assignee"] is None
    assert w.patch(w.url(sid, f"/tasks/{other}"), w.B, status="done").status_code == 200
    # ...but not the stale one (it is not theirs), and the stale assignee's name is not exposed.
    assert w.patch(w.url(sid, f"/tasks/{stale}"), w.B, status="done").status_code == 403
    assert "Ann" not in raw(w.get(w.url(sid, "/tasks"), w.B))
    # The owner reassigns to a valid current member.
    res = w.patch(w.url(sid, f"/tasks/{stale}"), w.O, assignee_id=w.b)
    assert res.status_code == 200 and res.get_json()["data"]["needs_reassignment"] is False
    assert w.patch(w.url(sid, f"/tasks/{stale}"), w.B, status="in_progress").status_code == 200
