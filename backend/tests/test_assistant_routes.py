"""Tests for the persistence contract routes/assistant.py exposes over HTTP —
conversation CRUD, chat history, structured-block persistence, selected-
project/idea persistence, and résumé-context persistence. general_reply()'s
own tool-calling orchestration is already covered against a fake Groq client
in test_ai_assistant.py; these tests instead exercise the HTTP layer around
it — the part that actually reads/writes Mongo, enforces device ownership,
and is what a page refresh or a reopened conversation depends on.

A Flask test client is the right tool here (not a direct service-layer call,
the pattern the rest of this suite uses) because, unlike teams/service.py or
auth/service.py, there is no separate service module: the persistence logic
under test — ownership checks, the $push/$slice history update, which fields
get $set — lives directly in the route functions themselves.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from db import client as db
from nlp import ai_assistant

DEVICE_A = "device-aaaaaaaa"
DEVICE_B = "device-bbbbbbbb"

PROJECT = {
    "project_id": "pm-route-001",
    "title": "AI-Powered Medical Diagnosis Assistant",
    "description": "A clinical decision support system that predicts likely conditions.",
    "domain": "Artificial Intelligence",
    "difficulty": "Advanced",
    "technologies": ["Python", "scikit-learn", "Flask"],
    "skills": ["Supervised learning", "REST API development"],
    "duration_weeks": 12,
}

IDEA_ARGS = {
    "id": "idea-2",
    "name": "Smart Campus Notes",
    "problem": "Students lose track of scattered lecture notes.",
    "solution": "A unifying, searchable notes hub with AI summaries.",
}


def _hdr(device: str) -> dict[str, str]:
    return {"X-Device-Id": device}


@pytest.fixture
def project(mongo_test_db):
    db.projects().insert_one(dict(PROJECT))
    return PROJECT


@pytest.fixture(autouse=True)
def assistant_enabled(monkeypatch):
    # Every test in this file that reaches the LLM mocks _create_completion
    # directly (see the fakes below) — this just satisfies general_reply()'s
    # own "is the assistant configured at all" gate so that mock is reached,
    # independent of whether a real GROQ_API_KEY happens to be set in this
    # environment's .env.
    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)


# --- fake Groq completions, same shape as test_ai_assistant.py ---------------


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


def _create_conversation(client, device=DEVICE_A) -> str:
    resp = client.post("/api/conversations", headers=_hdr(device))
    assert resp.status_code == 201
    return resp.get_json()["data"]["conversation_id"]


def _seed_recommendations_turn(conversation_id: str) -> None:
    """Simulate an earlier turn that already showed catalogue projects —
    written straight to Mongo the same shape send_conversation_message
    itself would produce, so tests can exercise "does a reload/second turn
    correctly thread this back in" without depending on the real hybrid
    search index being built for a throwaway test project."""
    now = datetime.now(timezone.utc)
    block = {
        "type": "project_recommendations",
        "projects": [
            {"project_id": "pm-shown-1", "title": "First Shown", "difficulty": "Beginner", "technologies": ["Python"]},
            {"project_id": PROJECT["project_id"], "title": PROJECT["title"], "difficulty": PROJECT["difficulty"], "technologies": PROJECT["technologies"]},
        ],
    }
    db.conversations().update_one(
        {"conversation_id": conversation_id},
        {
            "$push": {
                "messages": {
                    "$each": [
                        {"role": "user", "content": "show me AI projects", "created_at": now},
                        {"role": "assistant", "content": "Here are two.", "blocks": [block], "created_at": now},
                    ]
                }
            },
            "$set": {"updated_at": now},
        },
    )


# --- conversation CRUD ---------------------------------------------------


def test_create_conversation_starts_empty_with_a_placeholder_title(client):
    resp = client.post("/api/conversations", headers=_hdr(DEVICE_A))
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    assert data["title"] == "New chat"
    assert data["messages"] == []
    assert data["selected_project_id"] is None
    assert data["selected_idea"] is None


def test_created_conversation_appears_in_list_for_the_same_device(client):
    conversation_id = _create_conversation(client)
    resp = client.get("/api/conversations", headers=_hdr(DEVICE_A))
    ids = [row["conversation_id"] for row in resp.get_json()["data"]]
    assert conversation_id in ids


def test_list_conversations_is_isolated_between_devices(client):
    _create_conversation(client, DEVICE_A)
    resp = client.get("/api/conversations", headers=_hdr(DEVICE_B))
    assert resp.get_json()["data"] == []


def test_list_conversations_never_leaks_device_id_or_message_bodies(client):
    _create_conversation(client)
    resp = client.get("/api/conversations", headers=_hdr(DEVICE_A))
    row = resp.get_json()["data"][0]
    assert "device_id" not in row
    assert "messages" not in row


def test_get_conversation_404s_for_a_different_device(client):
    conversation_id = _create_conversation(client, DEVICE_A)
    resp = client.get(f"/api/conversations/{conversation_id}", headers=_hdr(DEVICE_B))
    assert resp.status_code == 404


def test_get_conversation_404s_for_an_unknown_id(client):
    resp = client.get("/api/conversations/does-not-exist", headers=_hdr(DEVICE_A))
    assert resp.status_code == 404


def test_delete_conversation_removes_it(client):
    conversation_id = _create_conversation(client)
    resp = client.delete(f"/api/conversations/{conversation_id}", headers=_hdr(DEVICE_A))
    assert resp.status_code == 200
    assert client.get(f"/api/conversations/{conversation_id}", headers=_hdr(DEVICE_A)).status_code == 404


def test_delete_conversation_404s_for_a_different_device_and_leaves_it_intact(client):
    conversation_id = _create_conversation(client, DEVICE_A)
    resp = client.delete(f"/api/conversations/{conversation_id}", headers=_hdr(DEVICE_B))
    assert resp.status_code == 404
    # The owner's conversation must survive a stranger's failed delete attempt.
    assert client.get(f"/api/conversations/{conversation_id}", headers=_hdr(DEVICE_A)).status_code == 200


def test_create_conversation_requires_a_device_id(client):
    resp = client.post("/api/conversations")
    assert resp.status_code == 400


# --- chat history / message + block persistence ---------------------------


def test_send_message_persists_both_turns(client, monkeypatch):
    conversation_id = _create_conversation(client)
    monkeypatch.setattr(ai_assistant, "_create_completion", lambda **_: _text_completion("Hi there!"))

    resp = client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"message": "hello"},
        headers=_hdr(DEVICE_A),
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["reply"] == "Hi there!"

    doc = client.get(f"/api/conversations/{conversation_id}", headers=_hdr(DEVICE_A)).get_json()["data"]
    assert [m["role"] for m in doc["messages"]] == ["user", "assistant"]
    assert doc["messages"][0]["content"] == "hello"
    assert doc["messages"][1]["content"] == "Hi there!"


def test_send_message_sets_the_title_from_the_first_message_only(client, monkeypatch):
    conversation_id = _create_conversation(client)
    monkeypatch.setattr(ai_assistant, "_create_completion", lambda **_: _text_completion("ok"))

    client.post(f"/api/conversations/{conversation_id}/messages", json={"message": "help me pick a project"}, headers=_hdr(DEVICE_A))
    first_title = client.get(f"/api/conversations/{conversation_id}", headers=_hdr(DEVICE_A)).get_json()["data"]["title"]
    assert first_title == "help me pick a project"

    client.post(f"/api/conversations/{conversation_id}/messages", json={"message": "a second question"}, headers=_hdr(DEVICE_A))
    second_title = client.get(f"/api/conversations/{conversation_id}", headers=_hdr(DEVICE_A)).get_json()["data"]["title"]
    assert second_title == first_title  # unchanged by later turns


def test_send_message_persists_structured_blocks_not_just_text(client, monkeypatch, project):
    conversation_id = _create_conversation(client)
    responses = iter(
        [
            _tool_call_completion("select_project", f'{{"project_id": "{project["project_id"]}"}}'),
            _text_completion("Good pick."),
        ]
    )
    monkeypatch.setattr(ai_assistant, "_create_completion", lambda **_: next(responses))

    client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"message": "let's build the diagnosis one"},
        headers=_hdr(DEVICE_A),
    )

    doc = client.get(f"/api/conversations/{conversation_id}", headers=_hdr(DEVICE_A)).get_json()["data"]
    assistant_turn = doc["messages"][-1]
    assert assistant_turn["blocks"][0]["type"] == "project_selected"
    assert assistant_turn["blocks"][0]["project"]["project_id"] == project["project_id"]


def test_conversation_survives_a_reload_after_a_refresh(client, monkeypatch, project):
    """Simulates the exact scenario section 2/3 of the spec calls out: send a
    turn, then read the conversation back as a brand new GET — as a page
    refresh or reopened tab would — and confirm nothing was lost."""
    conversation_id = _create_conversation(client)
    monkeypatch.setattr(ai_assistant, "_create_completion", lambda **_: _text_completion("Sure, here's how."))
    client.post(f"/api/conversations/{conversation_id}/messages", json={"message": "how do I start?"}, headers=_hdr(DEVICE_A))

    reloaded = client.get(f"/api/conversations/{conversation_id}", headers=_hdr(DEVICE_A)).get_json()["data"]
    assert len(reloaded["messages"]) == 2
    assert reloaded["messages"][1]["content"] == "Sure, here's how."


def test_second_turn_threads_earlier_shown_projects_back_to_the_model(client, monkeypatch):
    """The "second project"/"third idea" follow-up resolution contract: once
    a conversation has a stored project_recommendations block, the very next
    turn's outgoing request to the model must carry the shown-projects
    context note built from Mongo-persisted state, not just in-memory state
    from the same process."""
    conversation_id = _create_conversation(client)
    _seed_recommendations_turn(conversation_id)

    captured = {}

    def capture(**kwargs):
        captured["messages"] = kwargs["messages"]
        return _text_completion("The second one is more advanced.")

    monkeypatch.setattr(ai_assistant, "_create_completion", capture)

    client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"message": "tell me about the second one"},
        headers=_hdr(DEVICE_A),
    )

    # The note is threaded onto the replayed *assistant* turn that originally
    # showed the projects (see nlp/ai_assistant.py:_history_messages), one
    # message before the new user turn — not onto the new message itself.
    replayed_assistant_turn = captured["messages"][-2]
    assert replayed_assistant_turn["role"] == "assistant"
    assert "projects shown above" in replayed_assistant_turn["content"]
    assert PROJECT["project_id"] in replayed_assistant_turn["content"]


def test_generated_ideas_survive_a_reload(client):
    """Same persistence contract as the recommendations test above, for a
    generated_project_ideas block — generated ideas are never written to
    Mongo as their own record (see nlp/ai_assistant.py's _shown_ideas_note
    docstring), so the conversation's own stored blocks are the only place
    they can survive a refresh from."""
    conversation_id = _create_conversation(client)
    now = datetime.now(timezone.utc)
    idea_block = {"type": "generated_project_ideas", "ideas": [{"id": "idea-3", "name": "Third Idea", "problem": "p", "solution": "s"}]}
    db.conversations().update_one(
        {"conversation_id": conversation_id},
        {"$push": {"messages": {"$each": [{"role": "assistant", "content": "Here are 3 ideas.", "blocks": [idea_block], "created_at": now}]}}},
    )

    doc = client.get(f"/api/conversations/{conversation_id}", headers=_hdr(DEVICE_A)).get_json()["data"]
    assert doc["messages"][0]["blocks"][0]["ideas"][0]["name"] == "Third Idea"


# --- selected project / idea persistence -----------------------------------


def test_select_project_tool_call_persists_selection_and_clears_any_idea(client, monkeypatch, project):
    conversation_id = _create_conversation(client)
    db.conversations().update_one({"conversation_id": conversation_id}, {"$set": {"selected_idea": {"name": "Old Idea"}}})

    responses = iter(
        [
            _tool_call_completion("select_project", f'{{"project_id": "{project["project_id"]}"}}'),
            _text_completion("Great choice!"),
        ]
    )
    monkeypatch.setattr(ai_assistant, "_create_completion", lambda **_: next(responses))
    client.post(f"/api/conversations/{conversation_id}/messages", json={"message": "let's build it"}, headers=_hdr(DEVICE_A))

    doc = client.get(f"/api/conversations/{conversation_id}", headers=_hdr(DEVICE_A)).get_json()["data"]
    assert doc["selected_project_id"] == project["project_id"]
    assert doc["selected_idea"] is None


def test_select_idea_tool_call_persists_selection_and_clears_the_project(client, monkeypatch, project):
    conversation_id = _create_conversation(client)
    db.conversations().update_one({"conversation_id": conversation_id}, {"$set": {"selected_project_id": project["project_id"]}})

    responses = iter(
        [
            _tool_call_completion("select_idea", f'{{"id": "{IDEA_ARGS["id"]}", "name": "{IDEA_ARGS["name"]}"}}'),
            _text_completion("Let's build the notes idea."),
        ]
    )
    monkeypatch.setattr(ai_assistant, "_create_completion", lambda **_: next(responses))
    client.post(f"/api/conversations/{conversation_id}/messages", json={"message": "let's build the notes idea instead"}, headers=_hdr(DEVICE_A))

    doc = client.get(f"/api/conversations/{conversation_id}", headers=_hdr(DEVICE_A)).get_json()["data"]
    assert doc["selected_project_id"] is None
    assert doc["selected_idea"]["name"] == IDEA_ARGS["name"]


def test_selection_survives_a_reload_and_grounds_the_next_turn(client, monkeypatch, project):
    """The AI Mentor's core persistence promise: select once, and every later
    turn — including one from a freshly reloaded conversation — is grounded
    in it without the student repeating the project."""
    conversation_id = _create_conversation(client)
    db.conversations().update_one({"conversation_id": conversation_id}, {"$set": {"selected_project_id": project["project_id"]}})

    captured = {}

    def capture(**kwargs):
        captured["messages"] = kwargs["messages"]
        return _text_completion("Use Flask for the backend.")

    monkeypatch.setattr(ai_assistant, "_create_completion", capture)
    client.post(f"/api/conversations/{conversation_id}/messages", json={"message": "how should I build the backend?"}, headers=_hdr(DEVICE_A))

    last_user_message = captured["messages"][-1]["content"]
    assert project["title"] in last_user_message
    assert "active project" in last_user_message


def test_select_project_route_sets_selection_without_an_llm_call(client, project):
    conversation_id = _create_conversation(client)
    resp = client.post(
        f"/api/conversations/{conversation_id}/select-project",
        json={"project_id": project["project_id"]},
        headers=_hdr(DEVICE_A),
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["selected_project_id"] == project["project_id"]

    doc = client.get(f"/api/conversations/{conversation_id}", headers=_hdr(DEVICE_A)).get_json()["data"]
    assert doc["selected_project_id"] == project["project_id"]


def test_select_project_route_404s_for_an_unknown_project(client):
    conversation_id = _create_conversation(client)
    resp = client.post(f"/api/conversations/{conversation_id}/select-project", json={"project_id": "does-not-exist"}, headers=_hdr(DEVICE_A))
    assert resp.status_code == 404


def test_select_project_route_requires_a_project_id(client):
    conversation_id = _create_conversation(client)
    resp = client.post(f"/api/conversations/{conversation_id}/select-project", json={}, headers=_hdr(DEVICE_A))
    assert resp.status_code == 400


def test_selected_project_survives_its_catalogue_project_being_deleted(client, monkeypatch, project):
    """'If the project no longer exists, handle gracefully' — a conversation
    must stay fully usable (readable, still chattable) even after its
    selected project is later removed from the catalogue."""
    conversation_id = _create_conversation(client)
    client.post(f"/api/conversations/{conversation_id}/select-project", json={"project_id": project["project_id"]}, headers=_hdr(DEVICE_A))

    db.projects().delete_one({"project_id": project["project_id"]})

    # Still readable, and still (harmlessly) reports the stale id rather than crashing.
    doc = client.get(f"/api/conversations/{conversation_id}", headers=_hdr(DEVICE_A)).get_json()["data"]
    assert doc["selected_project_id"] == project["project_id"]

    monkeypatch.setattr(ai_assistant, "_create_completion", lambda **_: _text_completion("Let's talk generally."))
    resp = client.post(f"/api/conversations/{conversation_id}/messages", json={"message": "what next?"}, headers=_hdr(DEVICE_A))
    assert resp.status_code == 200


# --- résumé-context persistence --------------------------------------------


def test_attach_resume_skills_persists_and_threads_into_the_next_turn(client, monkeypatch):
    conversation_id = _create_conversation(client)
    resp = client.post(f"/api/conversations/{conversation_id}/resume-skills", json={"skills": ["Python", "React"]}, headers=_hdr(DEVICE_A))
    assert resp.status_code == 200

    doc = client.get(f"/api/conversations/{conversation_id}", headers=_hdr(DEVICE_A)).get_json()["data"]
    assert doc["resume_skills"] == ["Python", "React"]

    captured = {}

    def capture(**kwargs):
        captured["messages"] = kwargs["messages"]
        return _text_completion("You already know Python.")

    monkeypatch.setattr(ai_assistant, "_create_completion", capture)
    client.post(f"/api/conversations/{conversation_id}/messages", json={"message": "which project fits me best?"}, headers=_hdr(DEVICE_A))

    assert "résumé skills" in captured["messages"][-1]["content"]


def test_attach_resume_skills_rejects_a_non_list(client):
    conversation_id = _create_conversation(client)
    resp = client.post(f"/api/conversations/{conversation_id}/resume-skills", json={"skills": "Python"}, headers=_hdr(DEVICE_A))
    assert resp.status_code == 400


def test_attach_resume_skills_rejects_an_all_blank_list(client):
    conversation_id = _create_conversation(client)
    resp = client.post(f"/api/conversations/{conversation_id}/resume-skills", json={"skills": ["  ", ""]}, headers=_hdr(DEVICE_A))
    assert resp.status_code == 400


# --- validation / error handling -------------------------------------------


def test_send_message_rejects_an_empty_message(client):
    conversation_id = _create_conversation(client)
    resp = client.post(f"/api/conversations/{conversation_id}/messages", json={"message": "   "}, headers=_hdr(DEVICE_A))
    assert resp.status_code == 400


def test_send_message_rejects_an_overlong_message(client):
    conversation_id = _create_conversation(client)
    resp = client.post(f"/api/conversations/{conversation_id}/messages", json={"message": "x" * 2001}, headers=_hdr(DEVICE_A))
    assert resp.status_code == 400


def test_send_message_404s_for_an_unknown_conversation(client, monkeypatch):
    monkeypatch.setattr(ai_assistant, "_create_completion", lambda **_: _text_completion("hi"))
    resp = client.post("/api/conversations/does-not-exist/messages", json={"message": "hello"}, headers=_hdr(DEVICE_A))
    assert resp.status_code == 404


def test_project_chat_404s_for_an_unknown_project(client, monkeypatch):
    monkeypatch.setattr(ai_assistant, "_create_completion", lambda **_: _text_completion("hi"))
    resp = client.post("/api/project/does-not-exist/chat", json={"message": "hello"})
    assert resp.status_code == 404


def test_project_chat_returns_503_when_the_assistant_is_not_configured(client, monkeypatch, project):
    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", False)
    resp = client.post(f"/api/project/{project['project_id']}/chat", json={"message": "hello"})
    assert resp.status_code == 503
    assert resp.get_json()["code"] == "LLM_UNAVAILABLE"


def test_project_chat_grounds_replies_in_the_real_project(client, monkeypatch, project):
    monkeypatch.setattr(ai_assistant, "_create_completion", lambda **_: _text_completion("Use scikit-learn as the project already does."))
    resp = client.post(f"/api/project/{project['project_id']}/chat", json={"message": "what ML library should I use?"})
    assert resp.status_code == 200
    assert resp.get_json()["data"]["reply"] == "Use scikit-learn as the project already does."


# --- LLM failure -> HTTP status/code mapping (reliability sections 2/7) -----
#
# Full-stack: a real request through the Flask test client, down through
# reply()/general_reply(), _create_completion()'s retry/rotation, and back
# out through routes/assistant.py's _raise_for_llm_failure — not just the
# service-layer behaviour test_ai_assistant.py already covers in isolation.
# APPLICATION FAILURE (a bug on our side) is deliberately not exercised here
# — every case below is an EXTERNAL SERVICE FAILURE (Groq not configured,
# rate-limited, or erroring), and the point of these tests is that each one
# still produces a clean, typed HTTP response instead of a raw 500.


def _groq_rate_limit_error():
    import httpx
    from groq import RateLimitError

    request = httpx.Request("POST", "https://api.groq.test/openai/v1/chat/completions")
    response = httpx.Response(429, request=request)
    return RateLimitError("rate limited", response=response, body=None)


def _groq_request_too_large_error():
    # Groq's real shape for "this request's tokens exceed the model's
    # tokens-per-minute budget" — a plain APIStatusError at HTTP 413, not
    # RateLimitError, and not something any of the named exception
    # subclasses (BadRequestError, ...) cover — reproduced live against a
    # real over-budget conversation during this investigation.
    import httpx
    from groq import APIStatusError

    request = httpx.Request("POST", "https://api.groq.test/openai/v1/chat/completions")
    response = httpx.Response(413, request=request)
    return APIStatusError("Request too large", response=response, body=None)


def test_project_chat_returns_502_with_llm_error_code_on_an_unexpected_failure(client, monkeypatch, project):
    def boom(**_):
        raise RuntimeError("simulated provider/network failure")

    monkeypatch.setattr(ai_assistant, "_create_completion", boom)
    resp = client.post(f"/api/project/{project['project_id']}/chat", json={"message": "hello"})

    assert resp.status_code == 502
    body = resp.get_json()
    assert body["code"] == "LLM_ERROR"
    assert "error" in body  # existing string-message contract is unchanged


def test_project_chat_returns_502_with_rate_limited_code_when_every_key_is_exhausted(client, monkeypatch, project):
    monkeypatch.setattr(ai_assistant, "_sleep", lambda _s: None)
    monkeypatch.setattr(ai_assistant, "_clients", lambda: [object()])  # one "key"; create() below always 429s

    def always_rate_limited(**_):
        raise _groq_rate_limit_error()

    # _create_completion calls client.chat.completions.create(...) — patch
    # the call site directly rather than building a full fake client, since
    # this test only cares about the HTTP mapping, not the retry mechanics
    # already covered in test_ai_assistant.py.
    monkeypatch.setattr(ai_assistant, "_call_with_retry", lambda _client, _kwargs: always_rate_limited())

    resp = client.post(f"/api/project/{project['project_id']}/chat", json={"message": "hello"})

    assert resp.status_code == 502
    assert resp.get_json()["code"] == "LLM_RATE_LIMITED"


def test_project_chat_returns_context_too_large_code_on_a_413(client, monkeypatch, project):
    """RELIABILITY: a request-too-large failure must be told apart from a
    flaky rate limit — "wait and retry" is actively wrong advice for it (the
    retried request is identically oversized and fails identically), so it
    gets its own code and an honest "start a new chat" message instead."""
    monkeypatch.setattr(ai_assistant, "_sleep", lambda _s: None)
    monkeypatch.setattr(ai_assistant, "_clients", lambda: [object()])

    def always_too_large(**_):
        raise _groq_request_too_large_error()

    monkeypatch.setattr(ai_assistant, "_call_with_retry", lambda _client, _kwargs: always_too_large())

    resp = client.post(f"/api/project/{project['project_id']}/chat", json={"message": "hello"})

    assert resp.status_code == 502
    body = resp.get_json()
    assert body["code"] == "LLM_CONTEXT_TOO_LARGE"
    assert body["code"] != "LLM_RATE_LIMITED"
    assert "start a new chat" in body["error"]


def test_send_message_returns_503_with_llm_unavailable_code_when_not_configured(client, monkeypatch):
    conversation_id = _create_conversation(client)
    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", False)

    resp = client.post(
        f"/api/conversations/{conversation_id}/messages", json={"message": "hello"}, headers=_hdr(DEVICE_A)
    )

    assert resp.status_code == 503
    assert resp.get_json()["code"] == "LLM_UNAVAILABLE"


def test_send_message_returns_502_with_llm_error_code_on_an_unexpected_failure(client, monkeypatch):
    conversation_id = _create_conversation(client)

    def boom(**_):
        raise RuntimeError("simulated provider/network failure")

    monkeypatch.setattr(ai_assistant, "_create_completion", boom)
    resp = client.post(
        f"/api/conversations/{conversation_id}/messages", json={"message": "hello"}, headers=_hdr(DEVICE_A)
    )

    assert resp.status_code == 502
    body = resp.get_json()
    assert body["code"] == "LLM_ERROR"
    assert "error" in body


def test_conversation_is_still_readable_and_unmodified_after_a_failed_turn(client, monkeypatch):
    """RELIABILITY: an LLM failure must not corrupt or partially write the
    conversation — the failed turn is never persisted, so a retry starts
    from exactly the same state as before the failure."""
    conversation_id = _create_conversation(client)

    def boom(**_):
        raise RuntimeError("simulated provider/network failure")

    monkeypatch.setattr(ai_assistant, "_create_completion", boom)
    resp = client.post(
        f"/api/conversations/{conversation_id}/messages", json={"message": "hello"}, headers=_hdr(DEVICE_A)
    )
    assert resp.status_code == 502

    doc = client.get(f"/api/conversations/{conversation_id}", headers=_hdr(DEVICE_A)).get_json()["data"]
    assert doc["messages"] == []
    assert doc["title"] == "New chat"

    # A subsequent, successful turn works normally — the earlier failure
    # left no residue behind to interfere with it.
    monkeypatch.setattr(ai_assistant, "_create_completion", lambda **_: _text_completion("Hi there!"))
    resp = client.post(
        f"/api/conversations/{conversation_id}/messages", json={"message": "hello"}, headers=_hdr(DEVICE_A)
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["reply"] == "Hi there!"
