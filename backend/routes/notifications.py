"""In-app notifications — list and mark read. See notify.py for how these
get created (currently: team joins and new team messages)."""

from __future__ import annotations

from flask import Blueprint, request

from db import client as db
from extensions import limiter
from routes.helpers import current_user, get_int, ok

bp = Blueprint("notifications", __name__, url_prefix="/api/notifications")

# Cheap, authenticated Mongo reads/writes — not "expensive" in the sense the
# rest of this app's rate limits target (an external API call, an SMTP send,
# a heavy aggregation). The frontend bell polls list_notifications every 30s
# (NotificationsBell.jsx), so this is a generous ceiling that comfortably
# covers that plus normal manual mark-read clicks, purely as a defense-in-
# depth floor against a runaway/malicious client rather than a real cost
# concern.
_NOTIFICATIONS_LIMIT = "60 per minute"


@bp.get("")
@limiter.limit(_NOTIFICATIONS_LIMIT)
def list_notifications():
    user = current_user()
    limit = get_int(request.args.to_dict(), "limit", 30, 1, 100)

    rows = (
        db.notifications()
        .find({"user_id": user["user_id"]}, {"_id": 0})
        .sort("created_at", -1)
        .limit(limit)
    )
    payload = [{**row, "created_at": row["created_at"].isoformat()} for row in rows]
    unread = db.notifications().count_documents({"user_id": user["user_id"], "read": False})

    return ok(payload, count=len(payload), unread=unread)


@bp.post("/<notification_id>/read")
@limiter.limit(_NOTIFICATIONS_LIMIT)
def mark_read(notification_id: str):
    user = current_user()
    db.notifications().update_one(
        {"notification_id": notification_id, "user_id": user["user_id"]},
        {"$set": {"read": True}},
    )
    return ok({"read": True})


@bp.post("/read-all")
@limiter.limit(_NOTIFICATIONS_LIMIT)
def mark_all_read():
    user = current_user()
    db.notifications().update_many(
        {"user_id": user["user_id"], "read": False}, {"$set": {"read": True}}
    )
    return ok({"read": True})
