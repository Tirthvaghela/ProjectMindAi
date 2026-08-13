"""Per-device state: favourites, search history, feedback.

Identity is a client-generated UUID sent as X-Device-Id — see helpers.device_id
for why this project deliberately has no accounts.
"""

from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, request
from pymongo.errors import DuplicateKeyError

import config
from db import client as db
from db.schema import public_view
from routes.helpers import ApiError, device_id, get_int, json_body, ok

bp = Blueprint("user", __name__, url_prefix="/api")


@bp.post("/favorite")
def add_favorite():
    body = json_body()
    caller = device_id()
    project_id = (body.get("project_id") or "").strip()

    if not project_id:
        raise ApiError("'project_id' is required.", status=400)
    if db.projects().count_documents({"project_id": project_id}, limit=1) == 0:
        raise ApiError(f"No project with id '{project_id}'.", status=404)

    try:
        db.favorites().insert_one(
            {
                "device_id": caller,
                "project_id": project_id,
                "created_at": datetime.now(timezone.utc),
            }
        )
        created = True
    except DuplicateKeyError:
        # Unique index already guarantees one row per (device, project).
        # Favouriting twice is idempotent, not an error.
        created = False

    return ok({"project_id": project_id, "favorited": True, "created": created})


@bp.delete("/favorite/<project_id>")
def remove_favorite(project_id: str):
    caller = device_id()
    result = db.favorites().delete_one(
        {"device_id": caller, "project_id": project_id}
    )
    return ok({"project_id": project_id, "favorited": False, "removed": result.deleted_count})


@bp.get("/favorites")
def list_favorites():
    """Return full project documents, not just ids — the UI needs to render
    cards and would otherwise have to issue N follow-up requests."""
    caller = device_id()
    rows = list(
        db.favorites().find({"device_id": caller}).sort("created_at", -1)
    )
    ids = [row["project_id"] for row in rows]

    documents = {
        doc["project_id"]: public_view(doc)
        for doc in db.projects().find({"project_id": {"$in": ids}})
    }

    # Preserve favourite order, and skip ids whose project was deleted.
    payload = [documents[pid] for pid in ids if pid in documents]
    return ok(payload, count=len(payload))


@bp.get("/history")
def list_history():
    caller = device_id()
    limit = get_int(request.args.to_dict(), "limit", 20, 1, config.MAX_HISTORY_PER_DEVICE)

    rows = (
        db.history()
        .find({"device_id": caller}, {"_id": 0, "device_id": 0})
        .sort("created_at", -1)
        .limit(limit)
    )
    payload = [{**row, "created_at": row["created_at"].isoformat()} for row in rows]
    return ok(payload, count=len(payload))


@bp.delete("/history")
def clear_history():
    caller = device_id()
    result = db.history().delete_many({"device_id": caller})
    return ok({"deleted": result.deleted_count})


@bp.post("/feedback")
def submit_feedback():
    """Capture relevance feedback. Doubles as labelled data for evaluation."""
    body = json_body()
    caller = device_id(required=False)

    message = (body.get("message") or "").strip()
    rating = body.get("rating")
    project_id = (body.get("project_id") or "").strip() or None
    query = (body.get("query") or "").strip() or None

    if rating is not None:
        try:
            rating = int(rating)
        except (TypeError, ValueError):
            raise ApiError("'rating' must be an integer 1-5.", status=400) from None
        if not 1 <= rating <= 5:
            raise ApiError("'rating' must be between 1 and 5.", status=400)

    if not message and rating is None:
        raise ApiError("Provide a 'message' or a 'rating'.", status=400)

    db.feedback().insert_one(
        {
            "device_id": caller,
            "project_id": project_id,
            "query": query,
            "rating": rating,
            "message": message,
            "created_at": datetime.now(timezone.utc),
        }
    )
    return ok({"received": True}), 201
