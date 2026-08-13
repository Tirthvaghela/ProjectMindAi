from nlp.timeline import predict

DOC = {
    "project_id": "pm-001",
    "domain": "Artificial Intelligence",
    "difficulty": "Advanced",
    "duration_weeks": 12,
}


def test_solo_at_matching_experience_equals_baseline():
    result = predict(DOC, team_size=1, experience_level="Advanced")
    assert result["predicted_weeks"] == result["base_weeks"] == 12


def test_less_experienced_than_project_takes_longer():
    result = predict(DOC, team_size=1, experience_level="Beginner")
    assert result["predicted_weeks"] > result["base_weeks"]


def test_more_experienced_than_project_is_faster():
    faster_doc = {**DOC, "difficulty": "Beginner"}
    result = predict(faster_doc, team_size=1, experience_level="Advanced")
    assert result["predicted_weeks"] < result["base_weeks"]


def test_larger_team_reduces_time_but_not_linearly():
    solo = predict(DOC, team_size=1, experience_level="Advanced")
    team_of_4 = predict(DOC, team_size=4, experience_level="Advanced")
    # Faster, but nowhere near a full 4x speed-up (coordination overhead).
    assert team_of_4["predicted_weeks"] < solo["predicted_weeks"]
    assert team_of_4["predicted_weeks"] > solo["predicted_weeks"] / 4


def test_team_multiplier_has_a_floor():
    result = predict(DOC, team_size=20, experience_level="Advanced")
    # Never modelled as finishing in under 40% of the solo baseline.
    assert result["predicted_weeks"] >= 12 * 0.4 - 0.5


def test_predicted_weeks_never_drops_below_one():
    tiny_doc = {**DOC, "duration_weeks": 1, "difficulty": "Beginner"}
    result = predict(tiny_doc, team_size=10, experience_level="Advanced")
    assert result["predicted_weeks"] >= 1.0


def test_phases_are_replanned_against_the_predicted_total():
    result = predict(DOC, team_size=4, experience_level="Advanced")
    assert sum(p["weeks"] for p in result["phases"]) == result["predicted_weeks"]


def test_unset_experience_level_defaults_to_the_projects_own_difficulty():
    result = predict(DOC, team_size=1, experience_level=None)
    assert result["predicted_weeks"] == result["base_weeks"]
    assert result["experience_level"] == "Advanced"
