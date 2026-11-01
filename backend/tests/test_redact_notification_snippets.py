"""scripts/redact_notification_snippets.py - exercised only on the throwaway test database."""

from __future__ import annotations

from datetime import datetime, timezone

import config
from db import client as db
from scripts import redact_notification_snippets as redact


def note(n, type_, body, **extra):
    return {"notification_id": n, "user_id": f"u-{n}", "type": type_, "title": f"title-{n}", "body": body,
            "team_id": "t1", "project_id": None, "read": n == "d", "created_at": datetime.now(timezone.utc), **extra}


def seed():
    db.notifications().insert_many([
        note("a", "team_message", "Sam: the admin password is hunter2"),
        note("b", "subteam_message", "Sam: private sub-team text"),
        note("c", "subteam_task", "You were assigned: Fire the intern"),
        note("d", "team_join", "Sam joined your team for X."),
        note("e", "team_leave", "Sam is no longer on your team."),
        note("f", "team_message", redact.GENERIC_BODY["team_message"]),
    ])


def snapshot():
    return {d["notification_id"]: d for d in db.notifications().find({}, {"_id": 0})}


def test_dry_run_reports_counts_and_changes_nothing(mongo_test_db, capsys):
    seed()
    before = snapshot()
    assert redact.plan() == {"team_message": 1, "subteam_message": 1, "subteam_task": 1}
    assert redact.main([]) == 0
    out = capsys.readouterr().out
    assert "dry run" in out and "hunter2" not in out and "intern" not in out  # counts only, never contents
    assert snapshot() == before


def test_apply_redacts_only_the_target_bodies_and_is_idempotent(mongo_test_db):
    seed()
    before = snapshot()
    assert redact.apply() == {"team_message": 1, "subteam_message": 1, "subteam_task": 1}
    after = snapshot()
    assert after["a"]["body"] == redact.GENERIC_BODY["team_message"]
    assert after["b"]["body"] == redact.GENERIC_BODY["subteam_message"]
    assert after["c"]["body"] == redact.GENERIC_BODY["subteam_task"]
    for key in ("d", "e", "f"):
        assert after[key] == before[key]  # other types and already-generic records untouched
    for key in ("a", "b", "c"):  # nothing but the body changed
        assert {k: v for k, v in after[key].items() if k != "body"} == {k: v for k, v in before[key].items() if k != "body"}
    assert redact.apply() == {"team_message": 0, "subteam_message": 0, "subteam_task": 0}
    assert redact.plan() == {"team_message": 0, "subteam_message": 0, "subteam_task": 0}


def _stub(monkeypatch, name):
    """Point the script at database `name` with plan()/apply() stubbed, so that no test in
    this group can touch any real collection while the configured name is a live-looking one."""
    monkeypatch.setattr(config, "MONGO_DB", name)
    calls = {"plan": 0, "apply": 0}
    monkeypatch.setattr(redact, "plan", lambda: calls.__setitem__("plan", calls["plan"] + 1) or {t: 0 for t in redact.GENERIC_BODY})
    monkeypatch.setattr(redact, "apply", lambda: calls.__setitem__("apply", calls["apply"] + 1) or {t: 0 for t in redact.GENERIC_BODY})
    return calls


def test_apply_fails_closed_on_any_non_throwaway_database_name(mongo_test_db, monkeypatch, capsys):
    for name in ("projectmind", "projectmind_prod", "prod", "anything_else", ""):
        calls = _stub(monkeypatch, name)
        assert redact.main(["--apply"]) == 2, name
        assert redact.main(["--apply", "--confirm-database", "some-other-db"]) == 2, name
        assert redact.main(["--apply", "--confirm-database", ""]) == 2, name
        assert calls == {"plan": 0, "apply": 0}  # refused before touching the database at all
    assert "refusing" in capsys.readouterr().err


def test_an_exact_database_name_is_the_only_override(mongo_test_db, monkeypatch):
    calls = _stub(monkeypatch, "my_real_database")
    assert redact.main(["--apply", "--confirm-database", "my_real_database"]) == 0
    assert calls == {"plan": 1, "apply": 1}


def test_throwaway_prefixes_need_no_confirmation(mongo_test_db, monkeypatch):
    for name in ("projectmind_test_123", "projectmind_e2e_run1"):
        calls = _stub(monkeypatch, name)
        assert redact.main(["--apply"]) == 0 and calls["apply"] == 1
    assert not redact.is_throwaway("projectmind") and not redact.is_throwaway("prod") and not redact.is_throwaway("")


def test_no_environment_variable_or_old_flag_can_override_the_guard(mongo_test_db, monkeypatch):
    for key in ("CONFIRM_DATABASE", "REDACT_CONFIRM", "LIVE_OK", "I_HAVE_A_BACKUP_AND_APPROVAL", "FORCE"):
        monkeypatch.setenv(key, "projectmind")
    calls = _stub(monkeypatch, "projectmind")
    assert redact.main(["--apply"]) == 2 and calls["apply"] == 0
    try:
        redact.main(["--apply", "--i-have-a-backup-and-approval"])  # the removed boolean flag is no longer accepted
    except SystemExit as exit_:
        assert exit_.code == 2
    assert calls["apply"] == 0


def test_a_dry_run_on_a_non_throwaway_database_never_applies(mongo_test_db, monkeypatch, capsys):
    calls = _stub(monkeypatch, "projectmind")
    assert redact.main([]) == 0
    assert calls == {"plan": 1, "apply": 0} and "dry run" in capsys.readouterr().out


def test_an_interrupted_run_leaves_consistent_records_and_a_rerun_finishes(mongo_test_db, monkeypatch):
    seed()
    before = snapshot()

    class Boom:
        def __init__(self, coll):
            self._coll, self._updates = coll, 0

        def update_many(self, *a, **k):
            self._updates += 1
            if self._updates == 2:
                raise RuntimeError("connection lost")
            return self._coll.update_many(*a, **k)

        def __getattr__(self, name):
            return getattr(self._coll, name)

    real = db.notifications
    boom = Boom(real())
    monkeypatch.setattr(db, "notifications", lambda: boom)
    try:
        redact.apply()
        raise AssertionError("expected the simulated failure")
    except RuntimeError:
        pass
    monkeypatch.setattr(db, "notifications", real)
    partial = snapshot()
    assert partial["a"]["body"] == redact.GENERIC_BODY["team_message"]  # first type done
    assert partial["b"] == before["b"] and partial["c"] == before["c"]  # the rest untouched, not half-written
    assert redact.apply() == {"team_message": 0, "subteam_message": 1, "subteam_task": 1}  # rerun completes
    assert redact.plan() == {"team_message": 0, "subteam_message": 0, "subteam_task": 0}


def test_the_script_sends_nothing_creates_nothing_and_logs_no_contents(mongo_test_db, caplog, capsys):
    import inspect

    seed()
    count = db.notifications().count_documents({})
    with caplog.at_level("DEBUG"):
        redact.main(["--apply"])  # the configured database here is the throwaway test one
    out = capsys.readouterr().out + " | ".join(r.getMessage() for r in caplog.records if not r.name.startswith("pymongo"))
    assert "hunter2" not in out and "intern" not in out and "private sub-team" not in out
    assert db.notifications().count_documents({}) == count  # no notification created
    assert not hasattr(redact, "notify") and "notify" not in inspect.getsource(redact).replace("notification", "")  # no mail path


def test_the_generic_team_message_text_matches_what_the_code_now_writes():
    from teams import service

    assert redact.GENERIC_BODY["team_message"] == service.TEAM_MESSAGE_NOTIFICATION_BODY
