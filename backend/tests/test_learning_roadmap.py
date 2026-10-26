"""Personalised learning roadmaps (Feature 5): nlp/learning_roadmap.py,
roadmaps/service.py and /api/roadmap/*. The builder is pure and tested on plain
dicts; the HTTP tests fake the retriever's document store so nothing depends on
embeddings, a model or the network."""

from __future__ import annotations

import copy

import pytest

from db import client as db
from nlp import learning_path, recommend
from nlp import learning_roadmap as lr


def doc(difficulty="Intermediate", technologies=("Python", "Flask", "React"), skills=("REST API development",), **extra):
    return {
        "project_id": "pm-x", "title": "Campus Marketplace", "domain": "Web Development",
        "difficulty": difficulty, "technologies": list(technologies), "skills": list(skills), "keywords": [], **extra,
    }


def prof(skills=(), history=(), goals=(), interests=(), status="in_progress"):
    return {
        "skills": [{"name": n, "level": lv} for n, lv in skills],
        "experience": [{"title": "Past", "technologies": list(history)}] if history else [],
        "learning_goals": list(goals), "interests": list(interests),
        "completion": {"status": status, "percent": 40},
    }


def ids(road):
    return [s["id"] for s in road["steps"]]


def step(road, skill):
    return next(s for s in road["steps"] if s["skill"] == skill)


# --- personalisation ---------------------------------------------------------------------------


def test_empty_profile_gets_foundations_first_and_a_limited_notice():
    road = lr.build_roadmap(doc(), prof(status="not_started"))
    order = [s["skill"] for s in road["steps"]]
    assert order.index("Python") < order.index("Flask")
    assert any("lists no skills" in n for n in road["notes"])
    assert road["ordering"]["reliable"] is False
    assert all(s["classification"] == "missing" for s in road["steps"])


def test_different_profiles_get_different_roadmaps_for_the_same_project():
    a = lr.build_roadmap(doc(), prof())
    b = lr.build_roadmap(doc(), prof([("Python", "Advanced"), ("Flask", "Advanced")]))
    c = lr.build_roadmap(doc(), prof([("Python", "Advanced"), ("Flask", "Advanced"), ("React", "Advanced"), ("REST API development", "Advanced")]))
    assert ids(a) != ids(b) != ids(c)
    assert len(ids(a)) > len(ids(b)) > len(ids(c)) or ids(c) == []


def test_skills_the_user_already_has_at_the_bar_get_no_step_and_are_listed_as_covered():
    road = lr.build_roadmap(doc(), prof([("Python", "Intermediate"), ("Flask", "Intermediate")]))
    assert "Python" not in [s["skill"] for s in road["steps"]]
    assert {"Python", "Flask"} <= set(road["overview"]["already_covered"])


def test_fully_covered_project_has_no_steps_and_says_so():
    road = lr.build_roadmap(doc(), prof([("Python", "Advanced"), ("Flask", "Advanced"), ("React", "Advanced"), ("REST API development", "Intermediate")]))
    assert road["steps"] == [] and road["overview"]["steps"] == 0
    assert "already covered" in " ".join(road["notes"]) and "start building" in road["overview"]["finish"]


def test_beginner_skill_becomes_an_improve_step_with_a_self_check_not_a_certificate():
    road = lr.build_roadmap(doc("Intermediate"), prof([("React", "Beginner"), ("Python", "Advanced"), ("Flask", "Advanced"), ("REST API development", "Advanced")]))
    react = step(road, "React")
    assert react["kind"] == "improve" and react["classification"] == "needs_improvement"
    assert "You rate React Beginner" in react["why_for_you"]
    assert "self-check" in react["completion_criterion"]
    assert lr.build_roadmap(doc("Beginner"), prof([("React", "Beginner"), ("Python", "Advanced"), ("Flask", "Advanced"), ("REST API development", "Advanced")]))["steps"] == []


def test_past_project_technology_is_a_confirm_step_with_no_invented_level():
    road = lr.build_roadmap(doc("Intermediate"), prof([("Flask", "Advanced"), ("React", "Advanced"), ("REST API development", "Advanced")], history=["Python"]))
    py = step(road, "Python")
    assert py["kind"] == "confirm" and py["classification"] == "unclear"
    assert py["evidence"]["level"] is None and py["evidence"]["source"] == "past_project"
    assert "level is recorded" in py["why_for_you"] and "update your" in py["completion_criterion"].lower()


def test_related_only_match_stays_uncertain_and_never_counts_as_competence():
    road = lr.build_roadmap(doc(technologies=("React", "Node.js"), skills=("REST API development",)), prof([("REST", "Advanced"), ("React", "Advanced"), ("Node.js", "Advanced")]))
    s = step(road, "REST API development")
    assert s["kind"] == "confirm" and s["evidence"]["source"] == "related" and s["evidence"]["self_reported"] is False
    assert "not the same skill" in s["why_for_you"]


def test_unclear_and_missing_skills_both_appear():
    road = lr.build_roadmap(doc(), prof(history=["Python"]))
    kinds = {s["skill"]: s["kind"] for s in road["steps"]}
    assert kinds["Python"] == "confirm" and kinds["Flask"] == "learn"


def test_learning_goal_text_is_echoed_only_on_matching_steps():
    road = lr.build_roadmap(doc(), prof(goals=["Get comfortable with Flask", "Travel more"]))
    assert step(road, "Flask")["matches_your_goal"] == "Get comfortable with Flask"
    assert step(road, "React")["matches_your_goal"] is None


def test_domain_interest_is_reported_in_the_overview():
    assert lr.build_roadmap(doc(), prof(interests=["Web Development"]))["overview"]["domain_interest"] is True
    assert lr.build_roadmap(doc(), prof(interests=["Robotics"]))["overview"]["domain_interest"] is False


# --- steps & content ---------------------------------------------------------------------------------


def test_every_step_has_the_required_fields_and_is_numbered_in_order():
    road = lr.build_roadmap(doc(), prof())
    required = {"id", "number", "kind", "skill", "skills", "classification", "evidence", "why_it_matters", "why_for_you",
                "prerequisites", "practice_task", "completion_criterion", "resources", "priority", "after", "from_project_requirements"}
    for n, s in enumerate(road["steps"], start=1):
        assert required <= set(s) and s["number"] == n
        assert s["practice_task"] and s["completion_criterion"]


def test_after_points_to_the_next_step_and_the_last_has_none():
    road = lr.build_roadmap(doc(), prof())
    for cur, nxt in zip(road["steps"], road["steps"][1:]):
        assert cur["after"] == {"id": nxt["id"], "skill": nxt["skill"]}
    assert road["steps"][-1]["after"] is None


def test_low_priority_concepts_are_grouped_into_one_step():
    road = lr.build_roadmap(doc(technologies=("React",), skills=("CRUD design", "Tag management", "Search")), prof([("React", "Advanced")]))
    concepts = step(road, "Project concepts")
    assert concepts["id"] == "concepts" and concepts["skills"] == ["CRUD design", "Tag management", "Search"]
    assert [s["id"] for s in road["steps"]] == ["concepts"]


def test_a_single_concept_is_not_grouped():
    road = lr.build_roadmap(doc(technologies=("React",), skills=("Search",)), prof([("React", "Advanced")]))
    assert ids(road) == ["s-search"]


def test_practice_tasks_are_project_specific_and_have_no_time_estimates_or_fake_courses():
    road = lr.build_roadmap(doc(), prof())
    blob = str([(s["practice_task"], s["completion_criterion"]) for s in road["steps"]]).lower()
    assert "campus marketplace" in blob
    for banned in ("hours", "weeks", "days", "certificate", "certification", "udemy"):
        assert banned not in blob


def test_resources_are_the_existing_learning_path_links():
    road = lr.build_roadmap(doc(), prof())
    flask = step(road, "Flask")
    assert flask["resources"] == learning_path.resources_for("Flask")
    assert all(r["url"].startswith("https://") for s in road["steps"] for r in s["resources"])


# --- prerequisites & ordering ---------------------------------------------------------------------------


def test_prerequisite_not_in_the_project_becomes_a_labelled_foundation_step():
    road = lr.build_roadmap(doc(technologies=("React",), skills=("Search", "Filtering")), prof())
    js = step(road, "JavaScript")
    assert js["kind"] == "prerequisite" and js["from_project_requirements"] is False
    assert ids(road).index("s-javascript") < ids(road).index("s-react")
    assert step(road, "React")["prerequisites"] == [{"skill": "JavaScript", "status": "in_roadmap"}]


def test_prerequisite_already_on_the_profile_adds_no_step():
    road = lr.build_roadmap(doc(technologies=("React",), skills=()), prof([("JavaScript", "Beginner")]))
    assert "JavaScript" not in [s["skill"] for s in road["steps"]]
    assert step(road, "React")["prerequisites"] == [{"skill": "JavaScript", "status": "on_profile"}]


def test_chains_are_followed_and_ordered():
    road = lr.build_roadmap(doc(technologies=("Next.js",), skills=()), prof())
    order = [s["skill"] for s in road["steps"]]
    assert order.index("JavaScript") < order.index("React") < order.index("Next.js")


def test_cycle_in_prerequisite_metadata_falls_back_safely():
    table = {"Alpha": ("Beta",), "Beta": ("Alpha",)}
    road = lr.build_roadmap(doc(technologies=("Alpha", "Beta"), skills=()), prof(), prerequisites=table)
    assert sorted(s["skill"] for s in road["steps"]) == ["Alpha", "Beta"]
    assert road["ordering"]["cycle_detected"] is True and any("loop" in n for n in road["notes"])
    assert lr.build_roadmap(doc(technologies=("Alpha", "Beta"), skills=()), prof(), prerequisites=table) == road


def test_order_steps_directly_handles_cycles_and_is_deterministic():
    keys = {"a": (0,), "b": (0,), "c": (1,)}
    order, cycle = lr.order_steps(keys, {("a", "b"), ("b", "a")})
    assert cycle and set(order) == {"a", "b", "c"} and order == lr.order_steps(keys, {("a", "b"), ("b", "a")})[0]
    order, cycle = lr.order_steps(keys, {("c", "a")})
    assert not cycle and order.index("c") < order.index("a")


def test_missing_prerequisite_metadata_orders_by_learning_sequence_alone():
    road = lr.build_roadmap(doc(technologies=("Docker", "Python", "MongoDB"), skills=()), prof(), prerequisites={})
    assert [s["skill"] for s in road["steps"]] == ["Python", "MongoDB", "Docker"]
    # the only edges left are Feature 4's own language prerequisite (Python first); the table adds none
    assert road["ordering"]["known_prerequisite_edges"] == 2
    none_at_all = lr.build_roadmap(doc(technologies=("Docker", "MongoDB"), skills=()), prof(), prerequisites={})
    assert [s["skill"] for s in none_at_all["steps"]] == ["MongoDB", "Docker"]
    assert none_at_all["ordering"]["known_prerequisite_edges"] == 0 and all(s["prerequisites"] == [] for s in none_at_all["steps"])
    assert "suggestion, not a requirement" in none_at_all["ordering"]["note"]


def test_priority_breaks_ties_within_a_tier_high_before_low():
    road = lr.build_roadmap(doc(technologies=("MongoDB",), skills=("Caching", "Testing")), prof(), prerequisites={})
    # MongoDB (a stack technology, data tier) comes first by tier; the two concept skills are grouped after it
    assert [s["skill"] for s in road["steps"]] == ["MongoDB", "Project concepts"]


# --- incomplete project data ------------------------------------------------------------------------------


def test_project_without_requirements_gets_no_invented_steps():
    road = lr.build_roadmap(doc(technologies=(), skills=()), prof([("React", "Advanced")]))
    assert road["steps"] == [] and any("nothing to compare" in n for n in road["notes"])


def test_sparse_requirements_are_flagged_limited():
    road = lr.build_roadmap(doc(technologies=("Docker",), skills=()), prof())
    assert road["requirements"]["limited"] is True and road["ordering"]["reliable"] is False


def test_malformed_project_and_profile_do_not_crash():
    road = lr.build_roadmap({"project_id": "x", "technologies": "oops", "skills": [None, "Search"]}, {"skills": "nope", "experience": [None]})
    assert isinstance(road["steps"], list)


def test_same_inputs_give_identical_output_without_mutating_them():
    d, p = doc(), prof([("React", "Beginner")], history=["Express"], goals=["Flask"])
    d0, p0 = copy.deepcopy(d), copy.deepcopy(p)
    assert lr.build_roadmap(d, p) == lr.build_roadmap(d, p)
    assert d == d0 and p == p0


def test_disclaimer_denies_guarantees_and_verification():
    road = lr.build_roadmap(doc(), prof())
    assert "not a guarantee" in road["disclaimer"] and "self-reported" in road["disclaimer"]


# --- existing learning-path behaviour is unchanged ------------------------------------------------------------


def test_learning_tier_matches_sequence_technologies():
    for skill in ("Python", "Go", "React", "MongoDB", "Docker", "Totally Unknown"):
        tier, reason = learning_path.learning_tier(skill)
        assert learning_path.sequence_technologies([skill])[0]["reason"] == reason
    assert learning_path.learning_tier("Python")[0] < learning_path.learning_tier("React")[0] < learning_path.learning_tier("Docker")[0]


# --- HTTP ------------------------------------------------------------------------------------------------------


class _Fake:
    def __init__(self, docs):
        self.documents = docs


@pytest.fixture
def api(client, monkeypatch):
    monkeypatch.setattr(recommend, "get_retriever", lambda: _Fake({"pm-x": doc(), "pm-empty": doc(technologies=(), skills=(), project_id="pm-empty")}))
    return client


def signup(client, email):
    res = client.post("/api/auth/signup", json={"email": email, "password": "correcthorse1", "name": "T"})
    assert res.status_code == 201
    return {"X-Auth-Token": res.get_json()["token"]}


def get(client, h, pid="pm-x"):
    return client.get(f"/api/roadmap/me?project_id={pid}", headers=h)


def put(client, h, step_id, status, pid="pm-x"):
    return client.put("/api/roadmap/me/progress", json={"project_id": pid, "step_id": step_id, "status": status}, headers=h)


def test_requires_sign_in_on_every_route(api):
    assert api.get("/api/roadmap/me?project_id=pm-x").status_code == 401
    assert api.put("/api/roadmap/me/progress", json={}).status_code == 401
    assert api.delete("/api/roadmap/me/progress?project_id=pm-x&confirm=true").status_code == 401
    assert api.get("/api/roadmap/me?project_id=pm-x", headers={"X-Device-Id": "d"}).status_code == 401


def test_project_id_validation(api):
    h = signup(api, "a@example.com")
    assert api.get("/api/roadmap/me", headers=h).status_code == 400
    assert api.get("/api/roadmap/me?project_id=%20", headers=h).status_code == 400
    assert api.get("/api/roadmap/me?project_id=" + "x" * 65, headers=h).status_code == 400
    assert get(api, h, "nope").status_code == 404
    assert api.put("/api/roadmap/me/progress", json={"step_id": "s-python", "status": "completed"}, headers=h).status_code == 400
    assert put(api, h, "s-python", "completed", "nope").status_code == 404


def test_account_without_a_profile_gets_a_foundation_roadmap_and_nothing_is_written(api):
    h = signup(api, "a@example.com")
    body = get(api, h).get_json()["data"]
    assert body["profile"]["status"] == "not_started" and body["steps"][0]["skill"] == "Python"
    assert all(s["status"] == "not_started" for s in body["steps"])
    assert body["progress"] == {"not_started": len(body["steps"]), "in_progress": 0, "completed": 0, "total": len(body["steps"])}
    assert db.profiles().count_documents({}) == 0 and db.roadmap_progress().count_documents({}) == 0


def test_two_users_get_different_roadmaps_for_the_same_project(api):
    a, b = signup(api, "a@example.com"), signup(api, "b@example.com")
    api.put("/api/profile", json={"skills": [{"name": "Python", "level": "Advanced"}, {"name": "Flask", "level": "Advanced"}]}, headers=b)
    sa = [s["id"] for s in get(api, a).get_json()["data"]["steps"]]
    sb = [s["id"] for s in get(api, b).get_json()["data"]["steps"]]
    assert sa != sb and "s-python" in sa and "s-python" not in sb


def test_progress_persists_across_requests_and_never_changes_the_profile(api):
    h = signup(api, "a@example.com")
    api.put("/api/profile", json={"skills": [{"name": "Python", "level": "Beginner"}]}, headers=h)
    profile_before = api.get("/api/profile", headers=h).get_json()
    body = put(api, h, "s-flask", "in_progress").get_json()["data"]
    assert next(s for s in body["steps"] if s["id"] == "s-flask")["status"] == "in_progress"
    put(api, h, "s-react", "completed")
    again = get(api, h).get_json()["data"]
    assert {s["id"]: s["status"] for s in again["steps"]}["s-flask"] == "in_progress"
    assert again["progress"]["in_progress"] == 1 and again["progress"]["completed"] == 1
    assert api.get("/api/profile", headers=h).get_json() == profile_before  # completing a step never edits skills


def test_completing_a_step_does_not_complete_or_unlock_anything_else(api):
    h = signup(api, "a@example.com")
    put(api, h, "s-python", "completed")
    statuses = {s["id"]: s["status"] for s in get(api, h).get_json()["data"]["steps"]}
    assert statuses["s-python"] == "completed" and all(v == "not_started" for k, v in statuses.items() if k != "s-python")


def test_not_started_clears_a_step(api):
    h = signup(api, "a@example.com")
    put(api, h, "s-flask", "completed")
    body = put(api, h, "s-flask", "not_started").get_json()["data"]
    assert body["progress"]["completed"] == 0


@pytest.mark.parametrize("step_id,status,code", [
    ("s-unknown", "completed", 404), ("", "completed", 400), (None, "completed", 400), (5, "completed", 400),
    ("s-flask", "done", 400), ("s-flask", None, 400), ("s-flask", ["completed"], 400), ("s-flask", "", 400),
])
def test_invalid_step_or_status_is_rejected_without_writing(api, step_id, status, code):
    h = signup(api, "a@example.com")
    res = api.put("/api/roadmap/me/progress", json={"project_id": "pm-x", "step_id": step_id, "status": status}, headers=h)
    assert res.status_code == code
    assert db.roadmap_progress().count_documents({}) == 0


def test_a_step_that_is_not_in_this_users_roadmap_cannot_be_recorded(api):
    h = signup(api, "a@example.com")
    api.put("/api/profile", json={"skills": [{"name": "Python", "level": "Advanced"}]}, headers=h)
    assert put(api, h, "s-python", "completed").status_code == 404  # already covered: no such step for this user


def test_progress_is_isolated_between_users(api):
    a, b = signup(api, "a@example.com"), signup(api, "b@example.com")
    uid = api.get("/api/auth/me", headers=a).get_json()["data"]["user_id"]
    put(api, a, "s-flask", "completed")
    body = api.get(f"/api/roadmap/me?project_id=pm-x&user_id={uid}", headers=b).get_json()["data"]
    assert all(s["status"] == "not_started" for s in body["steps"])
    res = api.put("/api/roadmap/me/progress", json={"project_id": "pm-x", "step_id": "s-react", "status": "completed", "user_id": uid}, headers=b)
    assert res.status_code == 200
    assert {s["id"]: s["status"] for s in get(api, a).get_json()["data"]["steps"]}.get("s-react") == "not_started"
    assert db.roadmap_progress().count_documents({}) == 2


def test_roadmap_changes_keep_matching_progress_and_never_mark_new_steps_done(api):
    h = signup(api, "a@example.com")
    put(api, h, "s-flask", "completed")
    put(api, h, "s-python", "in_progress")
    api.put("/api/profile", json={"skills": [{"name": "Python", "level": "Advanced"}, {"name": "React", "level": "Advanced"}]}, headers=h)
    body = get(api, h).get_json()["data"]
    by_id = {s["id"]: s["status"] for s in body["steps"]}
    assert by_id["s-flask"] == "completed"  # still a step, progress kept
    assert "s-python" not in by_id and "s-react" not in by_id
    assert body["retired_steps"] == [{"id": "s-python", "label": "Python", "status": "in_progress"}]
    assert all(v != "completed" for k, v in by_id.items() if k != "s-flask")
    # coming back later restores the saved status rather than losing it
    api.put("/api/profile", json={"skills": []}, headers=h)
    assert {s["id"]: s["status"] for s in get(api, h).get_json()["data"]["steps"]}["s-python"] == "in_progress"


def test_reset_requires_explicit_confirmation(api):
    h = signup(api, "a@example.com")
    put(api, h, "s-flask", "completed")
    assert api.delete("/api/roadmap/me/progress?project_id=pm-x", headers=h).status_code == 400
    assert api.delete("/api/roadmap/me/progress?project_id=pm-x&confirm=false", headers=h).status_code == 400
    assert api.delete("/api/roadmap/me/progress", json={"project_id": "pm-x", "confirm": "yes"}, headers=h).status_code == 400
    assert get(api, h).get_json()["data"]["progress"]["completed"] == 1

    res = api.delete("/api/roadmap/me/progress?project_id=pm-x&confirm=true", headers=h)
    assert res.status_code == 200 and res.get_json()["data"]["reset"] is True
    assert res.get_json()["data"]["roadmap"]["progress"]["completed"] == 0
    assert api.delete("/api/roadmap/me/progress", json={"project_id": "pm-x", "confirm": True}, headers=h).get_json()["data"]["reset"] is False


def test_reset_only_touches_the_callers_own_project_progress(api, monkeypatch):
    a, b = signup(api, "a@example.com"), signup(api, "b@example.com")
    put(api, a, "s-flask", "completed")
    put(api, b, "s-flask", "completed")
    api.delete("/api/roadmap/me/progress?project_id=pm-x&confirm=true", headers=b)
    assert get(api, a).get_json()["data"]["progress"]["completed"] == 1
    assert get(api, b).get_json()["data"]["progress"]["completed"] == 0


def test_project_without_requirements_yields_an_empty_explained_roadmap(api):
    h = signup(api, "a@example.com")
    body = get(api, h, "pm-empty").get_json()["data"]
    assert body["steps"] == [] and body["requirements"]["limited"] is True and body["notes"]
    assert put(api, h, "s-anything", "completed", "pm-empty").status_code == 404


def test_identical_requests_give_identical_responses(api):
    h = signup(api, "a@example.com")
    api.put("/api/profile", json={"skills": ["React"], "learning_goals": ["Flask"]}, headers=h)
    assert get(api, h).get_json() == get(api, h).get_json()


def test_feature_4_endpoint_and_legacy_skill_gap_are_unchanged(api):
    h = signup(api, "a@example.com")
    assert set(api.get("/api/skill-gap/me?project_id=pm-x", headers=h).get_json()["data"]) == {
        "project", "profile", "requirements", "summary", "items", "rules", "ranking", "notes", "disclaimer"}
    assert set(api.post("/api/skill-gap", json={"project_id": "pm-x", "skills": ["React"]}).get_json()["data"]) == {
        "project_id", "required_skills", "skills_you_have", "skills_to_learn", "readiness_percent"}
