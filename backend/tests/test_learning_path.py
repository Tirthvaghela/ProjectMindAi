from nlp.learning_path import learning_path_for, resources_for, sequence_technologies, sequenced_learning_path


def test_known_technology_gets_official_docs_first():
    resources = resources_for("React")
    assert resources[0]["platform"] == "React docs"


def test_unknown_skill_still_gets_search_links():
    resources = resources_for("Quantum Basket Weaving")
    platforms = [r["platform"] for r in resources]
    assert "YouTube" in platforms
    assert "Coursera" in platforms
    assert not any(p.endswith("docs") for p in platforms)


def test_every_resource_url_is_well_formed():
    for resource in resources_for("Docker"):
        assert resource["url"].startswith("https://")
        assert " " not in resource["url"]


def test_learning_path_deduplicates_case_insensitively():
    path = learning_path_for(["Python", "python", "PYTHON", "React"])
    skills = [entry["skill"] for entry in path]
    assert len(skills) == 2


def test_learning_path_preserves_first_seen_order():
    path = learning_path_for(["React", "Python", "Docker"])
    assert [entry["skill"] for entry in path] == ["React", "Python", "Docker"]


# --- Technology learning sequence ---------------------------------------------


def test_sequence_is_not_alphabetical():
    # Alphabetical would put "Database" before "FastAPI" before "Python" —
    # the sensible build order is the opposite.
    sequence = sequence_technologies(["Database", "FastAPI", "Python"])
    assert [s["skill"] for s in sequence] == ["Python", "FastAPI", "Database"]


def test_sequence_matches_the_documented_nlp_example():
    # Python -> Machine Learning -> NLP -> Transformers -> FastAPI -> Database -> Deployment
    sequence = sequence_technologies(
        ["FastAPI", "Python", "Transformers", "Database", "Machine Learning", "Deployment", "NLP"]
    )
    assert [s["skill"] for s in sequence] == [
        "Python", "Machine Learning", "NLP", "Transformers", "FastAPI", "Database", "Deployment",
    ]


def test_sequence_language_comes_before_framework():
    sequence = sequence_technologies(["TensorFlow", "Python"])
    assert [s["skill"] for s in sequence] == ["Python", "TensorFlow"]


def test_sequence_deployment_comes_last():
    sequence = sequence_technologies(["Docker", "Python", "MongoDB"])
    assert sequence[-1]["skill"] == "Docker"


def test_sequence_unrecognised_terms_go_last_not_first():
    sequence = sequence_technologies(["Quantum Basket Weaving", "Python"])
    assert [s["skill"] for s in sequence] == ["Python", "Quantum Basket Weaving"]


def test_sequence_preserves_input_order_within_a_tier():
    # Both React and Vue are "frontend" tier — no real basis to rank one
    # before the other, so the caller's own order should survive.
    sequence = sequence_technologies(["Vue", "React"])
    assert [s["skill"] for s in sequence] == ["Vue", "React"]


def test_sequence_deduplicates_case_insensitively_keeping_first_spelling():
    sequence = sequence_technologies(["Python", "python", "PYTHON"])
    assert [s["skill"] for s in sequence] == ["Python"]


def test_sequence_every_entry_has_a_non_empty_reason():
    for entry in sequence_technologies(["Python", "Quantum Basket Weaving"]):
        assert entry["reason"]


def test_sequenced_learning_path_reorders_and_carries_reason():
    path = sequenced_learning_path(["Docker", "Python", "MongoDB"])
    assert [entry["skill"] for entry in path] == ["Python", "MongoDB", "Docker"]
    assert all(entry["reason"] for entry in path)
    # Same resources as the unordered call — sequencing reorders, it doesn't
    # change what learning_path_for() itself returns per skill.
    assert path[0]["resources"] == learning_path_for(["Python"])[0]["resources"]
