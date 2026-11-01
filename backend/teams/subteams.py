"""Module/workstream sub-teams under a parent team: roster, invitations, chat,
role suggestions and tasks.

A sub-team is a smaller group of EXISTING parent-team members working on one
module. It is never an independent team and never a way into the parent.

Storage (see db/client.py): `sub_teams` (one document per sub-team, with its
member ids, a hashed invitation, and each member's own role decision),
`sub_team_messages` and `sub_team_tasks`. They are separate from `teams` so a
sub-team's chat and tasks cannot bloat or contend with the parent document, and
every query is keyed by sub_team_id.

THE central invariant: authorisation is always derived from the parent team's
CURRENT roster, read on every request (`_access`). A sub-team's stored member
list is only ever used as `stored ∩ parent roster`, so a stale or injected entry
- a member removed from the parent, a race between two writes, a hand-edited
document - grants nothing. `on_parent_member_removed` and `_reconcile` merely tidy
those inert entries; security never depends on them having run.

Roles: the parent OWNER administers everything (create/rename/archive/delete, add
and remove members, invitations, tasks). A sub-team MEMBER reads the roster,
tasks and chat, posts to chat, sees role suggestions, records their OWN role
decision and updates the status of a task assigned to them. A parent member who
is not in the sub-team sees only its name and module in the list. The owner does
not read a sub-team's chat unless they are a member of it.

Failures that would reveal whether something exists (wrong team, wrong sub-team,
not a member) all look like the same 404, as in teams/service.py.
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from pymongo.errors import DuplicateKeyError

from db import client as db
from nlp.team_builder import role_fit, suggest_roles
from notify import notify
from profiles import service as profile_service
from teams import service as teams

log = logging.getLogger(__name__)
TeamError = teams.TeamError

MAX_SUB_TEAMS = 20
MAX_NAME_CHARS = 80
MAX_DESCRIPTION_CHARS = 500
MAX_MODULE_CHARS = 80
MAX_INITIAL_MEMBERS = 50
MAX_TASKS = 200
MAX_TITLE_CHARS = 120
MAX_TASK_DESCRIPTION_CHARS = 1000
MAX_MESSAGE_CHARS = 2000
MAX_ID_CHARS = 64

SUB_TEAM_STATUSES = ("active", "archived")
TASK_STATUSES = ("todo", "in_progress", "blocked", "done")
ROLE_DECISION_STATUSES = ("accepted", "rejected", "custom")

INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I
INVITE_LENGTH = 10  # 32**10 = 50 bits, and every attempt is rate limited
DEFAULT_INVITE_DAYS = 7
MAX_INVITE_DAYS = 30
_CODE_RE = re.compile(r"^[A-Z0-9]{6,32}$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_SPACE_RE = re.compile(r"\s+")

NOT_FOUND = "No team found, or you are not a member."
NO_SUB_TEAM = "No sub-team found."
BAD_CODE = "Invalid or expired invite code."


# --- small helpers ---------------------------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Any) -> Optional[datetime]:
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value: Any) -> Optional[str]:
    aware = _aware(value)
    return aware.isoformat() if aware else None


def _id(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_ID_CHARS:
        raise TeamError(NO_SUB_TEAM)
    return value


def _text(value: Any, field_name: str, limit: int, *, required: bool = False, multiline: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise TeamError(f"'{field_name}' must be text.", status=400)
    text = _CONTROL_RE.sub(" ", value.replace("\r\n", "\n"))
    text = text.strip() if multiline else _SPACE_RE.sub(" ", text).strip()
    if required and not text:
        raise TeamError(f"'{field_name}' is required.", status=400)
    if len(text) > limit:
        raise TeamError(f"'{field_name}' must be {limit} characters or fewer.", status=400)
    return text


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _new_code() -> str:
    return "".join(secrets.choice(INVITE_ALPHABET) for _ in range(INVITE_LENGTH))


# --- access ----------------------------------------------------------------------------------------------------------


@dataclass
class Access:
    """Everything authorisation needs, resolved fresh for one request."""

    team: dict[str, Any]
    sub: dict[str, Any]
    user_id: str
    roster: dict[str, dict[str, Any]]  # CURRENT parent members by id
    member_ids: list[str] = field(default_factory=list)  # sub-team members who are STILL parent members
    is_owner: bool = False
    is_member: bool = False

    def name_of(self, user_id: str) -> str:
        return (self.roster.get(user_id) or {}).get("name") or user_id


def _roster(team: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        m["user_id"]: m
        for m in team.get("members") or []
        if isinstance(m, dict) and isinstance(m.get("user_id"), str)
    }


def _effective_ids(sub: dict[str, Any], roster: dict[str, dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for entry in sub.get("members") or []:
        uid = entry.get("user_id") if isinstance(entry, dict) else None
        if isinstance(uid, str) and uid in roster and uid not in out:
            out.append(uid)
    return out


def _access_for(team: dict[str, Any], sub: dict[str, Any], user_id: str) -> Access:
    roster = _roster(team)
    ids = _effective_ids(sub, roster)
    return Access(
        team=team, sub=sub, user_id=user_id, roster=roster, member_ids=ids,
        is_owner=team.get("owner_user_id") == user_id, is_member=user_id in ids,
    )


def _find_sub(team_id: str, sub_team_id: Any) -> dict[str, Any]:
    sub = db.sub_teams().find_one({"sub_team_id": _id(sub_team_id), "parent_team_id": team_id})
    if sub is None:
        raise TeamError(NO_SUB_TEAM)
    return sub


def _access(team_id: str, sub_team_id: Any, user_id: str) -> Access:
    """Parent membership first (so a non-member learns nothing), then the sub-team
    resolved UNDER that parent (so an id from another team is simply not found)."""
    team = teams._member_team_or_none(team_id, user_id)
    if team is None:
        raise TeamError(NOT_FOUND)
    return _access_for(team, _find_sub(team_id, sub_team_id), user_id)


def _viewer(team_id: str, sub_team_id: Any, user_id: str) -> Access:
    """A sub-team member, or the parent owner (who administers it)."""
    acc = _access(team_id, sub_team_id, user_id)
    if not (acc.is_member or acc.is_owner):
        raise TeamError(NO_SUB_TEAM)
    return acc


def _member(team_id: str, sub_team_id: Any, user_id: str, *, action: str = "use this sub-team's chat") -> Access:
    acc = _viewer(team_id, sub_team_id, user_id)
    if not acc.is_member:
        # Only the owner can get here; they know it exists, so say what to do.
        raise TeamError(f"Join this sub-team to {action}.", status=403)
    return acc


def _owner(team_id: str, sub_team_id: Any, user_id: str) -> Access:
    acc = _access(team_id, sub_team_id, user_id)
    if not acc.is_owner:
        if acc.is_member:
            raise TeamError("Only the team owner can manage sub-teams.", status=403)
        raise TeamError(NO_SUB_TEAM)
    return acc


def _owner_of_team(team_id: str, user_id: str) -> dict[str, Any]:
    team = teams._member_team_or_none(team_id, user_id)
    if team is None:
        raise TeamError(NOT_FOUND)
    if team.get("owner_user_id") != user_id:
        raise TeamError("Only the team owner can manage sub-teams.", status=403)
    return team


def _still_on_parent(team_id: str, user_id: str) -> bool:
    team = db.teams().find_one({"team_id": team_id}, {"members.user_id": 1})
    return bool(team) and any(isinstance(m, dict) and m.get("user_id") == user_id for m in team.get("members") or [])


def _undo_if_removed_meanwhile(team_id: str, sub_team_id: str, user_id: str) -> bool:
    """Close the check-then-write window against a concurrent parent-team removal.

    A membership row is written AFTER the parent roster was read, so the person may
    have been removed from the parent in between. Re-read the parent once the row is
    in: if they are gone, take the row back out and report it. Why this is enough:
    if the re-read still shows them, the parent removal had not happened yet, so its
    own cleanup (on_parent_member_removed) runs after this row exists and clears it."""
    if _still_on_parent(team_id, user_id):
        return False
    db.sub_teams().update_one({"sub_team_id": sub_team_id}, {"$pull": {"members": {"user_id": user_id}}})
    return True


def _assignee_still_valid(team_id: str, sub_team_id: str, user_id: str) -> bool:
    """Is this person STILL on the parent team AND on this sub-team? Read after an
    assignment write, to close the window against a concurrent removal. If they are,
    the removal had not yet happened, so its cleanup (which unassigns their tasks)
    will run after this write; if not, the caller takes the assignment back."""
    if not _still_on_parent(team_id, user_id):
        return False
    return db.sub_teams().find_one({"sub_team_id": sub_team_id, "members.user_id": user_id}, {"_id": 1}) is not None


def _require_active(acc: Access) -> None:
    if acc.sub.get("status") == "archived":
        raise TeamError("This sub-team is archived. Reactivate it to make changes.", status=400)


# --- presentation ---------------------------------------------------------------------------------------------------


def _invite_state(sub: dict[str, Any]) -> dict[str, Any]:
    invite = sub.get("invite") if isinstance(sub.get("invite"), dict) else None
    if not invite or not invite.get("code_hash"):
        return {"active": False, "expires_at": None}
    expires = _aware(invite.get("expires_at"))
    live = expires is not None and expires > _now()
    return {"active": live, "expired": not live, "expires_at": _iso(expires)}


def _public_sub(acc: Access, *, new_code: Optional[str] = None) -> dict[str, Any]:
    """Never contains: the invitation hash or code (except `new_code`, once, to the
    owner), any member email, role decisions, or another team's data."""
    sub = acc.sub
    out: dict[str, Any] = {
        "sub_team_id": sub["sub_team_id"],
        "parent_team_id": sub["parent_team_id"],
        "name": sub.get("name"),
        "module": sub.get("module") or "",
        "description": sub.get("description") or "",
        "status": sub.get("status") or "active",
        "created_at": _iso(sub.get("created_at")),
        "updated_at": _iso(sub.get("updated_at")),
        "member_count": len(acc.member_ids),
        "is_member": acc.is_member,
        "can_manage": acc.is_owner,
    }
    if acc.is_member or acc.is_owner:
        out["members"] = [{"user_id": uid, "name": acc.name_of(uid)} for uid in acc.member_ids]
    if acc.is_owner:
        out["invite"] = _invite_state(sub)
        if new_code:
            out["invite"]["code"] = new_code
    return out


def _notify(user_id: str, acc: Access, type_: str, title: str, body: str) -> None:
    """Best-effort and only AFTER the write succeeded; a notification never grants
    access and never contains an invitation secret."""
    try:
        notify(user_id, type_=type_, title=title, body=body, team_id=acc.team["team_id"], project_id=acc.team.get("project_id"))
    except Exception:  # noqa: BLE001
        log.warning("Could not store a sub-team notification")


# --- sub-team lifecycle ----------------------------------------------------------------------------------------------


def _validated_member_ids(raw: Any, roster: dict[str, dict[str, Any]]) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_INITIAL_MEMBERS or not all(isinstance(x, str) for x in raw):
        raise TeamError("'member_ids' must be a list of team members.", status=400)
    out: list[str] = []
    for uid in raw:
        if uid not in roster:
            raise TeamError("Every member must already be on the parent team.", status=400)
        if uid not in out:
            out.append(uid)
    return out


def list_sub_teams(team_id: str, user_id: str) -> list[dict[str, Any]]:
    team = teams._member_team_or_none(team_id, user_id)
    if team is None:
        raise TeamError(NOT_FOUND)
    rows = list(db.sub_teams().find({"parent_team_id": team_id}).sort("created_at", 1).limit(MAX_SUB_TEAMS * 2))
    return [_public_sub(_access_for(team, sub, user_id)) for sub in rows if isinstance(sub.get("sub_team_id"), str)]


def create_sub_team(team_id: str, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    team = _owner_of_team(team_id, user_id)
    name = _text(payload.get("name"), "name", MAX_NAME_CHARS, required=True)
    description = _text(payload.get("description"), "description", MAX_DESCRIPTION_CHARS, multiline=True)
    module = _text(payload.get("module"), "module", MAX_MODULE_CHARS)
    roster = _roster(team)
    member_ids = _validated_member_ids(payload.get("member_ids"), roster)
    if db.sub_teams().count_documents({"parent_team_id": team_id}) >= MAX_SUB_TEAMS:
        raise TeamError(f"A team can have at most {MAX_SUB_TEAMS} sub-teams.", status=400)

    now = _now()
    sub = {
        "sub_team_id": str(uuid.uuid4()),
        "parent_team_id": team_id,
        "name": name,
        "name_key": name.casefold(),
        "module": module,
        "description": description,
        "status": "active",
        "owner_user_id": user_id,
        "members": [{"user_id": uid, "added_at": now} for uid in member_ids],
        "created_at": now,
        "updated_at": now,
    }
    try:
        db.sub_teams().insert_one(sub)
    except DuplicateKeyError:
        raise TeamError("A sub-team with that name already exists.", status=409) from None

    acc = _access_for(team, sub, user_id)
    for uid in member_ids:
        if uid != user_id:
            _notify(uid, acc, "subteam_added", f"You were added to {name}", f"You are now on the “{name}” sub-team of {team['name']}.")
    return _public_sub(acc)


def get_sub_team(team_id: str, sub_team_id: str, user_id: str) -> dict[str, Any]:
    return _public_sub(_viewer(team_id, sub_team_id, user_id))


def update_sub_team(team_id: str, sub_team_id: str, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    acc = _owner(team_id, sub_team_id, user_id)
    updates: dict[str, Any] = {}
    if "name" in payload:
        updates["name"] = _text(payload["name"], "name", MAX_NAME_CHARS, required=True)
        updates["name_key"] = updates["name"].casefold()
    if "description" in payload:
        updates["description"] = _text(payload["description"], "description", MAX_DESCRIPTION_CHARS, multiline=True)
    if "module" in payload:
        updates["module"] = _text(payload["module"], "module", MAX_MODULE_CHARS)
    if "status" in payload:
        if payload["status"] not in SUB_TEAM_STATUSES:
            raise TeamError(f"'status' must be one of {', '.join(SUB_TEAM_STATUSES)}.", status=400)
        updates["status"] = payload["status"]
    if not updates:
        raise TeamError("Nothing to update.", status=400)
    updates["updated_at"] = _now()
    try:
        db.sub_teams().update_one({"sub_team_id": acc.sub["sub_team_id"], "parent_team_id": team_id}, {"$set": updates})
    except DuplicateKeyError:
        raise TeamError("A sub-team with that name already exists.", status=409) from None
    acc.sub = {**acc.sub, **updates}
    return _public_sub(acc)


def delete_sub_team(team_id: str, sub_team_id: str, user_id: str, confirm: Any) -> dict[str, Any]:
    acc = _owner(team_id, sub_team_id, user_id)
    if confirm not in (True, "true"):
        raise TeamError("Deleting a sub-team removes its chat and tasks and cannot be undone; send confirm=true.", status=400)
    sid = acc.sub["sub_team_id"]
    # The sub-team document goes FIRST: once it is gone nothing can reach its chat or
    # tasks (every access resolves the sub-team), so a failure in the cascade below
    # leaves only unreachable rows, never a half-visible sub-team.
    db.sub_teams().delete_one({"sub_team_id": sid, "parent_team_id": team_id})
    try:
        db.sub_team_messages().delete_many({"sub_team_id": sid})
        db.sub_team_tasks().delete_many({"sub_team_id": sid})
    except Exception:  # noqa: BLE001
        log.warning("Sub-team %s was deleted but its chat/tasks could not be fully removed", sid)
    return {"deleted": True, "sub_team_id": sid}


# --- members -----------------------------------------------------------------------------------------------------------


def add_member(team_id: str, sub_team_id: str, user_id: str, target_id: Any) -> dict[str, Any]:
    acc = _owner(team_id, sub_team_id, user_id)
    _require_active(acc)
    if not isinstance(target_id, str) or target_id not in acc.roster:
        raise TeamError("That person is not a member of the parent team.", status=400)
    if target_id not in acc.member_ids:
        try:
            result = db.sub_teams().update_one(
                {"sub_team_id": acc.sub["sub_team_id"], "members.user_id": {"$ne": target_id}},
                {"$push": {"members": {"user_id": target_id, "added_at": _now()}}, "$set": {"updated_at": _now()}},
            )
            added = result.modified_count == 1
        except DuplicateKeyError:
            added = False
        if added and _undo_if_removed_meanwhile(team_id, acc.sub["sub_team_id"], target_id):
            raise TeamError("That person is not a member of the parent team.", status=400)
        if added:
            acc.member_ids.append(target_id)
            if target_id != user_id:
                _notify(target_id, acc, "subteam_added", f"You were added to {acc.sub['name']}",
                        f"You are now on the “{acc.sub['name']}” sub-team of {acc.team['name']}.")
    acc.is_member = user_id in acc.member_ids
    return _public_sub(acc)


def remove_member(team_id: str, sub_team_id: str, user_id: str, target_id: Any) -> dict[str, Any]:
    acc = _owner(team_id, sub_team_id, user_id)
    if not isinstance(target_id, str) or not target_id or len(target_id) > MAX_ID_CHARS:
        raise TeamError("That person is not on this sub-team.")
    stored = [e.get("user_id") for e in acc.sub.get("members") or [] if isinstance(e, dict)]
    if target_id not in stored:
        raise TeamError("That person is not on this sub-team.")
    now = _now()
    db.sub_teams().update_one(
        {"sub_team_id": acc.sub["sub_team_id"]},
        {"$pull": {"members": {"user_id": target_id}}, "$unset": {f"role_decisions.{target_id}": ""}, "$set": {"updated_at": now}},
    )
    # Their tasks go back to "unassigned" so the owner can reassign them.
    db.sub_team_tasks().update_many(
        {"sub_team_id": acc.sub["sub_team_id"], "assignee_id": target_id}, {"$set": {"assignee_id": None, "updated_at": now}}
    )
    acc.member_ids = [x for x in acc.member_ids if x != target_id]
    acc.is_member = user_id in acc.member_ids
    return _public_sub(acc)


def on_parent_member_removed(team_id: str, removed_user_id: str) -> None:
    """Called after a person leaves or is removed from the PARENT team. Access is
    already gone (every check reads the parent roster); this clears the inert
    leftovers: their membership rows, role decisions and task assignments."""
    now = _now()
    db.sub_teams().update_many(
        {"parent_team_id": team_id},
        {"$pull": {"members": {"user_id": removed_user_id}}, "$unset": {f"role_decisions.{removed_user_id}": ""}},
    )
    db.sub_team_tasks().update_many(
        {"team_id": team_id, "assignee_id": removed_user_id}, {"$set": {"assignee_id": None, "updated_at": now}}
    )


# --- invitations -----------------------------------------------------------------------------------------------------


def create_invite(team_id: str, sub_team_id: str, user_id: str, expires_in_days: Any = None) -> dict[str, Any]:
    """Create OR rotate: any previous code stops working at once. The plaintext
    code is returned exactly once; only its SHA-256 is stored."""
    acc = _owner(team_id, sub_team_id, user_id)
    _require_active(acc)
    days = DEFAULT_INVITE_DAYS if expires_in_days is None else expires_in_days
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= MAX_INVITE_DAYS:
        raise TeamError(f"'expires_in_days' must be a whole number from 1 to {MAX_INVITE_DAYS}.", status=400)
    now = _now()
    for attempt in range(3):
        code = _new_code()
        invite = {"code_hash": _hash_code(code), "created_at": now, "expires_at": now + timedelta(days=days)}
        try:
            db.sub_teams().update_one(
                {"sub_team_id": acc.sub["sub_team_id"]}, {"$set": {"invite": invite, "updated_at": now}}
            )
            break
        except DuplicateKeyError:
            if attempt == 2:
                raise TeamError("Could not create an invitation - please try again.", status=500) from None
    acc.sub = {**acc.sub, "invite": invite}
    return _public_sub(acc, new_code=code)


def revoke_invite(team_id: str, sub_team_id: str, user_id: str) -> dict[str, Any]:
    acc = _owner(team_id, sub_team_id, user_id)
    db.sub_teams().update_one({"sub_team_id": acc.sub["sub_team_id"]}, {"$unset": {"invite": ""}, "$set": {"updated_at": _now()}})
    acc.sub = {k: v for k, v in acc.sub.items() if k != "invite"}
    return _public_sub(acc)


def join_by_code(invite_code: Any, user: dict[str, Any]) -> dict[str, Any]:
    """Join a sub-team the caller's PARENT team already contains them in.

    Every failure - malformed, unknown, revoked, expired, archived, or the caller
    is not on the parent team - is the same 404, so a code reveals nothing about
    which team it belongs to. Parent membership is read now, not when the code
    was made, and the write itself re-checks the code, expiry and "not already in".
    """
    code = invite_code.strip().upper() if isinstance(invite_code, str) else ""
    if not _CODE_RE.match(code):
        raise TeamError(BAD_CODE)
    code_hash = _hash_code(code)
    now = _now()
    sub = db.sub_teams().find_one({"invite.code_hash": code_hash})
    if sub is None or sub.get("status") == "archived":
        raise TeamError(BAD_CODE)
    expires = _aware((sub.get("invite") or {}).get("expires_at"))
    if expires is None or expires <= now:
        raise TeamError(BAD_CODE)
    team = teams._member_team_or_none(sub.get("parent_team_id"), user["user_id"])
    if team is None:
        raise TeamError(BAD_CODE)

    acc = _access_for(team, sub, user["user_id"])
    if not acc.is_member:
        try:
            result = db.sub_teams().update_one(
                {
                    "sub_team_id": sub["sub_team_id"],
                    "invite.code_hash": code_hash,
                    "invite.expires_at": {"$gt": now},
                    "status": {"$ne": "archived"},
                    "members.user_id": {"$ne": user["user_id"]},
                },
                {"$push": {"members": {"user_id": user["user_id"], "added_at": now}}, "$set": {"updated_at": now}},
            )
            joined = result.modified_count == 1
        except DuplicateKeyError:
            joined = False  # a concurrent join by the same person already landed
        if joined and _undo_if_removed_meanwhile(team["team_id"], sub["sub_team_id"], user["user_id"]):
            raise TeamError(BAD_CODE)  # removed from the parent between the check and the write
        fresh = db.sub_teams().find_one({"sub_team_id": sub["sub_team_id"]})
        if fresh is None or user["user_id"] not in _effective_ids(fresh, acc.roster):
            raise TeamError(BAD_CODE)  # revoked/expired between the read and the write
        acc = _access_for(team, fresh, user["user_id"])
        if joined and team.get("owner_user_id") != user["user_id"]:
            _notify(team["owner_user_id"], acc, "subteam_join", f"{user.get('name') or 'Someone'} joined {fresh['name']}",
                    f"{user.get('name') or 'A teammate'} joined the “{fresh['name']}” sub-team.")
    return _public_sub(acc)


# --- chat ----------------------------------------------------------------------------------------------------------------


def list_messages(team_id: str, sub_team_id: str, user_id: str, limit: int = 50, before: Any = None) -> tuple[list[dict[str, Any]], bool]:
    """Newest `limit` messages (oldest first), optionally those older than the ISO
    timestamp `before`. Returns (messages, has_more). Members only."""
    acc = _member(team_id, sub_team_id, user_id)
    query: dict[str, Any] = {"sub_team_id": acc.sub["sub_team_id"]}
    if before is not None:
        try:
            cutoff = datetime.fromisoformat(str(before).replace("Z", "+00:00").replace(" ", "+"))
        except ValueError:
            raise TeamError("'before' must be an ISO timestamp.", status=400) from None
        query["created_at"] = {"$lt": cutoff if cutoff.tzinfo is None else cutoff.astimezone(timezone.utc).replace(tzinfo=None)}
    rows = list(db.sub_team_messages().find(query, {"_id": 0}).sort("created_at", -1).limit(limit + 1))
    has_more = len(rows) > limit
    return [_public_message(m) for m in reversed(rows[:limit])], has_more


def post_message(team_id: str, sub_team_id: str, user: dict[str, Any], content: Any) -> dict[str, Any]:
    acc = _member(team_id, sub_team_id, user["user_id"])
    _require_active(acc)
    text = _text(content, "content", MAX_MESSAGE_CHARS, required=True, multiline=True)
    message = {
        "message_id": str(uuid.uuid4()),
        "sub_team_id": acc.sub["sub_team_id"],
        "team_id": team_id,
        "user_id": user["user_id"],
        "author_name": acc.name_of(user["user_id"]),
        "content": text,
        "created_at": _now(),
    }
    db.sub_team_messages().insert_one(message)
    for uid in acc.member_ids:
        if uid != user["user_id"]:
            # Deliberately no message text: notifications outlive membership (and may be emailed).
            _notify(uid, acc, "subteam_message", f"New message in {acc.sub['name']}", f"{message['author_name']} posted in the “{acc.sub['name']}” sub-team chat.")
    return _public_message(message)


def _public_message(message: dict[str, Any]) -> dict[str, Any]:
    out = {k: message[k] for k in ("message_id", "sub_team_id", "user_id", "author_name", "content") if k in message}
    out["created_at"] = _iso(message.get("created_at"))
    return out


# --- role suggestions --------------------------------------------------------------------------------------------------


def _decisions(acc: Access) -> list[dict[str, Any]]:
    stored = acc.sub.get("role_decisions") if isinstance(acc.sub.get("role_decisions"), dict) else {}
    rows = []
    for uid in acc.member_ids:
        d = stored.get(uid)
        if isinstance(d, dict) and d.get("status"):
            rows.append({"user_id": uid, "name": acc.name_of(uid), "status": d["status"], "role": d.get("role")})
    return rows


def sub_team_roles(team_id: str, sub_team_id: str, user_id: str) -> dict[str, Any]:
    """The parent-team role engine, run on THIS sub-team's roster only.

    The roster is the sub-team's members that are still on the parent. Profile-based
    skills go through teams._role_fit_members, which re-reads every person's
    `share_with_teams` on this call and treats a missing or false value as "not
    shared" (the person is matched on skills typed for the team and marked
    info_unavailable). There is no fallback to the full parent roster."""
    acc = _viewer(team_id, sub_team_id, user_id)
    context = teams._context_for(acc.team)
    if context is None:
        raise TeamError("This team's project no longer exists - role suggestions need a real project to split into.")
    subset = [acc.roster[uid] for uid in acc.member_ids]
    members = [{"id": m["user_id"], "name": m.get("name") or m["user_id"], "skills": m.get("skills") or []} for m in subset]
    result = suggest_roles(context, members)
    result["role_fit"] = role_fit(context, teams._role_fit_members({"members": subset}, user_id))
    result["decisions"] = _decisions(acc)
    result["scope"] = {"sub_team_id": acc.sub["sub_team_id"], "name": acc.sub.get("name"), "member_count": len(subset)}
    return result


def set_role_decision(team_id: str, sub_team_id: str, user_id: str, status: Any, role: Any) -> list[dict[str, Any]]:
    """The caller's OWN decision, as in teams.service.set_role_decision. The owner
    cannot decide for anyone, and only a current sub-team member can decide."""
    acc = _member(team_id, sub_team_id, user_id, action="record a role decision")
    _require_active(acc)
    if status not in ROLE_DECISION_STATUSES:
        raise TeamError(f"'status' must be one of {', '.join(ROLE_DECISION_STATUSES)}.", status=400)
    if status in ("accepted", "custom") and role not in profile_service.TEAM_ROLES:
        raise TeamError("Choose one of the listed team roles.", status=400)
    if role is not None and role not in profile_service.TEAM_ROLES:
        raise TeamError("Choose one of the listed team roles.", status=400)
    decision = {"status": status, "role": role, "decided_at": _now()}
    db.sub_teams().update_one(
        {"sub_team_id": acc.sub["sub_team_id"], "members.user_id": user_id}, {"$set": {f"role_decisions.{user_id}": decision}}
    )
    acc.sub = {**acc.sub, "role_decisions": {**(acc.sub.get("role_decisions") or {}), user_id: decision}}
    return _decisions(acc)


def clear_role_decision(team_id: str, sub_team_id: str, user_id: str) -> list[dict[str, Any]]:
    acc = _member(team_id, sub_team_id, user_id, action="record a role decision")
    _require_active(acc)
    db.sub_teams().update_one({"sub_team_id": acc.sub["sub_team_id"]}, {"$unset": {f"role_decisions.{user_id}": ""}})
    (acc.sub.get("role_decisions") or {}).pop(user_id, None)
    return _decisions(acc)


# --- tasks -----------------------------------------------------------------------------------------------------------------


def _public_task(task: dict[str, Any], acc: Access) -> dict[str, Any]:
    assignee_id = task.get("assignee_id") if isinstance(task.get("assignee_id"), str) else None
    current = assignee_id in acc.member_ids
    return {
        "task_id": task["task_id"],
        "sub_team_id": task["sub_team_id"],
        "title": task.get("title"),
        "description": task.get("description") or "",
        "status": task.get("status") if task.get("status") in TASK_STATUSES else "todo",
        "assignee": {"user_id": assignee_id, "name": acc.name_of(assignee_id)} if current else None,
        # Assigned to someone who has since left: shown so the owner can reassign.
        "needs_reassignment": bool(assignee_id) and not current,
        "created_by": task.get("creator_id"),
        "created_at": _iso(task.get("created_at")),
        "updated_at": _iso(task.get("updated_at")),
        "can_update_status": (acc.is_owner or (current and assignee_id == acc.user_id)) and acc.sub.get("status") != "archived",
    }


def _assignee(value: Any, acc: Access) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or value not in acc.member_ids:
        raise TeamError("Tasks can only be assigned to members of this sub-team.", status=400)
    return value


def _task_status(value: Any) -> str:
    if value not in TASK_STATUSES:
        raise TeamError(f"'status' must be one of {', '.join(TASK_STATUSES)}.", status=400)
    return value


def list_tasks(team_id: str, sub_team_id: str, user_id: str) -> list[dict[str, Any]]:
    acc = _viewer(team_id, sub_team_id, user_id)
    rows = db.sub_team_tasks().find({"sub_team_id": acc.sub["sub_team_id"], "team_id": team_id}, {"_id": 0}).sort("created_at", 1).limit(MAX_TASKS)
    return [_public_task(t, acc) for t in rows if isinstance(t.get("task_id"), str)]


def create_task(team_id: str, sub_team_id: str, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    acc = _owner(team_id, sub_team_id, user_id)
    _require_active(acc)
    title = _text(payload.get("title"), "title", MAX_TITLE_CHARS, required=True)
    description = _text(payload.get("description"), "description", MAX_TASK_DESCRIPTION_CHARS, multiline=True)
    assignee = _assignee(payload.get("assignee_id"), acc)
    status = _task_status(payload["status"]) if "status" in payload else "todo"
    if db.sub_team_tasks().count_documents({"sub_team_id": acc.sub["sub_team_id"]}) >= MAX_TASKS:
        raise TeamError(f"A sub-team can have at most {MAX_TASKS} tasks.", status=400)
    now = _now()
    task = {
        "task_id": str(uuid.uuid4()), "team_id": team_id, "sub_team_id": acc.sub["sub_team_id"], "title": title,
        "description": description, "status": status, "creator_id": user_id, "assignee_id": assignee,
        "created_at": now, "updated_at": now,
    }
    db.sub_team_tasks().insert_one(task)
    if assignee and not _assignee_still_valid(team_id, acc.sub["sub_team_id"], assignee):
        db.sub_team_tasks().delete_one({"task_id": task["task_id"]})
        raise TeamError("Tasks can only be assigned to members of this sub-team.", status=400)
    if assignee and assignee != user_id:
        _notify(assignee, acc, "subteam_task", f"New task in {acc.sub['name']}", f"A task was assigned to you in the “{acc.sub['name']}” sub-team.")
    return _public_task(task, acc)


def _task_or_404(acc: Access, task_id: Any) -> dict[str, Any]:
    task = None
    if isinstance(task_id, str) and 0 < len(task_id) <= MAX_ID_CHARS:
        task = db.sub_team_tasks().find_one(
            {"task_id": task_id, "sub_team_id": acc.sub["sub_team_id"], "team_id": acc.team["team_id"]}
        )
    if task is None:
        raise TeamError("No task found.")
    return task


_OWNER_TASK_FIELDS = {"title", "description", "assignee_id", "status"}


def update_task(team_id: str, sub_team_id: str, user_id: str, task_id: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Owner: any of title/description/assignee_id/status. An assignee: `status` only,
    on their own task, and only while still a member of the sub-team and parent."""
    acc = _viewer(team_id, sub_team_id, user_id)
    task = _task_or_404(acc, task_id)
    unknown = set(payload) - _OWNER_TASK_FIELDS
    if unknown:
        raise TeamError(f"Unknown field(s): {', '.join(sorted(str(k)[:30] for k in unknown))}.", status=400)
    if not payload:
        raise TeamError("Nothing to update.", status=400)
    if not acc.is_owner:
        assignee_id = task.get("assignee_id")
        if not (acc.is_member and assignee_id == user_id):
            raise TeamError("Only the team owner or the person assigned can change this task.", status=403)
        if set(payload) != {"status"}:
            raise TeamError("You can only change the status of your own task.", status=403)
    _require_active(acc)

    updates: dict[str, Any] = {}
    if "title" in payload:
        updates["title"] = _text(payload["title"], "title", MAX_TITLE_CHARS, required=True)
    if "description" in payload:
        updates["description"] = _text(payload["description"], "description", MAX_TASK_DESCRIPTION_CHARS, multiline=True)
    if "assignee_id" in payload:
        updates["assignee_id"] = _assignee(payload["assignee_id"], acc)
    if "status" in payload:
        updates["status"] = _task_status(payload["status"])
    updates["updated_at"] = _now()
    db.sub_team_tasks().update_one({"task_id": task["task_id"], "sub_team_id": acc.sub["sub_team_id"]}, {"$set": updates})
    previous_assignee = task.get("assignee_id")
    new_assignee = updates.get("assignee_id")
    if new_assignee and not _assignee_still_valid(team_id, acc.sub["sub_team_id"], new_assignee):
        # They left between the check and the write: put back everything this call changed.
        db.sub_team_tasks().update_one(
            {"task_id": task["task_id"], "assignee_id": new_assignee},
            {"$set": {k: task.get(k) for k in updates if k != "updated_at"} | {"updated_at": task.get("updated_at")}},
        )
        raise TeamError("Tasks can only be assigned to members of this sub-team.", status=400)
    task = {**task, **updates}
    if "assignee_id" in payload and new_assignee and new_assignee != user_id and new_assignee != previous_assignee:
        _notify(new_assignee, acc, "subteam_task", f"Task assigned in {acc.sub['name']}", f"A task was assigned to you in the “{acc.sub['name']}” sub-team.")
    return _public_task(task, acc)


def delete_task(team_id: str, sub_team_id: str, user_id: str, task_id: Any, confirm: Any) -> dict[str, Any]:
    acc = _owner(team_id, sub_team_id, user_id)
    task = _task_or_404(acc, task_id)
    if confirm not in (True, "true"):
        raise TeamError("Deleting a task cannot be undone; send confirm=true.", status=400)
    db.sub_team_tasks().delete_one({"task_id": task["task_id"], "sub_team_id": acc.sub["sub_team_id"]})
    return {"deleted": True, "task_id": task["task_id"]}
