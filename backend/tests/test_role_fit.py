"""Profile-aware job-role suggestions and team coverage (Feature 3).

The engine (nlp/team_builder.py: role_fit & friends) is pure and tested on plain
dicts; the HTTP tests cover profile resolution, privacy and role decisions
through the real routes. The legacy module-level suggest_roles() has its own
suite (test_team_builder.py, test_teams*.py) and must keep passing unchanged.
"""

from __future__ import annotations

import pytest

from db import client as db
from nlp import team_builder as tb
from profiles.service import TEAM_ROLES

WEB_DOC = {
    "project_id": "pm-web",
    "title": "Campus Marketplace",
    "domain": "Web Development",
    "difficulty": "Intermediate",
    "technologies": ["React", "Node.js", "PostgreSQL"],
    "skills": ["REST API development"],
    "duration_weeks": 8,
}


def S(name, level=None):
    return {"name": name, "level": level}


def M(name, skills, source="profile", preferred=None, interests=None, uid=None):
    return {
        "id": uid or name.lower(),
        "name": name,
        "source": source,
        "skills": skills,
        "preferred_roles": preferred or [],
        "interests": interests or [],
        "profile_status": "complete" if source != "none" else "not_started",
    }


def fit(members, doc=WEB_DOC):
    return tb.role_fit(doc, members)


def suggested(result, name):
    return next(m for m in result["members"] if m["name"] == name)["suggested"]


# --- vocabulary ----------------------------------------------------------------------


def test_every_profile_role_has_rules_and_vice_versa():
    assert set(tb.ROLE_KEYWORDS) == set(TEAM_ROLES)


def test_all_requested_roles_exist():
    for role in ("Frontend Developer", "Backend Developer", "Full-Stack Developer", "AI / ML Engineer", "Data Engineer",
                 "Database Engineer", "QA / Test Engineer", "DevOps Engineer", "UI / UX Designer", "Project Coordinator"):
        assert role in tb.ROLE_KEYWORDS


# --- individual scoring ----------------------------------------------------------------------


def test_complete_profile_gets_a_supported_explained_suggestion():
    result = fit([M("Ada", [S("React", "Advanced"), S("CSS", "Intermediate"), S("TypeScript", "Intermediate")])])
    top = suggested(result, "Ada")
    assert top["role"] == "Frontend Developer"
    assert top["confidence"] == "strong"
    assert [s["name"] for s in top["supporting_skills"]] == ["React", "CSS", "TypeScript"]
    assert "saved profile" in top["explanation"] and "self-reported" in top["explanation"]
    assert "Node.js" in top["missing_skills"] or top["missing_skills"] == []  # only front-end needs are this role's


def test_scores_are_bounded_and_deterministic():
    skills = [S(n, "Advanced") for n in ("React", "Vue", "Angular", "CSS", "HTML", "TypeScript", "Redux", "Sass")]
    a, b = fit([M("Ada", skills)]), fit([M("Ada", skills)])
    assert a == b
    assert 0 <= suggested(a, "Ada")["score"] <= 100


def test_more_and_stronger_evidence_never_lowers_a_score():
    base = tb.score_role("Frontend Developer", [S("React", "Beginner")], [], [])["score"]
    more = tb.score_role("Frontend Developer", [S("React", "Beginner"), S("CSS", "Beginner")], [], [])["score"]
    stronger = tb.score_role("Frontend Developer", [S("React", "Advanced"), S("CSS", "Beginner")], [], [])["score"]
    assert base < more < stronger <= 100


def test_proficiency_changes_the_score_but_is_labelled_self_reported():
    beginner = tb.score_role("Backend Developer", [S("Flask", "Beginner")], [], [])
    advanced = tb.score_role("Backend Developer", [S("Flask", "Advanced")], [], [])
    assert advanced["score"] > beginner["score"]


def test_unlevelled_skills_count_between_beginner_and_intermediate():
    lv = lambda lvl: tb.score_role("Backend Developer", [S("Flask", lvl)], [], [])["score"]
    assert lv("Beginner") < lv(None) < lv("Intermediate")


def test_a_preferred_role_without_evidence_scores_zero():
    fit_ = tb.score_role("DevOps Engineer", [S("React", "Advanced")], ["DevOps Engineer"], [])
    assert fit_["score"] == 0 and fit_["preferred"] is True


def test_preference_helps_only_when_there_is_also_evidence():
    skills = [S("Docker", "Intermediate"), S("Linux", "Intermediate")]
    plain = tb.score_role("DevOps Engineer", skills, [], [])["score"]
    preferred = tb.score_role("DevOps Engineer", skills, ["DevOps Engineer"], [])["score"]
    other_pref = tb.score_role("DevOps Engineer", skills, ["QA / Test Engineer"], [])["score"]
    assert preferred > plain > other_pref


def test_preference_is_a_small_part_of_the_score():
    skills = [S("Docker", "Intermediate")]
    assert tb.score_role("DevOps Engineer", skills, ["DevOps Engineer"], [])["score"] - tb.score_role(
        "DevOps Engineer", skills, [], [])["score"] < 20


def test_aliases_resolve_to_the_same_evidence():
    a = tb.score_role("Frontend Developer", [S("reactjs", "Advanced")], [], [])["score"]
    b = tb.score_role("Frontend Developer", [S("React", "Advanced")], [], [])["score"]
    assert a == b > 0


def test_keywords_match_whole_words_not_substrings():
    assert tb.score_role("UI / UX Designer", [S("Build systems", "Advanced")], [], [])["score"] == 0
    assert tb.score_role("Backend Developer", [S("Hexagonal", "Advanced")], [], [])["score"] == 0
    # "java" is not "javascript"
    assert tb.score_role("Backend Developer", [S("JavaScript", "Advanced")], [], [])["score"] < tb.score_role(
        "Backend Developer", [S("Java", "Advanced")], [], [])["score"]


def test_custom_skills_that_match_nothing_give_no_role_but_do_not_crash():
    result = fit([M("Bo", [S("Basket weaving", "Advanced")])])
    bo = next(m for m in result["members"] if m["name"] == "Bo")
    assert bo["suggested"] is None and "role area" in bo["message"]


def test_python_alone_is_weak_evidence_and_does_not_make_an_ml_engineer():
    result = fit([M("Cy", [S("Python", "Advanced")])])
    top = suggested(result, "Cy")
    assert top is None or top["confidence"] != "strong"


def test_project_coverage_changes_the_score_and_lists_missing_skills():
    skills = [S("React", "Advanced"), S("CSS", "Advanced")]
    with_reqs = tb.score_role("Frontend Developer", skills, [], ["React", "Vue"])
    assert with_reqs["missing_skills"] == ["Vue"]
    assert with_reqs["components"]["coverage"] == 0.5
    without = tb.score_role("Frontend Developer", skills, [], [])
    assert "coverage" not in without["components"] and without["missing_skills"] == []


def test_missing_requirements_neither_help_nor_hurt():
    skills = [S("Flask", "Intermediate"), S("Django", "Intermediate")]
    no_doc = tb.role_fit(None, [M("Di", skills)])
    assert no_doc["has_project_requirements"] is False
    top = suggested(no_doc, "Di")
    assert top["role"] == "Backend Developer" and top["missing_skills"] == []
    assert no_doc["team"]["needed_roles"] == []


def test_full_stack_needs_both_sides():
    only_front = tb.score_role("Full-Stack Developer", [S("React", "Advanced"), S("CSS", "Advanced"), S("HTML", "Advanced")], [], [])
    both = tb.score_role("Full-Stack Developer", [S("React", "Advanced"), S("CSS", "Advanced"), S("Flask", "Advanced"), S("Django", "Advanced")], [], [])
    assert only_front["score"] == 0 or only_front["score"] < both["score"] / 2
    assert both["score"] >= 60


def test_balanced_front_and_back_evidence_suggests_full_stack_with_alternatives():
    result = fit([M("Eve", [S("React", "Advanced"), S("CSS", "Intermediate"), S("Node.js", "Advanced"), S("Express", "Intermediate")])])
    eve = next(m for m in result["members"] if m["name"] == "Eve")
    roles = [eve["suggested"]["role"]] + [a["role"] for a in eve["alternatives"]]
    assert "Full-Stack Developer" in roles and len(roles) <= 1 + tb.MAX_ALTERNATIVES
    assert {"Frontend Developer", "Backend Developer"} & set(roles)


def test_alternatives_must_be_meaningful_and_close():
    result = fit([M("Fay", [S("React", "Advanced"), S("CSS", "Advanced"), S("HTML", "Advanced")])])
    fay = next(m for m in result["members"] if m["name"] == "Fay")
    top = fay["suggested"]["score"]
    assert all(a["score"] >= tb.ALTERNATIVE_MIN_SCORE and a["score"] >= top - tb.ALTERNATIVE_BAND for a in fay["alternatives"])


def test_past_project_and_manual_sources_are_labelled_in_the_explanation():
    manual = fit([M("Gus", [S("Flask"), S("Django")], source="manual")])
    assert "entered for this team" in suggested(manual, "Gus")["explanation"]
    assert "Levels are self-reported" not in suggested(manual, "Gus")["explanation"]
    both = fit([M("Hal", [S("Flask", "Advanced"), S("Django")], source="profile+manual")])
    assert "profile and the skills they entered" in suggested(both, "Hal")["explanation"]


def test_interest_in_the_domain_is_mentioned_but_does_not_change_the_score():
    skills = [S("Flask", "Advanced"), S("Django", "Advanced")]
    a = suggested(fit([M("Ivy", skills, interests=["Web Development"])]), "Ivy")
    b = suggested(fit([M("Ivy", skills)]), "Ivy")
    assert a["score"] == b["score"] and "interested in Web Development" in a["explanation"]


# --- members with nothing --------------------------------------------------------------------


def test_member_without_skills_or_profile_gets_a_message_not_a_role():
    result = fit([M("Jo", [], source="none")])
    jo = result["members"][0]
    assert jo["suggested"] is None and "complete your profile" in jo["message"].lower()


def test_empty_team_returns_a_well_formed_empty_result():
    result = tb.role_fit(WEB_DOC, [])
    assert result["members"] == []
    assert result["team"]["covered"] == [] and result["team"]["plan"] == []


# --- team coverage -----------------------------------------------------------------------------


def team_of(*members, doc=WEB_DOC):
    return tb.role_fit(doc, list(members))["team"]


FRONT = [S("React", "Advanced"), S("CSS", "Advanced"), S("HTML", "Intermediate")]
BACK = [S("Node.js", "Advanced"), S("Express", "Intermediate"), S("REST", "Intermediate")]
DB = [S("PostgreSQL", "Advanced"), S("SQL", "Advanced"), S("MongoDB", "Intermediate")]


def test_needs_come_from_the_projects_modules_and_technologies():
    needs = {n["role"] for n in team_of(M("A", FRONT))["needed_roles"]}
    assert {"Frontend Developer", "Backend Developer"} <= needs


def test_a_complementary_team_covers_the_priority_roles():
    team = team_of(M("Ada", FRONT), M("Ben", BACK))
    covered = {c["role"] for c in team["covered"]}
    assert {"Frontend Developer", "Backend Developer"} <= covered
    assert team["gaps"] == [] and team["overlaps"] == []


def test_missing_role_is_a_gap_and_names_who_could_double_up():
    team = team_of(M("Ada", FRONT), M("Ben", [S("Flask", "Intermediate"), S("PostgreSQL", "Intermediate")]), M("Cy", FRONT))
    assert {c["role"]: c["primary"] for c in team["covered"]} == {"Frontend Developer": ["Ada", "Cy"], "Database Engineer": ["Ben"]}
    gap = next(g for g in team["gaps"] if g["role"] == "Backend Developer")
    assert [c["member"] for c in gap["candidates"]] == ["Ben"] and "alongside their main role" in gap["note"]


def test_a_gap_with_no_candidate_says_so_plainly():
    team = team_of(M("Ada", FRONT), M("Bea", FRONT))
    gap = next(g for g in team["gaps"] if g["role"] == "Backend Developer")
    assert gap["candidates"] == [] and "No one on the team" in gap["note"]


def test_overlap_suggests_rebalancing_only_to_someone_inside_the_overlap():
    # Ben (not in the front-end overlap) is the only backend candidate: no rebalance advice for Ada/Cy.
    team = team_of(M("Ada", FRONT), M("Ben", [S("Flask", "Intermediate"), S("PostgreSQL", "Intermediate")]), M("Cy", FRONT))
    overlap = next(o for o in team["overlaps"] if o["role"] == "Frontend Developer")
    assert overlap["members"] == ["Ada", "Cy"] and overlap["rebalance"] is False
    assert "large enough to share" in overlap["note"]


def test_the_plan_moves_a_person_to_an_uncovered_role_and_keeps_their_own_suggestion():
    team = team_of(M("Ada", FRONT), M("Bea", FRONT + [S("Flask", "Intermediate"), S("Django", "Intermediate")]))
    plan = {p["member"]: p for p in team["plan"]}
    assert plan["Ada"]["differs"] is False
    assert plan["Bea"]["role"] == "Backend Developer" and plan["Bea"]["individual_role"] == "Frontend Developer" and plan["Bea"]["differs"]
    assert team["overlaps"] == []  # once moved, nothing overlaps


def test_rebalance_is_offered_when_an_overlapping_member_can_fill_a_gap():
    both = FRONT + [S("Flask", "Intermediate")]
    team = team_of(M("Ada", FRONT + [S("Vue", "Advanced"), S("Angular", "Advanced")]), M("Bea", both), M("Cy", FRONT), doc=WEB_DOC)
    for o in team["overlaps"]:
        assert o["rebalance"] == ("could take" in o["note"])


def test_the_plan_never_changes_an_individual_suggestion():
    members = [M("Ada", FRONT), M("Bea", FRONT + [S("Flask", "Intermediate"), S("Django", "Intermediate")])]
    result = tb.role_fit(WEB_DOC, members)
    solo = tb.role_fit(WEB_DOC, members[1:])
    assert suggested(result, "Bea")["score"] == suggested(solo, "Bea")["score"]
    assert suggested(result, "Bea")["role"] == suggested(solo, "Bea")["role"]


def test_one_role_per_person_in_the_plan_and_priority_roles_not_duplicated_when_avoidable():
    team = team_of(M("Ada", FRONT), M("Ben", BACK), M("Cy", DB))
    assert {p["member"]: p["role"] for p in team["plan"]} == {"Ada": "Frontend Developer", "Ben": "Backend Developer", "Cy": "Database Engineer"}
    assert {p["member"] for p in team["plan"]} == {"Ada", "Ben", "Cy"}


def test_small_teams_are_not_told_every_specialty_is_missing():
    team = team_of(M("Solo", FRONT + BACK))
    priority = [n for n in team["needed_roles"] if n["priority"]]
    assert len(priority) == 2  # max(2, team size)
    assert len(team["needed_roles"]) > len(priority)  # the rest are optional, not gaps
    assert not {g["role"] for g in team["gaps"]} - {n["role"] for n in priority}


def test_one_person_who_can_cover_several_roles_is_shown():
    team = team_of(M("Eve", FRONT + BACK))
    assert team["multi_role_members"] and team["multi_role_members"][0]["member"] == "Eve"


def test_roster_with_members_who_have_nothing_still_works():
    team = team_of(M("Ada", FRONT), M("Nobody", [], source="none"))
    assert {p["member"] for p in team["plan"]} == {"Ada"}


def test_unknown_domain_still_produces_a_result():
    doc = {**WEB_DOC, "domain": "Underwater Basketry"}
    result = tb.role_fit(doc, [M("Ada", FRONT)])
    assert result["members"][0]["suggested"]["role"] == "Frontend Developer"


# --- HTTP ---------------------------------------------------------------------------------------------


def _signup(client, email, name="Member"):
    res = client.post("/api/auth/signup", json={"email": email, "password": "correcthorse1", "name": name})
    assert res.status_code == 201, res.get_json()
    return {"X-Auth-Token": res.get_json()["token"]}


@pytest.fixture
def team_ctx(client):
    db.projects().insert_one({**WEB_DOC})
    owner = _signup(client, "owner@example.com", "Owner")
    created = client.post("/api/teams", json={"project_id": "pm-web", "name": "T"}, headers=owner).get_json()["data"]
    member = _signup(client, "member@example.com", "Member")
    client.post("/api/teams/join", json={"invite_code": created["invite_code"]}, headers=member)
    return client, created["team_id"], owner, member


def _roles(client, team_id, headers):
    res = client.get(f"/api/teams/{team_id}/roles", headers=headers)
    assert res.status_code == 200, res.get_json()
    return res.get_json()["data"]


def test_legacy_fields_are_unchanged_and_new_ones_are_additive(team_ctx):
    client, team_id, owner, _ = team_ctx
    data = _roles(client, team_id, owner)
    for key in ("project_id", "roles", "assignments", "unassigned_members", "unfilled_roles"):
        assert key in data
    assert {"role_fit", "decisions"} <= set(data)


def test_legacy_manual_skills_still_drive_suggestions(team_ctx):
    client, team_id, owner, _ = team_ctx
    client.post(f"/api/teams/{team_id}/skills", json={"skills": ["reactjs", "css"]}, headers=owner)
    fit_ = _roles(client, team_id, owner)["role_fit"]
    me = next(m for m in fit_["members"] if m["name"] == "Owner")
    assert me["source"] == "manual" and me["suggested"]["role"] == "Frontend Developer"
    assert "entered for this team" in me["suggested"]["explanation"]


def test_saved_profiles_are_used_for_every_member_and_merged_with_manual_skills(team_ctx):
    client, team_id, owner, member = team_ctx
    client.put("/api/profile", json={"skills": [{"name": "nodejs", "level": "Advanced"}, {"name": "Express", "level": "Intermediate"}], "preferred_roles": ["Backend Developer"], "share_with_teams": True}, headers=member)
    client.put("/api/profile", json={"skills": [{"name": "React", "level": "Advanced"}]}, headers=owner)
    client.post(f"/api/teams/{team_id}/skills", json={"skills": ["react", "CSS"]}, headers=owner)  # react duplicates the profile

    members = {m["name"]: m for m in _roles(client, team_id, owner)["role_fit"]["members"]}
    assert members["Member"]["source"] == "profile"
    assert members["Member"]["suggested"]["role"] == "Backend Developer" and members["Member"]["suggested"]["preferred"]
    assert members["Owner"]["source"] == "profile+manual"
    names = [s["name"] for s in members["Owner"]["suggested"]["supporting_skills"]]
    assert names.count("React") == 1 and "CSS" in names


def test_past_project_technologies_count_as_unlevelled_evidence(team_ctx):
    client, team_id, owner, _ = team_ctx
    client.put("/api/profile", json={"experience": [{"title": "Shop", "technologies": ["Flask", "Django"]}]}, headers=owner)
    me = next(m for m in _roles(client, team_id, owner)["role_fit"]["members"] if m["name"] == "Owner")
    assert me["suggested"]["role"] == "Backend Developer"
    assert all(s["level"] is None for s in me["suggested"]["supporting_skills"])


def test_member_without_profile_or_skills_is_reported_gracefully(team_ctx):
    client, team_id, owner, _ = team_ctx
    data = _roles(client, team_id, owner)["role_fit"]
    assert all(m["suggested"] is None and m["message"] for m in data["members"])
    assert all(m["source"] == "none" and m["profile_status"] == "not_started" for m in data["members"])


def test_response_exposes_only_role_relevant_profile_data(team_ctx):
    client, team_id, owner, member = team_ctx
    client.put(
        "/api/profile",
        json={
            "skills": [{"name": "React", "level": "Advanced"}, {"name": "Basket weaving", "level": "Advanced"}],
            "learning_goals": ["secret goal"], "career_interests": ["secret career"], "education": "secret school",
            "availability": {"hours_per_week": 7}, "experience": [{"title": "Secret job", "description": "secret text", "technologies": ["Vue"]}],
            "share_with_teams": True,
        },
        headers=member,
    )
    text = str(_roles(client, team_id, owner))  # the OWNER reads the MEMBER's suggestion
    for leaked in ("secret", "Basket weaving", "member@example.com", "hours_per_week"):
        assert leaked not in text
    assert "React" in text


def test_non_members_and_signed_out_callers_get_nothing(team_ctx):
    client, team_id, owner, _ = team_ctx
    client.put("/api/profile", json={"skills": ["React"]}, headers=owner)
    outsider = _signup(client, "outsider@example.com")
    assert client.get(f"/api/teams/{team_id}/roles", headers=outsider).status_code == 404
    assert client.get(f"/api/teams/{team_id}/roles").status_code == 401
    assert client.put(f"/api/teams/{team_id}/roles/mine", json={"status": "rejected"}, headers=outsider).status_code == 404
    assert client.put(f"/api/teams/{team_id}/roles/mine", json={"status": "rejected"}).status_code == 401


def test_users_cannot_inject_ids_to_read_other_profiles(team_ctx):
    client, team_id, owner, _ = team_ctx
    outsider = _signup(client, "outsider@example.com")
    client.put("/api/profile", json={"skills": ["Solidity"]}, headers=outsider)
    res = client.get(f"/api/teams/{team_id}/roles?user_id=anyone&user_ids=x", headers=owner)
    assert "Solidity" not in str(res.get_json())


def test_a_suggestion_is_advice_until_the_member_decides(team_ctx):
    client, team_id, owner, member = team_ctx
    client.put("/api/profile", json={"skills": [{"name": "React", "level": "Advanced"}]}, headers=member)
    assert _roles(client, team_id, owner)["decisions"] == []  # reading never records anything

    res = client.put(f"/api/teams/{team_id}/roles/mine", json={"status": "accepted", "role": "Frontend Developer"}, headers=member)
    assert res.status_code == 200
    decisions = _roles(client, team_id, owner)["decisions"]  # visible to teammates, authored by the member only
    assert [(d["name"], d["status"], d["role"]) for d in decisions] == [("Member", "accepted", "Frontend Developer")]

    client.put(f"/api/teams/{team_id}/roles/mine", json={"status": "custom", "role": "QA / Test Engineer"}, headers=member)
    assert _roles(client, team_id, owner)["decisions"][0]["role"] == "QA / Test Engineer"

    client.put(f"/api/teams/{team_id}/roles/mine", json={"status": "rejected"}, headers=member)
    assert _roles(client, team_id, owner)["decisions"][0] == {"user_id": decisions[0]["user_id"], "name": "Member", "status": "rejected", "role": None}

    assert client.delete(f"/api/teams/{team_id}/roles/mine", headers=member).get_json()["data"] == []


def test_owner_cannot_decide_for_a_member(team_ctx):
    client, team_id, owner, member = team_ctx
    client.put(f"/api/teams/{team_id}/roles/mine", json={"status": "accepted", "role": "DevOps Engineer"}, headers=owner)
    decisions = _roles(client, team_id, member)["decisions"]
    assert [d["name"] for d in decisions] == ["Owner"]  # the owner's call only ever records the owner's own decision


@pytest.mark.parametrize(
    "body",
    [{}, {"status": "maybe"}, {"status": "accepted"}, {"status": "accepted", "role": "CEO"}, {"status": "rejected", "role": "CEO"},
     {"status": 3}, {"status": "accepted", "role": ["Frontend Developer"]}],
)
def test_invalid_decisions_are_rejected_without_writing(team_ctx, body):
    client, team_id, owner, _ = team_ctx
    assert client.put(f"/api/teams/{team_id}/roles/mine", json=body, headers=owner).status_code == 400
    assert _roles(client, team_id, owner)["decisions"] == []


def test_decisions_do_not_change_membership_or_the_team_payload(team_ctx):
    client, team_id, owner, member = team_ctx
    before = client.get(f"/api/teams/{team_id}", headers=owner).get_json()["data"]
    client.put(f"/api/teams/{team_id}/roles/mine", json={"status": "accepted", "role": "Frontend Developer"}, headers=member)
    after = client.get(f"/api/teams/{team_id}", headers=owner).get_json()["data"]
    assert after == before and "role_decisions" not in after
    assert len(after["members"]) == 2


def test_a_removed_member_loses_their_decision(team_ctx):
    client, team_id, owner, member = team_ctx
    client.put(f"/api/teams/{team_id}/roles/mine", json={"status": "accepted", "role": "Frontend Developer"}, headers=member)
    me = client.get("/api/auth/me", headers=member).get_json()["data"]
    client.delete(f"/api/teams/{team_id}/members/{me['user_id']}", headers=member)
    assert _roles(client, team_id, owner)["decisions"] == []


def test_team_without_a_real_project_still_reports_the_existing_error(client):
    owner = _signup(client, "o@example.com")
    team = client.post("/api/teams", json={"idea": {"name": "I", "domain": "Robotics", "difficulty": "Beginner", "duration_weeks": 4, "technologies": ["Python"], "problem": "p", "solution": "s"}, "name": "T"}, headers=owner).get_json()["data"]
    assert client.get(f"/api/teams/{team['team_id']}/roles", headers=owner).status_code == 200
