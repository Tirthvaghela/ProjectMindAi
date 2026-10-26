"""Personalised skill-gap analysis (Feature 4): nlp/personal_skill_gap.py and
GET /api/skill-gap/me. Pure-function tests use plain dicts; the HTTP tests use
the real routes with the retriever's document store faked, so nothing depends on
embeddings or any model."""

from __future__ import annotations

import copy

import pytest

from nlp import personal_skill_gap as g
from nlp import recommend


def doc(difficulty="Intermediate", technologies=("React", "Node.js", "PostgreSQL"), skills=("REST API development", "Authentication"), **extra):
    return {
        "project_id": "pm-x",
        "title": "Campus Marketplace",
        "domain": "Web Development",
        "difficulty": difficulty,
        "technologies": list(technologies),
        "skills": list(skills),
        "keywords": [],
        **extra,
    }


def prof(skills=(), history=(), status="in_progress"):
    return {
        "skills": [{"name": n, "level": lv} for n, lv in skills],
        "experience": [{"title": "Past", "technologies": list(history)}] if history else [],
        "completion": {"status": status, "percent": 40},
    }


def by_skill(result):
    return {i["skill"]: i for i in result["items"]}


# --- classification -------------------------------------------------------------------


def test_everything_covered_means_no_gaps_and_no_priorities():
    p = prof([("React", "Intermediate"), ("Node.js", "Intermediate"), ("PostgreSQL", "Intermediate"),
              ("REST API development", "Beginner"), ("Authentication", "Beginner")])
    r = g.analyse(doc(), p)
    assert r["summary"] == {"have": 5, "needs_improvement": 0, "unclear": 0, "missing": 0, "total": 5}
    assert all(i["priority"] is None and i["next_step"] is None for i in r["items"])


def test_missing_skills_are_classified_and_explained():
    r = g.analyse(doc(), prof([("React", "Advanced")]))
    items = by_skill(r)
    assert items["Node.js"]["classification"] == "missing"
    assert items["Node.js"]["evidence"] == {"source": "none", "skill": None, "level": None, "self_reported": False}
    assert "built with Node.js" in items["Node.js"]["why_it_matters"]
    assert "lists Authentication as a required skill" in items["Authentication"]["why_it_matters"]


def test_beginner_is_a_gap_only_when_the_project_is_harder_than_that():
    p = prof([("React", "Beginner")])
    assert by_skill(g.analyse(doc("Beginner"), p))["React"]["classification"] == "have"
    assert by_skill(g.analyse(doc("Intermediate"), p))["React"]["classification"] == "needs_improvement"
    assert by_skill(g.analyse(doc("Advanced"), p))["React"]["classification"] == "needs_improvement"


@pytest.mark.parametrize(
    "difficulty,level,expected",
    [
        ("Beginner", "Beginner", "have"),
        ("Intermediate", "Intermediate", "have"),
        ("Intermediate", "Advanced", "have"),
        ("Advanced", "Intermediate", "have"),  # capped: Advanced is never demanded
        ("Advanced", "Beginner", "needs_improvement"),
    ],
)
def test_technology_bar_by_difficulty(difficulty, level, expected):
    assert by_skill(g.analyse(doc(difficulty), prof([("React", level)])))["React"]["classification"] == expected


def test_listed_skills_have_a_lower_bar_than_stack_technologies():
    p = prof([("Authentication", "Beginner")])
    assert by_skill(g.analyse(doc("Intermediate"), p))["Authentication"]["classification"] == "have"
    assert by_skill(g.analyse(doc("Advanced"), p))["Authentication"]["classification"] == "needs_improvement"


def test_self_reported_levels_are_labelled_and_never_called_verified():
    r = g.analyse(doc(), prof([("React", "Intermediate")]))
    ev = by_skill(r)["React"]["evidence"]
    assert ev["self_reported"] is True and ev["level"] == "Intermediate"
    assert "self-reported" in r["disclaimer"].lower() and "not a verified assessment" in r["disclaimer"].lower()


def test_past_project_technology_counts_without_inventing_a_level():
    easy = by_skill(g.analyse(doc("Beginner"), prof(history=["Node.js"])))["Node.js"]
    assert easy["classification"] == "have" and easy["evidence"]["source"] == "past_project" and easy["evidence"]["level"] is None
    hard = by_skill(g.analyse(doc("Intermediate"), prof(history=["Node.js"])))["Node.js"]
    assert hard["classification"] == "unclear" and hard["evidence"]["level"] is None


def test_profile_level_beats_past_project_evidence_for_the_same_skill():
    r = g.analyse(doc(), prof([("nodejs", "Advanced")], history=["Node.js"]))
    node = by_skill(r)["Node.js"]
    assert node["evidence"]["source"] == "profile" and node["classification"] == "have"


def test_aliases_match_across_profile_history_and_requirements_without_duplicates():
    r = g.analyse(doc(technologies=("React", "Node.js", "Postgres")), prof([("reactjs", "Intermediate")], history=["node", "PostgreSQL"]))
    items = by_skill(r)
    assert items["React"]["classification"] == "have"
    assert items["Node.js"]["evidence"]["source"] == "past_project"
    assert items["PostgreSQL"]["evidence"]["source"] == "past_project"
    assert len([i for i in r["items"] if i["skill"] in ("PostgreSQL",)]) == 1


def test_a_requirement_listed_as_both_technology_and_skill_is_one_item():
    r = g.analyse(doc(technologies=("React",), skills=("react", "Testing")), prof())
    assert [i["skill"] for i in r["items"]].count("React") == 1
    assert by_skill(r)["React"]["kind"] == "technology" and by_skill(r)["React"]["mentions"] == 2


def test_related_skill_is_inferred_so_it_is_unclear_not_have():
    r = g.analyse(doc(skills=("REST API development",), technologies=("React", "Node.js")), prof([("REST", "Advanced")]))
    item = by_skill(r)["REST API development"]
    assert item["classification"] == "unclear"
    assert item["evidence"] == {"source": "related", "skill": "REST", "level": None, "self_reported": False}


def test_custom_skills_are_kept_and_unknown_requirements_still_reported():
    r = g.analyse(doc(technologies=("Obscure Framework",), skills=()), prof([("Basket weaving", "Advanced")]))
    item = by_skill(r)["Obscure Framework"]
    assert item["classification"] == "missing" and item["recognised"] is False
    matched = g.analyse(doc(technologies=("Obscure Framework",), skills=()), prof([("obscure framework", "Intermediate")]))
    assert by_skill(matched)["Obscure Framework"]["classification"] == "have"


# --- incomplete data ------------------------------------------------------------------------


def test_empty_profile_says_not_on_profile_and_flags_unreliable_ranking():
    r = g.analyse(doc(), prof(status="not_started"))
    assert r["profile"]["has_skills"] is False
    assert r["summary"]["missing"] == r["summary"]["total"] == 5
    assert r["ranking"]["reliable"] is False and "learning sequence" in r["ranking"]["note"]
    assert any("lists no skills" in n for n in r["notes"])
    assert "not recorded" in r["rules"]["classification"]["missing"]


def test_project_with_no_requirements_returns_no_invented_gaps():
    r = g.analyse(doc(technologies=(), skills=()), prof([("React", "Advanced")]))
    assert r["items"] == [] and r["requirements"] == {"total": 0, "limited": True}
    assert any("nothing to compare" in n for n in r["notes"])


def test_sparse_requirements_are_marked_limited():
    r = g.analyse(doc(technologies=("React",), skills=()), prof())
    assert r["requirements"]["limited"] is True and r["ranking"]["reliable"] is False
    assert any("very few requirements" in n for n in r["notes"])


def test_missing_or_malformed_metadata_does_not_crash():
    r = g.analyse({"project_id": "x", "technologies": [None, 3, "React"], "skills": "oops", "difficulty": "Impossible"}, {})
    assert [i["skill"] for i in r["items"]] == ["React"]
    assert r["project"]["difficulty"] == "Impossible" or r["project"]["difficulty"] is not None


# --- prioritisation ---------------------------------------------------------------------------


def test_missing_stack_technology_outranks_missing_listed_skills():
    r = g.analyse(doc(), prof([("React", "Advanced"), ("Node.js", "Advanced")]))
    gaps = [i for i in r["items"] if i["priority"]]
    assert gaps[0]["skill"] == "PostgreSQL" and gaps[0]["priority"]["level"] == "high"
    assert "technology stack" in gaps[0]["priority"]["reasons"][0]


def test_every_priority_has_a_reason_and_only_gaps_have_one():
    r = g.analyse(doc(), prof([("React", "Beginner")]))
    for i in r["items"]:
        if i["classification"] in ("missing", "needs_improvement"):
            assert i["priority"]["level"] in ("high", "medium", "low") and i["priority"]["reasons"]
        else:
            assert i["priority"] is None


def test_a_gap_that_builds_on_an_owned_skill_is_promoted_and_says_so():
    r = g.analyse(doc(technologies=("React",), skills=("Tailwind CSS", "Accessibility")), prof([("React", "Advanced")]))
    item = by_skill(r)["Tailwind CSS"]
    assert item["priority"]["level"] == "medium" and any("builds on React" in x for x in item["priority"]["reasons"])
    assert by_skill(r)["Accessibility"]["priority"]["level"] in ("low", "medium")


def test_repeated_mentions_raise_a_skill_to_medium():
    r = g.analyse(doc(technologies=("React", "Node.js"), skills=("Testing",), keywords=["testing", "Testing"]), prof([("React", "Advanced"), ("Node.js", "Advanced")]))
    assert by_skill(r)["Testing"]["priority"]["level"] == "medium"
    assert "3 places" in by_skill(r)["Testing"]["priority"]["reasons"][0]


def test_needs_improvement_is_explained_in_the_priority():
    r = g.analyse(doc(), prof([("React", "Beginner"), ("Node.js", "Advanced"), ("PostgreSQL", "Advanced")]))
    item = by_skill(r)["React"]
    assert item["classification"] == "needs_improvement"
    assert any("below the level" in x for x in item["priority"]["reasons"])


def test_ordering_is_gaps_first_then_unclear_then_have():
    r = g.analyse(doc(), prof([("React", "Advanced")], history=["Node.js"]))
    states = [i["classification"] for i in r["items"]]
    assert states == sorted(states, key=["missing", "needs_improvement", "unclear", "have"].index)


# --- next steps ------------------------------------------------------------------------------------


def test_next_steps_are_project_specific_and_not_generic():
    r = g.analyse(doc(), prof([("React", "Advanced")]))
    step = by_skill(r)["PostgreSQL"]["next_step"]
    assert "Campus Marketplace" in step and "PostgreSQL" in step and "Database Layer" in step
    assert not any(w in step.lower() for w in ("hours", "weeks", "days", "certificate"))


def test_needs_improvement_step_mentions_the_users_own_rating():
    r = g.analyse(doc(), prof([("React", "Beginner"), ("Node.js", "Advanced"), ("PostgreSQL", "Advanced")]))
    assert "You rate React as Beginner" in by_skill(r)["React"]["next_step"]


def test_resources_reuse_the_existing_learning_path_links_only():
    r = g.analyse(doc(), prof([("React", "Advanced")]))
    resources = by_skill(r)["PostgreSQL"]["resources"]
    assert resources and resources[0]["platform"].endswith("docs")
    assert all(x["url"].startswith("https://") for x in resources)


def test_language_prerequisite_comes_only_from_the_existing_sequence():
    r = g.analyse(doc(technologies=("Python", "Flask", "React"), skills=("API design",)), prof())
    items = by_skill(r)
    assert items["Flask"]["prerequisites"] == ["Python"] and items["React"]["prerequisites"] == ["Python"]
    assert items["Python"]["prerequisites"] == []
    covered = g.analyse(doc(technologies=("Python", "Flask"), skills=("API design",)), prof([("Python", "Advanced")]))
    assert by_skill(covered)["Flask"]["prerequisites"] == []


def test_no_unrequested_estimates_or_percentages_anywhere():
    r = g.analyse(doc(), prof([("React", "Beginner")]))
    text = str(r).lower()
    for banned in ("percent_ready", "readiness", "probab", "hours to", "weeks to learn"):
        assert banned not in text


def test_same_inputs_give_identical_output_and_inputs_are_not_mutated():
    d, p = doc(), prof([("React", "Beginner")], history=["Express"])
    d0, p0 = copy.deepcopy(d), copy.deepcopy(p)
    assert g.analyse(d, p) == g.analyse(d, p)
    assert d == d0 and p == p0


# --- HTTP --------------------------------------------------------------------------------------------------


class _Fake:
    def __init__(self, docs):
        self.documents = docs


@pytest.fixture
def api(client, monkeypatch):
    monkeypatch.setattr(recommend, "get_retriever", lambda: _Fake({"pm-x": doc(), "pm-empty": doc(technologies=(), skills=(), project_id="pm-empty")}))
    return client


def _signup(client, email):
    res = client.post("/api/auth/signup", json={"email": email, "password": "correcthorse1", "name": "T"})
    assert res.status_code == 201
    return {"X-Auth-Token": res.get_json()["token"]}


def test_requires_sign_in(api):
    assert api.get("/api/skill-gap/me?project_id=pm-x").status_code == 401
    assert api.get("/api/skill-gap/me?project_id=pm-x", headers={"X-Auth-Token": "bogus"}).status_code == 401
    assert api.get("/api/skill-gap/me?project_id=pm-x", headers={"X-Device-Id": "d"}).status_code == 401


def test_validates_the_project_id(api):
    h = _signup(api, "a@example.com")
    assert api.get("/api/skill-gap/me", headers=h).status_code == 400
    assert api.get("/api/skill-gap/me?project_id=%20", headers=h).status_code == 400
    assert api.get("/api/skill-gap/me?project_id=" + "x" * 65, headers=h).status_code == 400
    missing = api.get("/api/skill-gap/me?project_id=nope", headers=h)
    assert missing.status_code == 404 and "nope" in missing.get_json()["error"]


def test_account_without_a_profile_gets_a_graceful_limited_analysis(api):
    h = _signup(api, "a@example.com")
    body = api.get("/api/skill-gap/me?project_id=pm-x", headers=h).get_json()["data"]
    assert body["profile"]["status"] == "not_started" and body["profile"]["has_skills"] is False
    assert body["summary"]["missing"] == body["summary"]["total"]
    from db import client as db
    assert db.profiles().count_documents({}) == 0  # analysing never creates a profile


def test_saved_profile_drives_the_response_shape(api):
    h = _signup(api, "a@example.com")
    api.put("/api/profile", json={
        "skills": [{"name": "reactjs", "level": "Beginner"}, {"name": "Node.js", "level": "Advanced"}],
        "experience": [{"title": "Shop", "technologies": ["PostgreSQL"]}],
    }, headers=h)
    body = api.get("/api/skill-gap/me?project_id=pm-x", headers=h).get_json()["data"]
    assert set(body) == {"project", "profile", "requirements", "summary", "items", "rules", "ranking", "notes", "disclaimer"}
    assert body["project"] == {"project_id": "pm-x", "title": "Campus Marketplace", "domain": "Web Development", "difficulty": "Intermediate"}
    items = {i["skill"]: i for i in body["items"]}
    assert items["React"]["classification"] == "needs_improvement"
    assert items["Node.js"]["classification"] == "have"
    assert items["PostgreSQL"]["classification"] == "unclear" and items["PostgreSQL"]["evidence"]["source"] == "past_project"
    assert set(items["React"]) >= {"skill", "kind", "classification", "target_level", "evidence", "priority", "why_it_matters", "next_step", "prerequisites", "resources"}


def test_updating_the_profile_changes_the_next_analysis(api):
    h = _signup(api, "a@example.com")
    api.put("/api/profile", json={"skills": [{"name": "React", "level": "Beginner"}]}, headers=h)
    before = api.get("/api/skill-gap/me?project_id=pm-x", headers=h).get_json()["data"]["summary"]
    api.put("/api/profile", json={"skills": [{"name": "React", "level": "Advanced"}, {"name": "Node.js", "level": "Advanced"}]}, headers=h)
    after = api.get("/api/skill-gap/me?project_id=pm-x", headers=h).get_json()["data"]["summary"]
    assert after["have"] > before["have"] and after["needs_improvement"] < before["needs_improvement"]


def test_each_account_sees_only_its_own_profile_and_ignores_user_parameters(api):
    alice, bob = _signup(api, "alice@example.com"), _signup(api, "bob@example.com")
    api.put("/api/profile", json={"skills": [{"name": "React", "level": "Advanced"}, "Basket weaving"], "education": "Alice only"}, headers=alice)
    uid = api.get("/api/auth/me", headers=alice).get_json()["data"]["user_id"]
    body = api.get(f"/api/skill-gap/me?project_id=pm-x&user_id={uid}", headers=bob).get_json()
    assert body["data"]["profile"]["has_skills"] is False
    text = str(body)
    assert "Basket weaving" not in text and "Alice only" not in text
    assert {i["skill"]: i for i in api.get("/api/skill-gap/me?project_id=pm-x", headers=alice).get_json()["data"]["items"]}["React"]["classification"] == "have"


def test_project_without_requirements_is_reported_not_invented(api):
    h = _signup(api, "a@example.com")
    body = api.get("/api/skill-gap/me?project_id=pm-empty", headers=h).get_json()["data"]
    assert body["items"] == [] and body["requirements"]["limited"] is True


def test_existing_anonymous_skill_gap_endpoint_is_unchanged(client, monkeypatch):
    monkeypatch.setattr(recommend, "get_retriever", lambda: _Fake({"pm-x": doc()}))
    res = client.post("/api/skill-gap", json={"project_id": "pm-x", "skills": ["React"]})
    assert res.status_code == 200
    assert set(res.get_json()["data"]) == {"project_id", "required_skills", "skills_you_have", "skills_to_learn", "readiness_percent"}


def test_the_response_is_identical_for_identical_requests(api):
    h = _signup(api, "a@example.com")
    api.put("/api/profile", json={"skills": ["React"]}, headers=h)
    a = api.get("/api/skill-gap/me?project_id=pm-x", headers=h).get_json()
    b = api.get("/api/skill-gap/me?project_id=pm-x", headers=h).get_json()
    assert a == b
