"""Tests for the conversational orchestration layer (nlp/ai_assistant.py).

Two groups:
- The pure, non-LLM helpers (_shown_projects_note, _shown_ideas_note,
  _active_project_note, _active_idea_note, _match_scores_from_history) — no
  network, no mocking needed.
- general_reply()'s tool-calling loop, exercised with a fake Groq client so
  the RELIABILITY properties the assistant is supposed to guarantee (bounded
  loop, tolerates a malformed tool call, never crashes on an unexpected tool
  call, survives a tool raising) are verified deterministically rather than
  by hoping a real model behaves badly during manual testing.
"""

from __future__ import annotations

import pytest

from db import client as db
from nlp import ai_assistant, chat_tools

PROJECT = {
    "project_id": "pm-ai-001",
    "title": "AI-Powered Medical Diagnosis Assistant",
    "description": "A clinical decision support system that predicts likely conditions.",
    "domain": "Artificial Intelligence",
    "difficulty": "Advanced",
    "technologies": ["Python", "scikit-learn", "Flask", "Docker", "PostgreSQL"],
    "skills": ["Supervised learning", "REST API development"],
    "duration_weeks": 12,
}

IDEA = {
    "id": "idea-2",
    "name": "Smart Campus Notes",
    "problem": "Students lose track of scattered lecture notes.",
    "solution": "A unifying, searchable notes hub with AI summaries.",
    "unique_point": "Cross-references notes against the syllabus automatically.",
    "technologies": ["Python", "FastAPI", "React"],
    "domain": "Artificial Intelligence",
    "difficulty": "Intermediate",
    "duration_weeks": 10,
}


@pytest.fixture
def project(mongo_test_db):
    db.projects().insert_one(dict(PROJECT))
    return PROJECT


# --- _shown_projects_note / _shown_ideas_note --------------------------------


def test_shown_projects_note_is_empty_without_a_recommendations_block():
    assert ai_assistant._shown_projects_note([]) == ""
    assert ai_assistant._shown_projects_note([{"type": "skill_gap"}]) == ""


def test_shown_projects_note_numbers_projects_in_order():
    blocks = [
        {
            "type": "project_recommendations",
            "projects": [
                {"project_id": "pm-1", "title": "First", "difficulty": "Beginner", "technologies": ["Python"]},
                {"project_id": "pm-2", "title": "Second", "difficulty": "Advanced", "technologies": []},
            ],
        }
    ]
    note = ai_assistant._shown_projects_note(blocks)
    assert '1. pm-1 "First" (Beginner, Python)' in note
    assert '2. pm-2 "Second" (Advanced)' in note


def test_shown_ideas_note_is_empty_without_a_generated_ideas_block():
    assert ai_assistant._shown_ideas_note([{"type": "project_recommendations", "projects": []}]) == ""


def test_shown_ideas_note_includes_full_fields_for_later_refinement():
    blocks = [{"type": "generated_project_ideas", "ideas": [IDEA]}]
    note = ai_assistant._shown_ideas_note(blocks)
    assert "idea-2" in note
    assert "Smart Campus Notes" in note
    assert IDEA["unique_point"] in note


def test_shown_ideas_note_truncates_long_free_text_fields():
    # RELIABILITY: unlike technologies/domain/difficulty, problem/solution/
    # unique_point are unbounded model prose — replayed on every later turn,
    # several of these per idea across a conversation that generates ideas
    # more than once has driven a real request over a tools-heavy model's
    # tokens-per-minute budget (a 413 from Groq). Must stay short enough to
    # matter, long enough to still ground a follow-up question.
    long_idea = {
        **IDEA,
        "problem": "x" * 400,
        "solution": "y" * 400,
        "unique_point": "z" * 400,
    }
    note = ai_assistant._shown_ideas_note([{"type": "generated_project_ideas", "ideas": [long_idea]}])
    assert "x" * 400 not in note
    assert "y" * 400 not in note
    assert "z" * 400 not in note
    assert "…" in note
    # Still grounded in the idea's real content, not replaced wholesale.
    assert note.count("x") <= ai_assistant._IDEA_NOTE_FIELD_PREVIEW_CHARS + 5
    assert note.startswith("\n\n[Context")


def test_shown_ideas_note_leaves_short_fields_untouched():
    note = ai_assistant._shown_ideas_note([{"type": "generated_project_ideas", "ideas": [IDEA]}])
    assert IDEA["problem"] in note
    assert IDEA["solution"] in note
    assert "…" not in note


# --- _active_project_note / _active_idea_note --------------------------------


def test_active_project_note_is_empty_with_no_selection():
    assert ai_assistant._active_project_note(None) == ""


def test_active_project_note_names_the_selected_project(project):
    note = ai_assistant._active_project_note(project["project_id"])
    assert project["project_id"] in note
    assert project["title"] in note
    assert "active project" in note


def test_active_project_note_carries_requirements_not_just_the_name(project):
    # The Project AI Mentor must know description/duration/skills, not just
    # title/difficulty/domain — otherwise "how should I build the backend?"
    # has nothing to ground "requirements" in beyond a title.
    note = ai_assistant._active_project_note(project["project_id"])
    assert project["description"] in note
    assert f"{project['duration_weeks']} weeks" in note
    assert project["skills"][0] in note
    assert project["technologies"][0] in note


def test_active_project_note_truncates_a_long_description(mongo_test_db):
    doc = {**PROJECT, "project_id": "pm-long-desc", "description": "x" * 400}
    db.projects().insert_one(doc)
    note = ai_assistant._active_project_note(doc["project_id"])
    assert "…" in note
    assert "x" * 400 not in note


def test_active_project_note_is_empty_for_a_deleted_project(mongo_test_db):
    assert ai_assistant._active_project_note("does-not-exist") == ""


def test_active_idea_note_is_empty_with_no_selection():
    assert ai_assistant._active_idea_note(None) == ""
    assert ai_assistant._active_idea_note({}) == ""


def test_active_idea_note_names_the_selected_idea():
    note = ai_assistant._active_idea_note(IDEA)
    assert IDEA["name"] in note
    assert "active idea" in note
    assert "not a catalogue project" in note


def test_active_idea_note_carries_problem_and_solution():
    # Same "ground it in real requirements, not just a name" property
    # _active_project_note has, from the idea's own stored fields.
    note = ai_assistant._active_idea_note(IDEA)
    assert IDEA["problem"] in note
    assert IDEA["solution"] in note


def test_active_idea_and_active_project_notes_are_never_both_relevant_at_once(project):
    # Mirrors the mutual-exclusivity rule general_reply enforces: a caller
    # that already cleared one before calling the other never gets two
    # conflicting context notes glued into the same user turn.
    project_note = ai_assistant._active_project_note(project["project_id"])
    idea_note = ai_assistant._active_idea_note(None)
    assert project_note and not idea_note


# --- _named_reference_note ----------------------------------------------------
#
# RELIABILITY (reported live): every per-card action button in this app
# (Create Roadmap, Compare, Check Uniqueness, ...) sends a message that names
# its idea/project by exact quoted title — 'Create a roadmap for "QuizWhiz".'
# — trusting the model to resolve that against the shown-ideas/shown-projects
# note attached several turns back in history. Direct testing against the
# real message-construction code found that note WAS present in the request
# the model received, yet the model still asked the student to redescribe an
# idea whose fields were already right there — a model reliability gap, not
# a missing-context bug. _named_reference_note closes it deterministically:
# resolve the quoted name in code, and hand the model those exact fields on
# the turn it's actually reading (the current user message), not one it has
# to reach back for.


def test_named_reference_note_is_empty_without_a_quoted_name():
    history = [{"role": "assistant", "content": "Here.", "blocks": [{"type": "generated_project_ideas", "ideas": [IDEA]}]}]
    assert ai_assistant._named_reference_note("tell me about it", history) == ""


def test_named_reference_note_is_empty_without_a_matching_block():
    assert ai_assistant._named_reference_note('Create a roadmap for "QuizWhiz".', None) == ""
    assert ai_assistant._named_reference_note('Create a roadmap for "QuizWhiz".', []) == ""


def test_named_reference_note_resolves_a_quoted_idea_name():
    history = [{"role": "assistant", "content": "Here.", "blocks": [{"type": "generated_project_ideas", "ideas": [IDEA]}]}]
    note = ai_assistant._named_reference_note(f'Create a roadmap for "{IDEA["name"]}".', history)
    assert IDEA["name"] in note
    assert IDEA["problem"] in note
    assert IDEA["solution"] in note
    assert "already shown in this conversation" in note
    assert "never ask the student to redescribe it" in note


def test_named_reference_note_ignores_a_quoted_name_that_matches_nothing():
    history = [{"role": "assistant", "content": "Here.", "blocks": [{"type": "generated_project_ideas", "ideas": [IDEA]}]}]
    assert ai_assistant._named_reference_note('Create a roadmap for "Not A Real Idea".', history) == ""


def test_named_reference_note_resolves_a_quoted_project_title(project):
    history = [
        {
            "role": "assistant",
            "content": "Here.",
            "blocks": [{"type": "project_recommendations", "projects": [{"project_id": project["project_id"], "title": project["title"]}]}],
        }
    ]
    note = ai_assistant._named_reference_note(f'Create a roadmap for "{project["title"]}".', history)
    assert project["title"] in note
    assert project["project_id"] in note
    assert project["description"] in note


def test_named_reference_note_skips_the_name_already_covered_by_the_active_idea_note():
    """RELIABILITY (token budget): don't pay twice for the same idea's fields
    on one turn — _active_idea_note already carries them when the referenced
    idea IS the active one."""
    history = [{"role": "assistant", "content": "Here.", "blocks": [{"type": "generated_project_ideas", "ideas": [IDEA]}]}]
    note = ai_assistant._named_reference_note(
        f'Tell me more about "{IDEA["name"]}".', history, selected_idea=IDEA
    )
    assert note == ""


def test_named_reference_note_skips_the_name_already_covered_by_the_active_project_note(project):
    history = [
        {
            "role": "assistant",
            "content": "Here.",
            "blocks": [{"type": "project_recommendations", "projects": [{"project_id": project["project_id"], "title": project["title"]}]}],
        }
    ]
    note = ai_assistant._named_reference_note(
        f'Tell me more about "{project["title"]}".',
        history,
        selected_project_id=project["project_id"],
    )
    assert note == ""


def test_named_reference_note_resolves_multiple_quoted_names_in_one_message():
    idea_2 = {**IDEA, "id": "idea-3", "name": "Second Idea"}
    history = [
        {"role": "assistant", "content": "Here.", "blocks": [{"type": "generated_project_ideas", "ideas": [IDEA, idea_2]}]},
    ]
    note = ai_assistant._named_reference_note(
        f'Compare "{IDEA["name"]}" with "{idea_2["name"]}".', history
    )
    assert IDEA["name"] in note
    assert idea_2["name"] in note


def test_named_reference_note_prefers_the_most_recent_matching_block():
    older = {**IDEA, "id": "idea-old", "problem": "an old, superseded problem statement"}
    newer = {**IDEA, "id": "idea-new", "problem": "the current, up-to-date problem statement"}
    history = [
        {"role": "assistant", "content": "Here.", "blocks": [{"type": "generated_project_ideas", "ideas": [older]}]},
        {"role": "assistant", "content": "Here again.", "blocks": [{"type": "generated_project_ideas", "ideas": [newer]}]},
    ]
    note = ai_assistant._named_reference_note(f'Create a roadmap for "{IDEA["name"]}".', history)
    assert "current, up-to-date" in note
    assert "old, superseded" not in note


def test_general_reply_threads_the_named_reference_note_into_the_user_message(monkeypatch, mongo_test_db):
    """End-to-end: the exact live repro — a Dashboard 'Create Roadmap' click
    on an unselected generated idea must still ground the model, even though
    nothing was ever select_idea'd."""
    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)
    captured = {}

    def capture(**kwargs):
        captured["messages"] = kwargs["messages"]
        return _text_completion("Here's the roadmap.")

    monkeypatch.setattr(ai_assistant, "_create_completion", capture)

    history = [
        {"role": "user", "content": "Generate 5 new ideas."},
        {"role": "assistant", "content": "Here are five.", "blocks": [{"type": "generated_project_ideas", "ideas": [IDEA]}]},
    ]
    ai_assistant.general_reply(f'Create a roadmap for "{IDEA["name"]}".', history)

    last_user_message = captured["messages"][-1]["content"]
    assert IDEA["name"] in last_user_message
    assert IDEA["problem"] in last_user_message
    assert "never ask the student to redescribe it" in last_user_message


# --- _resume_context_note -----------------------------------------------------


def test_resume_context_note_is_empty_with_no_skills():
    assert ai_assistant._resume_context_note(None) == ""
    assert ai_assistant._resume_context_note([]) == ""


def test_resume_context_note_lists_the_skills():
    note = ai_assistant._resume_context_note(["Python", "React", "MongoDB"])
    assert "Python" in note
    assert "React" in note
    assert "MongoDB" in note
    assert "résumé skills" in note


def test_resume_context_note_can_coexist_with_an_active_project_note(project):
    # Unlike active-project vs active-idea, résumé context is independent of
    # project selection — both notes can be true on the same turn (a student
    # can have an uploaded résumé AND a selected project at once).
    project_note = ai_assistant._active_project_note(project["project_id"])
    resume_note = ai_assistant._resume_context_note(["Python"])
    assert project_note and resume_note


# --- Project AI Mentor guidance (prompt regression guards) --------------------
#
# These don't exercise a real model — they guard the *instructions* the model
# is given (nlp/ai_assistant.py's system prompts), the same way the rest of
# this file tests the deterministic scaffolding around it. A prompt edit that
# accidentally drops one of these behaviours should fail a test, not just be
# noticed the next time someone manually tries the missing scenario.


def test_general_system_message_instructs_adapted_architecture_guidance():
    content = ai_assistant._GENERAL_SYSTEM_MESSAGE["content"]
    assert "build mentor" in content
    assert "never one generic shape reused for every project" in content


def test_general_system_message_instructs_recalling_the_roadmap_for_phase_follow_ups():
    content = ai_assistant._GENERAL_SYSTEM_MESSAGE["content"]
    assert "call that same roadmap tool again" in content


def test_general_system_message_instructs_grounded_prioritisation():
    content = ai_assistant._GENERAL_SYSTEM_MESSAGE["content"]
    assert "prioritisation question under a real constraint" in content
    assert "predict_timeline" in content


def test_general_system_message_instructs_asking_when_no_project_is_active():
    content = ai_assistant._GENERAL_SYSTEM_MESSAGE["content"]
    assert "ask which project or idea before answering" in content


def test_general_system_message_forbids_claiming_implementation():
    content = ai_assistant._GENERAL_SYSTEM_MESSAGE["content"]
    assert "never claim to have" in content
    assert "implemented, written, tested, or changed" in content


def test_project_system_template_forbids_claiming_implementation():
    content = ai_assistant._SYSTEM_TEMPLATE
    assert "never claim to have implemented, written, tested, or changed" in content
    assert "say plainly that it isn't specified rather than inventing" in content


# --- _history_messages: only the most-recent shown-projects/ideas note --------
#
# RELIABILITY (unbounded request growth): before this, every assistant turn
# in the replayed window that ever showed projects/ideas got its full note
# threaded in on every later turn — a conversation that searches or
# generates ideas more than once accumulated every earlier turn's note
# without bound. This is exactly the shape of the real conversation that
# drove a request over Groq's tokens-per-minute limit (a 413, not a flaky
# rate limit) investigated live against that account.


def test_history_messages_only_threads_the_most_recent_ideas_note():
    older_idea = {**IDEA, "id": "idea-1", "name": "Older Idea"}
    newer_idea = {**IDEA, "id": "idea-9", "name": "Newer Idea"}
    history = [
        {"role": "user", "content": "give me ideas"},
        {"role": "assistant", "content": "Here are some.", "blocks": [{"type": "generated_project_ideas", "ideas": [older_idea]}]},
        {"role": "user", "content": "give me different ideas"},
        {"role": "assistant", "content": "Here are more.", "blocks": [{"type": "generated_project_ideas", "ideas": [newer_idea]}]},
    ]
    messages = ai_assistant._history_messages(history, with_shown_projects=True)

    all_content = " ".join(m["content"] for m in messages)
    assert "Newer Idea" in all_content
    assert "Older Idea" not in all_content


def test_history_messages_only_threads_the_most_recent_projects_note():
    history = [
        {"role": "user", "content": "find nlp projects"},
        {
            "role": "assistant",
            "content": "Here are some.",
            "blocks": [{"type": "project_recommendations", "projects": [{"project_id": "pm-old", "title": "Old Project"}]}],
        },
        {"role": "user", "content": "find cv projects instead"},
        {
            "role": "assistant",
            "content": "Here are those.",
            "blocks": [{"type": "project_recommendations", "projects": [{"project_id": "pm-new", "title": "New Project"}]}],
        },
    ]
    messages = ai_assistant._history_messages(history, with_shown_projects=True)

    all_content = " ".join(m["content"] for m in messages)
    assert "pm-new" in all_content
    assert "pm-old" not in all_content


def test_history_messages_tracks_projects_and_ideas_most_recent_independently():
    # A projects note and an ideas note are tracked separately — the most
    # recent of EACH kind survives, not just the single most recent turn
    # overall (a projects turn must not suppress an earlier ideas turn).
    history = [
        {
            "role": "assistant",
            "content": "Ideas first.",
            "blocks": [{"type": "generated_project_ideas", "ideas": [IDEA]}],
        },
        {
            "role": "assistant",
            "content": "Then projects.",
            "blocks": [{"type": "project_recommendations", "projects": [{"project_id": "pm-later", "title": "Later Project"}]}],
        },
    ]
    messages = ai_assistant._history_messages(history, with_shown_projects=True)

    all_content = " ".join(m["content"] for m in messages)
    assert IDEA["name"] in all_content
    assert "pm-later" in all_content


def test_history_messages_without_shown_projects_never_adds_notes():
    # reply()'s call path (no `blocks` concept at all) must stay exactly as
    # lean as before — this flag exists only for general_reply().
    history = [
        {"role": "assistant", "content": "Here are some.", "blocks": [{"type": "generated_project_ideas", "ideas": [IDEA]}]},
    ]
    messages = ai_assistant._history_messages(history, with_shown_projects=False)
    assert messages == [{"role": "assistant", "content": "Here are some."}]


# --- _match_scores_from_history -----------------------------------------------


def test_match_scores_from_history_reads_the_most_recent_recommendations_block():
    history = [
        {
            "role": "assistant",
            "blocks": [
                {
                    "type": "project_recommendations",
                    "projects": [{"project_id": "pm-1", "match_score": 0.42}],
                }
            ],
        }
    ]
    assert ai_assistant._match_scores_from_history(history) == {"pm-1": 0.42}


def test_match_scores_from_history_ignores_user_turns_and_missing_blocks():
    history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "blocks": None},
    ]
    assert ai_assistant._match_scores_from_history(history) == {}


# --- general_reply() orchestration reliability --------------------------------


class _FakeFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, call_id, name, arguments):
        self.id = call_id
        self.function = _FakeFunction(name, arguments)


class _FakeMessage:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class _FakeChoice:
    def __init__(self, message):
        self.message = message


class _FakeCompletion:
    def __init__(self, message):
        self.choices = [_FakeChoice(message)]


def _text_completion(content):
    return _FakeCompletion(_FakeMessage(content=content))


def _tool_call_completion(name, arguments, call_id="call-1"):
    return _FakeCompletion(_FakeMessage(tool_calls=[_FakeToolCall(call_id, name, arguments)]))


# --- _create_completion() retry/backoff/rotation reliability ------------------
#
# These exercise the real groq.* exception classes (constructed against a
# throwaway httpx.Request/Response, no network) against a fake Groq *client*
# — one level below general_reply()'s own tests above — so retry count,
# backoff, key rotation and bounded termination are all verified precisely,
# without waiting out real delays or depending on live Groq behaviour.


class _FakeCompletions:
    def __init__(self, script):
        self._script = list(script)
        self.calls = 0

    def create(self, **_kwargs):
        self.calls += 1
        if not self._script:
            raise AssertionError("fake client called more times than scripted")
        item = self._script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class _FakeClient:
    """Mimics groq.Groq's `client.chat.completions.create(...)` shape."""

    def __init__(self, script):
        self.completions = _FakeCompletions(script)
        self.chat = type("_Chat", (), {"completions": self.completions})()


def _fake_request():
    import httpx

    return httpx.Request("POST", "https://api.groq.test/openai/v1/chat/completions")


def _fake_response(status_code):
    import httpx

    return httpx.Response(status_code, request=_fake_request())


def _connection_error():
    from groq import APIConnectionError

    return APIConnectionError(request=_fake_request())


def _internal_server_error():
    from groq import InternalServerError

    return InternalServerError("upstream error", response=_fake_response(500), body=None)


def _rate_limit_error():
    from groq import RateLimitError

    return RateLimitError("rate limited", response=_fake_response(429), body=None)


def _bad_request_error():
    from groq import BadRequestError

    return BadRequestError("malformed request", response=_fake_response(400), body=None)


def _request_too_large_error():
    # Groq's real shape for "this account's tokens-per-minute budget can't
    # fit this request" — a plain APIStatusError at HTTP 413, not
    # RateLimitError and not any of the other named subclasses (BadRequestError
    # etc.) — reproduced live against a real over-budget conversation.
    from groq import APIStatusError

    return APIStatusError("request too large", response=_fake_response(413), body=None)


def test_create_completion_retries_a_transient_error_then_succeeds(monkeypatch):
    sleeps = []
    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)
    monkeypatch.setattr(ai_assistant, "_sleep", lambda seconds: sleeps.append(seconds))
    client = _FakeClient([_connection_error(), _connection_error(), _text_completion("Recovered!")])
    monkeypatch.setattr(ai_assistant, "_clients", lambda: [client])

    result = ai_assistant._create_completion(model="x", messages=[])

    assert result.choices[0].message.content == "Recovered!"
    assert client.completions.calls == 3
    assert len(sleeps) == 2  # one delay before each retry, none after the final success
    assert sleeps == sorted(sleeps)  # backoff grows (or holds), never shrinks


def test_create_completion_terminates_after_max_retries_on_a_persistent_transient_error(monkeypatch):
    """RELIABILITY: a transient error that never clears must not retry
    forever — bounded by MAX_LLM_RETRIES, then surfaced as a real failure."""
    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)
    monkeypatch.setattr(ai_assistant, "_sleep", lambda _seconds: None)
    from groq import InternalServerError

    always_fails = [_internal_server_error() for _ in range(ai_assistant.MAX_LLM_RETRIES + 5)]
    client = _FakeClient(always_fails)
    monkeypatch.setattr(ai_assistant, "_clients", lambda: [client])

    with pytest.raises(InternalServerError):
        ai_assistant._create_completion(model="x", messages=[])

    # Exactly MAX_LLM_RETRIES + 1 attempts on the one configured key — not
    # one more, not exhausting the whole scripted list.
    assert client.completions.calls == ai_assistant.MAX_LLM_RETRIES + 1


def test_create_completion_rotates_to_the_next_key_once_retries_are_exhausted(monkeypatch):
    import itertools

    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)
    monkeypatch.setattr(ai_assistant, "_sleep", lambda _seconds: None)
    monkeypatch.setattr(ai_assistant, "_key_rotation", itertools.count())  # deterministic: starts at key 0

    failing = _FakeClient([_connection_error() for _ in range(ai_assistant.MAX_LLM_RETRIES + 1)])
    working = _FakeClient([_text_completion("From the second key")])
    monkeypatch.setattr(ai_assistant, "_clients", lambda: [failing, working])

    result = ai_assistant._create_completion(model="x", messages=[])

    assert result.choices[0].message.content == "From the second key"
    assert failing.completions.calls == ai_assistant.MAX_LLM_RETRIES + 1
    assert working.completions.calls == 1


def test_create_completion_rotates_to_the_next_key_on_a_413_immediately(monkeypatch):
    """A 413 ("request too large for THIS key's account tokens-per-minute
    budget") is specific to the account behind the failing key — a
    different key (e.g. a different Groq account, its own independent
    budget, per the multi-account GROQ_API_KEYS setup this app supports)
    can genuinely succeed where this one failed, so it must be tried
    immediately, with no same-key backoff retry wasted first (unlike the
    transient-error case above)."""
    import itertools

    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)
    monkeypatch.setattr(ai_assistant, "_sleep", lambda _s: pytest.fail("must never sleep before rotating on a 413"))
    monkeypatch.setattr(ai_assistant, "_key_rotation", itertools.count())

    too_large = _FakeClient([_request_too_large_error()])
    working = _FakeClient([_text_completion("From a different account's key")])
    monkeypatch.setattr(ai_assistant, "_clients", lambda: [too_large, working])

    result = ai_assistant._create_completion(model="x", messages=[])

    assert result.choices[0].message.content == "From a different account's key"
    assert too_large.completions.calls == 1  # no same-key retry attempted
    assert working.completions.calls == 1


def test_create_completion_raises_when_every_key_rejects_the_request_as_too_large(monkeypatch):
    import itertools
    from groq import APIStatusError

    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)
    monkeypatch.setattr(ai_assistant, "_sleep", lambda _s: None)
    monkeypatch.setattr(ai_assistant, "_key_rotation", itertools.count())

    key_a = _FakeClient([_request_too_large_error()])
    key_b = _FakeClient([_request_too_large_error()])
    monkeypatch.setattr(ai_assistant, "_clients", lambda: [key_a, key_b])

    with pytest.raises(APIStatusError) as excinfo:
        ai_assistant._create_completion(model="x", messages=[])

    assert excinfo.value.status_code == 413
    assert key_a.completions.calls == 1
    assert key_b.completions.calls == 1


def test_create_completion_does_not_retry_a_permanent_error(monkeypatch):
    """RELIABILITY: a malformed request fails identically every time — retrying
    it just wastes the retry budget on an error that can never clear."""
    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)
    monkeypatch.setattr(ai_assistant, "_sleep", lambda _s: pytest.fail("must never sleep/retry a permanent error"))
    from groq import BadRequestError

    client = _FakeClient([_bad_request_error()])
    monkeypatch.setattr(ai_assistant, "_clients", lambda: [client])

    with pytest.raises(BadRequestError):
        ai_assistant._create_completion(model="x", messages=[])

    assert client.completions.calls == 1


def test_create_completion_rate_limit_rotates_keys_without_a_retry_delay(monkeypatch):
    """The existing key-rotation behaviour for 429s is unchanged by adding
    transient-error retry: still no backoff, straight to the next key."""
    import itertools

    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)
    sleeps = []
    monkeypatch.setattr(ai_assistant, "_sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(ai_assistant, "_key_rotation", itertools.count())

    limited = _FakeClient([_rate_limit_error()])
    working = _FakeClient([_text_completion("ok")])
    monkeypatch.setattr(ai_assistant, "_clients", lambda: [limited, working])

    result = ai_assistant._create_completion(model="x", messages=[])

    assert result.choices[0].message.content == "ok"
    assert limited.completions.calls == 1
    assert sleeps == []


def test_create_completion_raises_when_every_key_is_exhausted(monkeypatch):
    import itertools

    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)
    monkeypatch.setattr(ai_assistant, "_sleep", lambda _s: None)
    monkeypatch.setattr(ai_assistant, "_key_rotation", itertools.count())
    from groq import RateLimitError

    key_a = _FakeClient([_rate_limit_error()])
    key_b = _FakeClient([_rate_limit_error()])
    monkeypatch.setattr(ai_assistant, "_clients", lambda: [key_a, key_b])

    with pytest.raises(RateLimitError):
        ai_assistant._create_completion(model="x", messages=[])


# --- _complete() malformed-response reliability --------------------------------


def test_complete_handles_none_content_without_crashing(monkeypatch):
    """RELIABILITY: a completion shaped for tool use (or a provider quirk)
    can carry content=None even on a tools-free call — must not crash."""
    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)
    monkeypatch.setattr(ai_assistant, "_create_completion", lambda **_: _text_completion(None))

    result = ai_assistant._complete([{"role": "user", "content": "hi"}], temperature=0.4, max_tokens=100)

    assert result == ""


def test_complete_handles_empty_choices_without_crashing(monkeypatch):
    class _EmptyCompletion:
        choices: list = []

    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)
    monkeypatch.setattr(ai_assistant, "_create_completion", lambda **_: _EmptyCompletion())

    result = ai_assistant._complete([{"role": "user", "content": "hi"}], temperature=0.4, max_tokens=100)

    assert result == ""


def test_general_reply_handles_empty_choices_without_crashing(monkeypatch):
    class _EmptyCompletion:
        choices: list = []

    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)
    monkeypatch.setattr(ai_assistant, "_create_completion", lambda **_: _EmptyCompletion())

    content, blocks, selected_project_id, selected_idea = ai_assistant.general_reply("hello")

    assert content == ""
    assert blocks == []
    assert selected_project_id is None
    assert selected_idea is None


def test_general_reply_raises_when_assistant_not_configured(monkeypatch):
    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", False)
    with pytest.raises(ai_assistant.AssistantUnavailable):
        ai_assistant.general_reply("hello")


def test_general_reply_returns_final_text_with_no_tool_calls(monkeypatch):
    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)
    monkeypatch.setattr(ai_assistant, "_create_completion", lambda **_: _text_completion("Hi there!"))

    content, blocks, selected_project_id, selected_idea = ai_assistant.general_reply("hello")

    assert content == "Hi there!"
    assert blocks == []
    assert selected_project_id is None
    assert selected_idea is None


def test_general_reply_bounds_the_tool_calling_loop(monkeypatch):
    """RELIABILITY: a model that never stops requesting tools must not hang
    the turn — the loop is capped at MAX_TOOL_ROUNDS and always returns."""
    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)
    calls = {"n": 0}

    def always_wants_a_tool(**_):
        calls["n"] += 1
        # Always requests get_project_details, forever, with valid arguments —
        # a model that never converges to a final answer within budget.
        return _tool_call_completion("get_project_details", '{"project_id": "does-not-exist"}')

    monkeypatch.setattr(ai_assistant, "_create_completion", always_wants_a_tool)

    content, blocks, selected_project_id, selected_idea = ai_assistant.general_reply("find me something")

    assert calls["n"] == ai_assistant.MAX_TOOL_ROUNDS
    assert content == ""  # final round returns whatever text is present — none was ever given
    assert selected_project_id is None
    assert selected_idea is None


def test_general_reply_survives_malformed_tool_call_arguments(monkeypatch):
    """RELIABILITY: the model can emit non-JSON tool arguments; this must not
    raise, just fall back to an empty argument dict for that call."""
    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)
    responses = iter(
        [
            _tool_call_completion("get_project_details", "{not valid json"),
            _text_completion("Here's what I found."),
        ]
    )
    monkeypatch.setattr(ai_assistant, "_create_completion", lambda **_: next(responses))

    content, _blocks, _pid, _idea = ai_assistant.general_reply("tell me about it")

    assert content == "Here's what I found."


def test_general_reply_survives_an_unknown_tool_call(monkeypatch):
    """RELIABILITY: the assistant must never crash because the model
    requested a tool name that doesn't exist — chat_tools.call_tool already
    turns that into an {'error': ...} result; general_reply must pass it
    through as a normal tool result rather than raising."""
    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)
    responses = iter(
        [
            _tool_call_completion("not_a_real_tool", "{}"),
            _text_completion("Sorry, I can't do that."),
        ]
    )
    monkeypatch.setattr(ai_assistant, "_create_completion", lambda **_: next(responses))

    content, blocks, _pid, _idea = ai_assistant.general_reply("do the impossible thing")

    assert content == "Sorry, I can't do that."
    assert blocks == []


def test_general_reply_survives_a_tool_raising(monkeypatch):
    """RELIABILITY: a bug or transient failure inside a specific tool must
    degrade to an error result for that call, not crash the whole turn."""
    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)

    def boom(_name, _arguments):
        raise RuntimeError("boom")

    monkeypatch.setattr(chat_tools, "call_tool", boom)
    responses = iter(
        [
            _tool_call_completion("search_projects", '{"query": "nlp"}'),
            _text_completion("Something went wrong, but I'm still here."),
        ]
    )
    monkeypatch.setattr(ai_assistant, "_create_completion", lambda **_: next(responses))

    content, _blocks, _pid, _idea = ai_assistant.general_reply("find nlp projects")

    assert content == "Something went wrong, but I'm still here."


def test_general_reply_select_project_sets_selection_and_surfaces_a_block(monkeypatch, project):
    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)
    responses = iter(
        [
            _tool_call_completion("select_project", f'{{"project_id": "{project["project_id"]}"}}'),
            _text_completion("Great choice!"),
        ]
    )
    monkeypatch.setattr(ai_assistant, "_create_completion", lambda **_: next(responses))

    content, blocks, selected_project_id, selected_idea = ai_assistant.general_reply(
        "let's build the diagnosis one"
    )

    assert content == "Great choice!"
    assert selected_project_id == project["project_id"]
    assert selected_idea is None
    assert any(b["type"] == "project_selected" for b in blocks)


def test_general_reply_select_idea_sets_selection_and_clears_selected_project(monkeypatch, project):
    """A generated idea and a catalogue project are mutually exclusive active
    build targets — selecting an idea mid-turn must clear whatever project
    was previously selected, exactly like select_project clears an idea."""
    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)
    responses = iter(
        [
            _tool_call_completion("select_idea", f'{{"id": "idea-2", "name": "{IDEA["name"]}"}}'),
            _text_completion("Let's build it."),
        ]
    )
    monkeypatch.setattr(ai_assistant, "_create_completion", lambda **_: next(responses))

    content, blocks, selected_project_id, selected_idea = ai_assistant.general_reply(
        "let's build the notes idea instead",
        selected_project_id=project["project_id"],
    )

    assert content == "Let's build it."
    assert selected_project_id is None
    assert selected_idea is not None
    assert selected_idea["name"] == IDEA["name"]
    assert any(b["type"] == "idea_selected" for b in blocks)


def test_general_reply_switching_from_project_a_to_project_b_updates_the_selection(monkeypatch, mongo_test_db):
    """Selecting a second project mid-conversation must replace the first as
    the mentor's active context, not merge or ignore it — the same
    single-active-target rule select_idea already gets tested for above."""
    project_a = {**PROJECT, "project_id": "pm-a", "title": "Project A"}
    project_b = {**PROJECT, "project_id": "pm-b", "title": "Project B"}
    db.projects().insert_many([project_a, project_b])

    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)
    responses = iter(
        [
            _tool_call_completion("select_project", f'{{"project_id": "{project_b["project_id"]}"}}'),
            _text_completion("Switched to Project B."),
        ]
    )
    monkeypatch.setattr(ai_assistant, "_create_completion", lambda **_: next(responses))

    content, blocks, selected_project_id, selected_idea = ai_assistant.general_reply(
        "actually let's build project B instead", selected_project_id=project_a["project_id"]
    )

    assert content == "Switched to Project B."
    assert selected_project_id == project_b["project_id"]
    assert selected_idea is None
    selected_block = next(b for b in blocks if b["type"] == "project_selected")
    assert selected_block["project"]["project_id"] == project_b["project_id"]


def test_general_reply_threads_the_active_project_note_into_the_user_message(monkeypatch, project):
    """Mirrors the active-idea-note threading test below, for a selected
    CATALOGUE project — this is what lets 'how should I build the backend?'
    ground into the project's own description/technologies/skills without
    the student repeating them, per the enriched _active_project_note above."""
    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)
    captured = {}

    def capture(**kwargs):
        captured["messages"] = kwargs["messages"]
        return _text_completion("Use Flask for the backend.")

    monkeypatch.setattr(ai_assistant, "_create_completion", capture)

    ai_assistant.general_reply("how should I build the backend?", selected_project_id=project["project_id"])

    last_user_message = captured["messages"][-1]["content"]
    assert project["title"] in last_user_message
    assert project["description"] in last_user_message
    assert "active project" in last_user_message


def test_general_reply_threads_the_active_idea_note_into_the_user_message(monkeypatch):
    """The selected idea's context note must actually reach the model — this
    is what lets 'how should I build the backend?' ground into a selected
    idea instead of only ever working for a selected catalogue project."""
    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)
    captured = {}

    def capture(**kwargs):
        captured["messages"] = kwargs["messages"]
        return _text_completion("Use FastAPI for the backend.")

    monkeypatch.setattr(ai_assistant, "_create_completion", capture)

    ai_assistant.general_reply("how should I build the backend?", selected_idea=IDEA)

    last_user_message = captured["messages"][-1]["content"]
    assert IDEA["name"] in last_user_message
    assert "active idea" in last_user_message


def test_general_reply_threads_the_resume_context_note_into_the_user_message(monkeypatch):
    """The résumé-skills context note must actually reach the model — this is
    what lets 'which project fits me best?' work off a résumé uploaded
    earlier in the conversation without the student repeating their skills."""
    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)
    captured = {}

    def capture(**kwargs):
        captured["messages"] = kwargs["messages"]
        return _text_completion("You already know Python and React.")

    monkeypatch.setattr(ai_assistant, "_create_completion", capture)

    ai_assistant.general_reply("which project fits me best?", resume_skills=["Python", "React"])

    last_user_message = captured["messages"][-1]["content"]
    assert "Python" in last_user_message
    assert "React" in last_user_message
    assert "résumé skills" in last_user_message


# --- History-shrink retry on a persistent 413 (reply() / general_reply()) ----
#
# RELIABILITY: _create_completion's own 413 handling rotates across
# configured KEYS, but that has nothing left to try once every key alike
# rejects a request as too large — the fix at that point is a smaller
# REQUEST, not a different key. These verify reply() and general_reply()
# retry the turn with a shrinking history window (_HISTORY_SHRINK_STEPS)
# instead of surfacing "conversation grown too large" on the first 413, so a
# student can keep chatting in the SAME conversation whenever a smaller
# request would actually have fit the budget.


def test_reply_shrinks_history_and_retries_when_every_key_rejects_as_too_large(monkeypatch):
    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)
    calls = []

    def flaky(**kwargs):
        calls.append(kwargs["messages"])
        if len(calls) < len(ai_assistant._HISTORY_SHRINK_STEPS):
            raise _request_too_large_error()
        return _text_completion("Still here.")

    monkeypatch.setattr(ai_assistant, "_create_completion", flaky)

    history = [{"role": "user", "content": f"turn {i}"} for i in range(20)]
    result = ai_assistant.reply({"title": "P"}, "hello", history)

    assert result == "Still here."
    # One attempt per shrink step until the last one succeeds.
    assert len(calls) == len(ai_assistant._HISTORY_SHRINK_STEPS)
    lengths = [len(m) for m in calls]
    assert lengths[0] > lengths[1] > lengths[2] > lengths[3]
    assert lengths[-1] == 2  # system message + this turn's user message only


def test_reply_raises_immediately_on_a_non_413_error(monkeypatch):
    """A rate-limit failure (already exhausted every key inside
    _create_completion) is not a 'too large' problem — shrinking history
    cannot fix it, so it must propagate on the very first attempt, not after
    burning through every shrink step first."""
    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)
    from groq import RateLimitError

    calls = {"n": 0}

    def always_rate_limited(**_):
        calls["n"] += 1
        raise _rate_limit_error()

    monkeypatch.setattr(ai_assistant, "_create_completion", always_rate_limited)

    with pytest.raises(RateLimitError):
        ai_assistant.reply({"title": "P"}, "hello", [])

    assert calls["n"] == 1


def test_reply_raises_the_413_once_shrinking_to_zero_history_still_fails(monkeypatch):
    """Genuine floor: the fixed system-prompt overhead alone outgrows the
    budget, so no amount of history-shrinking can help — must still surface
    as the honest 413, not retry forever."""
    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)
    from groq import APIStatusError

    calls = {"n": 0}

    def always_too_large(**_):
        calls["n"] += 1
        raise _request_too_large_error()

    monkeypatch.setattr(ai_assistant, "_create_completion", always_too_large)

    with pytest.raises(APIStatusError) as excinfo:
        ai_assistant.reply({"title": "P"}, "hello", [])

    assert excinfo.value.status_code == 413
    # Empty history collapses every shrink step to the same 0-history
    # request (see _effective_shrink_steps) — one honest attempt, not four
    # identical, doomed ones.
    assert calls["n"] == 1


def test_general_reply_shrinks_history_and_retries_the_whole_turn_on_a_413(monkeypatch):
    """The Dashboard chat's tool-calling turn (GROQ_TOOL_MODEL) is the exact
    scenario reported live: several batches of generated ideas pushed one
    conversation's request past the account's tokens-per-minute budget. This
    must now recover in the same conversation rather than forcing a new one."""
    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)
    calls = []

    def flaky(**kwargs):
        calls.append(kwargs["messages"])
        if len(calls) < len(ai_assistant._HISTORY_SHRINK_STEPS):
            raise _request_too_large_error()
        return _text_completion("Still here, with tools available.")

    monkeypatch.setattr(ai_assistant, "_create_completion", flaky)

    history = [{"role": "user", "content": f"turn {i}"} for i in range(20)]
    content, blocks, selected_project_id, selected_idea = ai_assistant.general_reply("hello", history)

    assert content == "Still here, with tools available."
    assert blocks == []
    assert selected_project_id is None
    assert selected_idea is None
    assert len(calls) == len(ai_assistant._HISTORY_SHRINK_STEPS)
    lengths = [len(m) for m in calls]
    assert lengths[0] > lengths[1] > lengths[2] > lengths[3]


def test_general_reply_raises_the_413_once_shrinking_to_zero_history_still_fails(monkeypatch):
    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)
    from groq import APIStatusError

    calls = {"n": 0}

    def always_too_large(**_):
        calls["n"] += 1
        raise _request_too_large_error()

    monkeypatch.setattr(ai_assistant, "_create_completion", always_too_large)

    with pytest.raises(APIStatusError) as excinfo:
        ai_assistant.general_reply("hello", [{"role": "user", "content": "hi"}])

    assert excinfo.value.status_code == 413
    # 1 history message: steps 12/6/3 are all identical to "keep the one
    # message" (no dedup benefit lost) — only the trailing 0-history step
    # differs, so exactly 2 distinct attempts, not 4.
    assert calls["n"] == 2


# --- _effective_shrink_steps: skip retries that can't possibly help --------
#
# RELIABILITY (wasted latency, reported live): a short conversation can
# already be too large purely on the fixed system-prompt/tool-schema
# overhead plus one context-bearing turn. Without deduping, a student who
# just generated a batch of ideas and immediately asked a follow-up (2
# stored messages) would pay for THREE identical, doomed attempts (caps 12,
# 6, 3 all equal "keep both messages") before ever reaching the one cap (0)
# that changes anything — real added wall-clock time on a turn that was
# always going to need the last-resort step, observed live as the "Create a
# roadmap" follow-up itself timing out.


def test_effective_shrink_steps_dedupes_when_history_is_shorter_than_every_cap():
    assert ai_assistant._effective_shrink_steps(2) == (2, 0)


def test_effective_shrink_steps_dedupes_partial_overlap():
    # 5 history messages: caps 12 and 6 both collapse to "keep all 5"; cap 3
    # and cap 0 each still cut something further.
    assert ai_assistant._effective_shrink_steps(5) == (5, 3, 0)


def test_effective_shrink_steps_collapses_to_one_step_for_empty_history():
    assert ai_assistant._effective_shrink_steps(0) == (0,)


def test_effective_shrink_steps_keeps_every_step_for_a_long_history():
    # Unchanged behaviour for the case _HISTORY_SHRINK_STEPS was designed
    # for: a long-running conversation where every cap genuinely trims more.
    assert ai_assistant._effective_shrink_steps(20) == ai_assistant._HISTORY_SHRINK_STEPS


def test_reply_skips_redundant_shrink_attempts_on_a_short_history(monkeypatch):
    """LATENCY: a 2-message history must not retry 4 times when only 2
    distinct request sizes are possible — each wasted attempt is a real
    network round trip the student is waiting on."""
    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)
    calls = {"n": 0}

    def always_too_large(**_):
        calls["n"] += 1
        raise _request_too_large_error()

    monkeypatch.setattr(ai_assistant, "_create_completion", always_too_large)

    history = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
    from groq import APIStatusError

    with pytest.raises(APIStatusError):
        ai_assistant.reply({"title": "P"}, "hello", history)

    assert calls["n"] == 2  # (2, 0), not the full (12, 6, 3, 0)
