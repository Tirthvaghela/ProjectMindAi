"""MongoDB connection and index management.

One lazily-created client for the whole process. pymongo's MongoClient is
thread-safe and pools internally, so creating it per-request would be wasteful
and would exhaust connections under load.
"""

from __future__ import annotations

import logging
from typing import Optional

from pymongo import ASCENDING, DESCENDING, MongoClient, TEXT
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import ServerSelectionTimeoutError

import config

log = logging.getLogger(__name__)

_client: Optional[MongoClient] = None


def get_client() -> MongoClient:
    """Return the shared MongoClient, creating it on first use."""
    global _client
    if _client is None:
        # serverSelectionTimeoutMS keeps a dead mongod from hanging requests
        # for the 30s default — we want a fast, clear failure instead.
        _client = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=3000)
    return _client


def get_db() -> Database:
    return get_client()[config.MONGO_DB]


def projects() -> Collection:
    return get_db()[config.COLL_PROJECTS]


def favorites() -> Collection:
    return get_db()[config.COLL_FAVORITES]


def history() -> Collection:
    return get_db()[config.COLL_HISTORY]


def feedback() -> Collection:
    return get_db()[config.COLL_FEEDBACK]


def users() -> Collection:
    return get_db()[config.COLL_USERS]


def sessions() -> Collection:
    return get_db()[config.COLL_SESSIONS]


def teams() -> Collection:
    return get_db()[config.COLL_TEAMS]


def team_messages() -> Collection:
    return get_db()[config.COLL_TEAM_MESSAGES]


def notifications() -> Collection:
    return get_db()[config.COLL_NOTIFICATIONS]


def conversations() -> Collection:
    return get_db()[config.COLL_CONVERSATIONS]


def ping() -> bool:
    """True if mongod is reachable. Used by /api/health."""
    try:
        get_client().admin.command("ping")
        return True
    except ServerSelectionTimeoutError:
        return False


def ensure_indexes() -> None:
    """Create indexes needed for filtering and lookup.

    Idempotent — Mongo ignores an index that already exists, so this is safe
    to call on every startup.
    """
    p = projects()
    p.create_index([("project_id", ASCENDING)], unique=True, name="uq_project_id")
    p.create_index([("domain", ASCENDING)], name="ix_domain")
    p.create_index([("difficulty", ASCENDING)], name="ix_difficulty")
    p.create_index([("technologies", ASCENDING)], name="ix_technologies")

    # Mongo's text index is a fallback for /api/projects browsing only.
    # Actual search ranking is the hybrid dense+BM25 scorer, not this.
    p.create_index(
        [("title", TEXT), ("description", TEXT), ("keywords", TEXT)],
        name="txt_search",
    )

    favorites().create_index(
        [("device_id", ASCENDING), ("project_id", ASCENDING)],
        unique=True,
        name="uq_device_project",
    )
    # Supports list_favorites' {device_id: ...}.sort("created_at", -1) — the
    # unique index above is keyed on project_id first, so it can't serve that
    # sort. Same shape as history's ix_device_recent just below, for the same
    # per-device-recency query pattern.
    favorites().create_index(
        [("device_id", ASCENDING), ("created_at", DESCENDING)],
        name="ix_device_recent",
    )
    history().create_index(
        [("device_id", ASCENDING), ("created_at", DESCENDING)],
        name="ix_device_recent",
    )
    feedback().create_index([("created_at", DESCENDING)], name="ix_recent")

    users().create_index([("email", ASCENDING)], unique=True, name="uq_email")

    # TTL index: Mongo deletes a session document itself once expires_at is in
    # the past, so expired tokens clean themselves up without a cron job.
    sessions().create_index([("token", ASCENDING)], unique=True, name="uq_token")
    sessions().create_index([("expires_at", ASCENDING)], expireAfterSeconds=0, name="ttl_expires")

    teams().create_index([("team_id", ASCENDING)], unique=True, name="uq_team_id")
    teams().create_index([("invite_code", ASCENDING)], unique=True, name="uq_invite_code")
    teams().create_index([("project_id", ASCENDING)], name="ix_project")
    teams().create_index([("members.user_id", ASCENDING)], name="ix_member")
    # Backstops join_team()'s check-then-$push: a unique index over a
    # multikey field rejects a second array element with the same
    # (team_id, user_id) pair even within one document, so two concurrent
    # joins for the same user can't both land. ix_member above stays too —
    # it serves the team-id-less "which teams is this user on" lookup this
    # compound index can't.
    teams().create_index(
        [("team_id", ASCENDING), ("members.user_id", ASCENDING)],
        unique=True,
        name="uq_team_member",
    )

    team_messages().create_index([("team_id", ASCENDING), ("created_at", ASCENDING)], name="ix_team_recent")

    notifications().create_index([("user_id", ASCENDING), ("created_at", DESCENDING)], name="ix_user_recent")

    conversations().create_index([("conversation_id", ASCENDING)], unique=True, name="uq_conversation_id")
    conversations().create_index([("device_id", ASCENDING), ("updated_at", DESCENDING)], name="ix_device_recent")
    # Signed-in callers own conversations by account, not device — see
    # routes/assistant.py:_ownership_filter.
    conversations().create_index([("user_id", ASCENDING), ("updated_at", DESCENDING)], name="ix_user_recent")

    log.info("MongoDB indexes ensured")
