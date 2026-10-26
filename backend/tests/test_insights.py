"""Skill progress & profile insights (Feature 8): profiles/insights.py,
GET /api/insights/me, and the read-only `get_my_progress` assistant tool.

The property under test: insights are a faithful, current-state reading of what the
student declared (profile) and what they recorded (roadmap step statuses) - kept
separate, scoped to the signed-in account, never inventing history or levels, and
never writing anything.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone

import pytest

from db import client as db
from nlp import ai_assistant, personal_tools, recommend
from profiles import insights
from tests.test_assistant_routes import _text_completion, _tool_call_completion
from tests.test_personal_assistant import Script, signup

DOC = {
    "project_id": "pm-x", "title": "Campus Marketplace", "domain": "Web Development", "difficulty": "Intermediate",
    "description": "A marketplace.", "technologies": ["React", "Node.js", "PostgreSQL"], "skills": ["REST API development"],
    "keywords": [], "duration_weeks": 8,
}
DOC2 = {**DOC, "project_id": "pm-y", "title": "Study Planner", "technologies": ["Python", "Flask"], "skills": []}


class _Fake:
    def __init__(self, docs):
        self.documents = docs


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)


@pytest.fixture
def api(client, monkeypatch):
    docs = {"pm-x": copy.deepcopy(DOC), "pm-y": copy.deepcopy(DOC2)}
    monkeypatch.setattr(recommend, "get_retriever", lambda: _Fake(docs))
    return client


def save_profile(client, h, **fields):
    res = client.put("/api/profile", json=fields, headers=h)
    assert res.status_code == 200, res.get_json()
    return res.get_json()["data"]


def roadmap(client, h, project="pm-x"):
    return client.get(f"/api/roadmap/me?project_id={project}", headers=h).get_json()["data"]


def mark(client, h, step_id, status, project="pm-x"):
    res = client.put("/api/roadmap/me/progress", json={"project_id": project, "step_id": step_id, "status": status}, headers=h)
    assert res.status_code == 200, res.get_json()
    return res.get_json()["data"]


def get(client, h):
    res = client.get("/api/insights/me", headers=h)
    assert res.status_code == 200, res.get_json()
    return res.get_json()["data"]


PROFILE = {"skills": [{"name": "Python", "level": "Intermediate"}, {"name": "React", "level": "Beginner"}]}


def snapshot():
    return {
        name: sorted(json.dumps(d, default=str, sort_keys=True) for d in getattr(db, name)().find({}, {"_id": 0}))
        for name in ("profiles", "roadmap_progress", "teams", "users", "notifications")
    }


# --- auth & shape -------------------------------------------------------------------------------------


def test_requires_sign_in(api):
    assert api.get("/api/insights/me").status_code == 401
    assert api.get("/api/insights/me", headers={"X-Device-Id": "dev"}).status_code == 401


def test_rejects_query_parameters_including_account_ids(api):
    h, me = signup(api, "a@example.com", "Ada")
    for qs in ("?user_id=someone", "?email=x@y.z", "?limit=5"):
        assert api.get("/api/insights/me" + qs, headers=h).status_code == 400


def test_other_methods_are_not_allowed(api):
    h, _ = signup(api, "a@example.com", "Ada")
    for method in ("post", "put", "delete", "patch"):
        assert getattr(api, method)("/api/insights/me", headers=h).status_code == 405


def test_no_profile_and_no_progress_is_an_honest_empty_state(api):
    h, _ = signup(api, "a@example.com", "Ada")
    data = get(api, h)
    assert data["profile"]["status"] == "not_started" and data["profile"]["skill_count"] == 0
    assert data["profile_skills"] == []
    learning = data["learning"]
    assert learning["started"] is False and learning["projects_with_progress"] == 0
    assert learning["totals"] == {"completed": 0, "in_progress": 0, "remaining": 0, "total_steps": 0}
    assert learning["skills_worked_on"] == [] and learning["recent_activity"] == []
    assert data["history"]["available"] is False
    # The only suggestion is to build the profile; nothing is made up.
    assert [s["type"] for s in data["next_steps"]["items"]] == ["profile"]
    assert data["next_steps"]["items"][0]["link"] == "/profile"
    # Reading creates nothing.
    assert db.profiles().count_documents({}) == 0 and db.roadmap_progress().count_documents({}) == 0


def test_response_has_no_account_identifiers(api):
    h, me = signup(api, "a@example.com", "Ada")
    save_profile(api, h, **PROFILE)
    mark(api, h, roadmap(api, h)["steps"][0]["id"], "completed")
    data = get(api, h)
    raw = json.dumps(data)
    for private in (me["user_id"], "a@example.com", '"user_id"', "token", "password"):
        assert private not in raw

    def keys(node):
        if isinstance(node, dict):
            for k, v in node.items():
                yield k
                yield from keys(v)
        elif isinstance(node, list):
            for v in node:
                yield from keys(v)

    assert "_id" not in set(keys(data))  # no Mongo internals


# --- aggregation ----------------------------------------------------------------------------------------


def test_profile_section_counts_declared_levels(api):
    h, _ = signup(api, "a@example.com", "Ada")
    save_profile(api, h, skills=[{"name": "Python", "level": "Advanced"}, {"name": "React", "level": "Beginner"}, {"name": "SQL", "level": "Beginner"}])
    profile = get(api, h)["profile"]
    assert profile["skill_count"] == 3
    assert profile["level_counts"] == {"Beginner": 2, "Intermediate": 0, "Advanced": 1}
    assert "self-reported" in profile["provenance"]


def test_counts_completed_in_progress_and_remaining_from_saved_statuses(api):
    h, _ = signup(api, "a@example.com", "Ada")
    save_profile(api, h, **PROFILE)
    steps = roadmap(api, h)["steps"]
    assert len(steps) >= 3
    mark(api, h, steps[0]["id"], "completed")
    mark(api, h, steps[1]["id"], "in_progress")
    learning = get(api, h)["learning"]
    assert learning["totals"] == {"completed": 1, "in_progress": 1, "remaining": len(steps) - 2, "total_steps": len(steps)}
    assert learning["started"] is True
    (project,) = learning["projects"]
    assert project["project_id"] == "pm-x" and project["title"] == "Campus Marketplace"
    assert (project["completed"], project["in_progress"], project["remaining"]) == (1, 1, len(steps) - 2)


def test_viewing_a_roadmap_or_recommendations_records_no_progress(api):
    h, _ = signup(api, "a@example.com", "Ada")
    save_profile(api, h, **PROFILE)
    roadmap(api, h)
    roadmap(api, h, "pm-y")
    api.get("/api/profile", headers=h)
    learning = get(api, h)["learning"]
    assert learning["started"] is False and learning["totals"]["completed"] == 0 and learning["skills_worked_on"] == []


def test_not_started_clears_a_step_so_it_is_not_counted(api):
    h, _ = signup(api, "a@example.com", "Ada")
    save_profile(api, h, **PROFILE)
    sid = roadmap(api, h)["steps"][0]["id"]
    mark(api, h, sid, "completed")
    mark(api, h, sid, "not_started")
    assert get(api, h)["learning"]["totals"]["completed"] == 0


def test_skills_worked_on_come_from_recorded_steps_only(api):
    h, _ = signup(api, "a@example.com", "Ada")
    save_profile(api, h, **PROFILE)
    steps = roadmap(api, h)["steps"]
    mark(api, h, steps[0]["id"], "completed")
    mark(api, h, steps[1]["id"], "in_progress")
    worked = {w["skill"]: w for w in get(api, h)["learning"]["skills_worked_on"]}
    assert set(worked) == set(steps[0]["skills"]) | set(steps[1]["skills"])
    assert worked[steps[0]["skill"]]["recorded_status"] == "completed"
    assert worked[steps[1]["skill"]]["recorded_status"] == "in_progress"


def test_progress_across_two_projects_is_summed_with_one_progress_query(api, monkeypatch):
    h, _ = signup(api, "a@example.com", "Ada")
    save_profile(api, h, **PROFILE)
    mark(api, h, roadmap(api, h)["steps"][0]["id"], "completed")
    mark(api, h, roadmap(api, h, "pm-y")["steps"][0]["id"], "in_progress", project="pm-y")

    calls = []
    real = db.roadmap_progress

    class Counting:
        def __init__(self, coll):
            self.coll = coll

        def find(self, *a, **k):
            calls.append(("find", a))
            return self.coll.find(*a, **k)

        def __getattr__(self, name):
            calls.append((name, ()))
            return getattr(self.coll, name)

    monkeypatch.setattr(db, "roadmap_progress", lambda: Counting(real()))
    data = get(api, h)
    assert len(calls) == 1 and calls[0][0] == "find"  # no per-project queries
    assert {p["project_id"] for p in data["learning"]["projects"]} == {"pm-x", "pm-y"}
    assert data["learning"]["totals"]["completed"] == 1 and data["learning"]["totals"]["in_progress"] == 1


# --- declared vs recorded -------------------------------------------------------------------------------------


def test_completing_a_step_never_changes_the_declared_level(api):
    h, _ = signup(api, "a@example.com", "Ada")
    save_profile(api, h, **PROFILE)
    before = api.get("/api/profile", headers=h).get_json()["data"]
    for step in roadmap(api, h)["steps"]:
        mark(api, h, step["id"], "completed")
    after = api.get("/api/profile", headers=h).get_json()["data"]
    assert after["skills"] == before["skills"] and after["updated_at"] == before["updated_at"]
    data = get(api, h)
    levels = {s["name"]: s["declared_level"] for s in data["profile_skills"]}
    assert levels == {"Python": "Intermediate", "React": "Beginner"}


def test_profile_skills_are_flagged_as_recorded_only_when_a_step_was_recorded(api):
    h, _ = signup(api, "a@example.com", "Ada")
    save_profile(api, h, **PROFILE)
    data = get(api, h)
    assert {s["recorded_progress"] for s in data["profile_skills"]} == {"none"}
    # A completed step for a skill on the profile marks it as recorded, level unchanged.
    for step in roadmap(api, h)["steps"]:
        if any(s.lower() == "react" for s in step["skills"]):
            mark(api, h, step["id"], "completed")
    data = get(api, h)
    react = next(s for s in data["profile_skills"] if s["name"] == "React")
    python = next(s for s in data["profile_skills"] if s["name"] == "Python")
    assert python["recorded_progress"] == "none"
    assert react["declared_level"] == "Beginner"
    if react["recorded_progress"] != "none":
        assert react["recorded_progress"] == "completed"


def test_profile_review_prompts_for_completed_skills_not_on_profile(api):
    h, _ = signup(api, "a@example.com", "Ada")
    save_profile(api, h, skills=[{"name": "Python", "level": "Intermediate"}])
    steps = roadmap(api, h)["steps"]
    sid = steps[0]["id"]
    mark(api, h, sid, "completed")
    data = get(api, h)
    review = {r["skill"]: r for r in data["profile_review"]}
    assert steps[0]["skill"] in review
    assert "not on your profile" in review[steps[0]["skill"]]["reason"]
    # It asks; it never states or applies a new level.
    assert all(set(r) == {"skill", "declared_level", "reason"} for r in data["profile_review"])


def test_in_progress_alone_does_not_prompt_a_profile_review(api):
    h, _ = signup(api, "a@example.com", "Ada")
    save_profile(api, h, **PROFILE)
    mark(api, h, roadmap(api, h)["steps"][0]["id"], "in_progress")
    assert get(api, h)["profile_review"] == []


# --- history ------------------------------------------------------------------------------------------------------


def test_history_is_declared_unavailable_and_no_dates_are_invented(api):
    h, _ = signup(api, "a@example.com", "Ada")
    save_profile(api, h, **PROFILE)
    sid = roadmap(api, h)["steps"][0]["id"]
    mark(api, h, sid, "completed")
    data = get(api, h)
    assert data["history"]["available"] is False and "cannot be shown" in data["history"]["note"]
    (event,) = data["learning"]["recent_activity"]
    stored = db.roadmap_progress().find_one({})["steps"][sid]["updated_at"]
    assert event["status_set_at"][:19] == stored.replace(tzinfo=timezone.utc).isoformat()[:19]
    assert not any(k in data for k in ("timeline", "level_history", "achievements", "badges", "score", "skill_scores"))


def test_missing_timestamp_is_null_not_made_up(api):
    h, me = signup(api, "a@example.com", "Ada")
    save_profile(api, h, **PROFILE)
    sid = roadmap(api, h)["steps"][0]["id"]
    db.roadmap_progress().insert_one({"user_id": me["user_id"], "project_id": "pm-x", "steps": {sid: {"status": "completed", "label": "x"}}})
    (event,) = get(api, h)["learning"]["recent_activity"]
    assert event["status_set_at"] is None


def test_recent_activity_is_ordered_newest_first(api):
    h, me = signup(api, "a@example.com", "Ada")
    save_profile(api, h, **PROFILE)
    ids = [s["id"] for s in roadmap(api, h)["steps"][:3]]
    db.roadmap_progress().insert_one({
        "user_id": me["user_id"], "project_id": "pm-x", "updated_at": datetime(2026, 3, 1),
        "steps": {
            ids[0]: {"status": "completed", "label": "a", "updated_at": datetime(2026, 1, 1)},
            ids[1]: {"status": "completed", "label": "b", "updated_at": datetime(2026, 3, 1)},
            ids[2]: {"status": "in_progress", "label": "c", "updated_at": datetime(2026, 2, 1)},
        },
    })
    stamps = [e["status_set_at"] for e in get(api, h)["learning"]["recent_activity"]]
    assert stamps == sorted(stamps, reverse=True) and len(stamps) == 3


# --- legacy / malformed data ---------------------------------------------------------------------------------------


def test_malformed_legacy_progress_documents_are_skipped_not_trusted(api):
    h, me = signup(api, "a@example.com", "Ada")
    save_profile(api, h, **PROFILE)
    good = roadmap(api, h)["steps"][0]["id"]
    uid = me["user_id"]
    db.roadmap_progress().insert_many([
        {"user_id": uid, "project_id": "pm-x", "steps": {good: {"status": "completed", "label": "ok", "updated_at": datetime(2026, 1, 1)},
                                                          "weird": "completed", "also": {"status": "mastered"}, "none": None}},
        {"user_id": uid, "project_id": "pm-y", "steps": "not-a-dict"},
        {"user_id": uid, "project_id": "pm-gone", "steps": {"s": {"status": "completed", "label": "Old"}}},
        {"user_id": uid, "project_id": 42, "steps": {}},
        {"user_id": uid, "project_id": None},
    ])
    data = get(api, h)
    learning = data["learning"]
    assert learning["totals"]["completed"] == 1  # only the well-formed step on a known project
    assert learning["projects_unavailable"] == 3  # unknown / non-string project ids are reported, not counted as progress
    assert all(w["skill"] for w in learning["skills_worked_on"])


def test_saved_step_the_roadmap_no_longer_has_is_reported_not_counted(api):
    h, me = signup(api, "a@example.com", "Ada")
    save_profile(api, h, **PROFILE)
    db.roadmap_progress().insert_one({"user_id": me["user_id"], "project_id": "pm-x", "steps": {"old-step": {"status": "completed", "label": "Gone Skill"}}})
    learning = get(api, h)["learning"]
    assert learning["totals"]["completed"] == 0
    assert learning["retired_recorded_steps"] == 1 and learning["started"] is True
    assert any(a["earlier_step"] and a["skill"] == "Gone Skill" for a in learning["recent_activity"])


def test_unknown_skill_names_are_listed_as_unrecognised(api):
    h, me = signup(api, "a@example.com", "Ada")
    save_profile(api, h, skills=[{"name": "Zebra Wrangling", "level": "Advanced"}])
    db.roadmap_progress().insert_one({"user_id": me["user_id"], "project_id": "pm-x", "steps": {"old": {"status": "completed", "label": "Zebra Wrangling"}}})
    data = get(api, h)
    assert data["profile_skills"][0]["recognised"] is False
    worked = data["learning"]["skills_worked_on"][0]
    assert worked["skill"] == "Zebra Wrangling" and worked["recognised"] is False and worked["on_profile"] is True


def test_a_failing_roadmap_build_degrades_to_unavailable_for_that_project(api, monkeypatch):
    h, _ = signup(api, "a@example.com", "Ada")
    save_profile(api, h, **PROFILE)
    mark(api, h, roadmap(api, h)["steps"][0]["id"], "completed")

    def boom(doc, profile):
        raise RuntimeError("bad catalogue row")

    monkeypatch.setattr(insights, "build_roadmap", boom)
    data = get(api, h)
    assert data["learning"]["projects_unavailable"] == 1 and data["learning"]["totals"]["completed"] == 0


def test_catalogue_unavailable_returns_a_degraded_summary(api, monkeypatch):
    h, _ = signup(api, "a@example.com", "Ada")
    save_profile(api, h, **PROFILE)
    mark(api, h, roadmap(api, h)["steps"][0]["id"], "completed")
    monkeypatch.setattr(recommend, "get_retriever", lambda: _Fake({}))
    data = get(api, h)
    assert data["profile"]["skill_count"] == 2 and data["learning"]["projects_unavailable"] == 1


# --- next steps ------------------------------------------------------------------------------------------------------


def test_next_step_continues_in_progress_then_first_unstarted_with_a_project_link(api):
    h, _ = signup(api, "a@example.com", "Ada")
    save_profile(api, h, **PROFILE)
    steps = roadmap(api, h)["steps"]
    mark(api, h, steps[0]["id"], "completed")
    items = get(api, h)["next_steps"]["items"]
    step_item = next(i for i in items if i["type"] == "roadmap_step")
    assert step_item["step_id"] == steps[1]["id"] and step_item["status"] == "not_started"
    assert step_item["link"] == "/project/pm-x" and "have not started" in step_item["reason"]

    mark(api, h, steps[2]["id"], "in_progress")
    step_item = next(i for i in get(api, h)["next_steps"]["items"] if i["type"] == "roadmap_step")
    assert step_item["step_id"] == steps[2]["id"] and step_item["status"] == "in_progress"


def test_next_step_is_never_reported_as_completed(api):
    h, _ = signup(api, "a@example.com", "Ada")
    save_profile(api, h, **PROFILE)
    mark(api, h, roadmap(api, h)["steps"][0]["id"], "in_progress")
    before = db.roadmap_progress().find_one({})
    items = get(api, h)["next_steps"]["items"]
    assert all(i.get("status") != "completed" for i in items)
    assert db.roadmap_progress().find_one({}) == before


def test_finished_roadmap_has_no_roadmap_next_step(api):
    h, _ = signup(api, "a@example.com", "Ada")
    save_profile(api, h, **PROFILE, interests=["Web Development"], learning_goals=["Backend"], preferred_roles=["Backend Developer"], availability={"hours_per_week": 5})
    for step in roadmap(api, h)["steps"]:
        mark(api, h, step["id"], "completed")
    data = get(api, h)
    assert not any(i["type"] == "roadmap_step" for i in data["next_steps"]["items"])
    assert data["learning"]["totals"]["remaining"] == 0


def test_complete_profile_gets_no_profile_reminder(api):
    h, _ = signup(api, "a@example.com", "Ada")
    save_profile(api, h, **PROFILE, interests=["Web Development"], learning_goals=["Backend"], preferred_roles=["Backend Developer"], availability={"hours_per_week": 5})
    assert get(api, h)["profile"]["status"] == "complete"
    assert not any(i["type"] == "profile" for i in get(api, h)["next_steps"]["items"])


# --- isolation & no mutation ---------------------------------------------------------------------------------------------


def test_each_account_sees_only_its_own_data(api):
    ha, _ = signup(api, "a@example.com", "Ada")
    hb, _ = signup(api, "b@example.com", "Bob")
    save_profile(api, ha, skills=[{"name": "Zebra Wrangling", "level": "Advanced"}])
    mark(api, ha, roadmap(api, ha)["steps"][0]["id"], "completed")
    save_profile(api, hb, skills=[{"name": "Python", "level": "Beginner"}])
    a, b = get(api, ha), get(api, hb)
    assert a["learning"]["totals"]["completed"] == 1 and b["learning"]["totals"]["completed"] == 0
    assert "Zebra Wrangling" not in json.dumps(b) and b["learning"]["started"] is False
    assert "Python" not in json.dumps({k: a[k] for k in ("profile_skills",)})


def test_teammate_private_profile_never_appears(api):
    ha, _ = signup(api, "a@example.com", "Ada")
    hb, _ = signup(api, "b@example.com", "Bob")
    save_profile(api, hb, skills=[{"name": "Zebra Wrangling", "level": "Advanced"}], share_with_teams=False)
    team = api.post("/api/teams", json={"name": "T", "project_id": "pm-x"}, headers=ha)
    if team.status_code in (200, 201):
        code = team.get_json()["data"].get("invite_code")
        if code:
            api.post("/api/teams/join", json={"invite_code": code}, headers=hb)
    assert "Zebra Wrangling" not in json.dumps(get(api, ha))


def test_reading_insights_changes_nothing(api):
    h, _ = signup(api, "a@example.com", "Ada")
    save_profile(api, h, **PROFILE)
    mark(api, h, roadmap(api, h)["steps"][0]["id"], "completed")
    before = snapshot()
    for _ in range(3):
        get(api, h)
    assert snapshot() == before


def test_does_not_log_private_data(api, caplog):
    h, _ = signup(api, "a@example.com", "Ada")
    save_profile(api, h, skills=[{"name": "Zebra Wrangling", "level": "Advanced"}])
    with caplog.at_level("DEBUG"):
        get(api, h)
    # The app's own loggers; pymongo's DEBUG driver log echoes raw replies and is not app code.
    app_logs = " | ".join(r.getMessage() for r in caplog.records if not r.name.startswith("pymongo"))
    assert "Zebra Wrangling" not in app_logs


# --- assistant tool -------------------------------------------------------------------------------------------------------------


def _turn(client, h, message, *completions, monkeypatch):
    script = Script(*completions)
    monkeypatch.setattr(ai_assistant, "_create_completion", script)
    conv = client.post("/api/conversations", headers=h).get_json()["data"]["conversation_id"]
    res = client.post(f"/api/conversations/{conv}/messages", json={"message": message}, headers=h)
    return res, script, conv


def _tool_payload(script):
    return json.loads([m["content"] for m in script.calls[-1]["messages"] if m["role"] == "tool"][-1])


def test_progress_tool_is_offered_only_when_signed_in_and_has_no_parameters(api, monkeypatch):
    assert "get_my_progress" in personal_tools.PERSONAL_TOOL_NAMES
    schema = next(t for t in personal_tools.PERSONAL_TOOL_SCHEMAS if t["function"]["name"] == "get_my_progress")
    assert schema["function"]["parameters"]["properties"] == {} and schema["function"]["parameters"]["additionalProperties"] is False
    h, _ = signup(api, "a@example.com", "Ada")
    res, script, _ = _turn(api, h, "hi", _text_completion("Hello"), monkeypatch=monkeypatch)
    assert "get_my_progress" in {t["function"]["name"] for t in script.calls[0]["tools"]}
    res, script, _ = _turn(api, {"X-Device-Id": "anon"}, "hi", _text_completion("Hello"), monkeypatch=monkeypatch)
    assert "get_my_progress" not in {t["function"]["name"] for t in script.calls[0]["tools"]}


def test_progress_tool_returns_only_the_callers_real_data_with_a_grounding_block(api, monkeypatch):
    ha, _ = signup(api, "a@example.com", "Ada")
    hb, _ = signup(api, "b@example.com", "Bob")
    save_profile(api, ha, **PROFILE)
    steps = roadmap(api, ha)["steps"]
    mark(api, ha, steps[0]["id"], "completed")
    save_profile(api, hb, skills=[{"name": "Zebra Wrangling", "level": "Advanced"}])
    # Even if a gullible model passes someone else's id, the tool refuses it.
    res, script, _ = _turn(
        api, hb, "how am I doing?",
        _tool_call_completion("get_my_progress", json.dumps({"user_id": "victim"})), _text_completion("Refused."),
        monkeypatch=monkeypatch,
    )
    assert "Unexpected argument" in _tool_payload(script)["error"]

    res, script, _ = _turn(
        api, ha, "how am I doing?",
        _tool_call_completion("get_my_progress", "{}"), _text_completion("You completed one step."),
        monkeypatch=monkeypatch,
    )
    assert res.status_code == 200
    seen = _tool_payload(script)
    assert seen["recorded_learning_progress"]["totals"]["completed"] == 1
    assert {s["name"]: s["declared_level"] for s in seen["declared_skills_self_reported"]} == {"Python": "Intermediate", "React": "Beginner"}
    assert seen["history_available"] is False and "never changed" in seen["how_to_read"]
    assert "Zebra Wrangling" not in json.dumps(seen)
    block = next(b for b in res.get_json()["data"]["blocks"] if b["type"] == "grounding")
    assert block["sources"][0]["kind"] == "progress"


def test_progress_tool_empty_state_tells_the_model_not_to_claim_learning(api, monkeypatch):
    h, _ = signup(api, "a@example.com", "Ada")
    res, script, _ = _turn(
        api, h, "what have I learned?",
        _tool_call_completion("get_my_progress", "{}"), _text_completion("Nothing recorded yet."), monkeypatch=monkeypatch,
    )
    seen = _tool_payload(script)
    assert seen["recorded_learning_progress"]["started"] is False and "Do not describe any skill as learned" in seen["note"]


def test_progress_tool_refuses_without_a_user_and_reports_failures_plainly(api, monkeypatch):
    result, block = personal_tools.call_personal_tool("get_my_progress", {}, None)
    assert "not signed in" in result["error"] and block is None
    h, _ = signup(api, "a@example.com", "Ada")

    def boom(user_id):
        raise RuntimeError("db down")

    monkeypatch.setattr(personal_tools.insights_service, "build_insights", boom)
    res, script, _ = _turn(
        api, h, "progress?", _tool_call_completion("get_my_progress", "{}"), _text_completion("I couldn't read your progress."),
        monkeypatch=monkeypatch,
    )
    assert res.status_code == 200
    assert "Tool call failed" in _tool_payload(script)["error"]
    assert not any(b["type"] == "grounding" for b in (res.get_json()["data"].get("blocks") or []))


def test_progress_tool_does_not_write_anything(api, monkeypatch):
    h, _ = signup(api, "a@example.com", "Ada")
    save_profile(api, h, **PROFILE)
    mark(api, h, roadmap(api, h)["steps"][0]["id"], "in_progress")
    before = snapshot()
    _turn(api, h, "progress?", _tool_call_completion("get_my_progress", "{}"), _text_completion("ok"), monkeypatch=monkeypatch)
    assert snapshot() == before
