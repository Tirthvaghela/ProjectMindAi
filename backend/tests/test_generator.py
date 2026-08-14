from nlp.generator import idea_doc, milestones_for, milestones_from_phases, phase_plan, roadmap_for, synopsis_for

DOC = {
    "project_id": "pm-001",
    "title": "AI-Powered Medical Diagnosis Assistant",
    "description": "A clinical decision support system that predicts likely conditions.",
    "domain": "Artificial Intelligence",
    "difficulty": "Advanced",
    "technologies": ["Python", "scikit-learn", "Flask"],
    "skills": ["Supervised learning", "REST API development"],
    "duration_weeks": 12,
}


def test_roadmap_phases_sum_to_total_weeks():
    roadmap = roadmap_for(DOC)
    assert sum(p["weeks"] for p in roadmap["phases"]) == roadmap["total_weeks"] == 12


def test_roadmap_uses_the_domain_specific_core_phase():
    roadmap = roadmap_for(DOC)
    phase_names = [p["phase"] for p in roadmap["phases"]]
    assert "Model Development & Training" in phase_names


def test_roadmap_handles_a_very_short_duration_without_zero_week_phases():
    roadmap = roadmap_for({**DOC, "duration_weeks": 1})
    assert roadmap["total_weeks"] == 1
    assert all(p["weeks"] > 0 for p in roadmap["phases"])
    assert sum(p["weeks"] for p in roadmap["phases"]) == 1


def test_roadmap_handles_the_half_week_floor_edge_case_without_a_zero_week_phase():
    # duration_weeks=4 used to floor all 6 earlier phases to exactly 0.5
    # weeks each (sum 4.0), leaving the last phase — whatever's left over —
    # at exactly 0, landing its milestone on the same week as the phase
    # before it.
    for weeks in (3.5, 4, 4.5):
        phases = phase_plan(weeks, DOC["domain"])
        assert all(p["weeks"] > 0 for p in phases), f"a phase hit 0 weeks at duration_weeks={weeks}"
        assert sum(p["weeks"] for p in phases) == weeks


def test_roadmap_falls_back_to_default_profile_for_unknown_domain():
    roadmap = roadmap_for({**DOC, "domain": "Something Not In The Schema"})
    phase_names = [p["phase"] for p in roadmap["phases"]]
    assert "Core Feature Development" in phase_names


def test_synopsis_uses_an_before_vowel_leading_domain():
    synopsis = synopsis_for(DOC)
    assert "an artificial intelligence system" in synopsis["objectives"][0]


def test_synopsis_uses_a_before_consonant_leading_domain():
    synopsis = synopsis_for({**DOC, "domain": "Web Development"})
    assert "a web development system" in synopsis["objectives"][0]


def test_synopsis_methodology_matches_roadmap_phase_names():
    synopsis = synopsis_for(DOC)
    roadmap = roadmap_for(DOC)
    assert synopsis["methodology"] == [p["phase"] for p in roadmap["phases"]]


def test_synopsis_technology_stack_is_the_projects_own_list():
    synopsis = synopsis_for(DOC)
    assert synopsis["technology_stack"] == DOC["technologies"]


# --- Implementation planning (roadmap phase enrichment) ----------------------


def test_roadmap_phases_carry_implementation_detail():
    roadmap = roadmap_for(DOC)
    for phase in roadmap["phases"]:
        assert "objective" in phase
        assert "tasks" in phase
        assert "technologies" in phase
        assert "expected_output" in phase
        assert "dependencies" in phase


def test_roadmap_first_phase_has_no_dependencies():
    roadmap = roadmap_for(DOC)
    assert roadmap["phases"][0]["dependencies"] == []


def test_roadmap_phases_depend_on_the_immediately_preceding_phase():
    roadmap = roadmap_for(DOC)
    names = [p["phase"] for p in roadmap["phases"]]
    for i, phase in enumerate(roadmap["phases"][1:], start=1):
        assert phase["dependencies"] == [names[i - 1]]


def test_roadmap_core_phase_tasks_come_from_the_domain_profile_modules():
    roadmap = roadmap_for(DOC)
    core_phase = next(p for p in roadmap["phases"] if p["phase"] == "Model Development & Training")
    # Artificial Intelligence's domain profile module list — every task here
    # must trace back to a real module, never an invented one.
    assert any("Model Training" in task for task in core_phase["tasks"])
    assert core_phase["technologies"] == DOC["technologies"]


def test_roadmap_phase_tasks_never_invent_technologies_not_on_the_project():
    roadmap = roadmap_for(DOC)
    for phase in roadmap["phases"]:
        assert set(phase["technologies"]) <= set(DOC["technologies"])


def test_roadmap_with_no_technologies_still_produces_tasks_not_a_crash():
    roadmap = roadmap_for({**DOC, "technologies": [], "skills": []})
    core_phase = next(p for p in roadmap["phases"] if p["phase"] == "Model Development & Training")
    assert len(core_phase["tasks"]) > 0
    assert core_phase["technologies"] == []


# --- Milestones ----------------------------------------------------------------


def test_milestones_one_per_phase():
    result = milestones_for(DOC)
    roadmap = roadmap_for(DOC)
    assert len(result["milestones"]) == len(roadmap["phases"])


def test_milestones_final_week_equals_total_weeks():
    result = milestones_for(DOC)
    assert result["milestones"][-1]["week"] == result["total_weeks"] == 12


def test_milestones_weeks_are_non_decreasing():
    result = milestones_for(DOC)
    weeks = [m["week"] for m in result["milestones"]]
    assert weeks == sorted(weeks)


def test_milestones_titles_reference_their_phase():
    result = milestones_for(DOC)
    for milestone in result["milestones"]:
        assert milestone["phase"] in milestone["title"]


def test_milestones_ids_are_sequential():
    result = milestones_for(DOC)
    assert [m["id"] for m in result["milestones"]] == [f"M{i}" for i in range(1, len(result["milestones"]) + 1)]


def test_milestones_from_phases_matches_a_personalised_timeline_phase_list():
    # Milestones must also work from timeline.predict()'s (lean) phase list,
    # not just roadmap_for()'s enriched one — same function, either input.
    personalised_phases = phase_plan(6, "Artificial Intelligence")
    milestones = milestones_from_phases(personalised_phases)
    assert len(milestones) == len(personalised_phases)
    assert milestones[-1]["week"] == sum(p["weeks"] for p in personalised_phases)


# --- idea_doc: synthetic doc for a GENERATED idea (no project_id) ------------
#
# A generated idea is never written to Mongo, so every idea-scoped caller
# (nlp/chat_tools.py's generate_idea_* tools, routes/ideas.py's REST
# endpoints) builds a doc from the idea's own fields via this function
# instead of a Mongo lookup — same shape roadmap_for/synopsis_for/
# milestones_for/skill_gap_for_doc already expect.


def test_idea_doc_has_no_project_id():
    assert idea_doc("My Idea")["project_id"] is None


def test_idea_doc_uses_the_name_as_title():
    assert idea_doc("Smart Notes Hub")["title"] == "Smart Notes Hub"


def test_idea_doc_mirrors_technologies_into_skills():
    # A generated idea has no separate skills taxonomy distinct from its tech
    # stack (unlike a catalogue project's curated "skills" list) — technologies
    # is the honest stand-in, so skill_gap_for_doc() has something real to
    # compare a student's known skills against.
    doc = idea_doc("X", technologies=["Python", "React"])
    assert doc["skills"] == ["Python", "React"] == doc["technologies"]


def test_idea_doc_defaults_description_to_empty_string():
    assert idea_doc("X")["description"] == ""


def test_idea_doc_uses_the_given_description():
    doc = idea_doc("X", description="A problem. A solution.")
    assert doc["description"] == "A problem. A solution."


def test_idea_doc_normalises_an_invalid_domain_and_difficulty_to_empty():
    doc = idea_doc("X", domain="Not A Real Domain", difficulty="Not A Real Difficulty")
    assert doc["domain"] == ""
    assert doc["difficulty"] == ""


def test_idea_doc_clamps_duration_weeks_and_defaults_when_missing():
    assert idea_doc("X")["duration_weeks"] == 8
    assert idea_doc("X", duration_weeks=999)["duration_weeks"] == 24
    assert idea_doc("X", duration_weeks=0)["duration_weeks"] == 1
    assert idea_doc("X", duration_weeks="not a number")["duration_weeks"] == 8


def test_idea_doc_roadmap_and_synopsis_are_grounded_in_the_ideas_own_fields():
    # End-to-end: idea_doc() feeds straight into the same generators a
    # catalogue project's own roadmap/synopsis use.
    doc = idea_doc(
        "Smart Notes Hub",
        domain="Artificial Intelligence",
        duration_weeks=10,
        technologies=["Python", "FastAPI"],
        description="Students lose track of scattered lecture notes. A unifying, searchable hub.",
    )
    roadmap = roadmap_for(doc)
    assert roadmap["total_weeks"] == 10
    assert "Model Development & Training" in [p["phase"] for p in roadmap["phases"]]

    synopsis = synopsis_for(doc)
    assert synopsis["title"] == "Smart Notes Hub"
    assert "scattered lecture notes" in synopsis["abstract"]
    assert "Python" in synopsis["technology_stack"]
