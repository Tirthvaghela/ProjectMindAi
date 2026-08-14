import pytest
from pymongo.errors import DuplicateKeyError

from db import client as db
from teams.service import (
    TeamError,
    create_team,
    get_team,
    join_team,
    list_messages,
    list_my_teams,
    post_message,
    remove_member,
    set_member_skills,
    team_roles,
    update_team,
)

OWNER = {"user_id": "u-owner", "name": "Owner", "email": "owner@example.com"}
JOINER = {"user_id": "u-joiner", "name": "Joiner", "email": "joiner@example.com"}
OUTSIDER = {"user_id": "u-outsider", "name": "Outsider", "email": "outsider@example.com"}


@pytest.fixture
def project(mongo_test_db):
    doc = {
        "project_id": "pm-test",
        "title": "Test Project",
        "description": "A test project for the team workspace.",
        "domain": "Artificial Intelligence",
        "difficulty": "Intermediate",
        "duration_weeks": 10,
        "technologies": ["Python", "Flask"],
        "skills": ["REST API design"],
    }
    db.projects().insert_one(doc)
    return doc


def test_create_team_requires_a_real_project(mongo_test_db):
    with pytest.raises(TeamError, match="No project"):
        create_team("My Team", OWNER, project_id="does-not-exist")


def test_create_team_makes_the_owner_the_first_member(project):
    team = create_team("My Team", OWNER, project_id=project["project_id"])
    assert len(team["members"]) == 1
    assert team["members"][0]["user_id"] == OWNER["user_id"]
    assert team["owner_user_id"] == OWNER["user_id"]
    assert len(team["invite_code"]) == 6


def test_join_team_adds_a_second_member(project):
    team = create_team("My Team", OWNER, project_id=project["project_id"])
    joined = join_team(team["invite_code"], JOINER)
    member_ids = {m["user_id"] for m in joined["members"]}
    assert member_ids == {OWNER["user_id"], JOINER["user_id"]}


def test_joining_twice_does_not_duplicate_membership(project):
    team = create_team("My Team", OWNER, project_id=project["project_id"])
    join_team(team["invite_code"], JOINER)
    joined_again = join_team(team["invite_code"], JOINER)
    assert len(joined_again["members"]) == 2


def test_join_team_rejects_unknown_invite_code(mongo_test_db):
    with pytest.raises(TeamError, match="No team found"):
        join_team("ZZZZZZ", JOINER)


def test_only_the_owner_gets_the_invite_code_back(project):
    # The invite code is a credential that grants membership — only the
    # owner (the one meant to be sharing it) should ever see it. A member
    # who joined via that same code must not get it echoed back to them,
    # whether from the join response itself or any later read of the team.
    team = create_team("My Team", OWNER, project_id=project["project_id"])
    assert "invite_code" in team

    joined = join_team(team["invite_code"], JOINER)
    assert "invite_code" not in joined

    owner_view = get_team(team["team_id"], OWNER["user_id"])
    assert owner_view["invite_code"] == team["invite_code"]

    joiner_view = get_team(team["team_id"], JOINER["user_id"])
    assert "invite_code" not in joiner_view

    owner_list = list_my_teams(OWNER["user_id"])
    assert owner_list[0]["invite_code"] == team["invite_code"]

    joiner_list = list_my_teams(JOINER["user_id"])
    assert "invite_code" not in joiner_list[0]


# --- races -----------------------------------------------------------------
# Same technique as test_auth.py's signup/update_profile race tests: rather
# than needing genuinely concurrent threads to reproduce a race against the
# real unique index, these proxy the collection so the one write in question
# raises DuplicateKeyError exactly as Mongo's index would once two racing
# writers collided — db/client.py's uq_team_member / uq_invite_code indexes
# are the actual backstop; these confirm the code that has to survive them.


class _DuplicateKeyOnMemberPush:
    """Passes reads through to the real collection. The one update_one call
    performs the *other*, already-racing request's push for real — as if it
    had already landed a moment earlier — then raises DuplicateKeyError, the
    same failure this request's own push would get from the unique
    (team_id, members.user_id) index colliding with that write."""

    def __init__(self, real, winning_push):
        self._real = real
        self._winning_push = winning_push

    def find_one(self, *args, **kwargs):
        return self._real.find_one(*args, **kwargs)

    def update_one(self, *args, **kwargs):
        self._real.update_one(*self._winning_push)
        raise DuplicateKeyError("E11000 duplicate key error collection: test.teams index: uq_team_member")


def test_join_team_converts_a_racing_duplicate_membership_into_a_clean_result(monkeypatch, project):
    team = create_team("My Team", OWNER, project_id=project["project_id"])
    real_collection = db.teams()
    winning_push = (
        {"team_id": team["team_id"]},
        {"$push": {"members": {"user_id": JOINER["user_id"], "name": JOINER["name"], "email": JOINER["email"]}}},
    )
    monkeypatch.setattr(db, "teams", lambda: _DuplicateKeyOnMemberPush(real_collection, winning_push))

    result = join_team(team["invite_code"], JOINER)

    # The member landed (via the "other" request's write) and the response
    # reflects it accurately rather than the stale pre-race snapshot.
    assert {m["user_id"] for m in result["members"]} == {OWNER["user_id"], JOINER["user_id"]}
    # The request that lost the race must not send its own round of
    # "X joined" notifications — the winner already did.
    assert db.notifications().count_documents({}) == 0


class _DuplicateKeyOnInsertThenSucceeds:
    """First insert_one raises DuplicateKeyError, as if the freshly drawn
    invite_code collided with an existing team's; the retry's insert_one
    (with a newly regenerated code) goes through to the real collection."""

    def __init__(self, real):
        self._real = real
        self._calls = 0

    def find_one(self, *args, **kwargs):
        return self._real.find_one(*args, **kwargs)

    def insert_one(self, *args, **kwargs):
        self._calls += 1
        if self._calls == 1:
            raise DuplicateKeyError("E11000 duplicate key error collection: test.teams index: uq_invite_code")
        return self._real.insert_one(*args, **kwargs)


def test_create_team_retries_once_on_a_racing_invite_code_collision(monkeypatch, project):
    real_collection = db.teams()
    # One shared instance, not "lambda: Proxy(...)" — the latter would hand
    # back a fresh call counter every time db.teams() is called inside the
    # retry loop, never actually accumulating past 1.
    proxy = _DuplicateKeyOnInsertThenSucceeds(real_collection)
    monkeypatch.setattr(db, "teams", lambda: proxy)

    team = create_team("My Team", OWNER, project_id=project["project_id"])

    assert len(team["invite_code"]) == 6
    assert real_collection.find_one({"team_id": team["team_id"]})["invite_code"] == team["invite_code"]


class _AlwaysDuplicateKeyOnInsert:
    def __init__(self, real):
        self._real = real

    def find_one(self, *args, **kwargs):
        return self._real.find_one(*args, **kwargs)

    def insert_one(self, *args, **kwargs):
        raise DuplicateKeyError("E11000 duplicate key error collection: test.teams index: uq_invite_code")


def test_create_team_gives_up_after_repeated_invite_code_collisions(monkeypatch, project):
    real_collection = db.teams()
    monkeypatch.setattr(db, "teams", lambda: _AlwaysDuplicateKeyOnInsert(real_collection))

    with pytest.raises(TeamError, match="Could not create the team"):
        create_team("My Team", OWNER, project_id=project["project_id"])


def test_non_member_cannot_read_the_team(project):
    team = create_team("My Team", OWNER, project_id=project["project_id"])
    with pytest.raises(TeamError, match="not a member"):
        get_team(team["team_id"], JOINER["user_id"])


def test_non_member_cannot_post_a_message(project):
    team = create_team("My Team", OWNER, project_id=project["project_id"])
    with pytest.raises(TeamError, match="not a member"):
        post_message(team["team_id"], JOINER, "hi")


def test_member_can_post_and_read_messages_in_order(project):
    team = create_team("My Team", OWNER, project_id=project["project_id"])
    join_team(team["invite_code"], JOINER)

    post_message(team["team_id"], OWNER, "first")
    post_message(team["team_id"], JOINER, "second")

    messages = list_messages(team["team_id"], OWNER["user_id"])
    assert [m["content"] for m in messages] == ["first", "second"]


# --- Team project context (section 5) ------------------------------------


def test_team_carries_the_full_project_context_not_just_the_title(project):
    # "Team is working on X" must be enough to ground architecture/backend/
    # timeline questions — that needs description/technologies/difficulty/
    # duration, not just a title, and it must come from the live catalogue
    # rather than a duplicated snapshot (see the module's own docstring).
    team = create_team("My Team", OWNER, project_id=project["project_id"])
    assert team["project"]["description"] == project["description"]
    assert team["project"]["technologies"] == project["technologies"]
    assert team["project"]["difficulty"] == project["difficulty"]
    assert team["project"]["duration_weeks"] == project["duration_weeks"]
    assert team["project"]["skills"] == project["skills"]
    # Back-compat top-level fields the existing frontend already reads.
    assert team["project_title"] == project["title"]
    assert team["domain"] == project["domain"]


def test_team_project_context_reflects_catalogue_edits_not_a_stale_snapshot(project):
    team = create_team("My Team", OWNER, project_id=project["project_id"])
    db.projects().update_one({"project_id": project["project_id"]}, {"$set": {"difficulty": "Advanced"}})
    refreshed = get_team(team["team_id"], OWNER["user_id"])
    assert refreshed["project"]["difficulty"] == "Advanced"


def test_get_team_stays_usable_after_its_project_is_deleted(project):
    # A team must never become inaccessible just because its catalogue
    # project was later removed — only the live project context should
    # become unavailable (section 11: "deleted project" error handling).
    team = create_team("My Team", OWNER, project_id=project["project_id"])
    db.projects().delete_one({"project_id": project["project_id"]})

    refreshed = get_team(team["team_id"], OWNER["user_id"])
    assert refreshed["project"] is None
    assert refreshed["domain"] is None
    assert refreshed["project_title"] == project["title"]  # falls back to the creation-time snapshot
    assert refreshed["members"][0]["user_id"] == OWNER["user_id"]  # the team itself is unaffected


def test_list_my_teams_batches_project_context_across_teams(mongo_test_db):
    project_a = {"project_id": "pm-a", "title": "Project A", "domain": "Web Development"}
    project_b = {"project_id": "pm-b", "title": "Project B", "domain": "Data Science"}
    db.projects().insert_many([project_a, project_b])

    create_team("Team A", OWNER, project_id="pm-a")
    create_team("Team B", OWNER, project_id="pm-b")

    teams = {t["project_id"]: t for t in list_my_teams(OWNER["user_id"])}
    assert teams["pm-a"]["domain"] == "Web Development"
    assert teams["pm-b"]["domain"] == "Data Science"


# --- Update team (section 2/3 — owner-only) -------------------------------


def test_owner_can_rename_the_team(project):
    team = create_team("My Team", OWNER, project_id=project["project_id"])
    updated = update_team(team["team_id"], OWNER["user_id"], "Renamed Team")
    assert updated["name"] == "Renamed Team"
    assert get_team(team["team_id"], OWNER["user_id"])["name"] == "Renamed Team"


def test_non_owner_member_cannot_rename_the_team(project):
    team = create_team("My Team", OWNER, project_id=project["project_id"])
    join_team(team["invite_code"], JOINER)
    with pytest.raises(TeamError, match="owner") as excinfo:
        update_team(team["team_id"], JOINER["user_id"], "Hijacked Name")
    assert excinfo.value.status == 403


def test_non_member_cannot_rename_the_team(project):
    team = create_team("My Team", OWNER, project_id=project["project_id"])
    with pytest.raises(TeamError, match="not a member") as excinfo:
        update_team(team["team_id"], OUTSIDER["user_id"], "Hijacked Name")
    assert excinfo.value.status == 404


def test_rename_rejects_an_empty_name(project):
    team = create_team("My Team", OWNER, project_id=project["project_id"])
    with pytest.raises(TeamError, match="required") as excinfo:
        update_team(team["team_id"], OWNER["user_id"], "   ")
    assert excinfo.value.status == 400


def test_rename_rejects_an_overlong_name(project):
    team = create_team("My Team", OWNER, project_id=project["project_id"])
    with pytest.raises(TeamError, match="80 characters") as excinfo:
        update_team(team["team_id"], OWNER["user_id"], "x" * 81)
    assert excinfo.value.status == 400


# --- Remove member (section 3 — owner kicks, member leaves) --------------


def test_owner_can_remove_another_member(project):
    team = create_team("My Team", OWNER, project_id=project["project_id"])
    join_team(team["invite_code"], JOINER)
    updated = remove_member(team["team_id"], OWNER["user_id"], JOINER["user_id"])
    assert {m["user_id"] for m in updated["members"]} == {OWNER["user_id"]}


def test_member_can_remove_themselves(project):
    team = create_team("My Team", OWNER, project_id=project["project_id"])
    join_team(team["invite_code"], JOINER)
    updated = remove_member(team["team_id"], JOINER["user_id"], JOINER["user_id"])
    assert {m["user_id"] for m in updated["members"]} == {OWNER["user_id"]}


def test_non_owner_cannot_remove_another_member(project):
    team = create_team("My Team", OWNER, project_id=project["project_id"])
    join_team(team["invite_code"], JOINER)
    third = {"user_id": "u-third", "name": "Third", "email": "third@example.com"}
    join_team(team["invite_code"], third)

    with pytest.raises(TeamError, match="owner") as excinfo:
        remove_member(team["team_id"], JOINER["user_id"], third["user_id"])
    assert excinfo.value.status == 403


def test_owner_cannot_remove_themselves(project):
    # Leaving requires transferring ownership first, which this deliberately
    # doesn't try to solve — a team must always have exactly one owner.
    team = create_team("My Team", OWNER, project_id=project["project_id"])
    with pytest.raises(TeamError, match="owner cannot be removed") as excinfo:
        remove_member(team["team_id"], OWNER["user_id"], OWNER["user_id"])
    assert excinfo.value.status == 400


def test_non_owner_cannot_remove_the_owner_either(project):
    # A non-owner is stopped by the "only the owner can remove someone else"
    # rule before the code ever gets to check whether the target is the
    # owner — so this is a 403, not the 400 the self-removal case gets.
    team = create_team("My Team", OWNER, project_id=project["project_id"])
    join_team(team["invite_code"], JOINER)
    with pytest.raises(TeamError, match="owner") as excinfo:
        remove_member(team["team_id"], JOINER["user_id"], OWNER["user_id"])
    assert excinfo.value.status == 403


def test_removing_a_non_member_target_fails(project):
    team = create_team("My Team", OWNER, project_id=project["project_id"])
    with pytest.raises(TeamError, match="not a member of this team"):
        remove_member(team["team_id"], OWNER["user_id"], "u-never-joined")


def test_outsider_cannot_remove_a_member(project):
    team = create_team("My Team", OWNER, project_id=project["project_id"])
    join_team(team["invite_code"], JOINER)
    with pytest.raises(TeamError, match="not a member") as excinfo:
        remove_member(team["team_id"], OUTSIDER["user_id"], JOINER["user_id"])
    assert excinfo.value.status == 404


# --- Data isolation / team switching (sections 8/9) -----------------------


def test_teams_are_isolated_from_each_other(mongo_test_db):
    project_a = {"project_id": "pm-a", "title": "Project A"}
    project_b = {"project_id": "pm-b", "title": "Project B"}
    db.projects().insert_many([project_a, project_b])

    team_a = create_team("Team A", OWNER, project_id="pm-a")
    team_b = create_team("Team B", JOINER, project_id="pm-b")

    # Switching from Team A to Team B must never leak A's members, project,
    # or messages into B's response — each read is independently scoped.
    fetched_b = get_team(team_b["team_id"], JOINER["user_id"])
    assert fetched_b["team_id"] == team_b["team_id"]
    assert fetched_b["project_id"] == "pm-b"
    assert {m["user_id"] for m in fetched_b["members"]} == {JOINER["user_id"]}

    with pytest.raises(TeamError, match="not a member"):
        get_team(team_a["team_id"], JOINER["user_id"])


def test_list_my_teams_only_returns_teams_the_user_belongs_to(mongo_test_db):
    project_a = {"project_id": "pm-a", "title": "Project A"}
    project_b = {"project_id": "pm-b", "title": "Project B"}
    db.projects().insert_many([project_a, project_b])

    create_team("Team A", OWNER, project_id="pm-a")
    create_team("Team B", JOINER, project_id="pm-b")

    owner_teams = list_my_teams(OWNER["user_id"])
    assert [t["project_id"] for t in owner_teams] == ["pm-a"]


def test_user_belonging_to_two_teams_sees_both_without_cross_contamination(mongo_test_db):
    project_a = {"project_id": "pm-a", "title": "Project A"}
    project_b = {"project_id": "pm-b", "title": "Project B"}
    db.projects().insert_many([project_a, project_b])

    team_a = create_team("Team A", OWNER, project_id="pm-a")
    team_b = create_team("Team B", OWNER, project_id="pm-b")
    join_team(team_b["invite_code"], JOINER)

    teams = list_my_teams(OWNER["user_id"])
    assert {t["team_id"] for t in teams} == {team_a["team_id"], team_b["team_id"]}
    team_a_result = next(t for t in teams if t["team_id"] == team_a["team_id"])
    team_b_result = next(t for t in teams if t["team_id"] == team_b["team_id"])
    assert len(team_a_result["members"]) == 1  # JOINER never joined Team A
    assert len(team_b_result["members"]) == 2


# --- Member skills / team roles (section 5 — "who should work on the backend?") ---


def test_setting_own_skills_only_changes_the_callers_own_membership(project):
    team = create_team("My Team", OWNER, project_id=project["project_id"])
    join_team(team["invite_code"], JOINER)

    updated = set_member_skills(team["team_id"], OWNER["user_id"], ["Python", "pandas"])
    by_id = {m["user_id"]: m for m in updated["members"]}
    assert by_id[OWNER["user_id"]]["skills"] == ["Python", "pandas"]
    assert by_id[JOINER["user_id"]].get("skills", []) == []


def test_non_member_cannot_set_skills(project):
    team = create_team("My Team", OWNER, project_id=project["project_id"])
    with pytest.raises(TeamError, match="not a member"):
        set_member_skills(team["team_id"], OUTSIDER["user_id"], ["Python"])


def test_team_roles_uses_the_teams_real_project_and_roster(project):
    # project fixture's domain is Artificial Intelligence, whose modules
    # split cleanly into a Data/ML role and a Frontend/UI role — see
    # nlp/team_builder.py's own test suite for the same mapping.
    team = create_team("My Team", OWNER, project_id=project["project_id"])
    join_team(team["invite_code"], JOINER)
    set_member_skills(team["team_id"], OWNER["user_id"], ["Python", "TensorFlow"])
    set_member_skills(team["team_id"], JOINER["user_id"], ["React", "CSS"])

    result = team_roles(team["team_id"], OWNER["user_id"])
    assert result["project_id"] == project["project_id"]
    # A member can hold more than one role now that every module always
    # gets an owner (nlp/team_builder.py) — keep each member's first
    # (best-fit, pass-1) assignment rather than a later leftover one.
    by_name = {}
    for a in result["assignments"]:
        by_name.setdefault(a["member"], a)
    assert by_name[OWNER["name"]]["category"] == "Data / ML"
    assert by_name[JOINER["name"]]["category"] == "Frontend / UI"


def test_team_roles_reflects_catalogue_edits_not_a_stale_project_snapshot(project):
    team = create_team("My Team", OWNER, project_id=project["project_id"])
    before = team_roles(team["team_id"], OWNER["user_id"])["roles"]
    db.projects().update_one({"project_id": project["project_id"]}, {"$set": {"domain": "Web Development"}})
    after = team_roles(team["team_id"], OWNER["user_id"])["roles"]
    assert after != before


def test_team_roles_fails_once_the_project_is_deleted(project):
    team = create_team("My Team", OWNER, project_id=project["project_id"])
    db.projects().delete_one({"project_id": project["project_id"]})
    with pytest.raises(TeamError, match="no longer exists"):
        team_roles(team["team_id"], OWNER["user_id"])


def test_non_member_cannot_get_team_roles(project):
    team = create_team("My Team", OWNER, project_id=project["project_id"])
    with pytest.raises(TeamError, match="not a member"):
        team_roles(team["team_id"], OUTSIDER["user_id"])


# --- Idea-backed teams (a generated idea, not a catalogue project) ---------
#
# A generated idea is never written to Mongo (nlp/ai_assistant.py's module
# docstring), so it has no project_id to key a team on the way a catalogue
# project does — create_team(idea=...) snapshots the idea's own fields onto
# the team document itself instead, and every other operation (join, roles,
# messages, rename, membership) works identically afterwards. No mongo_test_db
# project fixture needed here — that's the whole point.

IDEA = {
    "name": "Smart Campus Notes",
    "domain": "Artificial Intelligence",
    "difficulty": "Intermediate",
    "duration_weeks": 10,
    "technologies": ["Python", "FastAPI", "React"],
    "problem": "Students lose track of scattered lecture notes.",
    "solution": "A unifying, searchable notes hub with AI summaries.",
}


def test_create_team_requires_exactly_one_of_project_id_or_idea(mongo_test_db):
    with pytest.raises(TeamError, match="exactly one"):
        create_team("My Team", OWNER)
    with pytest.raises(TeamError, match="exactly one"):
        create_team("My Team", OWNER, project_id="pm-test", idea=IDEA)


def test_create_idea_team_requires_a_named_idea(mongo_test_db):
    with pytest.raises(TeamError, match="must have a 'name'"):
        create_team("My Team", OWNER, idea={**IDEA, "name": ""})


def test_create_idea_team_snapshots_the_idea_and_needs_no_catalogue_record(mongo_test_db):
    team = create_team("My Team", OWNER, idea=IDEA)
    assert team["project_id"] is None
    assert team["idea"]["name"] == IDEA["name"]
    assert team["idea"]["technologies"] == IDEA["technologies"]
    assert team["project_title"] == IDEA["name"]
    assert team["domain"] == IDEA["domain"]
    # project_id-shaped view of the idea (nlp/generator.py:idea_doc), for the
    # same rendering the catalogue-project case already uses.
    assert team["project"]["project_id"] is None
    assert team["project"]["title"] == IDEA["name"]
    assert team["project"]["technologies"] == IDEA["technologies"]


def test_idea_team_survives_a_second_read_with_no_catalogue_lookup(mongo_test_db):
    # Unlike a catalogue-backed team (re-read live from Mongo every time —
    # see _project_context), an idea-backed team's context always comes from
    # its own stored snapshot, so a later read never depends on anything
    # else still existing.
    team = create_team("My Team", OWNER, idea=IDEA)
    fetched = get_team(team["team_id"], OWNER["user_id"])
    assert fetched["idea"]["name"] == IDEA["name"]
    assert fetched["project"]["title"] == IDEA["name"]


def test_idea_team_join_and_messages_work_the_same_as_a_project_team(mongo_test_db):
    team = create_team("My Team", OWNER, idea=IDEA)
    joined = join_team(team["invite_code"], JOINER)
    assert {m["user_id"] for m in joined["members"]} == {OWNER["user_id"], JOINER["user_id"]}

    message = post_message(team["team_id"], JOINER, "Hello team")
    assert list_messages(team["team_id"], OWNER["user_id"])[-1]["message_id"] == message["message_id"]


def test_idea_team_roles_uses_the_ideas_domain(mongo_test_db):
    team = create_team("My Team", OWNER, idea=IDEA)
    set_member_skills(team["team_id"], OWNER["user_id"], ["Python", "TensorFlow"])

    result = team_roles(team["team_id"], OWNER["user_id"])
    assert result["title"] == IDEA["name"]
    assert any(a["member"] == OWNER["name"] for a in result["assignments"])


def test_idea_team_rename_and_leave_work_the_same_as_a_project_team(mongo_test_db):
    team = create_team("My Team", OWNER, idea=IDEA)
    join_team(team["invite_code"], JOINER)

    renamed = update_team(team["team_id"], OWNER["user_id"], "Renamed")
    assert renamed["name"] == "Renamed"

    left = remove_member(team["team_id"], JOINER["user_id"], JOINER["user_id"])
    assert {m["user_id"] for m in left["members"]} == {OWNER["user_id"]}


def test_list_my_teams_mixes_project_and_idea_backed_teams(mongo_test_db):
    db.projects().insert_one({"project_id": "pm-mixed", "title": "Mixed Project"})
    project_team = create_team("Project Team", OWNER, project_id="pm-mixed")
    idea_team = create_team("Idea Team", OWNER, idea=IDEA)

    teams = {t["team_id"]: t for t in list_my_teams(OWNER["user_id"])}
    assert teams[project_team["team_id"]]["project_title"] == "Mixed Project"
    assert teams[idea_team["team_id"]]["project_title"] == IDEA["name"]
    assert teams[idea_team["team_id"]]["project_id"] is None
