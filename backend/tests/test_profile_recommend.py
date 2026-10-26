"""Profile-aware recommendations (Feature 2).

`recommend.search` / `get_retriever` are monkeypatched, as in
test_recommend_constraints.py, with every candidate at EQUAL relevance — so any
ordering difference can only come from the profile signals under test, not from
embeddings. The un-personalised path is asserted unchanged, field for field.
"""

from __future__ import annotations

import copy

import pytest

import config
from nlp import recommend
from nlp.similarity import ScoredProject
from profiles import personalization


def _doc(pid, domain="Machine Learning", difficulty="Intermediate", weeks=8, technologies=("Python",), skills=("Modelling",)):
    return {
        "project_id": pid,
        "title": f"Project {pid}",
        "domain": domain,
        "difficulty": difficulty,
        "technologies": list(technologies),
        "skills": list(skills),
        "duration_weeks": weeks,
    }


DOCS = {
    "ml": _doc("ml", "Machine Learning", technologies=("Python", "scikit-learn"), skills=("Supervised learning",)),
    "web": _doc("web", "Web Development", technologies=("React", "Node.js"), skills=("REST API development",)),
    "iot": _doc("iot", "Internet of Things", weeks=6, technologies=("MQTT",), skills=("Embedded systems",)),
    "long": _doc("long", "Web Development", weeks=20, technologies=("React",), skills=("Frontend design",)),
    "bare": {"project_id": "bare", "title": "Bare", "domain": "Robotics", "difficulty": "Beginner"},  # missing metadata
}


class _FakeRetriever:
    def __init__(self, documents):
        self.documents = documents


def _scored(pid, score=0.5):
    return ScoredProject(project_id=pid, score=score, dense_score=score, sparse_score=0.0, matched_terms=[], document=DOCS[pid])


@pytest.fixture(autouse=True)
def pool(monkeypatch):
    seen = {}
    monkeypatch.setattr(recommend, "get_retriever", lambda: _FakeRetriever(DOCS))

    def fake_search(query, filters=None, top_k=10, **_):
        seen["query"] = query
        seen["filters"] = filters
        return [_scored(pid) for pid in DOCS if not filters or not filters.get("domain") or DOCS[pid].get("domain") == filters["domain"]]

    monkeypatch.setattr(recommend, "search", fake_search)
    return seen


def _profile(**overrides):
    base = {
        "skills": [],
        "interests": [],
        "experience": [],
        "learning_goals": [],
        "career_interests": [],
        "preferred_roles": [],
        "availability": {"hours_per_week": None, "max_project_weeks": None},
    }
    base.update(overrides)
    return base


def _ctx(**overrides):
    return personalization.build_context(_profile(**overrides))


def _recs(ctx=None, **kwargs):
    return recommend.personalized_recommend(profile_context=ctx, top_k=10, **kwargs)


def _ids(recs):
    return [r["project_id"] for r in recs]


# --- context building (pure) ---------------------------------------------------


def test_empty_and_dismissal_only_profiles_are_not_usable():
    assert _ctx()["usable"] is False
    assert personalization.build_context({**_profile(), "onboarding_dismissed": True})["usable"] is False


def test_each_signal_alone_makes_a_profile_usable():
    assert _ctx(skills=[{"name": "Python", "level": "Beginner"}])["usable"]
    assert _ctx(interests=["Robotics"])["usable"]
    assert _ctx(availability={"hours_per_week": 5, "max_project_weeks": None})["usable"]
    assert _ctx(availability={"hours_per_week": None, "max_project_weeks": 8})["usable"]


def test_past_project_technologies_count_as_skills_without_overriding_stated_levels():
    ctx = _ctx(
        skills=[{"name": "React", "level": "Advanced"}],
        experience=[{"title": "Site", "description": "", "technologies": ["reactjs", "PostgreSQL"]}],
    )
    assert ctx["skills"] == ["React", "PostgreSQL"]
    assert ctx["skill_levels"][personalization.skill_names.normalize_key("React")] == "Advanced"
    assert ctx["skill_levels"][personalization.skill_names.normalize_key("PostgreSQL")] is None


def test_experience_level_is_inferred_only_from_enough_skills():
    two = _ctx(skills=[{"name": "Python", "level": "Advanced"}, {"name": "SQL", "level": "Advanced"}])
    assert two["experience_level"] is None
    three = _ctx(skills=[{"name": n, "level": "Advanced"} for n in ("Python", "SQL", "Git")])
    assert three["experience_level"] == "Advanced"
    mixed = _ctx(skills=[{"name": "Python", "level": "Beginner"}, {"name": "SQL", "level": "Beginner"}, {"name": "Git", "level": "Intermediate"}])
    assert mixed["experience_level"] == "Beginner"


def test_merge_skills_is_alias_aware_and_keeps_explicit_first():
    assert personalization.merge_skills(["reactjs", "Python"], ["React", "node", "Node.js", " "]) == ["reactjs", "Python", "node"]


def test_pace_adjustment_is_clamped_and_inert_without_hours():
    assert personalization.pace_adjusted_weeks(8, None) == 8
    assert personalization.pace_adjusted_weeks(8, config.REFERENCE_HOURS_PER_WEEK) == 8
    assert personalization.pace_adjusted_weeks(8, 1) == 24  # clamped at 3x
    assert personalization.pace_adjusted_weeks(8, 80) == 4  # clamped at 0.5x


# --- no profile: exactly the old behaviour -----------------------------------------


@pytest.mark.parametrize("ctx", [None, {"usable": False}, _ctx()])
def test_without_a_usable_profile_results_are_identical(ctx):
    baseline = recommend.personalized_recommend(known_skills=["Python"], experience_level="Intermediate", top_k=10)
    again = recommend.personalized_recommend(known_skills=["Python"], experience_level="Intermediate", top_k=10, profile_context=ctx)
    assert again == baseline
    assert all("profile_match" not in r for r in again)


# --- complete / incomplete profiles -------------------------------------------------


def test_profile_skills_drive_a_query_less_request_and_are_explained():
    ctx = _ctx(skills=[{"name": "reactjs", "level": "Intermediate"}], interests=["Web Development"])
    recs = _recs(ctx)
    assert recs and _ids(recs)[0] in {"web", "long"}  # web domain + React skill
    top = recs[0]
    assert top["profile_match"]["skills_you_have"] == [{"name": "React", "level": "Intermediate"}]
    assert "Web Development, one of the domains you said you are interested in" in top["recommendation_reason"]
    assert "React (Intermediate)" in top["recommendation_reason"] and "in your profile" in top["recommendation_reason"]
    assert "Matches your interest: Web Development" in top["matching_factors"]


def test_skills_only_profile_works_without_interest_or_time_signals():
    ctx = _ctx(skills=[{"name": "Python", "level": "Beginner"}])
    recs = _recs(ctx)
    assert recs[0]["project_id"] == "ml"
    assert recs[0]["profile_match"]["domain_interest"] is None
    assert "interested" not in recs[0]["recommendation_reason"]


def test_missing_sections_do_not_penalise_scores():
    skills = [{"name": "Python", "level": "Beginner"}]
    plain = _recs(_ctx(skills=skills))
    rich_but_empty_interests = _recs(_ctx(skills=skills, interests=[]))
    assert [r["overall_score"] for r in plain] == [r["overall_score"] for r in rich_but_empty_interests]


def test_proficiency_is_shown_as_self_reported_and_never_scores_by_itself():
    beginner = _recs(_ctx(skills=[{"name": "Python", "level": "Beginner"}]))
    advanced = _recs(_ctx(skills=[{"name": "Python", "level": "Advanced"}]))
    # Same skill, different self-rating: wording differs, readiness numbers do not.
    assert [r["skill_gap"]["readiness_percent"] for r in beginner] == [r["skill_gap"]["readiness_percent"] for r in advanced]
    assert "Python (Beginner)" in beginner[0]["recommendation_reason"]
    assert "verified" not in beginner[0]["recommendation_reason"].lower()


# --- profile changes change the output -------------------------------------------------


def test_changing_interests_changes_the_ranking():
    skills = [{"name": "Python", "level": "Beginner"}]
    first = _ids(_recs(_ctx(skills=skills, interests=["Internet of Things"])))
    second = _ids(_recs(_ctx(skills=skills, interests=["Web Development"])))
    assert first[0] == "iot"
    assert second[0] in {"web", "long"}
    assert first != second


def test_adding_a_skill_changes_readiness_and_explanation():
    before = {r["project_id"]: r for r in _recs(_ctx(skills=[{"name": "Python", "level": "Beginner"}]))}
    after = {r["project_id"]: r for r in _recs(_ctx(skills=[{"name": "Python", "level": "Beginner"}, {"name": "MQTT", "level": "Beginner"}]))}
    assert after["iot"]["skill_gap"]["readiness_percent"] > before["iot"]["skill_gap"]["readiness_percent"]


# --- aliases and custom skills ------------------------------------------------------------


def test_aliases_in_the_profile_match_catalogue_names():
    recs = {r["project_id"]: r for r in _recs(_ctx(skills=[{"name": "nodejs", "level": "Beginner"}, {"name": "sklearn", "level": "Beginner"}]))}
    assert "Node.js" in recs["web"]["skill_gap"]["skills_you_have"]
    assert "scikit-learn" in recs["ml"]["skill_gap"]["skills_you_have"]


def test_custom_skills_are_accepted_and_never_crash_or_match_unrelated_projects():
    recs = _recs(_ctx(skills=[{"name": "Basket weaving", "level": "Advanced"}, {"name": "Python", "level": "Beginner"}]))
    assert recs
    iot = next(r for r in recs if r["project_id"] == "iot")
    assert "Basket weaving" not in iot["skill_gap"]["skills_you_have"]


def test_request_skills_and_profile_skills_count_once():
    ctx = _ctx(skills=[{"name": "Python", "level": "Beginner"}])
    both = _recs(ctx, known_skills=["python"])
    profile_only = _recs(ctx)
    ml_both = next(r for r in both if r["project_id"] == "ml")
    ml_profile = next(r for r in profile_only if r["project_id"] == "ml")
    assert ml_both["skill_gap"]["skills_you_have"] == ml_profile["skill_gap"]["skills_you_have"] == ["Python"]
    assert ml_both["skill_gap"]["readiness_percent"] == ml_profile["skill_gap"]["readiness_percent"]


# --- interests: preference, not filter; no double counting --------------------------------------


def test_interests_rank_but_do_not_exclude():
    recs = _recs(_ctx(skills=[{"name": "Python", "level": "Beginner"}], interests=["Internet of Things"]))
    assert {"ml", "web", "iot"} <= set(_ids(recs))


def test_interest_effect_is_bounded_by_its_weight():
    skills = [{"name": "Python", "level": "Beginner"}]
    with_interest = {r["project_id"]: r["overall_score"] for r in _recs(_ctx(skills=skills, interests=["Internet of Things"]))}
    without = {r["project_id"]: r["overall_score"] for r in _recs(_ctx(skills=skills))}
    swing = max(abs(with_interest[p] - without[p]) for p in without)
    assert 0 < swing <= 100 * config.RECOMMEND_INTEREST_WEIGHT / (config.RECOMMEND_INTEREST_WEIGHT + config.RECOMMEND_RELEVANCE_WEIGHT)


def test_an_explicit_domain_filter_disables_the_interest_signal():
    ctx = _ctx(skills=[{"name": "Python", "level": "Beginner"}], interests=["Machine Learning", "Internet of Things"])
    recs = _recs(ctx, domain="Machine Learning")
    assert _ids(recs) == ["ml"]
    assert recs[0]["profile_match"]["domain_interest"] is None  # not counted twice
    assert not any("interest" in f for f in recs[0]["matching_factors"])


def test_interest_domains_seed_the_query_when_none_was_given(pool):
    _recs(_ctx(interests=["Robotics"], skills=[{"name": "Python", "level": "Beginner"}]))
    assert "Python" in pool["query"] and "Robotics" in pool["query"]


# --- hours and deadlines ----------------------------------------------------------------------------


def test_preferred_length_is_soft_and_never_excludes():
    ctx = _ctx(skills=[{"name": "Python", "level": "Beginner"}], availability={"hours_per_week": None, "max_project_weeks": 7})
    recs = {r["project_id"]: r for r in _recs(ctx)}
    assert "long" in recs  # 20 weeks > 7 preferred, still offered
    assert recs["iot"]["overall_score"] > recs["long"]["overall_score"]  # a nudge in the ordering, not a filter


def test_preferred_length_explains_fit_and_overrun():
    ctx = _ctx(skills=[{"name": "Python", "level": "Beginner"}], availability={"hours_per_week": 10, "max_project_weeks": 8})
    recs = {r["project_id"]: r for r in _recs(ctx)}
    assert "within the 8 weeks you prefer" in recs["iot"]["recommendation_reason"]
    assert "longer than the 8 weeks you prefer" in recs["long"]["recommendation_reason"]


def test_fewer_weekly_hours_stretch_the_estimate_for_the_soft_preference():
    base = dict(skills=[{"name": "Python", "level": "Beginner"}])
    fast = {r["project_id"]: r for r in _recs(_ctx(**base, availability={"hours_per_week": 20, "max_project_weeks": 10}))}
    slow = {r["project_id"]: r for r in _recs(_ctx(**base, availability={"hours_per_week": 5, "max_project_weeks": 10}))}
    assert slow["ml"]["profile_match"]["pace_weeks"] > fast["ml"]["profile_match"]["pace_weeks"]


def test_an_explicit_deadline_is_the_only_hard_limit_and_overrides_the_preference():
    ctx = _ctx(skills=[{"name": "Python", "level": "Beginner"}], availability={"hours_per_week": 2, "max_project_weeks": 30})
    recs = _recs(ctx, max_duration_weeks=7)
    assert _ids(recs) == ["iot"]  # unscaled estimate vs the explicit deadline; hours do not tighten it
    assert recs[0]["profile_match"]["pace_weeks"] > 7  # the pace note is advisory only


def test_projects_with_no_duration_are_excluded_only_by_an_explicit_deadline():
    ctx = _ctx(skills=[{"name": "Python", "level": "Beginner"}], availability={"hours_per_week": None, "max_project_weeks": 6})
    assert "bare" in _ids(_recs(ctx))
    assert "bare" not in _ids(_recs(ctx, max_duration_weeks=52))


# --- missing metadata / empty ------------------------------------------------------------------------------


def test_projects_missing_metadata_are_handled():
    recs = _recs(_ctx(skills=[{"name": "Python", "level": "Beginner"}], interests=["Robotics"]))
    bare = next(r for r in recs if r["project_id"] == "bare")
    assert bare["profile_match"]["skills_you_have"] == []
    assert bare["profile_match"]["domain_interest"] is True


def test_an_empty_candidate_pool_returns_an_empty_list(monkeypatch):
    monkeypatch.setattr(recommend, "search", lambda *a, **k: [])
    assert _recs(_ctx(skills=[{"name": "Python", "level": "Beginner"}])) == []


def test_profile_with_no_query_signal_and_no_request_returns_nothing():
    assert _recs(_ctx(availability={"hours_per_week": 5, "max_project_weeks": None})) == []


def test_catalogue_documents_are_never_mutated():
    before = copy.deepcopy(DOCS)
    _recs(_ctx(skills=[{"name": "Python", "level": "Beginner"}], interests=["Robotics"]))
    assert DOCS == before


# --- HTTP ----------------------------------------------------------------------------------------------------------


def _signup(client, email):
    res = client.post("/api/auth/signup", json={"email": email, "password": "correcthorse1", "name": "T"})
    assert res.status_code == 201
    return {"X-Auth-Token": res.get_json()["token"]}


def _recommend(client, headers=None, **body):
    return client.post("/api/recommend", json=body, headers=headers or {})


def test_default_response_shape_is_unchanged(client):
    res = _recommend(client, known_skills=["Python"])
    body = res.get_json()
    assert res.status_code == 200
    assert "personalization" not in body
    assert all("profile_match" not in r for r in body["data"])


def test_use_profile_must_be_a_boolean(client):
    assert _recommend(client, known_skills=["Python"], use_profile="yes").status_code == 400


def test_signed_out_use_profile_is_answered_normally_with_a_reason(client):
    plain = _recommend(client, known_skills=["Python"]).get_json()
    asked = _recommend(client, known_skills=["Python"], use_profile=True).get_json()
    assert asked["personalization"] == {"requested": True, "applied": False, "reason": "sign_in_required"}
    assert asked["data"] == plain["data"]


def test_signed_out_use_profile_without_other_input_is_still_a_400(client):
    assert _recommend(client, use_profile=True).status_code == 400


def test_bogus_token_does_not_grant_a_profile(client):
    res = _recommend(client, headers={"X-Auth-Token": "bogus"}, known_skills=["Python"], use_profile=True)
    assert res.get_json()["personalization"]["reason"] == "sign_in_required"


def test_account_without_a_profile_gets_the_plain_results(client):
    headers = _signup(client, "none@example.com")
    plain = _recommend(client, known_skills=["Python"]).get_json()
    res = _recommend(client, headers, known_skills=["Python"], use_profile=True).get_json()
    assert res["personalization"]["applied"] is False and res["personalization"]["reason"] == "no_profile"
    assert res["data"] == plain["data"]


def test_profile_alone_is_enough_input_for_a_signed_in_request(client):
    headers = _signup(client, "a@example.com")
    client.put("/api/profile", json={"skills": [{"name": "reactjs", "level": "Intermediate"}], "interests": ["Web Development"]}, headers=headers)
    res = _recommend(client, headers, use_profile=True)
    body = res.get_json()
    assert res.status_code == 200 and body["count"] > 0
    assert body["personalization"]["applied"] is True
    assert body["personalization"]["skills_from_profile"] == 1
    assert body["personalization"]["interests"] == ["Web Development"]
    assert body["data"][0]["project_id"] in {"web", "long"}


def test_updating_the_profile_changes_the_next_response_without_a_new_account(client):
    headers = _signup(client, "a@example.com")
    client.put("/api/profile", json={"skills": ["Python"], "interests": ["Internet of Things"]}, headers=headers)
    first = _recommend(client, headers, use_profile=True).get_json()["data"]
    client.put("/api/profile", json={"interests": ["Web Development"]}, headers=headers)
    second = _recommend(client, headers, use_profile=True).get_json()["data"]
    assert first[0]["project_id"] == "iot"
    assert second[0]["project_id"] in {"web", "long"}


def test_each_account_only_ever_sees_its_own_profile_in_results(client):
    alice = _signup(client, "alice@example.com")
    bob = _signup(client, "bob@example.com")
    client.put("/api/profile", json={"skills": [{"name": "Basket weaving", "level": "Advanced"}, "Python"], "education": "Alice only"}, headers=alice)
    client.put("/api/profile", json={"skills": ["MQTT"]}, headers=bob)

    bob_body = _recommend(client, bob, use_profile=True).get_json()
    assert bob_body["personalization"]["skills_from_profile"] == 1
    text = str(bob_body)
    assert "Basket weaving" not in text and "Alice only" not in text

    alice_body = _recommend(client, alice, use_profile=True).get_json()
    assert alice_body["personalization"]["skills_from_profile"] == 2
    assert "MQTT" not in str(alice_body["personalization"])


def test_the_response_never_echoes_free_text_or_identity(client):
    headers = _signup(client, "a@example.com")
    client.put("/api/profile", json={"skills": ["Python"], "learning_goals": ["secret goal"], "education": "secret school"}, headers=headers)
    text = str(_recommend(client, headers, use_profile=True).get_json())
    assert "secret" not in text and "a@example.com" not in text


def test_explicit_request_values_beat_the_profile(client):
    headers = _signup(client, "a@example.com")
    client.put(
        "/api/profile",
        json={"skills": [{"name": n, "level": "Advanced"} for n in ("Python", "SQL", "Git")], "availability": {"max_project_weeks": 30}},
        headers=headers,
    )
    inferred = _recommend(client, headers, known_skills=["Python"], use_profile=True).get_json()["personalization"]
    assert inferred["experience_level"] == "Advanced" and inferred["experience_level_source"] == "profile_skill_levels"
    explicit = _recommend(client, headers, known_skills=["Python"], use_profile=True, experience_level="Beginner", max_duration_weeks=7).get_json()
    assert explicit["personalization"]["experience_level_source"] == "request"
    assert explicit["personalization"]["experience_level"] == "Beginner"
    assert all(r["timeline"]["predicted_weeks"] <= 7 for r in explicit["data"])


def test_a_dismissal_only_profile_is_treated_as_no_profile(client):
    headers = _signup(client, "a@example.com")
    client.put("/api/profile", json={"onboarding_dismissed": True}, headers=headers)
    body = _recommend(client, headers, known_skills=["Python"], use_profile=True).get_json()
    assert body["personalization"]["applied"] is False
