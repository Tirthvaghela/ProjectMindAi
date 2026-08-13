from nlp.resume import detect_skills, normalize_skill_variants

VOCAB = ["Python", "Java", "JavaScript", "React", "Model evaluation", "Evaluation", "Deployment"]
NORMALIZATION_VOCAB = ["React", "Node.js", "MongoDB", "TensorFlow", "scikit-learn"]


def test_detects_exact_vocabulary_terms_case_insensitively():
    found = detect_skills("Experienced in python and REACT development.", VOCAB)
    assert "Python" in found
    assert "React" in found


def test_does_not_false_match_java_inside_javascript():
    found = detect_skills("5 years of JavaScript experience", VOCAB)
    assert "JavaScript" in found
    assert "Java" not in found


def test_bare_generic_word_is_dropped_when_a_specific_phrase_also_matches():
    # Both "Evaluation" and "Model evaluation" are in the vocabulary; the
    # résumé mentioning "model evaluation" should surface only the specific
    # phrase, not also the bare word it contains.
    found = detect_skills("Worked on model evaluation and deployment.", VOCAB)
    assert "Model evaluation" in found
    assert "Evaluation" not in found
    # "Deployment" has no more-specific match in this vocabulary, so it stays.
    assert "Deployment" in found


def test_no_matches_returns_empty_list():
    assert detect_skills("I enjoy hiking and photography.", VOCAB) == []


def test_deduplicates_repeated_mentions():
    found = detect_skills("Python, python, PYTHON — I really know Python.", VOCAB)
    assert found.count("Python") == 1


# --- Skill normalization -----------------------------------------------------


def test_normalizes_reactjs_and_react_dot_js_to_react():
    assert normalize_skill_variants("Built UIs with ReactJS") == "Built UIs with React"
    assert normalize_skill_variants("Built UIs with React.js") == "Built UIs with React"


def test_normalizes_mongo_db_with_space_to_mongodb():
    assert normalize_skill_variants("Database: Mongo DB") == "Database: MongoDB"


def test_leaves_already_canonical_terms_unchanged():
    assert normalize_skill_variants("Backend in Node.js") == "Backend in Node.js"
    assert normalize_skill_variants("Strong in Machine Learning") == "Strong in Machine Learning"


def test_does_not_touch_react_native_when_normalizing_react():
    # "React Native" must stay its own term, not collapse into "React".
    normalized = normalize_skill_variants("Mobile apps with React Native")
    assert normalized == "Mobile apps with React Native"


def test_detect_skills_recognizes_variant_spellings_via_normalization():
    found = detect_skills("Experience with ReactJS, Mongo DB and TensorFlow.", NORMALIZATION_VOCAB)
    assert "React" in found
    assert "MongoDB" in found
    assert "TensorFlow" in found
