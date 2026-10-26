"""AI chat assistant endpoints — the one blueprint that calls an external LLM.

Rate-limited (unlike most routes in this app) because, unlike the rest of the
API, each call here has a real external cost against the operator's Groq
quota — see nlp/ai_assistant.py for why this is the one place that trade-off
exists at all.

Two shapes of chat live here:
- POST /project/<id>/chat — the project-grounded widget. Stateless on the
  server, exactly like every other endpoint in this app: the frontend resends
  the conversation each turn, keyed on nothing but the project id in the URL.
- /conversations... — the full-page general assistant. Unlike the rest of
  this app it *does* keep server-side state (one document per conversation),
  because a ChatGPT-style history list needs something to list — but it's
  still keyed on the anonymous X-Device-Id header, not an account, the same
  identity model as favourites/history.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from flask import Blueprint, request

import config
from db import client as db
from extensions import limiter
from nlp import decision_center
from nlp.ai_assistant import AssistantUnavailable, general_reply, reply
from routes.helpers import ApiError, current_user, device_id, json_body, ok

bp = Blueprint("assistant", __name__, url_prefix="/api")


def _validate_message(body: dict) -> str:
    message = (body.get("message") or "").strip()
    if not message:
        raise ApiError("'message' is required.", status=400)
    if len(message) > 2000:
        raise ApiError("'message' must be 2000 characters or fewer.", status=400)
    return message


def _raise_for_llm_failure(error: Exception) -> None:
    """Turn any exception raised out of reply()/general_reply() into a clean
    ApiError, with a stable `code` for callers that want to branch on *why*
    without parsing `message` — the one place this mapping lives, reused by
    both chat surfaces below rather than duplicated per route.

    Always raises; never returns. Existing `message`/`status` values are
    unchanged from before `code` existed, so this is purely additive.
    """
    if isinstance(error, AssistantUnavailable):
        raise ApiError(
            "AI assistant is not configured. Set GROQ_API_KEY in backend/.env to enable it.",
            status=503,
            code="LLM_UNAVAILABLE",
        ) from None

    from groq import APIStatusError, RateLimitError

    if isinstance(error, RateLimitError):
        # Every configured Groq key (see nlp/ai_assistant.py:_create_completion)
        # was still rate-limited after rotating through all of them — a real,
        # distinguishable failure mode from a generic provider/network error,
        # even though both currently answer with the same 502 (retryable).
        raise ApiError(
            "The AI assistant is receiving too many requests right now — try again shortly.",
            status=502,
            code="LLM_RATE_LIMITED",
        ) from None

    if isinstance(error, APIStatusError) and getattr(error, "status_code", None) == 413:
        # Groq's own "request too large for this model's tokens-per-minute
        # budget" response — a long conversation (or one that's generated
        # several batches of ideas) plus the assistant's own system prompt
        # and tool schemas together outgrew it. Deliberately NOT labelled
        # LLM_RATE_LIMITED: that code tells the frontend "wait a few seconds
        # and silently retry" (see api.js), which is actively wrong here —
        # retrying resends this exact same oversized request and fails
        # identically every time. The only real fix is a smaller request, so
        # the honest answer is "start a new chat," not "try again."
        raise ApiError(
            "This conversation has grown too large for the assistant to process in one go — "
            "start a new chat to continue.",
            status=502,
            code="LLM_CONTEXT_TOO_LARGE",
        ) from None

    raise ApiError(
        "The AI assistant could not respond right now — try again.", status=502, code="LLM_ERROR"
    ) from None


@bp.post("/project/<project_id>/chat")
@limiter.limit("20 per hour")
def chat(project_id: str):
    """Body: {message, history?: [{role: 'user'|'assistant', content}]}"""
    body = json_body()
    message = _validate_message(body)
    history = body.get("history") or []
    if not isinstance(history, list):
        raise ApiError("'history' must be a list.", status=400)

    doc = db.projects().find_one({"project_id": project_id}, {"_id": 0})
    if doc is None:
        raise ApiError(f"No project with id '{project_id}'.", status=404)

    try:
        answer = reply(doc, message, history)
    except Exception as error:  # noqa: BLE001
        _raise_for_llm_failure(error)

    return ok({"reply": answer})


def _serialize(doc: dict, *, with_messages: bool) -> dict:
    payload = {
        "conversation_id": doc["conversation_id"],
        "title": doc["title"],
        "selected_project_id": doc.get("selected_project_id"),
        "selected_idea": doc.get("selected_idea"),
        "resume_skills": doc.get("resume_skills") or [],
        "created_at": doc["created_at"].isoformat(),
        "updated_at": doc["updated_at"].isoformat(),
    }
    if with_messages:
        payload["messages"] = [
            {
                "role": m["role"],
                "content": m["content"],
                # Only present on an assistant turn that recommended
                # projects — see nlp/ai_assistant.py:general_reply. Omitted
                # rather than an empty list so the frontend's "does this
                # message have cards" check is a plain truthiness check.
                **({"blocks": m["blocks"]} if m.get("blocks") else {}),
                "created_at": m["created_at"].isoformat(),
            }
            for m in doc["messages"]
        ]
    return payload


def _ownership_filter() -> dict:
    """Who a conversation belongs to.

    Signed-in callers own conversations by account (user_id), so the sidebar's
    history follows them across devices and survives sign-out/sign-in — a
    fresh browser (or one that rotated its device id at a previous sign-out,
    see api.js:rotateDeviceId) used to mean "No conversations yet." even for
    a returning, authenticated user, since chat_conversations was keyed only
    on the anonymous X-Device-Id header, same as favourites/history. Anonymous
    callers still own by device_id, unchanged from before accounts existed.
    """
    user = current_user(required=False)
    if user:
        return {"user_id": user["user_id"]}
    return {"device_id": device_id()}


def _owned_conversation(conversation_id: str) -> dict:
    doc = db.conversations().find_one(
        {"conversation_id": conversation_id, **_ownership_filter()}, {"_id": 0}
    )
    if doc is None:
        raise ApiError(f"No conversation with id '{conversation_id}'.", status=404)
    return doc


@bp.get("/conversations")
def list_conversations():
    rows = (
        db.conversations()
        .find(_ownership_filter(), {"_id": 0, "messages": 0, "device_id": 0, "user_id": 0})
        .sort("updated_at", -1)
        .limit(config.MAX_CONVERSATIONS_PER_DEVICE)
    )
    payload = [
        {**row, "created_at": row["created_at"].isoformat(), "updated_at": row["updated_at"].isoformat()}
        for row in rows
    ]
    return ok(payload, count=len(payload))


@bp.post("/conversations")
def create_conversation():
    caller = device_id()
    user = current_user(required=False)
    now = datetime.now(timezone.utc)
    doc = {
        "conversation_id": uuid.uuid4().hex,
        "device_id": caller,
        # None for an anonymous chat — see _ownership_filter().
        "user_id": user["user_id"] if user else None,
        "title": "New chat",
        "messages": [],
        "created_at": now,
        "updated_at": now,
    }
    db.conversations().insert_one(doc)
    return ok(_serialize(doc, with_messages=True)), 201


@bp.get("/conversations/<conversation_id>")
def get_conversation(conversation_id: str):
    doc = _owned_conversation(conversation_id)
    return ok(_serialize(doc, with_messages=True))


@bp.get("/conversations/<conversation_id>/decision-center")
def get_decision_center(conversation_id: str):
    """The unified Decision/Action Center for whichever project or idea is
    currently active in this conversation (nlp/decision_center.py). No LLM
    call — every number it returns already comes from the same deterministic
    analyzers the chat tools wrap, just assembled into one response instead
    of several separate chat turns.

    Query: team_size?, experience_level?, target_weeks? — everything else
    (which project/idea, known skills) comes from the conversation's own
    already-persisted context, never re-asked for.
    """
    doc = _owned_conversation(conversation_id)
    project_id = doc.get("selected_project_id")
    idea = doc.get("selected_idea")
    if not project_id and not idea:
        raise ApiError("No project or idea selected in this conversation yet.", status=400)

    result = decision_center.build(
        project_id=project_id,
        idea=idea,
        known_skills=doc.get("resume_skills"),
        team_size=request.args.get("team_size") or None,
        experience_level=request.args.get("experience_level") or None,
        target_weeks=request.args.get("target_weeks") or None,
    )
    if result.get("error"):
        raise ApiError(result["error"], status=404)
    return ok(result)


@bp.delete("/conversations/<conversation_id>")
def delete_conversation(conversation_id: str):
    result = db.conversations().delete_one(
        {"conversation_id": conversation_id, **_ownership_filter()}
    )
    if result.deleted_count == 0:
        raise ApiError(f"No conversation with id '{conversation_id}'.", status=404)
    return ok({"deleted": True})


@bp.post("/conversations/<conversation_id>/messages")
@limiter.limit("30 per hour")
def send_conversation_message(conversation_id: str):
    """Body: {message}. Unlike /project/<id>/chat, history is not re-sent by
    the caller — it's read back from the stored conversation, since this is
    the one chat surface that actually persists one."""
    body = json_body()
    message = _validate_message(body)

    doc = _owned_conversation(conversation_id)
    history = [
        {"role": m["role"], "content": m["content"], "blocks": m.get("blocks")}
        for m in doc["messages"]
    ]

    try:
        answer, blocks, selected_project_id, selected_idea = general_reply(
            message,
            history,
            selected_project_id=doc.get("selected_project_id"),
            selected_idea=doc.get("selected_idea"),
            resume_skills=doc.get("resume_skills"),
            # Resolved from the session token, never from the body or the model:
            # signed-in turns get the read-only personal tools, others do not.
            user=current_user(required=False),
        )
    except Exception as error:  # noqa: BLE001
        _raise_for_llm_failure(error)

    now = datetime.now(timezone.utc)
    assistant_message = {"role": "assistant", "content": answer, "created_at": now}
    if blocks:
        assistant_message["blocks"] = blocks
    new_messages = [
        {"role": "user", "content": message, "created_at": now},
        assistant_message,
    ]

    update = {
        "$push": {
            "messages": {
                "$each": new_messages,
                # Bounds the stored document (and the history replayed on the
                # next turn) even if a conversation runs on indefinitely.
                "$slice": -config.MAX_MESSAGES_PER_CONVERSATION,
            }
        },
        "$set": {"updated_at": now},
    }
    if not doc["messages"]:
        # First turn — replace the placeholder "New chat" title with something
        # that actually distinguishes this conversation in the sidebar.
        title = message if len(message) <= 60 else message[:59].rstrip() + "…"
        update["$set"]["title"] = title
    if selected_project_id != doc.get("selected_project_id"):
        # Only the select_project/select_idea tools change these mid-turn
        # (see nlp/ai_assistant.py) — a normal question leaves them untouched
        # rather than clearing a prior selection. The two are mutually
        # exclusive (general_reply clears one when the other is set), so both
        # are written together whenever either changes.
        update["$set"]["selected_project_id"] = selected_project_id
    if selected_idea != doc.get("selected_idea"):
        update["$set"]["selected_idea"] = selected_idea

    db.conversations().update_one({"conversation_id": conversation_id}, update)

    return ok(
        {
            "reply": answer,
            "blocks": blocks,
            "title": update["$set"].get("title", doc["title"]),
            "selected_project_id": selected_project_id,
            "selected_idea": selected_idea,
        }
    )


@bp.post("/conversations/<conversation_id>/select-project")
def select_project(conversation_id: str):
    """Body: {project_id}. The [Select Project] button's direct path — no LLM
    round-trip needed for a deterministic action; natural-language "select
    this project" still works too, via the select_project tool in a normal
    chat turn (see nlp/ai_assistant.py)."""
    body = json_body()
    project_id = (body.get("project_id") or "").strip()
    if not project_id:
        raise ApiError("'project_id' is required.", status=400)

    _owned_conversation(conversation_id)
    if db.projects().count_documents({"project_id": project_id}, limit=1) == 0:
        raise ApiError(f"No project with id '{project_id}'.", status=404)

    db.conversations().update_one(
        {"conversation_id": conversation_id},
        {
            "$set": {
                "selected_project_id": project_id,
                # Mutually exclusive with an active idea — see
                # nlp/ai_assistant.py:general_reply for the same rule on the
                # natural-language select_project/select_idea tool path.
                "selected_idea": None,
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )
    return ok({"selected_project_id": project_id, "selected_idea": None})


@bp.post("/conversations/<conversation_id>/resume-skills")
def attach_resume_skills(conversation_id: str):
    """Body: {skills}. Attaches skills already detected by /api/resume-suggest
    to this conversation, so chat follow-ups ('which project fits me best',
    'which one needs the fewest new skills', 'what should I learn for the
    second project') can use them without the student re-uploading or
    re-typing their résumé — see nlp/ai_assistant.py's résumé context note
    and nlp/chat_tools.py:match_resume_projects.

    Deliberately takes the already-detected skill list rather than a résumé
    file/text — the frontend already has it from the /api/resume-suggest
    call that produced the match results the student is now continuing from,
    so this never re-parses or stores the résumé itself, only the same
    derived skill list already shown to the student.
    """
    body = json_body()
    skills = body.get("skills") or []
    if not isinstance(skills, list) or not all(isinstance(s, str) for s in skills):
        raise ApiError("'skills' must be a list of strings.", status=400)
    skills = [s.strip() for s in skills if s.strip()][:50]
    if not skills:
        raise ApiError("'skills' must contain at least one non-empty skill.", status=400)

    _owned_conversation(conversation_id)
    db.conversations().update_one(
        {"conversation_id": conversation_id},
        {"$set": {"resume_skills": skills, "updated_at": datetime.now(timezone.utc)}},
    )
    return ok({"resume_skills": skills})
