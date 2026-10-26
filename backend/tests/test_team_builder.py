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


def test_member_whose_area_has_no_role_is_reported_not_given_an_unrelated_role():
    # This project's (AI) modules have no Testing/QA-category role.
    members = [{"name": "Devi", "skills": ["pytest", "manual testing"]}]
    result = suggest_roles(DOC, members)

    assert result["assignments"] == []
    [entry] = result["unassigned_members"]
    assert entry["member"] == "Devi"
    assert entry["reason"] == "no_role_in_area"
    assert entry["strongest_category"] == "Testing / QA"
    assert "no role" in entry["message"].lower()
    # Nothing was claimed, so every real module is still reported open.
    assert result["unfilled_roles"] == result["roles"]


def test_member_with_no_skills_is_asked_for_skills_not_assigned_a_role():
    result = suggest_roles(DOC, [{"name": "NewGuy", "skills": []}])
    assert result["assignments"] == []
    assert result["unassigned_members"][0]["reason"] == "no_skills"


def test_missing_or_malformed_profile_fields_do_not_crash():
    members = [
        {"name": "A"},  # no skills key at all
        {"name": None, "skills": None},
        {"name": "  ", "skills": ["", "   ", 7, "Python"]},
    ]
    result = suggest_roles(DOC, members)
    assert {u["member"] for u in result["unassigned_members"]} >= {"A", "Member 2"}
    assert [a["member"] for a in result["assignments"]] == ["Member 3"]


def test_skills_that_map_to_no_role_area_are_reported_as_unrecognised():
    result = suggest_roles(DOC, [{"name": "Zed", "skills": ["Knitting", "Cooking"]}])
    assert result["assignments"] == []
    assert result["unassigned_members"][0]["reason"] == "unrecognised_skills"


def test_a_solo_member_gets_one_role_and_the_rest_stay_open():
    # Previously a team of one was handed every module, each flagged as a
    # fallback "to keep every seat covered" — the same person in mutually
    # exclusive roles. One person, one role; the remainder is honestly open.
    result = suggest_roles(DOC, [{"name": "Solo", "skills": ["Python"]}])
    assert len(result["assignments"]) == 1
    assert result["assignments"][0]["category"] == "Data / ML"
    assert result["assignments"][0]["fallback"] is False
    assigned = result["assignments"][0]["assigned_role"]
    assert sorted(result["unfilled_roles"] + [assigned]) == sorted(result["roles"])
    assert result["unassigned_members"] == []


def test_each_member_holds_at_most_one_role_and_each_role_has_one_owner():
    members = [
        {"name": "Asha", "skills": ["Python", "scikit-learn"]},
        {"name": "Bala", "skills": ["React", "CSS"]},
        {"name": "Chen", "skills": ["Python", "pandas", "TensorFlow"]},
    ]
    result = suggest_roles(DOC, members)
    owners = [a["member"] for a in result["assignments"]]
    roles_taken = [a["assigned_role"] for a in result["assignments"]]
    assert len(owners) == len(set(owners))
    assert len(roles_taken) == len(set(roles_taken))
    assert set(roles_taken).isdisjoint(result["unfilled_roles"])
    assert set(roles_taken) | set(result["unfilled_roles"]) == set(result["roles"])


def test_the_stronger_claim_wins_a_contested_role_regardless_of_listing_order():
    # Both only fit Frontend / UI; the AI profile has exactly one such role.
    weak_first = [
        {"name": "Weak", "skills": ["CSS"]},
        {"name": "Strong", "skills": ["React", "CSS", "Figma", "Tailwind"]},
    ]
    result = suggest_roles(DOC, weak_first)
    frontend = [a for a in result["assignments"] if a["category"] == "Frontend / UI"]
    assert [a["member"] for a in frontend] == ["Strong"]
    loser = {u["member"]: u for u in result["unassigned_members"]}["Weak"]
    assert loser["reason"] == "roles_taken"


def test_matched_skills_come_from_the_members_own_list():
    members = [{"name": "Asha", "skills": ["Python", "pandas", "Knitting"]}]
    [a] = suggest_roles(DOC, members)["assignments"]
    assert set(a["matched_skills"]) == {"Python", "pandas"}


def test_duplicate_roster_entries_do_not_create_duplicate_recommendations():
    members = [
        {"name": "Asha", "skills": ["Python"]},
        {"name": "  asha ", "skills": ["pandas", "python"]},  # same person, retyped
    ]
    result = suggest_roles(DOC, members)
    assert len(result["assignments"]) == 1
    assert result["unassigned_members"] == []
    assert set(result["assignments"][0]["matched_skills"]) == {"Python", "pandas"}


def test_distinct_people_sharing_a_name_are_kept_apart_when_ids_are_given():
    members = [
        {"id": "u1", "name": "Sam", "skills": ["Python"]},
        {"id": "u2", "name": "Sam", "skills": ["React"]},
    ]
    result = suggest_roles(DOC, members)
    assert {a["category"] for a in result["assignments"]} == {"Data / ML", "Frontend / UI"}
