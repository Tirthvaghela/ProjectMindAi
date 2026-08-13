from db.schema import validate, embedding_text

VALID_DOC = {
    "project_id": "pm-test-001",
    "title": "Test Project",
    "description": "x" * 80,
    "domain": "Web Development",
    "technologies": ["Python", "Flask"],
    "difficulty": "Beginner",
    "duration_weeks": 4,
    "skills": ["REST APIs"],
    "keywords": ["web"],
}


def test_valid_document_has_no_problems():
    assert validate(VALID_DOC) == []


def test_rejects_short_description():
    doc = {**VALID_DOC, "description": "too short"}
    problems = validate(doc)
    assert any("description" in p for p in problems)


def test_rejects_unknown_domain():
    doc = {**VALID_DOC, "domain": "Underwater Basket Weaving"}
    assert any("not one of" in p for p in validate(doc))


def test_rejects_unknown_difficulty():
    doc = {**VALID_DOC, "difficulty": "Expert"}
    assert any("must be one of" in p for p in validate(doc))


def test_rejects_missing_required_field():
    doc = {k: v for k, v in VALID_DOC.items() if k != "title"}
    assert any("missing required field 'title'" in p for p in validate(doc))


def test_rejects_empty_list_field():
    doc = {**VALID_DOC, "technologies": []}
    assert any("'technologies' is empty" in p for p in validate(doc))


def test_rejects_duration_out_of_range():
    doc = {**VALID_DOC, "duration_weeks": 100}
    assert any("outside the sane range" in p for p in validate(doc))


def test_embedding_text_includes_core_fields():
    text = embedding_text(VALID_DOC)
    assert VALID_DOC["title"] in text
    assert "Python" in text
    assert "Web Development" in text
