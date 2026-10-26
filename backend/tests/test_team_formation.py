"""Smart team formation (Feature 6): nlp/team_formation.py and
POST /api/teams/formation. The engine is pure and tested on plain dicts; the
HTTP tests fake the retriever's document store (no model, no network) and check
the privacy and no-side-effect guarantees through the real routes."""

from __future__ import annotations

import copy

import pytest

from db import client as db
from nlp import recommend
from nlp import team_formation as tf

DOC = {
    "project_id": "pm-x", "title": "Campus Marketplace", "domain": "Web Development", "difficulty": "Intermediate",
    "technologies": ["React", "Node.js", "PostgreSQL"], "skills": ["REST API development", "Authentication"], "keywords": [],
}


def C(name, skills, source="profile", preferred=None, status="complete"):
    return {
        "id": name.lower(), "name": name, "source": source,
        "skills": [{"name": n, "level": lv} for n, lv in skills],
        "preferred_roles": preferred or [], "interests": [], "profile_status": status,
    }


FRONT = [("React", "Advanced"), ("CSS", "Advanced"), ("HTML", "Advanced"), ("TypeScript", "Advanced")]
BACK = [("Node.js", "Advanced"), ("Express", "Intermediate")]
DB = [("PostgreSQL", "Advanced"), ("SQL", "Advanced")]


def teams(result):
    return {t["key"]: t for t in result["teams"]}


def members(team):
    return sorted(m["name"] for m in team["members"])


# --- complementarity vs individual scores ---------------------------------------------------------


def test_complementary_team_beats_redundant_high_scorers():
    pool = [C("F1", FRONT), C("F2", FRONT), C("F3", FRONT), C("Ben", BACK), C("Dee", DB)]
    result = tf.form_teams(DOC, pool, team_size=3)
    best = teams(result)["best_coverage"]
    assert {"Ben", "Dee"} <= set(members(best))
    ref = teams(result)["top_individuals"]
    assert set(members(ref)) == {"F1", "F2", "F3"} and ref["recommended"] is False
    assert best["requirements"]["solid"] > ref["requirements"]["solid"]
    assert best["vs_individual_ranking"]["covers_more"] is True
    assert "instead of by how their skills combine" in ref["explanation"]


def test_a_lower_scoring_candidate_is_chosen_for_a_skill_nobody_else_has():
    pool = [C("Ada", FRONT), C("Ben", BACK), C("Low", [("PostgreSQL", "Beginner")])]
    result = tf.form_teams(DOC, pool, team_size=3)
    best = teams(result)["best_coverage"]
    low = next(m for m in best["members"] if m["name"] == "Low")
    # Beginner is below this Intermediate project's bar for a stack technology: partial, but still the only coverage of it
    assert [(c["skill"], c["strength"]) for c in low["contributes"]] == [("PostgreSQL", "partial")]
    pg = next(i for i in best["requirements"]["items"] if i["skill"] == "PostgreSQL")
    assert pg["status"] == "partial" and pg["partial_by"] == ["Low"]
    without = tf.form_teams(DOC, [C("Ada", FRONT), C("Ben", BACK)], team_size=2)
    assert teams(without)["best_coverage"]["requirements"]["partial"] < best["requirements"]["partial"]


def test_requirements_covered_by_several_people_are_listed_with_all_holders():
    result = tf.form_teams(DOC, [C("A", FRONT), C("B", FRONT)], team_size=2)
    react = next(i for i in teams(result)["best_coverage"]["requirements"]["items"] if i["skill"] == "React")
    assert react["status"] == "solid" and react["solid_by"] == ["A", "B"]


def test_uncovered_requirements_are_named_and_pool_gaps_suggest_recruiting():
    result = tf.form_teams(DOC, [C("A", FRONT), C("B", FRONT)], team_size=2)
    best = teams(result)["best_coverage"]
    assert {"Node.js", "PostgreSQL", "REST API development", "Authentication"} <= {i["skill"] for i in best["requirements"]["items"] if i["status"] == "uncovered"}
    assert "Node.js" in best["explanation"] and "not covered" in best["explanation"]
    assert any("Consider recruiting" in n for n in result["notes"])
    assert "Node.js" in result["pool"]["coverage"]["uncovered"]


# --- sizes and pools -----------------------------------------------------------------------------------


def test_default_size_is_documented_and_bounded():
    pool = [C(f"P{i}", FRONT + BACK + DB) for i in range(6)]
    result = tf.form_teams(DOC, pool)
    assert result["inputs"]["source"] == "default" and 2 <= result["inputs"]["team_size"] <= 4
    assert "between 2 and 4" in result["inputs"]["default_rule"]


@pytest.mark.parametrize("size", [1, 2, 3, 5])
def test_explicit_size_is_respected_and_no_smaller_variant_is_offered(size):
    pool = [C(f"P{i}", FRONT + BACK + DB) for i in range(6)]
    result = tf.form_teams(DOC, pool, team_size=size)
    assert result["inputs"] == {"team_size": size, "requested": size, "source": "requested", "default_rule": None}
    assert all(t["size"] == size for t in result["teams"])
    assert "smaller" not in teams(result)


def test_smaller_team_is_offered_only_for_the_default_size_and_only_if_coverage_holds():
    pool = [C("Ada", FRONT + BACK + DB), C("X", [("React", "Advanced")]), C("Y", [("Node.js", "Advanced")])]
    result = tf.form_teams(DOC, pool)
    smaller = teams(result).get("smaller")
    assert smaller and smaller["size"] < result["inputs"]["team_size"] and members(smaller) == ["Ada"]
    assert smaller["requirements"]["solid"] >= teams(result)["best_coverage"]["requirements"]["solid"] * tf.ACCEPTABLE_FRACTION


def test_size_is_capped_by_the_matchable_pool_and_says_so():
    result = tf.form_teams(DOC, [C("A", FRONT), C("B", BACK)], team_size=5)
    assert result["inputs"]["team_size"] == 2 and any("rather than 5" in n for n in result["notes"])


def test_single_candidate_gets_one_team_and_no_alternatives():
    result = tf.form_teams(DOC, [C("Solo", FRONT + BACK)], team_size=1)
    assert [t["key"] for t in result["teams"]] == ["best_coverage"]
    assert any("no alternative teams" in n for n in result["notes"])


def test_balanced_alternative_is_offered_when_it_keeps_coverage_with_less_dependence_on_one_person():
    pool = [
        C("P0", [("React", "Advanced")]),
        C("P1", [("PostgreSQL", "Advanced"), ("Authentication", "Advanced"), ("REST API development", "Advanced")]),
        C("P2", [("Node.js", "Advanced"), ("Authentication", "Advanced")]),
        C("P3", [("REST API development", "Advanced"), ("React", "Advanced")]),
        C("P4", [("Authentication", "Advanced"), ("Node.js", "Advanced"), ("REST API development", "Advanced")]),
    ]
    ts = teams(tf.form_teams(DOC, pool, team_size=2))
    assert members(ts["best_coverage"]) == ["P1", "P3"] and members(ts["balanced"]) == ["P1", "P4"]
    assert ts["balanced"]["requirements"]["solid"] == ts["best_coverage"]["requirements"]["solid"] == 4
    assert ts["balanced"]["label"] == "More evenly shared responsibilities"


def test_bottleneck_is_reported_for_a_single_person_dependency():
    result = tf.form_teams(DOC, [C("Star", FRONT + BACK + DB), C("Minor", [("HTML", "Beginner")])], team_size=2)
    best = teams(result)["best_coverage"]
    assert best["bottlenecks"] and best["bottlenecks"][0]["member"] == "Star"
    assert "only person" in best["bottlenecks"][0]["note"]


def test_alternatives_are_distinct_teams():
    pool = [C(f"P{i}", FRONT if i % 2 else BACK + DB) for i in range(7)]
    result = tf.form_teams(DOC, pool)
    sets = [frozenset(members(t)) for t in result["teams"]]
    assert len(sets) == len(set(sets))


# --- missing and messy data ---------------------------------------------------------------------------------


def test_candidates_without_skills_are_never_invented_and_are_reported_neutrally():
    result = tf.form_teams(DOC, [C("A", FRONT), C("Nobody", [], source="none", status="not_started")], team_size=2)
    assert result["pool"]["not_matched"] == [{"name": "Nobody", "source": "none", "reason": "No skills on file for this person. That says nothing about what they can do."}]
    assert all("Nobody" not in members(t) for t in result["teams"])
    assert result["inputs"]["team_size"] == 1


def test_all_candidates_without_skills_yields_no_teams_and_explains():
    result = tf.form_teams(DOC, [C("A", [], source="none"), C("B", [], source="none")])
    assert result["teams"] == [] and any("None of the candidates has skills" in n for n in result["notes"])


def test_project_without_requirements_gets_no_optimisation():
    result = tf.form_teams({**DOC, "technologies": [], "skills": []}, [C("A", FRONT)])
    assert result["teams"] == [] and any("nothing to optimise" in n for n in result["notes"])


def test_sparse_requirements_are_flagged_as_loosely_specific():
    result = tf.form_teams({**DOC, "technologies": ["React"], "skills": []}, [C("A", FRONT)], team_size=1)
    assert result["requirements"]["limited"] is True and any("loosely project-specific" in x for x in result["limitations"])


def test_past_project_and_manual_skills_without_levels_count_as_partial_on_harder_projects():
    pool = [C("Hist", [("React", None), ("Node.js", None)], source="profile")]
    result = tf.form_teams(DOC, pool, team_size=1)
    items = {i["skill"]: i for i in teams(result)["best_coverage"]["requirements"]["items"]}
    assert items["React"]["status"] == "partial" and items["React"]["partial_by"] == ["Hist"]
    contrib = {c["skill"]: c for c in teams(result)["best_coverage"]["members"][0]["contributes"]}
    assert contrib["React"]["level"] is None and contrib["React"]["strength"] == "partial"


def test_unlevelled_skills_are_solid_on_a_beginner_project():
    result = tf.form_teams({**DOC, "difficulty": "Beginner"}, [C("Hist", [("React", None)])], team_size=1)
    assert next(i for i in teams(result)["best_coverage"]["requirements"]["items"] if i["skill"] == "React")["status"] == "solid"


def test_aliases_collapse_and_match_requirements():
    pool = [C("Al", [("reactjs", "Advanced"), ("nodejs", "Advanced")])]
    items = {i["skill"]: i for i in teams(tf.form_teams(DOC, pool, team_size=1))["best_coverage"]["requirements"]["items"]}
    assert items["React"]["status"] == "solid" and items["Node.js"]["status"] == "solid"


def test_related_only_skills_earn_no_coverage():
    result = tf.form_teams({**DOC, "technologies": ["React", "Node.js"], "skills": ["REST API development"]}, [C("R", [("REST", "Advanced")])], team_size=1)
    item = next(i for i in teams(result)["best_coverage"]["requirements"]["items"] if i["skill"] == "REST API development")
    assert item["status"] == "uncovered"


def test_custom_and_unknown_skills_are_kept_but_never_match_unrelated_requirements():
    result = tf.form_teams(DOC, [C("Weird", [("Basket weaving", "Advanced"), ("React", "Advanced")])], team_size=1)
    best = teams(result)["best_coverage"]
    assert [c["skill"] for c in best["members"][0]["contributes"]] == ["React"]
    custom = tf.form_teams({**DOC, "technologies": ["Obscure Thing"], "skills": ["Search"]}, [C("Weird", [("obscure thing", "Advanced")])], team_size=1)
    assert next(i for i in teams(custom)["best_coverage"]["requirements"]["items"] if i["skill"] == "Obscure Thing")["status"] == "solid"


def test_members_expose_only_requirement_relevant_skills_and_no_private_fields():
    pool = [{**C("A", FRONT + [("Basket weaving", "Advanced")]), "education": "secret school", "learning_goals": ["secret goal"], "email": "a@b.co"}]
    text = str(tf.form_teams(DOC, pool, team_size=1))
    for leaked in ("secret", "a@b.co", "Basket weaving", "CSS", "HTML"):
        assert leaked not in text


# --- roles are reused from Feature 3 -----------------------------------------------------------------------------


def test_roles_section_comes_from_the_existing_role_coverage_logic():
    result = tf.form_teams(DOC, [C("Ada", FRONT), C("Ben", BACK), C("Dee", DB)], team_size=3)
    best = teams(result)["best_coverage"]
    assert {c["role"] for c in best["roles"]["covered"]} >= {"Frontend Developer", "Backend Developer"}
    by = {m["name"]: m["suggested_role"]["role"] for m in best["members"]}
    assert by["Ada"] == "Frontend Developer" and by["Ben"] == "Backend Developer"
    assert set(best["roles"]) == {"needed_roles", "covered", "gaps", "overlaps", "plan", "optional_roles"}


def test_individual_role_fit_is_not_changed_by_who_else_is_on_the_team():
    from nlp import team_builder as tb
    solo = tb.role_fit(DOC, [C("Ada", FRONT)])["members"][0]["suggested"]["score"]
    in_team = next(m for m in tf.form_teams(DOC, [C("Ada", FRONT), C("Ben", BACK)], team_size=2)["teams"][0]["members"] if m["name"] == "Ada")
    assert in_team["suggested_role"]["score"] == solo


# --- determinism / safety ------------------------------------------------------------------------------------------


def test_identical_inputs_give_identical_output_in_any_candidate_order():
    pool = [C("A", FRONT), C("B", BACK), C("D", DB), C("E", FRONT + BACK)]
    a = tf.form_teams(DOC, pool)
    b = tf.form_teams(DOC, list(reversed(pool)))
    assert a == tf.form_teams(DOC, pool)
    assert [(t["key"], members(t)) for t in a["teams"]] == [(t["key"], members(t)) for t in b["teams"]]


def test_inputs_are_not_mutated():
    pool, doc = [C("A", FRONT), C("B", BACK)], copy.deepcopy(DOC)
    before = copy.deepcopy(pool)
    tf.form_teams(doc, pool, team_size=2)
    assert pool == before and doc == DOC


def test_large_pools_fall_back_to_greedy_and_say_so(monkeypatch):
    monkeypatch.setattr(tf, "EXHAUSTIVE_LIMIT", 5)
    pool = [C(f"P{i}", FRONT if i % 3 == 0 else BACK if i % 3 == 1 else DB) for i in range(9)]
    result = tf.form_teams(DOC, pool, team_size=3)
    assert any("greedily" in x for x in result["limitations"])
    best = teams(result)["best_coverage"]
    assert best["requirements"]["solid"] >= 3 and result == tf.form_teams(DOC, pool, team_size=3)


def test_no_probabilities_or_percentages_are_claimed():
    text = str(tf.form_teams(DOC, [C("A", FRONT), C("B", BACK)], team_size=2)).lower()
    for banned in ("probab", "optimal team", "% match", "percent"):
        assert banned not in text.replace("not a claim that a team is objectively optimal", "")


def test_limitations_state_the_assumptions():
    lim = " ".join(tf.form_teams(DOC, [C("A", FRONT)], team_size=1)["limitations"]).lower()
    assert "self-reported" in lim and "availability" in lim and "heuristic" in lim


# --- HTTP ------------------------------------------------------------------------------------------------------------


class _Fake:
    def __init__(self, docs):
        self.documents = docs


@pytest.fixture
def api(client, monkeypatch):
    monkeypatch.setattr(recommend, "get_retriever", lambda: _Fake({"pm-x": copy.deepcopy(DOC), "pm-empty": {**DOC, "project_id": "pm-empty", "technologies": [], "skills": []}}))
    db.projects().insert_one({**DOC})
    return client


def signup(client, email, name="Member"):
    res = client.post("/api/auth/signup", json={"email": email, "password": "correcthorse1", "name": name})
    assert res.status_code == 201
    return {"X-Auth-Token": res.get_json()["token"]}


def post(client, h, **body):
    return client.post("/api/teams/formation", json=body, headers=h)


def snapshot():
    return {n: sorted(str(d) for d in c.find({})) for n, c in {
        "teams": db.teams(), "users": db.users(), "profiles": db.profiles(), "notifications": db.notifications(),
        "progress": db.roadmap_progress(), "favorites": db.favorites(),
    }.items()}


def test_requires_sign_in(api):
    assert api.post("/api/teams/formation", json={"project_id": "pm-x"}).status_code == 401
    assert api.post("/api/teams/formation", json={"project_id": "pm-x"}, headers={"X-Auth-Token": "bogus"}).status_code == 401
    assert api.post("/api/teams/formation", json={"project_id": "pm-x"}, headers={"X-Device-Id": "d"}).status_code == 401


@pytest.mark.parametrize("body,code", [
    ({}, 400), ({"project_id": ""}, 400), ({"project_id": 5}, 400), ({"project_id": "x" * 65}, 400), ({"project_id": "nope"}, 404),
    ({"project_id": "pm-x", "team_size": 0}, 400), ({"project_id": "pm-x", "team_size": 9}, 400), ({"project_id": "pm-x", "team_size": True}, 400),
    ({"project_id": "pm-x", "team_size": 2.5}, 400), ({"project_id": "pm-x", "team_size": "3"}, 400),
    ({"project_id": "pm-x", "include_self": "yes"}, 400), ({"project_id": "pm-x", "team_id": 5}, 400),
    ({"project_id": "pm-x", "candidates": "bob"}, 400), ({"project_id": "pm-x", "candidates": [5]}, 400),
    ({"project_id": "pm-x", "candidates": [{"name": "", "skills": []}]}, 400), ({"project_id": "pm-x", "candidates": [{"name": "A", "skills": "x"}]}, 400),
    ({"project_id": "pm-x", "candidates": [{"name": "A", "skills": [1]}]}, 400),
    ({"project_id": "pm-x", "candidates": [{"name": "A" * 61, "skills": []}]}, 400),
    ({"project_id": "pm-x", "candidates": [{"name": f"P{i}", "skills": []} for i in range(13)]}, 400),
    ({"project_id": "pm-x", "include_self": False}, 400),
])
def test_validation(api, body, code):
    h = signup(api, "a@example.com")
    assert post(api, h, **body).status_code == code


def test_pool_size_limit(api):
    h = signup(api, "a@example.com")
    many = [{"name": f"P{i}", "skills": ["React"]} for i in range(12)]
    assert post(api, h, project_id="pm-x", candidates=many).status_code == 200
    team = api.post("/api/teams", json={"project_id": "pm-x", "name": "T"}, headers=h).get_json()["data"]
    for i in range(3):
        j = signup(api, f"m{i}@example.com")
        api.post("/api/teams/join", json={"invite_code": team["invite_code"]}, headers=j)
    assert post(api, h, project_id="pm-x", team_id=team["team_id"], candidates=many).status_code == 400


def test_self_candidate_uses_the_saved_profile_and_is_private_to_the_caller(api):
    h = signup(api, "a@example.com", "Ada")
    api.put("/api/profile", json={"skills": [{"name": "reactjs", "level": "Advanced"}], "education": "secret school", "learning_goals": ["secret goal"]}, headers=h)
    res = post(api, h, project_id="pm-x", team_size=1)
    assert res.status_code == 200
    body = res.get_json()["data"]
    best = teams(body)["best_coverage"]
    assert best["members"][0]["name"] == "Ada" and best["members"][0]["source"] == "profile"
    assert [c["skill"] for c in best["members"][0]["contributes"]] == ["React"]
    assert "secret" not in str(body) and "a@example.com" not in str(body)


def test_manual_candidates_work_without_accounts_and_are_not_stored(api):
    h = signup(api, "a@example.com")
    before = snapshot()
    res = post(api, h, project_id="pm-x", include_self=False, team_size=2, candidates=[
        {"name": "Friend A", "skills": ["react", "css"]}, {"name": "Friend B", "skills": ["nodejs", "postgres"]}])
    body = res.get_json()["data"]
    assert members(teams(body)["best_coverage"]) == ["Friend A", "Friend B"]
    assert all(m["user_id"] is None and m["source"] == "manual" and m["profile_status"] is None for m in teams(body)["best_coverage"]["members"])
    assert snapshot() == before


def test_team_roster_is_the_pool_for_members_only(api):
    owner, member = signup(api, "o@example.com", "Owner"), signup(api, "m@example.com", "Mem")
    team = api.post("/api/teams", json={"project_id": "pm-x", "name": "T"}, headers=owner).get_json()["data"]
    api.post("/api/teams/join", json={"invite_code": team["invite_code"]}, headers=member)
    api.put("/api/profile", json={"skills": [{"name": "React", "level": "Advanced"}], "education": "secret", "share_with_teams": True}, headers=owner)
    api.put("/api/profile", json={"skills": [{"name": "Node.js", "level": "Advanced"}], "learning_goals": ["secret goal"], "share_with_teams": True}, headers=member)

    body = post(api, member, project_id="pm-x", team_id=team["team_id"], team_size=2).get_json()["data"]
    best = teams(body)["best_coverage"]
    assert members(best) == ["Mem", "Owner"]
    assert {m["name"]: [c["skill"] for c in m["contributes"]] for m in best["members"]} == {"Owner": ["React"], "Mem": ["Node.js"]}
    assert "secret" not in str(body)

    outsider = signup(api, "x@example.com")
    assert post(api, outsider, project_id="pm-x", team_id=team["team_id"]).status_code == 404
    assert post(api, outsider, project_id="pm-x", team_id="no-such-team").status_code == 404


def test_cannot_name_other_accounts_to_reach_their_profiles(api):
    alice, bob = signup(api, "alice@example.com", "Alice"), signup(api, "bob@example.com", "Bob")
    api.put("/api/profile", json={"skills": [{"name": "Solidity", "level": "Advanced"}, {"name": "React", "level": "Advanced"}]}, headers=alice)
    uid = api.get("/api/auth/me", headers=alice).get_json()["data"]["user_id"]
    res = post(api, bob, project_id="pm-x", user_id=uid, user_ids=[uid], candidates=[{"name": "Alice", "user_id": uid, "skills": []}])
    body = res.get_json()["data"]
    # Bob (no profile) and a typed "Alice" (no skills) are the whole pool: the real Alice's profile is unreachable.
    assert body["teams"] == []
    assert [c["name"] for c in body["pool"]["not_matched"]] == ["Bob", "Alice"]
    assert "Solidity" not in str(body) and uid not in str(body)


def test_nothing_is_created_invited_or_changed(api):
    owner = signup(api, "o@example.com", "Owner")
    team = api.post("/api/teams", json={"project_id": "pm-x", "name": "T"}, headers=owner).get_json()["data"]
    api.put("/api/profile", json={"skills": [{"name": "React", "level": "Advanced"}]}, headers=owner)
    api.put(f"/api/teams/{team['team_id']}/roles/mine", json={"status": "accepted", "role": "Frontend Developer"}, headers=owner)
    before = snapshot()
    for body in ({"project_id": "pm-x"}, {"project_id": "pm-x", "team_id": team["team_id"], "team_size": 1}, {"project_id": "pm-empty"},
                 {"project_id": "pm-x", "candidates": [{"name": "Z", "skills": ["Node.js"]}]}):
        assert post(api, owner, **body).status_code == 200
    assert snapshot() == before
    assert db.teams().count_documents({}) == 1


def test_project_without_requirements_is_reported(api):
    h = signup(api, "a@example.com")
    body = post(api, h, project_id="pm-empty", candidates=[{"name": "A", "skills": ["React"]}]).get_json()["data"]
    assert body["teams"] == [] and body["requirements"] == {"total": 0, "limited": True}


def test_response_shape_and_determinism(api):
    h = signup(api, "a@example.com")
    req = dict(project_id="pm-x", team_size=2, candidates=[{"name": "A", "skills": ["react"]}, {"name": "B", "skills": ["nodejs"]}, {"name": "C", "skills": ["postgres"]}])
    a = post(api, h, **req).get_json()
    assert set(a["data"]) == {"project", "requirements", "pool", "objective", "teams", "limitations", "notes", "inputs"}
    team = a["data"]["teams"][0]
    assert set(team) == {"key", "label", "recommended", "size", "members", "requirements", "roles", "bottlenecks", "explanation", "vs_individual_ranking"}
    assert post(api, h, **req).get_json() == a


def test_duplicate_display_names_stay_separate(api):
    h = signup(api, "a@example.com", "Sam")
    api.put("/api/profile", json={"skills": ["React"]}, headers=h)
    body = post(api, h, project_id="pm-x", team_size=2, candidates=[{"name": "Sam", "skills": ["Node.js"]}]).get_json()["data"]
    assert sorted(m["name"] for m in teams(body)["best_coverage"]["members"]) == ["Sam", "Sam (2)"]


def test_existing_team_builder_and_role_endpoints_are_unchanged(api):
    h = signup(api, "a@example.com")
    res = api.post("/api/team-builder", json={"project_id": "pm-x", "members": [{"name": "A", "skills": ["React"]}]})
    assert res.status_code == 200 and set(res.get_json()["data"]) >= {"assignments", "unassigned_members", "unfilled_roles", "roles"}
    team = api.post("/api/teams", json={"project_id": "pm-x", "name": "T"}, headers=h).get_json()["data"]
    roles = api.get(f"/api/teams/{team['team_id']}/roles", headers=h).get_json()["data"]
    assert {"role_fit", "decisions", "assignments"} <= set(roles)
