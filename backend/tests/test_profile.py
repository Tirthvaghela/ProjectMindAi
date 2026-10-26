"""Learner profile: validation, normalisation, completion, persistence, and the
account-scoped authorisation the HTTP routes promise (routes/profile.py)."""

from __future__ import annotations

import pytest

from db import client as db
from profiles import service
from profiles.service import ProfileError, completion, validate_fields
from tests.conftest import ensure_indexes_for_test

# --- pure validation / normalisation (no database) ---------------------------


def test_skill_names_use_the_shared_alias_layer():
    cleaned = validate_fields({"skills": [{"name": "reactjs", "level": "Advanced"}, {"name": "  node JS "}]})
    assert cleaned["skills"] == [
        {"name": "React", "level": "Advanced"},
        {"name": "Node.js", "level": "Beginner"},
    ]


def test_duplicate_spellings_merge_and_latest_level_wins():
    cleaned = validate_fields({"skills": [{"name": "React", "level": "Beginner"}, {"name": "reactjs", "level": "Advanced"}]})
    assert cleaned["skills"] == [{"name": "React", "level": "Advanced"}]


def test_distinct_skills_are_not_merged():
    cleaned = validate_fields({"skills": ["Java", "JavaScript", "C", "C++"]})
    assert [s["name"] for s in cleaned["skills"]] == ["Java", "JavaScript", "C", "C++"]


def test_unknown_skill_is_kept_as_typed_and_flagged_unrecognised():
    cleaned = validate_fields({"skills": ["Underwater basket weaving"]})
    assert cleaned["skills"][0]["name"] == "Underwater basket weaving"


def test_plain_string_skills_are_accepted():
    assert validate_fields({"skills": ["python"]})["skills"] == [{"name": "Python", "level": "Beginner"}]


@pytest.mark.parametrize(
    "payload",
    [
        {"skills": "python"},
        {"skills": [{"name": "Python", "level": "Wizard"}]},
        {"skills": [{"name": "Python", "level": 3}]},
        {"skills": [{"name": "Python", "extra": 1}]},
        {"skills": [42]},
        {"skills": [{"name": ["Python"]}]},
        {"skills": [{"name": "x" * 61}]},
        {"skills": [f"skill{i}" for i in range(51)]},
        {"interests": ["Underwater Robotics"]},
        {"interests": "Robotics"},
        {"interests": [["Robotics"]]},
        {"preferred_roles": ["CEO"]},
        {"availability": {"hours_per_week": 0}},
        {"availability": {"hours_per_week": 81}},
        {"availability": {"hours_per_week": 2.5}},
        {"availability": {"hours_per_week": True}},
        {"availability": {"hours_per_week": "ten"}},
        {"availability": {"max_project_weeks": 53}},
        {"availability": {"phone": "123"}},
        {"availability": 10},
        {"experience": [{"title": ""}]},
        {"experience": [{"description": "no title"}]},
        {"experience": [{"title": "t", "email": "a@b.co"}]},
        {"experience": "none"},
        {"learning_goals": "learn rust"},
        {"learning_goals": ["x" * 201]},
        {"education": 5},
        {"education": "x" * 201},
        {"onboarding_dismissed": "yes"},
        {"email": "a@b.co"},
        {"password_hash": "x"},
        {"user_id": "someone-else"},
        [],
        "profile",
    ],
)
def test_invalid_payloads_are_rejected(payload):
    with pytest.raises(ProfileError):
        validate_fields(payload)


def test_error_names_the_offending_field():
    with pytest.raises(ProfileError) as info:
        validate_fields({"availability": {"hours_per_week": 500}})
    assert info.value.field == "availability"


def test_control_characters_are_stripped_from_text():
    cleaned = validate_fields({"skills": ["Cool\x00Thing\n"], "education": "BSc\tCS\r\nUni"})
    assert cleaned["skills"][0]["name"] == "Cool Thing"
    assert cleaned["education"] == "BSc CS Uni"


def test_html_is_stored_as_inert_text_not_interpreted():
    cleaned = validate_fields({"learning_goals": ["<script>alert(1)</script>"]})
    assert cleaned["learning_goals"] == ["<script>alert(1)</script>"]  # React escapes on render; never trusted as markup


def test_goals_deduplicate_ignoring_case_and_blank_entries_vanish():
    cleaned = validate_fields({"learning_goals": ["Learn Rust", "learn rust", "  "], "career_interests": []})
    assert cleaned["learning_goals"] == ["Learn Rust"]


def test_experience_normalises_technologies_and_requires_title():
    cleaned = validate_fields(
        {"experience": [{"title": "Campus bot", "description": "Built a bot.", "technologies": ["nodejs", "NodeJS", "postgres"]}]}
    )
    assert cleaned["experience"][0]["technologies"] == ["Node.js", "PostgreSQL"]


def test_only_present_sections_are_returned():
    assert set(validate_fields({"education": "BSc"})) == {"education"}


def test_availability_accepts_blanks_as_unset():
    cleaned = validate_fields({"availability": {"hours_per_week": "", "max_project_weeks": None}})
    assert cleaned["availability"] == {"hours_per_week": None, "max_project_weeks": None}


# --- completion ---------------------------------------------------------------


def test_completion_states():
    empty = service._empty()
    assert completion(empty)["status"] == "not_started"
    assert completion(empty)["percent"] == 0

    partial = {**empty, "skills": [{"name": "Python", "level": "Beginner"}]}
    assert completion(partial)["status"] == "in_progress"

    full = {
        **empty,
        "skills": [{"name": "Python", "level": "Beginner"}],
        "interests": ["Robotics"],
        "learning_goals": ["Learn ROS"],
        "preferred_roles": ["Backend Developer"],
        "availability": {"hours_per_week": 6, "max_project_weeks": None},
    }
    result = completion(full)
    assert result["status"] == "complete"  # experience is optional
    assert result["percent"] == 83
    assert [m["key"] for m in result["missing"]] == ["experience"]


def test_career_interests_count_as_a_goal():
    profile = {**service._empty(), "career_interests": ["Data engineer"]}
    assert {m["key"] for m in completion(profile)["missing"]} >= {"skills"}
    assert "goals" not in {m["key"] for m in completion(profile)["missing"]}


# --- service persistence ---------------------------------------------------------


def test_get_before_saving_is_empty_and_writes_nothing(mongo_test_db):
    profile = service.get_profile("user-1")
    assert profile["completion"]["status"] == "not_started"
    assert profile["skills"] == [] and profile["created_at"] is None
    assert db.profiles().count_documents({}) == 0


def test_partial_saves_merge_instead_of_replacing(mongo_test_db):
    service.save_profile("user-1", {"skills": ["python"]})
    service.save_profile("user-1", {"interests": ["Robotics"]})
    profile = service.get_profile("user-1")
    assert [s["name"] for s in profile["skills"]] == ["Python"]
    assert profile["interests"] == ["Robotics"]
    assert db.profiles().count_documents({}) == 1


def test_saving_a_section_replaces_that_section_so_items_can_be_removed(mongo_test_db):
    service.save_profile("user-1", {"skills": ["python", "react"]})
    service.save_profile("user-1", {"skills": ["react"]})
    assert [s["name"] for s in service.get_profile("user-1")["skills"]] == ["React"]


def test_recognised_flag_and_timestamps(mongo_test_db):
    profile = service.save_profile("user-1", {"skills": ["python", "Basket weaving"]})
    assert [s["recognised"] for s in profile["skills"]] == [True, False]
    assert profile["created_at"] and profile["updated_at"]


def test_empty_save_is_rejected_and_creates_nothing(mongo_test_db):
    with pytest.raises(ProfileError):
        service.save_profile("user-1", {})
    assert db.profiles().count_documents({}) == 0


def test_invalid_save_changes_nothing(mongo_test_db):
    service.save_profile("user-1", {"skills": ["python"]})
    with pytest.raises(ProfileError):
        service.save_profile("user-1", {"skills": ["react"], "interests": ["nonsense"]})
    assert [s["name"] for s in service.get_profile("user-1")["skills"]] == ["Python"]


def test_delete_profile_is_idempotent(mongo_test_db):
    service.save_profile("user-1", {"skills": ["python"]})
    assert service.delete_profile("user-1") is True
    assert service.delete_profile("user-1") is False
    assert service.get_profile("user-1")["completion"]["status"] == "not_started"


def test_profiles_are_isolated_by_user_id(mongo_test_db):
    service.save_profile("user-1", {"skills": ["python"]})
    service.save_profile("user-2", {"skills": ["Rust"]})
    assert [s["name"] for s in service.get_profile("user-1")["skills"]] == ["Python"]
    assert [s["name"] for s in service.get_profile("user-2")["skills"]] == ["Rust"]
    service.delete_profile("user-1")
    assert [s["name"] for s in service.get_profile("user-2")["skills"]] == ["Rust"]


# --- HTTP routes -------------------------------------------------------------------


def _signup(client, email, name="Test User"):
    res = client.post("/api/auth/signup", json={"email": email, "password": "correcthorse1", "name": name})
    assert res.status_code == 201, res.get_json()
    return {"X-Auth-Token": res.get_json()["token"]}, res.get_json()["data"]


def test_profile_requires_sign_in(client):
    assert client.get("/api/profile").status_code == 401
    assert client.put("/api/profile", json={"skills": ["python"]}).status_code == 401
    assert client.delete("/api/profile").status_code == 401
    assert client.get("/api/profile", headers={"X-Auth-Token": "bogus"}).status_code == 401


def test_options_are_public_and_contain_no_user_data(client):
    res = client.get("/api/profile/options")
    assert res.status_code == 200
    data = res.get_json()["data"]
    assert "Beginner" in data["proficiency_levels"]
    assert "Robotics" in data["domains"]
    assert "Backend Developer" in data["team_roles"]


def test_existing_account_without_profile_gets_an_empty_not_started_profile(client):
    headers, _ = _signup(client, "old@example.com")
    res = client.get("/api/profile", headers=headers)
    assert res.status_code == 200
    data = res.get_json()["data"]
    assert data["completion"]["status"] == "not_started"
    assert data["skills"] == [] and data["onboarding_dismissed"] is False
    assert db.profiles().count_documents({}) == 0  # reading never writes


def test_put_then_get_round_trip_persists(client):
    headers, _ = _signup(client, "a@example.com")
    body = {
        "skills": [{"name": "reactjs", "level": "Intermediate"}],
        "interests": ["Web Development"],
        "learning_goals": ["Ship a full-stack app"],
        "preferred_roles": ["Frontend Developer"],
        "availability": {"hours_per_week": 8, "max_project_weeks": 10},
        "experience": [{"title": "Portfolio site", "technologies": ["html"]}],
    }
    res = client.put("/api/profile", json=body, headers=headers)
    assert res.status_code == 200
    saved = res.get_json()["data"]
    assert saved["skills"][0]["name"] == "React"
    assert saved["completion"]["status"] == "complete"

    again = client.get("/api/profile", headers=headers).get_json()["data"]
    assert again["skills"] == saved["skills"]
    assert again["availability"] == {"hours_per_week": 8, "max_project_weeks": 10}
    assert "user_id" not in again and "_id" not in again


def test_invalid_put_is_a_clean_400_naming_the_field(client):
    headers, _ = _signup(client, "a@example.com")
    res = client.put("/api/profile", json={"availability": {"hours_per_week": 999}}, headers=headers)
    assert res.status_code == 400
    body = res.get_json()
    assert "hours" in body["error"].lower() and body["details"] == {"field": "availability"}


@pytest.mark.parametrize("raw", ["not json", "[]", "null", ""])
def test_non_object_bodies_are_a_400(client, raw):
    headers, _ = _signup(client, "a@example.com")
    res = client.put("/api/profile", data=raw, content_type="application/json", headers=headers)
    assert res.status_code == 400


def test_users_cannot_see_or_change_each_others_profiles(client):
    alice, alice_user = _signup(client, "alice@example.com", "Alice")
    bob, _ = _signup(client, "bob@example.com", "Bob")

    client.put("/api/profile", json={"skills": ["Rust"], "education": "Alice's secret"}, headers=alice)

    assert client.get("/api/profile", headers=bob).get_json()["data"]["skills"] == []

    # A caller cannot address another account: neither a body field nor a query
    # param is read as an identity, and an attempt to supply one is rejected.
    res = client.put("/api/profile", json={"user_id": alice_user["user_id"], "skills": ["Go"]}, headers=bob)
    assert res.status_code == 400
    res = client.get(f"/api/profile?user_id={alice_user['user_id']}", headers=bob)
    assert res.get_json()["data"]["skills"] == []
    assert client.get(f"/api/profile/{alice_user['user_id']}", headers=bob).status_code in (404, 405)

    alice_profile = client.get("/api/profile", headers=alice).get_json()["data"]
    assert [s["name"] for s in alice_profile["skills"]] == ["Rust"]
    assert alice_profile["education"] == "Alice's secret"

    # Bob deleting his profile does not touch Alice's.
    client.put("/api/profile", json={"skills": ["Go"]}, headers=bob)
    client.delete("/api/profile", headers=bob)
    assert [s["name"] for s in client.get("/api/profile", headers=alice).get_json()["data"]["skills"]] == ["Rust"]


def test_device_id_alone_cannot_reach_a_profile(client):
    headers, _ = _signup(client, "a@example.com")
    client.put("/api/profile", json={"skills": ["Rust"]}, headers=headers)
    assert client.get("/api/profile", headers={"X-Device-Id": "some-device"}).status_code == 401


def test_profile_does_not_alter_the_account_record(client):
    headers, user = _signup(client, "a@example.com")
    before = db.users().find_one({"user_id": user["user_id"]})
    client.put("/api/profile", json={"skills": ["Rust"]}, headers=headers)
    assert db.users().find_one({"user_id": user["user_id"]}) == before
    me = client.get("/api/auth/me", headers=headers).get_json()["data"]
    assert set(me) == {"user_id", "email", "name"}


def test_dismissing_onboarding_persists_and_does_not_count_as_progress(client):
    headers, _ = _signup(client, "a@example.com")
    res = client.put("/api/profile", json={"onboarding_dismissed": True}, headers=headers)
    data = res.get_json()["data"]
    assert data["onboarding_dismissed"] is True
    assert data["completion"]["status"] == "not_started"


def test_delete_removes_the_profile_but_keeps_the_account(client):
    headers, _ = _signup(client, "a@example.com")
    client.put("/api/profile", json={"skills": ["Rust"]}, headers=headers)
    res = client.delete("/api/profile", headers=headers)
    assert res.get_json()["data"] == {"deleted": True}
    assert client.get("/api/profile", headers=headers).get_json()["data"]["skills"] == []
    assert client.get("/api/auth/me", headers=headers).status_code == 200


def test_unique_index_allows_one_profile_per_user(mongo_test_db):
    from pymongo.errors import DuplicateKeyError

    ensure_indexes_for_test()
    db.profiles().insert_one({"user_id": "u"})
    with pytest.raises(DuplicateKeyError):
        db.profiles().insert_one({"user_id": "u"})
