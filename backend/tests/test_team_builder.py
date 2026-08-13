from nlp.team_builder import suggest_roles

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

    by_name = {a["member"]: a for a in result["assignments"]}
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


def test_unfilled_roles_reported_when_team_smaller_than_role_count():
    result = suggest_roles(DOC, [{"name": "Solo", "skills": ["Python"]}])
    assert len(result["unfilled_roles"]) == len(result["roles"]) - 1
