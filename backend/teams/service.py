"""Persistent project teams — create, join by invite code, and an async
shared message board.

Deliberately not real-time (no WebSockets/Socket.IO): a team here is a
handful of students on one project, and messages are infrequent, so a client
polling GET /teams/<id>/messages on an interval is enough — and it keeps the
deployment story identical to the rest of this app (no separate WSGI
requirements for websocket support, no extra moving part). Revisit if this
ever genuinely needs to feel instant rather than "refresh and see it."
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pymongo.errors import DuplicateKeyError

from db import client as db
from nlp.generator import idea_doc
from nlp.team_builder import suggest_roles
from notify import notify

_MAX_SKILLS = 30


class TeamError(Exception):
    """Team lookup/membership/permission failure with a message safe to show
    the caller, and the HTTP status routes/teams.py should answer with.

    Defaults to 404 — "no such team" and "you're not a member of that team"
    deliberately look identical to a caller (see _member_team_or_none), so a
    non-member can't even confirm a team exists. A permission failure for an
    actual member (not the owner) is a different case — the team's existence
    is already known to them — and passes status=403 explicitly; a bad
    request (empty name, removing the owner) passes status=400.
    """

    def __init__(self, message: str, status: int = 404):
        super().__init__(message)
        self.status = status


# The project fields a team's workspace needs to ground "our project" —
# deliberately the same set nlp/chat_tools.py:get_project_details returns to
# the AI mentor, so a team's project context and the mentor's mean the same
# thing. Never stored on the team document itself (see module docstring's
# "no duplicate project storage" rule) — always read fresh from the
# catalogue, here and in get_project_details alike.
_PROJECT_CONTEXT_FIELDS = {
    "_id": 0,
    "project_id": 1,
    "title": 1,
    "description": 1,
    "domain": 1,
    "difficulty": 1,
    "duration_weeks": 1,
    "technologies": 1,
    "skills": 1,
}


def _invite_code() -> str:
    # 6 chars, no ambiguous 0/O/1/I — short enough to read aloud or type in.
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(6))


def _project_context(project_id: str) -> dict[str, Any] | None:
    """One team's full project context, freshly read from the catalogue —
    None if that project has since been deleted (the team itself must stay
    usable either way, see _public_team)."""
    return db.projects().find_one({"project_id": project_id}, _PROJECT_CONTEXT_FIELDS)


def _project_contexts(project_ids: list[str]) -> dict[str, dict[str, Any]]:
    """project_id -> context, batched in one query for list_my_teams — same
    shape _project_context returns, just N-at-once instead of N round trips."""
    docs = db.projects().find({"project_id": {"$in": list(set(project_ids))}}, _PROJECT_CONTEXT_FIELDS)
    return {d["project_id"]: d for d in docs}


# The idea fields worth keeping on an idea-backed team's own document —
# unlike a catalogue project (always re-read live, see _project_context), a
# generated idea has no persistent record anywhere else to read back from
# (nlp/ai_assistant.py's module docstring: ideas are never written to
# Mongo), so this snapshot IS the team's only record of what it's building.
# Taken once at creation time; refining/regenerating the idea afterwards
# doesn't change what the team is building, same as a team's catalogue
# project is fixed for its lifetime too.
_IDEA_SNAPSHOT_FIELDS = ("name", "domain", "difficulty", "duration_weeks", "technologies", "problem", "solution")


def _idea_snapshot(idea: dict[str, Any]) -> dict[str, Any]:
    return {field: idea.get(field) for field in _IDEA_SNAPSHOT_FIELDS}


def _idea_context(snapshot: dict[str, Any]) -> dict[str, Any]:
    """The idea-backed mirror of _project_context — a project-shaped dict
    built from the team's own stored idea snapshot (nlp/generator.py's
    idea_doc(), the same synthetic-doc builder routes/ideas.py and
    nlp/chat_tools.py's generate_idea_* tools already use) instead of a
    Mongo lookup, so _public_team/team_roles/suggest_roles all work
    identically regardless of what's backing the team."""
    return idea_doc(
        snapshot.get("name") or "",
        domain=snapshot.get("domain"),
        duration_weeks=snapshot.get("duration_weeks"),
        difficulty=snapshot.get("difficulty"),
        technologies=snapshot.get("technologies"),
        description=f"{snapshot.get('problem') or ''} {snapshot.get('solution') or ''}".strip(),
    )


def _context_for(team: dict[str, Any]) -> Optional[dict[str, Any]]:
    """One team's project/idea context, live where possible — _project_context
    for a catalogue-backed team, _idea_context (from the team's own stored
    snapshot) for an idea-backed one. What every read below calls instead of
    branching on project_id/idea itself."""
    if team.get("project_id"):
        return _project_context(team["project_id"])
    if team.get("idea"):
        return _idea_context(team["idea"])
    return None


def create_team(
    name: str,
    owner: dict[str, Any],
    *,
    project_id: Optional[str] = None,
    idea: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Start a team grounded in either a catalogue project (`project_id`) or
    a generated idea (`idea`, that idea's own fields — see routes/ideas.py
    for the same shape) — exactly one of the two. A catalogue-backed team
    stays live-linked to the project (see _project_context); an idea-backed
    one snapshots the idea's fields onto the team itself, since that's the
    only place they'd otherwise persist at all.
    """
    if bool(project_id) == bool(idea):
        raise TeamError("Provide exactly one of 'project_id' or 'idea'.", status=400)

    if project_id:
        context = _project_context(project_id)
        if context is None:
            raise TeamError(f"No project with id '{project_id}'.")
        team = {
            "team_id": str(uuid.uuid4()),
            "project_id": project_id,
            "project_title": context["title"],
            "name": name.strip() or f"{context['title']} team",
            "invite_code": _invite_code(),
            "owner_user_id": owner["user_id"],
            "members": [{"user_id": owner["user_id"], "name": owner["name"], "email": owner["email"]}],
            "created_at": datetime.now(timezone.utc),
        }
    else:
        idea_name = (idea.get("name") or "").strip()
        if not idea_name:
            raise TeamError("The idea must have a 'name'.", status=400)
        snapshot = _idea_snapshot({**idea, "name": idea_name})
        context = _idea_context(snapshot)
        team = {
            "team_id": str(uuid.uuid4()),
            "project_id": None,
            "idea": snapshot,
            "project_title": idea_name,
            "name": name.strip() or f"{idea_name} team",
            "invite_code": _invite_code(),
            "owner_user_id": owner["user_id"],
            "members": [{"user_id": owner["user_id"], "name": owner["name"], "email": owner["email"]}],
            "created_at": datetime.now(timezone.utc),
        }

    # team_id is a uuid4 — collision odds are astronomically lower than
    # invite_code's (6 chars over a 32-char alphabet, db/client.py:uq_invite_code)
    # — so a real DuplicateKeyError here is effectively always the invite
    # code. Bounded retry with a freshly drawn code rather than surfacing a
    # raw 500 for what is, from the caller's perspective, a random and
    # entirely retryable clash.
    for attempt in range(3):
        try:
            db.teams().insert_one(team)
            break
        except DuplicateKeyError:
            if attempt == 2:
                raise TeamError("Could not create the team — please try again.", status=500) from None
            team["invite_code"] = _invite_code()

    return _public_team(team, context, owner["user_id"])


def join_team(invite_code: str, user: dict[str, Any]) -> dict[str, Any]:
    team = db.teams().find_one({"invite_code": invite_code.strip().upper()})
    if team is None:
        raise TeamError("No team found with that invite code.")

    already_member = any(m["user_id"] == user["user_id"] for m in team["members"])
    if not already_member:
        try:
            db.teams().update_one(
                {"team_id": team["team_id"]},
                {"$push": {"members": {"user_id": user["user_id"], "name": user["name"], "email": user["email"]}}},
            )
        except DuplicateKeyError:
            # Lost a race with a concurrent join for this same user —
            # db/client.py's uq_team_member index already caught it, so this
            # member is on the team by the time we get here regardless. The
            # `team` fetched above now predates whichever request actually
            # won, so re-read rather than trust it, and skip re-notifying:
            # the winning request already sent that round of notifications.
            team = db.teams().find_one({"team_id": team["team_id"]})
            return _public_team(team, _context_for(team), user["user_id"])

        for member in team["members"]:
            notify(
                member["user_id"],
                type_="team_join",
                title=f"{user['name']} joined {team['name']}",
                body=f"{user['name']} joined your team for {team['project_title']}.",
                team_id=team["team_id"],
                project_id=team["project_id"],
            )
        team["members"].append({"user_id": user["user_id"], "name": user["name"], "email": user["email"]})

    return _public_team(team, _context_for(team), user["user_id"])


def list_my_teams(user_id: str) -> list[dict[str, Any]]:
    rows = list(db.teams().find({"members.user_id": user_id}, {"_id": 0}).sort("created_at", -1))
    # Batch the catalogue-project lookups (one query, not N); an idea-backed
    # team's context comes free from its own already-fetched snapshot.
    contexts = _project_contexts([t["project_id"] for t in rows if t.get("project_id")])

    def context_for_row(t: dict[str, Any]) -> Optional[dict[str, Any]]:
        if t.get("project_id"):
            return contexts.get(t["project_id"])
        if t.get("idea"):
            return _idea_context(t["idea"])
        return None

    return [_public_team(t, context_for_row(t), user_id) for t in rows]


def get_team(team_id: str, user_id: str) -> dict[str, Any]:
    team = _member_team_or_none(team_id, user_id)
    if team is None:
        raise TeamError("No team found, or you are not a member.")
    return _public_team(team, _context_for(team), user_id)


def update_team(team_id: str, user_id: str, name: str) -> dict[str, Any]:
    """Rename a team — owner-only, the one piece of team info that's actually
    editable (the associated project is fixed for the team's lifetime, and
    membership has its own add/remove operations below)."""
    team = _member_team_or_none(team_id, user_id)
    if team is None:
        raise TeamError("No team found, or you are not a member.")
    if team["owner_user_id"] != user_id:
        raise TeamError("Only the team owner can update the team.", status=403)

    name = name.strip()
    if not name:
        raise TeamError("'name' is required.", status=400)
    if len(name) > 80:
        raise TeamError("'name' must be 80 characters or fewer.", status=400)

    db.teams().update_one({"team_id": team_id}, {"$set": {"name": name}})
    team["name"] = name
    return _public_team(team, _context_for(team), user_id)


def remove_member(team_id: str, acting_user_id: str, target_user_id: str) -> dict[str, Any]:
    """Remove one member — the owner can remove any other member (kicking);
    any non-owner member can remove themselves (leaving). The owner can
    never be removed through this path, by themselves or anyone else — a
    team always needs exactly one owner, and transferring/deleting a team
    is a separate concern this doesn't need to solve."""
    team = _member_team_or_none(team_id, acting_user_id)
    if team is None:
        raise TeamError("No team found, or you are not a member.")

    is_owner = team["owner_user_id"] == acting_user_id
    is_self = acting_user_id == target_user_id
    if not is_owner and not is_self:
        raise TeamError("Only the team owner can remove another member.", status=403)
    if target_user_id == team["owner_user_id"]:
        raise TeamError("The team owner cannot be removed from the team.", status=400)

    target = next((m for m in team["members"] if m["user_id"] == target_user_id), None)
    if target is None:
        raise TeamError("That user is not a member of this team.")

    db.teams().update_one({"team_id": team_id}, {"$pull": {"members": {"user_id": target_user_id}}})
    remaining = [m for m in team["members"] if m["user_id"] != target_user_id]

    for member in remaining:
        notify(
            member["user_id"],
            type_="team_leave",
            title=(
                f"{target['name']} left {team['name']}"
                if is_self
                else f"{target['name']} was removed from {team['name']}"
            ),
            body=f"{target['name']} is no longer on your team for {team['project_title']}.",
            team_id=team_id,
            project_id=team["project_id"],
        )

    team["members"] = remaining
    return _public_team(team, _context_for(team), acting_user_id)


def post_message(team_id: str, user: dict[str, Any], content: str) -> dict[str, Any]:
    team = _member_team_or_none(team_id, user["user_id"])
    if team is None:
        raise TeamError("No team found, or you are not a member.")

    message = {
        "message_id": str(uuid.uuid4()),
        "team_id": team_id,
        "user_id": user["user_id"],
        "author_name": user["name"],
        "content": content.strip(),
        "created_at": datetime.now(timezone.utc),
    }
    db.team_messages().insert_one(message)

    for member in team["members"]:
        if member["user_id"] != user["user_id"]:
            notify(
                member["user_id"],
                type_="team_message",
                title=f"New message in {team['name']}",
                body=f"{user['name']}: {content.strip()[:120]}",
                team_id=team_id,
                project_id=team["project_id"],
            )

    return _public_message(message)


def list_messages(team_id: str, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
    team = _member_team_or_none(team_id, user_id)
    if team is None:
        raise TeamError("No team found, or you are not a member.")

    rows = db.team_messages().find({"team_id": team_id}, {"_id": 0}).sort("created_at", 1).limit(limit)
    return [_public_message(m) for m in rows]


def set_member_skills(team_id: str, user_id: str, skills: list[str]) -> dict[str, Any]:
    """A member's own skills for this team — the only input team_roles()
    below needs beyond the project itself. Self-service (any member sets
    only their own; there is no "set someone else's skills") rather than
    owner-only, since a member is the one authority on what they actually
    know. Stored on the membership record itself, not a second collection —
    it's a property of "this person, on this team", nothing more."""
    team = _member_team_or_none(team_id, user_id)
    if team is None:
        raise TeamError("No team found, or you are not a member.")

    clean = [s.strip() for s in (skills or []) if isinstance(s, str) and s.strip()][:_MAX_SKILLS]
    db.teams().update_one(
        {"team_id": team_id, "members.user_id": user_id},
        {"$set": {"members.$.skills": clean}},
    )
    for member in team["members"]:
        if member["user_id"] == user_id:
            member["skills"] = clean
    return _public_team(team, _context_for(team), user_id)


def team_roles(team_id: str, user_id: str) -> dict[str, Any]:
    """Who should work on what, for this team's real roster and real project
    or idea — nlp/team_builder.py:suggest_roles, the same role-assignment
    function POST /api/team-builder already exposes for an ad-hoc, re-typed
    member list, just fed this team's own persisted roster (name +
    set_member_skills above) and live context instead. Answers the spec's
    own "who should work on the backend?" example directly — no second
    role-assignment algorithm, and no member skill list to retype by hand."""
    team = _member_team_or_none(team_id, user_id)
    if team is None:
        raise TeamError("No team found, or you are not a member.")

    context = _context_for(team)
    if context is None:
        raise TeamError("This team's project no longer exists — role suggestions need a real project to split into.")

    members = [{"name": m.get("name") or m["user_id"], "skills": m.get("skills") or []} for m in team["members"]]
    return suggest_roles(context, members)


def _member_team_or_none(team_id: str, user_id: str) -> dict[str, Any] | None:
    team = db.teams().find_one({"team_id": team_id})
    if team is None or not any(m["user_id"] == user_id for m in team["members"]):
        return None
    return team


def _public_team(team: dict[str, Any], context: dict[str, Any] | None, caller_user_id: str) -> dict[str, Any]:
    """Team + its live project/idea context (see _context_for), one payload
    — `context` is None only when a catalogue-backed team's project has
    since been deleted (an idea-backed team's context comes from its own
    stored snapshot, so it's never missing once creation succeeds); the team
    itself (members, messages, invite code) stays fully usable either way,
    it just can't ground "what are we building" until it points somewhere
    real again.

    `invite_code` is the one field not just handed to every member — it's
    the credential that grants membership, so only the owner (the one
    person meant to be handing it out) gets it back; every other member has
    it stripped here rather than relying on the frontend to hide it.

    `project_title`/`domain` stay top-level (not just nested under
    `project`) for the existing frontend (Teams.jsx/TeamRoom.jsx) that
    already reads them there — sourced from the live/snapshot context so
    they never drift, falling back to the name recorded at creation only
    once that context can no longer be produced at all. `team.items()`
    already carries `idea` (the raw snapshot, only present on an idea-backed
    team) straight through — that's what TeamRoom.jsx uses to link back into
    the idea's own workspace, since `project` here is idea_doc()'s
    generic project-shaped view of it, not the original idea fields.
    """
    payload = {k: v for k, v in team.items() if k != "_id"}
    if team.get("owner_user_id") != caller_user_id:
        payload.pop("invite_code", None)
    payload["created_at"] = payload["created_at"].isoformat()
    payload["project"] = context
    payload["project_title"] = context.get("title") if context else team.get("project_title")
    payload["domain"] = context.get("domain") if context else None
    return payload


def _public_message(message: dict[str, Any]) -> dict[str, Any]:
    payload = {k: v for k, v in message.items() if k != "_id"}
    payload["created_at"] = payload["created_at"].isoformat()
    return payload
