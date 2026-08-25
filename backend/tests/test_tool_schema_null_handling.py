"""Groq tool-schema null-tolerance — the reliability fix for a real, live-
reproduced bug: Groq's tool-calling model frequently sends explicit JSON
`null` for an optional argument it has no value for, rather than omitting
the key. Any TOOL_SCHEMAS field typed e.g. `{"type": "string"}` (no "null"
in the type) makes Groq's OWN server-side schema validation reject that
call outright with a 400 — before nlp/chat_tools.py:call_tool() is ever
reached, so no amount of defensive Python code can save it. Confirmed live
this session for `team_size`/`technologies` (analyze_project_feasibility/
estimate_project_resources) and `known_skills`/`team_size`/
`experience_level`/`target_weeks` (recommend_decision).

Two things are tested here:
1. Every OPTIONAL field across all 24 tools' schemas explicitly allows
   null — a structural guard against ever reintroducing this bug as new
   tools/fields are added.
2. call_tool() dispatch doesn't crash or misbehave when a null actually
   arrives for those fields — including the specific `str(None) -> "None"`
   footgun this task found and fixed (str(x.get(key, "")) only applies its
   default when the key is ABSENT, not when it's present with value None).
"""

from __future__ import annotations

import pytest

from db import client as db
from nlp import chat_tools

# --- 1. Structural guard: every optional field accepts null ------------------


def _type_list(schema: dict) -> list[str]:
    t = schema.get("type")
    return [t] if isinstance(t, str) else list(t or [])


@pytest.mark.parametrize("tool", chat_tools.TOOL_SCHEMAS, ids=lambda t: t["function"]["name"])
def test_every_optional_field_explicitly_allows_null(tool):
    fn = tool["function"]
    params = fn["parameters"]
    required = set(params.get("required", []))
    properties = params.get("properties", {})

    for field_name, field_schema in properties.items():
        if field_name in required:
            continue
        assert "null" in _type_list(field_schema), (
            f"{fn['name']}.{field_name} is optional but its schema type "
            f"{field_schema.get('type')!r} does not include 'null' — Groq can "
            "send null for any field it has no value for, and this would 400."
        )


@pytest.mark.parametrize("tool", chat_tools.TOOL_SCHEMAS, ids=lambda t: t["function"]["name"])
def test_every_enum_field_that_allows_null_lists_null_in_its_own_enum(tool):
    # type ["string", "null"] alone isn't enough when "enum" is also present —
    # JSON Schema still requires the value to be one of the enum's own
    # members, so None must be listed there too, not just in "type".
    fn = tool["function"]
    for field_name, field_schema in fn["parameters"].get("properties", {}).items():
        if "enum" not in field_schema:
            continue
        if "null" in _type_list(field_schema):
            assert None in field_schema["enum"], (
                f"{fn['name']}.{field_name} allows null in its type but not in "
                "its own enum list — a null value would still fail enum validation."
            )


def test_required_fields_are_unchanged_and_never_nullable():
    # Spot-check a representative sample of fields that must stay required,
    # non-nullable, exactly as before this fix — the point of this task was
    # never to loosen what's mandatory.
    by_name = {t["function"]["name"]: t["function"] for t in chat_tools.TOOL_SCHEMAS}

    assert by_name["search_projects"]["parameters"]["required"] == ["query"]
    assert "null" not in _type_list(by_name["search_projects"]["parameters"]["properties"]["query"])

    assert set(by_name["check_skill_gap"]["parameters"]["required"]) == {"project_id", "known_skills"}
    assert "null" not in _type_list(by_name["check_skill_gap"]["parameters"]["properties"]["known_skills"])

    assert by_name["select_idea"]["parameters"]["required"] == ["name"]
    assert "null" not in _type_list(by_name["select_idea"]["parameters"]["properties"]["name"])

    assert set(by_name["refine_project_idea"]["parameters"]["required"]) == {"name", "instruction"}


# --- 2. Dispatch handles a real null without crashing or leaking "None" ------


class _FakeCursor(list):
    """db.projects().find(...) returns a Mongo cursor; a plain list satisfies
    the iteration recommend_decision/compare_projects actually do."""


class _FakeProjects:
    def __init__(self, docs):
        self._docs = docs

    def find_one(self, query, *_args, **_kwargs):
        return self._docs.get(query.get("project_id"))

    def find(self, query, *_args, **_kwargs):
        ids = set(query.get("project_id", {}).get("$in", []))
        return _FakeCursor(doc for pid, doc in self._docs.items() if pid in ids)


@pytest.fixture
def fake_projects(monkeypatch):
    docs = {
        "p1": {
            "project_id": "p1",
            "title": "Sample Project",
            "domain": "Web Development",
            "difficulty": "Beginner",
            "duration_weeks": 4,
            "technologies": ["React"],
            "skills": ["HTML"],
            "description": "A sample.",
        }
    }
    fake = _FakeProjects(docs)
    monkeypatch.setattr(db, "projects", lambda: fake)
    return fake


def test_select_idea_with_every_optional_field_null_never_leaks_the_string_none():
    # The exact bug this task found: str(arguments.get("problem", "")) only
    # applies "" when the key is ABSENT — with an explicit null (which Groq
    # legitimately sends), that used to produce the literal string "None".
    for_model, block = chat_tools.call_tool(
        "select_idea",
        {
            "name": "QuizWhiz",
            "id": None,
            "problem": None,
            "solution": None,
            "unique_point": None,
            "technologies": None,
            "domain": None,
            "difficulty": None,
            "duration_weeks": None,
        },
    )
    assert block["type"] == "idea_selected"
    idea = block["idea"]
    assert idea["problem"] == ""
    assert idea["solution"] == ""
    assert idea["unique_point"] == ""
    assert "None" not in idea.values()
    assert idea["technologies"] == []
    assert idea["domain"] == ""
    assert idea["difficulty"] == ""
    assert idea["duration_weeks"] is None


def test_refine_project_idea_with_every_optional_field_null_never_leaks_the_string_none(monkeypatch):
    monkeypatch.setattr(chat_tools.ideation, "refine_idea", lambda current, instruction: {**current, "id": current.get("id") or "idea-1"})

    for_model, block = chat_tools.call_tool(
        "refine_project_idea",
        {
            "name": "QuizWhiz",
            "instruction": "make it simpler",
            "id": None,
            "problem": None,
            "solution": None,
            "unique_point": None,
            "technologies": None,
            "domain": None,
            "difficulty": None,
            "duration_weeks": None,
        },
    )
    assert block["type"] == "generated_project_ideas"
    refined = block["ideas"][0]
    assert refined["problem"] == ""
    assert refined["solution"] == ""
    assert refined["unique_point"] == ""
    assert "None" not in [str(v) for v in refined.values() if v == "None"]


def test_generate_project_ideas_with_every_optional_field_null(monkeypatch):
    monkeypatch.setattr(
        chat_tools.ideation,
        "generate_ideas",
        lambda **kwargs: [] if kwargs.get("topic") == "None" else [{"id": "idea-1", "name": "X", "unique_point": "", "domain": "", "difficulty": "", "duration_weeks": 8, "originality_score": 80, "similar_projects": []}],
    )

    for_model, block = chat_tools.call_tool(
        "generate_project_ideas", {"topic": None, "domain": None, "difficulty": None, "count": None}
    )
    # The fake generate_ideas returns [] only if topic leaked through as the
    # literal string "None" — a non-empty result proves it didn't.
    assert block is not None
    assert block["ideas"]


def test_recommend_decision_with_every_optional_field_null(fake_projects, monkeypatch):
    # This is the exact call shape observed live: Groq sent every optional
    # field as an explicit null and the old schema 400'd before dispatch was
    # ever reached.
    monkeypatch.setattr(chat_tools.recommend, "similar", lambda *a, **k: [])
    for_model, block = chat_tools.call_tool(
        "recommend_decision",
        {
            "project_ids": ["p1"],
            "known_skills": None,
            "team_size": None,
            "experience_level": None,
            "prefers_unique": None,
            "target_weeks": None,
        },
    )
    assert "error" not in for_model
    assert block["type"] == "decision"


def test_search_projects_with_every_optional_field_null(monkeypatch):
    monkeypatch.setattr(chat_tools.recommend, "search", lambda *a, **k: [])
    for_model, block = chat_tools.call_tool(
        "search_projects",
        {
            "query": "web app",
            "difficulty": None,
            "domain": None,
            "max_duration_weeks": None,
            "top_k": None,
            "known_skills": None,
            "team_size": None,
            "experience_level": None,
        },
    )
    assert "error" not in for_model


def test_predict_timeline_with_optional_fields_null(fake_projects):
    for_model, block = chat_tools.call_tool(
        "predict_timeline", {"project_id": "p1", "team_size": None, "experience_level": None}
    )
    assert "error" not in for_model
    assert block["type"] == "timeline"


def test_find_similar_projects_top_k_null(fake_projects, monkeypatch):
    monkeypatch.setattr(chat_tools.recommend, "similar", lambda *a, **k: [])
    for_model, block = chat_tools.call_tool("find_similar_projects", {"project_id": "p1", "top_k": None})
    assert "error" not in for_model


def test_match_resume_projects_top_k_null(monkeypatch):
    monkeypatch.setattr(chat_tools.recommend, "personalized_recommend", lambda *a, **k: [])
    for_model, block = chat_tools.call_tool(
        "match_resume_projects", {"known_skills": ["Python"], "top_k": None}
    )
    assert "error" not in for_model


@pytest.mark.parametrize(
    "tool_name",
    ["generate_idea_roadmap", "generate_idea_timeline", "generate_idea_milestones"],
)
def test_generate_idea_tools_with_every_optional_field_null(tool_name):
    result = chat_tools.call_tool(
        tool_name,
        {
            "name": "QuizWhiz",
            "domain": None,
            "difficulty": None,
            "duration_weeks": None,
            "technologies": None,
            "team_size": None,
            "experience_level": None,
        },
    )
    for_model = result[0] if isinstance(result, tuple) else result
    assert "error" not in for_model
