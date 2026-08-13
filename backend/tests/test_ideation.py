"""nlp/ideation.py — the generate-then-validate pipeline behind
generate_project_ideas/refine_project_idea.

Fully mocked: _generate_raw (the Groq call) and recommend.check_uniqueness
(needs a live embedding index + MongoDB) are both monkeypatched, so these
tests never touch a network or a database — same philosophy as
test_generator.py for the deterministic pieces of this codebase.
"""

from __future__ import annotations

from nlp import ai_assistant, ideation

RAW_IDEA = {
    "name": "AI Codebase Understanding System",
    "problem": "Developers struggle to understand unfamiliar repositories.",
    "solution": "Upload a repo and ask questions about its architecture and execution flow.",
    "unique_point": "Builds a dependency-aware execution graph instead of plain RAG over files.",
    "technologies": ["Python", "FastAPI", "Tree-sitter", "React"],
    "domain": "Artificial Intelligence",
    "difficulty": "Advanced",
    "duration_weeks": 11,
}

ORIGINAL_UNIQUENESS_RESULT = {
    "is_unique": True,
    "originality_score": 82,
    "similar_projects": [],
    "overlapping_concepts": [],
}

DUPLICATE_UNIQUENESS_RESULT = {
    "is_unique": False,
    "originality_score": 30,
    "similar_projects": [{"project_id": "pm-001", "title": "Codebase Chat Assistant", "domain": "Artificial Intelligence"}],
    "overlapping_concepts": ["Python", "RAG"],
}


def test_generate_ideas_returns_validated_shape(monkeypatch):
    monkeypatch.setattr(ideation, "_generate_raw", lambda prompt: [RAW_IDEA])
    monkeypatch.setattr(ideation.recommend, "check_uniqueness", lambda *a, **k: ORIGINAL_UNIQUENESS_RESULT)

    ideas = ideation.generate_ideas(topic="AI", count=1)

    assert len(ideas) == 1
    idea = ideas[0]
    assert idea["id"] == "idea-1"
    assert idea["name"] == RAW_IDEA["name"]
    assert idea["originality_score"] == 82
    assert idea["is_unique"] is True
    assert idea["domain"] == "Artificial Intelligence"
    assert idea["difficulty"] == "Advanced"
    assert idea["duration_weeks"] == 11


def test_generate_ideas_assigns_sequential_ids(monkeypatch):
    monkeypatch.setattr(ideation, "_generate_raw", lambda prompt: [RAW_IDEA, {**RAW_IDEA, "name": "Second Idea"}])
    monkeypatch.setattr(ideation.recommend, "check_uniqueness", lambda *a, **k: ORIGINAL_UNIQUENESS_RESULT)

    ideas = ideation.generate_ideas(count=2)

    assert [i["id"] for i in ideas] == ["idea-1", "idea-2"]


def test_generate_ideas_drops_unknown_domain_and_difficulty(monkeypatch):
    bad = {**RAW_IDEA, "domain": "Not A Real Domain", "difficulty": "Expert"}
    monkeypatch.setattr(ideation, "_generate_raw", lambda prompt: [bad])
    monkeypatch.setattr(ideation.recommend, "check_uniqueness", lambda *a, **k: ORIGINAL_UNIQUENESS_RESULT)

    idea = ideation.generate_ideas(count=1)[0]

    assert idea["difficulty"] == "Intermediate"  # falls back rather than keeping an invalid enum value
    assert idea["domain"] == ""  # no similar_projects to borrow a domain from either


def test_generate_ideas_regenerates_once_when_too_similar(monkeypatch):
    calls = {"n": 0}

    def fake_raw(prompt):
        calls["n"] += 1
        return [RAW_IDEA]

    results = iter([DUPLICATE_UNIQUENESS_RESULT, ORIGINAL_UNIQUENESS_RESULT])
    monkeypatch.setattr(ideation, "_generate_raw", fake_raw)
    monkeypatch.setattr(ideation.recommend, "check_uniqueness", lambda *a, **k: next(results))

    ideas = ideation.generate_ideas(count=1)

    assert calls["n"] == 2  # one initial generation + one regeneration pass
    assert ideas[0]["originality_score"] == 82  # the regenerated (accepted) result, not the duplicate one


def test_generate_ideas_keeps_low_score_idea_if_regeneration_still_fails(monkeypatch):
    monkeypatch.setattr(ideation, "_generate_raw", lambda prompt: [RAW_IDEA])
    monkeypatch.setattr(ideation.recommend, "check_uniqueness", lambda *a, **k: DUPLICATE_UNIQUENESS_RESULT)

    ideas = ideation.generate_ideas(count=1)

    # Still returned, honestly labelled with the real (low) score — never
    # silently retried forever, never hidden from the student.
    assert ideas[0]["originality_score"] == 30
    assert ideas[0]["is_unique"] is False


def test_generate_ideas_handles_empty_generation(monkeypatch):
    monkeypatch.setattr(ideation, "_generate_raw", lambda prompt: [])

    assert ideation.generate_ideas(count=3) == []


def test_generate_ideas_caps_count_at_max(monkeypatch):
    monkeypatch.setattr(ideation, "_generate_raw", lambda prompt: [RAW_IDEA] * 10)
    monkeypatch.setattr(ideation.recommend, "check_uniqueness", lambda *a, **k: ORIGINAL_UNIQUENESS_RESULT)

    ideas = ideation.generate_ideas(count=999)

    assert len(ideas) == ideation.IDEA_COUNT_MAX


def test_refine_idea_reuses_id_and_revalidates(monkeypatch):
    monkeypatch.setattr(ideation, "_generate_raw", lambda prompt: [{**RAW_IDEA, "name": "More Innovative Version"}])
    monkeypatch.setattr(ideation.recommend, "check_uniqueness", lambda *a, **k: ORIGINAL_UNIQUENESS_RESULT)

    current = {**RAW_IDEA, "id": "idea-2"}
    refined = ideation.refine_idea(current, "make it more innovative")

    assert refined["id"] == "idea-2"
    assert refined["name"] == "More Innovative Version"


def test_refine_idea_falls_back_to_original_when_generation_empty(monkeypatch):
    monkeypatch.setattr(ideation, "_generate_raw", lambda prompt: [])
    monkeypatch.setattr(ideation.recommend, "check_uniqueness", lambda *a, **k: ORIGINAL_UNIQUENESS_RESULT)

    current = {**RAW_IDEA, "id": "idea-3"}
    refined = ideation.refine_idea(current, "make it shorter")

    assert refined["id"] == "idea-3"
    assert refined["name"] == RAW_IDEA["name"]


# --- _generate_raw() malformed-response reliability (structured response
# validation / repair-retry) -------------------------------------------------
#
# Unlike the tests above (which monkeypatch _generate_raw itself away), these
# exercise _generate_raw directly against a fake completion, monkeypatching
# only the underlying Groq call (nlp.ai_assistant._create_completion) it
# reads via a deferred import — no network, no real LLM.


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeCompletion:
    def __init__(self, content=None, no_choices=False):
        self.choices = [] if no_choices else [_FakeChoice(content)]


def test_generate_raw_retries_once_on_malformed_json(monkeypatch):
    responses = iter(
        [
            _FakeCompletion(content="not valid json {"),
            _FakeCompletion(content='{"ideas": [{"name": "Recovered Idea"}]}'),
        ]
    )
    monkeypatch.setattr(ai_assistant, "_create_completion", lambda **_: next(responses))

    ideas = ideation._generate_raw("generate ideas")

    assert ideas == [{"name": "Recovered Idea"}]


def test_generate_raw_gives_up_after_one_retry_if_still_malformed(monkeypatch):
    calls = {"n": 0}

    def always_bad(**_):
        calls["n"] += 1
        return _FakeCompletion(content="still not json")

    monkeypatch.setattr(ai_assistant, "_create_completion", always_bad)

    ideas = ideation._generate_raw("generate ideas")

    # RELIABILITY: exactly one initial attempt + one repair retry — never
    # more, so a persistently malformed response can't loop forever.
    assert ideas == []
    assert calls["n"] == 2


def test_generate_raw_retries_when_ideas_key_is_missing(monkeypatch):
    responses = iter(
        [
            _FakeCompletion(content='{"not_ideas": []}'),
            _FakeCompletion(content='{"ideas": [{"name": "Fixed"}]}'),
        ]
    )
    monkeypatch.setattr(ai_assistant, "_create_completion", lambda **_: next(responses))

    ideas = ideation._generate_raw("generate ideas")

    assert ideas == [{"name": "Fixed"}]


def test_generate_raw_does_not_retry_a_valid_but_empty_ideas_list(monkeypatch):
    calls = {"n": 0}

    def returns_empty(**_):
        calls["n"] += 1
        return _FakeCompletion(content='{"ideas": []}')

    monkeypatch.setattr(ai_assistant, "_create_completion", returns_empty)

    ideas = ideation._generate_raw("generate ideas")

    # A syntactically valid "no ideas" response is not malformed — spending
    # a retry on it would just be wasted latency for the same likely outcome.
    assert ideas == []
    assert calls["n"] == 1


def test_generate_raw_handles_no_choices_without_crashing(monkeypatch):
    responses = iter(
        [
            _FakeCompletion(no_choices=True),
            _FakeCompletion(content='{"ideas": [{"name": "Recovered"}]}'),
        ]
    )
    monkeypatch.setattr(ai_assistant, "_create_completion", lambda **_: next(responses))

    ideas = ideation._generate_raw("generate ideas")

    assert ideas == [{"name": "Recovered"}]
