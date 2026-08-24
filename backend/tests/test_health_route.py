"""HTTP-level test for GET /api/health — the route wiring itself (does the
response include what app.py promises, does a bad AI model_status leave the
rest of the health check unaffected), not model_status()'s own reachability
logic, which test_ai_assistant.py already covers directly against a fake
Groq client.
"""

from __future__ import annotations

from db import client as db
from nlp import ai_assistant, recommend


def test_health_reports_ai_model_and_tool_model_names(client, monkeypatch):
    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)
    monkeypatch.setattr(ai_assistant, "model_status", lambda: {"reachable": True, "missing_models": []})

    body = client.get("/api/health").get_json()

    assert body["ai_assistant"]["model"] == ai_assistant.config.GROQ_MODEL
    assert body["ai_assistant"]["tool_model"] == ai_assistant.config.GROQ_TOOL_MODEL
    assert body["ai_assistant"]["model_status"] == {"reachable": True, "missing_models": []}


def test_health_ai_section_is_none_when_the_assistant_is_not_configured(client, monkeypatch):
    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", False)

    body = client.get("/api/health").get_json()

    assert body["ai_assistant"]["enabled"] is False
    assert body["ai_assistant"]["model"] is None
    assert body["ai_assistant"]["tool_model"] is None
    assert body["ai_assistant"]["model_status"] is None


def test_health_stays_ok_even_when_the_ai_model_is_unreachable(client, monkeypatch):
    """A Groq-side outage or a dead model must not report the whole app
    degraded — every other feature works without the assistant; see
    nlp/ai_assistant.py's own module docstring."""
    # Forces app.py's own `healthy` formula to True regardless of the AI
    # section, so this test asserts something real rather than being
    # conditional on the throwaway test database's contents.
    db.projects().insert_one({"project_id": "pm-health-route-001", "title": "Health check fixture"})
    monkeypatch.setattr(ai_assistant.config, "AI_ASSISTANT_ENABLED", True)
    monkeypatch.setattr(
        ai_assistant, "model_status", lambda: {"reachable": False, "error": "model not found"}
    )

    response = client.get("/api/health")
    body = response.get_json()

    assert body["ai_assistant"]["model_status"]["reachable"] is False
    assert body["status"] == "ok"
    assert response.status_code == 200


# --- search_index staleness (§10) ------------------------------------------
#
# recommend.get_retriever() is monkeypatched to a small fake rather than the
# real process-wide singleton — that singleton is a real, cached, expensive
# object shared with every other test in this suite, and its actual id count
# depends on which test happened to build it first (see
# test_search_routes.py's own module docstring on this exact pitfall).
# Faking it here makes the comparison in app.py deterministic instead of
# accidentally depending on suite-wide execution order.


class _FakeRetriever:
    def __init__(self, ids):
        self.ids = ids


def test_health_reports_stale_when_mongo_outnumbers_the_index(client, monkeypatch):
    db.projects().insert_many(
        [{"project_id": f"pm-stale-{i}"} for i in range(3)]
    )  # 3 in Mongo, only 1 indexed below
    monkeypatch.setattr(recommend, "get_retriever", lambda: _FakeRetriever(["pm-stale-0"]))

    body = client.get("/api/health").get_json()

    assert body["search_index"]["indexed_projects"] == 1
    assert body["mongodb"]["projects"] == 3
    assert body["search_index"]["stale"] is True


def test_health_reports_not_stale_when_counts_agree(client, monkeypatch):
    db.projects().insert_many([{"project_id": "pm-fresh-0"}, {"project_id": "pm-fresh-1"}])
    monkeypatch.setattr(recommend, "get_retriever", lambda: _FakeRetriever(["pm-fresh-0", "pm-fresh-1"]))

    body = client.get("/api/health").get_json()

    assert body["search_index"]["indexed_projects"] == 2
    assert body["mongodb"]["projects"] == 2
    assert body["search_index"]["stale"] is False


def test_health_staleness_is_unknown_rather_than_false_when_the_retriever_is_unavailable(client, monkeypatch):
    """A broken/unbuilt retriever must not crash the health endpoint, and
    must not be misreported as "not stale" — None means "couldn't check",
    a real, distinct answer from "checked, and it's fine"."""
    def _boom():
        raise FileNotFoundError("index not built")

    monkeypatch.setattr(recommend, "get_retriever", _boom)

    body = client.get("/api/health").get_json()

    assert body["search_index"]["indexed_projects"] is None
    assert body["search_index"]["stale"] is False  # indexed_count is None -> not asserted stale
