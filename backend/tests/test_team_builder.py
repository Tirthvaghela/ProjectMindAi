from nlp.team_builder import _MODULE_CATEGORY, suggest_roles

DOC = {
    "project_id": "pm-001",
    "domain": "Artificial Intelligence",
}


def test_each_member_gets_a_role_matching_their_strongest_skill():
    members = [
        {"name": "Asha", "skills": ["Python", "scikit-learn", "pandas"]},
        {"name": "Bala", "skills": ["React", "CSS", "Figma"]},
    ]
    result = suggest_roles(DOC, members)

    # A member can now hold more than one role (see the "extra roles" tests
    # below), so keep each member's *first* — their own best-fit pick from
    # pass 1 — rather than a later leftover-module assignment from pass 2.
    by_name = {}
    for a in result["assignments"]:
        by_name.setdefault(a["member"], a)
    assert by_name["Asha"]["category"] == "Data / ML"
    assert by_name["Bala"]["category"] == "Frontend / UI"
    assert not by_name["Asha"]["fallback"]
    assert not by_name["Bala"]["fallback"]


def test_two_members_never_get_the_same_role():
    members = [
        {"name": "Asha", "skills": ["Python", "pandas"]},
        {"name": "Priya", "skills": ["Python", "TensorFlow"]},  # same category as Asha
    ]
    result = suggest_roles(DOC, members)
    roles_assigned = [a["assigned_role"] for a in result["assignments"]]
    assert len(roles_assigned) == len(set(roles_assigned))


def test_member_with_no_matching_role_gets_a_fallback_with_explanation():
    # This project's (AI) modules have no Testing/QA-category role.
    members = [{"name": "Devi", "skills": ["pytest", "manual testing"]}]
    result = suggest_roles(DOC, members)

    assignment = result["assignments"][0]
    assert assignment["fallback"] is True
    assert assignment["strongest_category"] == "Testing / QA"
    # The fallback role should still be one of this project's real modules.
    assert assignment["assigned_role"] in result["roles"]


def test_member_with_no_skills_still_gets_assigned_something():
    result = suggest_roles(DOC, [{"name": "NewGuy", "skills": []}])
    assert result["assignments"][0]["assigned_role"] in result["roles"]


def test_every_role_is_assigned_even_when_team_is_smaller_than_role_count():
    # A team of 1 can't wait for someone else to show up — Solo ends up
    # owning every module on the project, not just their best-fit one.
    result = suggest_roles(DOC, [{"name": "Solo", "skills": ["Python"]}])
    assert result["unfilled_roles"] == []
    assigned_roles = [a["assigned_role"] for a in result["assignments"]]
    assert sorted(assigned_roles) == sorted(result["roles"])
    assert all(a["member"] == "Solo" for a in result["assignments"])


def test_extra_roles_beyond_member_count_are_still_all_claimed():
    # Same idea with a 2-person team and 4 modules (this project's AI
    # domain profile): nobody is left "still open, nobody assigned".
    members = [
        {"name": "Asha", "skills": ["Python", "scikit-learn"]},
        {"name": "Bala", "skills": ["React", "CSS"]},
    ]
    result = suggest_roles(DOC, members)
    assert result["unfilled_roles"] == []
    assigned_roles = [a["assigned_role"] for a in result["assignments"]]
    assert sorted(assigned_roles) == sorted(result["roles"])
    assert len(assigned_roles) == len(set(assigned_roles))  # no module double-booked
    assert {a["member"] for a in result["assignments"]} == {"Asha", "Bala"}


def test_extra_roles_go_to_the_best_scoring_member_not_round_robin():
    # 3 modules for a Data / ML-heavy category, one member strong in it and
    # one who isn't — the extra Data/ML-flavoured module should still land
    # on the stronger fit rather than whoever is "next" in a naive rotation.
    members = [
        {"name": "Asha", "skills": ["Python", "pandas", "scikit-learn", "TensorFlow"]},
        {"name": "Bala", "skills": ["React", "CSS", "Figma"]},
    ]
    result = suggest_roles(DOC, members)
    by_role = {a["assigned_role"]: a["member"] for a in result["assignments"]}
    data_ml_roles = [r for r in result["roles"] if _MODULE_CATEGORY.get(r) == "Data / ML"]
    assert len(data_ml_roles) >= 2
    assert all(by_role[r] == "Asha" for r in data_ml_roles)
