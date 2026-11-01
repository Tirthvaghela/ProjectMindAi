"""Notification privacy: a team/sub-team message notification says THAT a message exists,
never what it says. Synthetic text, throwaway test database only."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import pytest

import notify
from db import client as db
from teams import service
from tests.test_sub_teams import World

SECRET = "ZEBRA-PASSWORD-hunter2-DISTINCTIVE"


@pytest.fixture
def w(client):
    return World(client)


def stored(type_):
    return list(db.notifications().find({"type": type_}, {"_id": 0}))


def test_a_parent_team_message_notification_is_generic(w):
    res = w.c.post(f"/api/teams/{w.tid}/messages", json={"content": SECRET}, headers=w.A)
    assert res.status_code == 201
    rows = stored("team_message")
    assert {r["user_id"] for r in rows} == {w.o, w.b}  # everyone but the sender
    for row in rows:
        assert row["body"] == service.TEAM_MESSAGE_NOTIFICATION_BODY == "A new message was posted in your team."
        assert SECRET not in json.dumps(row, default=str) and "hunter2" not in json.dumps(row, default=str)
        assert "Ann" not in row["body"]  # no "author: text" preview of any kind
        assert row["title"] == "New message in Parent"
        assert (row["type"], row["team_id"], row["project_id"], row["read"]) == ("team_message", w.tid, "pm-sub", False)
        assert set(row) == {"notification_id", "user_id", "type", "title", "body", "team_id", "project_id", "read", "created_at"}


def test_the_chat_itself_is_unchanged(w):
    w.c.post(f"/api/teams/{w.tid}/messages", json={"content": SECRET}, headers=w.A)
    messages = w.c.get(f"/api/teams/{w.tid}/messages", headers=w.O).get_json()["data"]
    assert [m["content"] for m in messages] == [SECRET] and messages[0]["author_name"] == "Ann"
    assert db.team_messages().find_one({"team_id": w.tid})["content"] == SECRET


def test_long_and_markup_messages_never_reach_a_notification(w):
    for text in ("x" * 2000, "<script>alert('" + SECRET + "')</script>", "**" + SECRET + "**\n" + SECRET):
        w.c.post(f"/api/teams/{w.tid}/messages", json={"content": text}, headers=w.B)
    assert SECRET not in json.dumps(list(db.notifications().find({}, {"_id": 0})), default=str)
    assert {r["body"] for r in stored("team_message")} == {service.TEAM_MESSAGE_NOTIFICATION_BODY}


def test_recipients_and_other_notification_types_are_unchanged(w):
    w.c.post(f"/api/teams/{w.tid}/messages", json={"content": "hi"}, headers=w.A)
    assert len(stored("team_message")) == 2
    assert [r["user_id"] for r in stored("team_message") if r["user_id"] == w.a] == []  # never the sender
    joins = stored("team_join")
    assert joins and all(r["body"].endswith("for Campus Marketplace.") for r in joins)  # unrelated wording untouched
    w.c.delete(f"/api/teams/{w.tid}/members/{w.b}", headers=w.O)
    leaves = stored("team_leave")
    assert leaves and all("is no longer on your team" in r["body"] for r in leaves)
    # A removed member receives nothing further.
    before = len([r for r in stored("team_message") if r["user_id"] == w.b])
    w.c.post(f"/api/teams/{w.tid}/messages", json={"content": "after"}, headers=w.A)
    assert len([r for r in stored("team_message") if r["user_id"] == w.b]) == before


def test_sub_team_notifications_stay_generic(w):
    sid = w.sub(member_ids=[w.a, w.b])
    w.post(w.url(sid, "/messages"), w.A, content=SECRET)
    w.post(w.url(sid, "/tasks"), w.O, title=SECRET, description=SECRET, assignee_id=w.b)
    rows = list(db.notifications().find({"type": {"$regex": "^subteam_"}}, {"_id": 0}))
    assert {r["type"] for r in rows} >= {"subteam_message", "subteam_task", "subteam_added"}
    assert SECRET not in json.dumps(rows, default=str)


def test_the_api_returns_the_same_shape_and_legacy_records_are_served_unchanged(w):
    db.notifications().insert_one({
        "notification_id": "legacy-1", "user_id": w.b, "type": "team_message", "title": "New message in Parent",
        "body": "Sam: legacy snippet kept until the separately approved redaction", "team_id": w.tid, "project_id": None,
        "read": False, "created_at": datetime.now(timezone.utc),
    })
    w.c.post(f"/api/teams/{w.tid}/messages", json={"content": SECRET}, headers=w.A)
    rows = w.c.get("/api/notifications", headers=w.B).get_json()["data"]
    bodies = {r["notification_id"]: r["body"] for r in rows}
    assert bodies["legacy-1"].startswith("Sam: legacy snippet")  # not rewritten by this change
    assert service.TEAM_MESSAGE_NOTIFICATION_BODY in bodies.values()
    assert all(set(r) >= {"notification_id", "type", "title", "body", "team_id", "read", "created_at"} for r in rows)


# --- email path and failures (fake SMTP; nothing is sent) --------------------------------------------------------------------


class FakeSMTP:
    sent: list = []
    fail = False

    def __init__(self, host, port, timeout=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        if FakeSMTP.fail:
            raise RuntimeError("smtp login rejected")

    def send_message(self, message):
        FakeSMTP.sent.append(message)


@pytest.fixture
def fake_mail(monkeypatch):
    FakeSMTP.sent, FakeSMTP.fail = [], False
    monkeypatch.setattr(notify.config, "SMTP_ENABLED", True)
    monkeypatch.setattr(notify.config, "SMTP_HOST", "smtp.invalid")
    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


def test_the_email_subject_and_body_never_contain_the_message(w, fake_mail):
    w.c.post(f"/api/teams/{w.tid}/messages", json={"content": SECRET}, headers=w.A)
    assert len(fake_mail.sent) == 2
    for message in fake_mail.sent:
        text = str(message["Subject"]) + message.get_content()
        assert SECRET not in text and "Ann:" not in text
        assert "A new message was posted in your team." in message.get_content()


def test_a_mail_failure_neither_raises_nor_exposes_the_message(w, fake_mail, caplog):
    fake_mail.fail = True
    with caplog.at_level(logging.DEBUG):
        res = w.c.post(f"/api/teams/{w.tid}/messages", json={"content": SECRET}, headers=w.A)
    assert res.status_code == 201  # the in-app notification and the message still succeed
    assert len(stored("team_message")) == 2
    logs = " | ".join(r.getMessage() + (r.exc_text or "") for r in caplog.records if not r.name.startswith("pymongo"))
    assert SECRET not in logs and "hunter2" not in logs
    assert res.get_json()["data"]["content"] == SECRET  # the author gets their own message back, as before


def test_a_failing_notification_store_does_not_expose_the_message(w, monkeypatch, caplog):
    def boom(*a, **k):
        raise RuntimeError("notification store down")

    monkeypatch.setattr(service, "notify", boom)
    with caplog.at_level(logging.DEBUG):
        res = w.c.post(f"/api/teams/{w.tid}/messages", json={"content": SECRET}, headers=w.A)
    body = res.get_data(as_text=True)
    assert res.status_code == 500 and SECRET not in body  # the error response carries no message text
    logs = " | ".join(r.getMessage() + (r.exc_text or "") for r in caplog.records if not r.name.startswith("pymongo"))
    assert SECRET not in logs.replace("notification store down", "")
