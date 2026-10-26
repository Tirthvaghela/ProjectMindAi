"""Team profile-sharing consent (Feature 6.1): `share_with_teams` on the profile,
honoured by role suggestions (Feature 3) and team formation (Feature 6).

Default is opt-OUT of sharing: a missing field - every profile saved before this
setting existed - means "not shared". Consent is rechecked on every response."""

from __future__ import annotations

import copy

import pytest

from db import client as db
from nlp import recommend
from profiles import service as profiles
from profiles.service import ProfileError, shares_with_teams, validate_fields

DOC = {
    "project_id": "pm-x", "title": "Campus Marketplace", "domain": "Web Development", "difficulty": "Intermediate",
    "technologies": ["React", "Node.js", "PostgreSQL"], "skills": ["REST API development"], "keywords": [],
}
SECRET_SKILL = "Zebra Wrangling"  # custom, never in any catalogue: easy to spot in any response


class _Fake:
    def __init__(self, docs):
        self.documents = docs


@pytest.fixture
def api(client, monkeypatch):
    monkeypatch.setattr(recommend, "get_retriever", lambda: _Fake({"pm-x": copy.deepcopy(DOC)}))
    db.projects().insert_one({**DOC})
    return client


def signup(client, email, name):
    res = client.post("/api/auth/signup", json={"email": email, "password": "correcthorse1", "name": name})
    assert res.status_code == 201
    return {"X-Auth-Token": res.get_json()["token"]}


def uid(client, h):
    return client.get("/api/auth/me", headers=h).get_json()["data"]["user_id"]


@pytest.fixture
def team_ctx(api):
    owner, member = signup(api, "owner@example.com", "Owner"), signup(api, "member@example.com", "Mem")
    team = api.post("/api/teams", json={"project_id": "pm-x", "name": "T"}, headers=owner).get_json()["data"]
    api.post("/api/teams/join", json={"invite_code": team["invite_code"]}, headers=member)
    return api, team["team_id"], owner, member


MEMBER_PROFILE = {
    "skills": [{"name": "React", "level": "Advanced"}, {"name": "CSS", "level": "Advanced"}, {"name": SECRET_SKILL, "level": "Advanced"}],
    "preferred_roles": ["Frontend Developer"], "interests": ["Web Development"],
    "experience": [{"title": "Secret gig", "description": "secret text", "technologies": ["Vue"]}],
    "learning_goals": ["secret goal"], "education": "secret school",
}


def fit_members(client, team_id, h):
    res = client.get(f"/api/teams/{team_id}/roles", headers=h)
    assert res.status_code == 200
    return {m["name"]: m for m in res.get_json()["data"]["role_fit"]["members"]}, res.get_json()["data"]


# --- the setting itself ----------------------------------------------------------------------


def test_default_is_not_shared_for_new_empty_and_pre_existing_profiles(api):
    h = signup(api, "a@example.com", "A")
    assert api.get("/api/profile", headers=h).get_json()["data"]["share_with_teams"] is False  # no profile at all
    api.put("/api/profile", json={"skills": ["React"]}, headers=h)
    assert api.get("/api/profile", headers=h).get_json()["data"]["share_with_teams"] is False  # new profile, not set

    # A profile document saved before the field existed (no key at all).
    db.profiles().insert_one({"user_id": "legacy", "skills": [{"name": "React", "level": "Advanced"}], "interests": []})
    legacy = profiles.get_profile("legacy")
    assert legacy["share_with_teams"] is False and shares_with_teams(legacy) is False
    assert "share_with_teams" not in db.profiles().find_one({"user_id": "legacy"})  # reading never writes or migrates


def test_only_an_explicit_true_counts_as_consent():
    assert shares_with_teams({"share_with_teams": True}) is True
    for value in (False, None, "true", 1, "yes", [], {}):
        assert shares_with_teams({"share_with_teams": value}) is False
    assert shares_with_teams(None) is False and shares_with_teams({}) is False


@pytest.mark.parametrize("bad", ["true", 1, 0, None, "yes", [], {}])
def test_setting_must_be_a_boolean(bad):
    with pytest.raises(ProfileError):
        validate_fields({"share_with_teams": bad})


def test_opt_in_and_out_round_trip_without_touching_other_fields(api):
    h = signup(api, "a@example.com", "A")
    api.put("/api/profile", json=MEMBER_PROFILE, headers=h)
    before = api.get("/api/profile", headers=h).get_json()["data"]
    on = api.put("/api/profile", json={"share_with_teams": True}, headers=h).get_json()["data"]
    assert on["share_with_teams"] is True
    off = api.put("/api/profile", json={"share_with_teams": False}, headers=h).get_json()["data"]
    assert off["share_with_teams"] is False
    strip = lambda d: {k: v for k, v in d.items() if k not in ("share_with_teams", "updated_at")}
    assert strip(off) == strip(before) == strip(on)


def test_toggling_alone_does_not_create_progress_or_change_completion(api):
    h = signup(api, "a@example.com", "A")
    data = api.put("/api/profile", json={"share_with_teams": True}, headers=h).get_json()["data"]
    assert data["completion"]["status"] == "not_started" and data["skills"] == []


def test_users_can_only_change_their_own_setting(api):
    alice, bob = signup(api, "alice@example.com", "Alice"), signup(api, "bob@example.com", "Bob")
    api.put("/api/profile", json={"skills": ["React"], "share_with_teams": True}, headers=alice)
    res = api.put("/api/profile", json={"share_with_teams": False, "user_id": uid(api, alice)}, headers=bob)
    assert res.status_code == 400
    assert api.get("/api/profile", headers=alice).get_json()["data"]["share_with_teams"] is True
    assert api.put("/api/profile", json={"share_with_teams": False}).status_code == 401
    api.put("/api/profile", json={"share_with_teams": False}, headers=bob)
    assert api.get("/api/profile", headers=alice).get_json()["data"]["share_with_teams"] is True


def test_deleting_the_profile_resets_consent(api):
    h = signup(api, "a@example.com", "A")
    api.put("/api/profile", json={"share_with_teams": True}, headers=h)
    api.delete("/api/profile", headers=h)
    assert api.get("/api/profile", headers=h).get_json()["data"]["share_with_teams"] is False


# --- Feature 3: role suggestions ----------------------------------------------------------------------


def test_teammates_cannot_see_or_use_a_profile_that_is_not_shared(team_ctx):
    api, team_id, owner, member = team_ctx
    api.put("/api/profile", json=MEMBER_PROFILE, headers=member)
    members, data = fit_members(api, team_id, owner)
    mem = members["Mem"]
    assert mem["suggested"] is None and mem["alternatives"] == []
    assert mem["source"] == "none" and mem["info_unavailable"] is True
    assert "No profile information is available" in mem["message"] and "says nothing about what this person can do" in mem["message"]
    text = str(data)
    # (role names and the project's own technologies legitimately appear: they describe the PROJECT, not this person)
    for leaked in (SECRET_SKILL, "CSS", "Vue", "secret", "member@example.com"):
        assert leaked not in text
    assert mem["profile_status"] == "not_started"


def test_withheld_profile_is_indistinguishable_from_no_profile(team_ctx):
    api, team_id, owner, member = team_ctx
    without, _ = fit_members(api, team_id, owner)
    api.put("/api/profile", json=MEMBER_PROFILE, headers=member)
    withheld, _ = fit_members(api, team_id, owner)
    assert without["Mem"] == withheld["Mem"]


def test_opting_in_shares_only_role_relevant_fields_and_opting_out_stops_it_immediately(team_ctx):
    api, team_id, owner, member = team_ctx
    api.put("/api/profile", json={**MEMBER_PROFILE, "share_with_teams": True}, headers=member)
    shared, data = fit_members(api, team_id, owner)
    assert shared["Mem"]["suggested"]["role"] == "Frontend Developer" and shared["Mem"]["source"] == "profile"
    assert "secret" not in str(data) and "info_unavailable" not in shared["Mem"]

    api.put("/api/profile", json={"share_with_teams": False}, headers=member)
    again, data = fit_members(api, team_id, owner)  # next response already respects the change
    assert again["Mem"]["suggested"] is None and SECRET_SKILL not in str(data)
    api.put("/api/profile", json={"share_with_teams": True}, headers=member)
    assert fit_members(api, team_id, owner)[0]["Mem"]["suggested"]["role"] == "Frontend Developer"


def test_a_user_always_sees_their_own_suggestions_and_their_sharing_state(team_ctx):
    api, team_id, owner, member = team_ctx
    api.put("/api/profile", json=MEMBER_PROFILE, headers=member)
    mine, _ = fit_members(api, team_id, member)
    assert mine["Mem"]["suggested"]["role"] == "Frontend Developer" and mine["Mem"]["source"] == "profile"
    assert mine["Mem"]["profile_shared"] is False and "info_unavailable" not in mine["Mem"]
    theirs, _ = fit_members(api, team_id, owner)
    assert "profile_shared" not in theirs["Mem"]  # another member never sees the flag


def test_manual_team_skills_still_work_and_stay_labelled_when_the_profile_is_withheld(team_ctx):
    api, team_id, owner, member = team_ctx
    api.put("/api/profile", json=MEMBER_PROFILE, headers=member)
    api.post(f"/api/teams/{team_id}/skills", json={"skills": ["nodejs", "express"]}, headers=member)
    members, data = fit_members(api, team_id, owner)
    mem = members["Mem"]
    assert mem["source"] == "manual" and mem["suggested"]["role"] == "Backend Developer"
    assert {s["name"] for s in mem["suggested"]["supporting_skills"]} == {"Node.js", "Express.js"}
    assert all(s["level"] is None for s in mem["suggested"]["supporting_skills"])
    assert "preferred" not in mem["suggested"]["explanation"] and SECRET_SKILL not in str(data)
    assert mem["suggested"]["preferred"] is False  # the profile's preferred role is withheld too


def test_role_decisions_and_membership_are_unaffected_by_consent(team_ctx):
    api, team_id, owner, member = team_ctx
    api.put("/api/profile", json=MEMBER_PROFILE, headers=member)
    assert api.put(f"/api/teams/{team_id}/roles/mine", json={"status": "custom", "role": "QA / Test Engineer"}, headers=member).status_code == 200
    _, data = fit_members(api, team_id, owner)
    assert [(d["name"], d["status"], d["role"]) for d in data["decisions"]] == [("Mem", "custom", "QA / Test Engineer")]
    team = api.get(f"/api/teams/{team_id}", headers=owner).get_json()["data"]
    assert len(team["members"]) == 2


def test_legacy_module_assignment_is_unchanged(team_ctx):
    api, team_id, owner, member = team_ctx
    api.put("/api/profile", json=MEMBER_PROFILE, headers=member)
    data = api.get(f"/api/teams/{team_id}/roles", headers=owner).get_json()["data"]
    assert {"roles", "assignments", "unassigned_members", "unfilled_roles"} <= set(data)
    assert all(SECRET_SKILL not in str(data[k]) for k in ("assignments", "unassigned_members"))


# --- Feature 6: team formation ----------------------------------------------------------------------------


def formation(client, h, **body):
    return client.post("/api/teams/formation", json={"project_id": "pm-x", **body}, headers=h)


def test_formation_excludes_unshared_profiles_and_explains_neutrally(team_ctx):
    api, team_id, owner, member = team_ctx
    api.put("/api/profile", json=MEMBER_PROFILE, headers=member)
    api.put("/api/profile", json={"skills": [{"name": "Node.js", "level": "Advanced"}], "share_with_teams": True}, headers=owner)
    body = formation(api, owner, team_id=team_id, team_size=2).get_json()["data"]
    assert [m["name"] for t in body["teams"] for m in t["members"]] == ["Owner"] * len(body["teams"])
    assert body["pool"]["not_matched"] == [{
        "name": "Mem", "source": "none",
        "reason": "No profile information is available for matching (it has not been shared with the team, or has not been added). "
                  "That says nothing about what this person can do.",
    }]
    text = str(body)
    for leaked in (SECRET_SKILL, "CSS", "Vue", "secret", "member@example.com"):
        assert leaked not in text
    assert "lack" not in text.lower()


def test_formation_uses_a_teammate_only_after_they_opt_in(team_ctx):
    api, team_id, owner, member = team_ctx
    api.put("/api/profile", json={"skills": [{"name": "React", "level": "Advanced"}], "share_with_teams": False}, headers=member)
    api.put("/api/profile", json={"skills": [{"name": "Node.js", "level": "Advanced"}]}, headers=owner)
    assert formation(api, owner, team_id=team_id, team_size=2).get_json()["data"]["pool"]["matchable"] == 1  # only the caller
    names = lambda b: sorted({m["name"] for t in b["teams"] for m in t["members"]})
    before = formation(api, owner, team_id=team_id, team_size=2).get_json()["data"]
    assert "Mem" not in names(before)
    api.put("/api/profile", json={"share_with_teams": True}, headers=member)
    after = formation(api, owner, team_id=team_id, team_size=2).get_json()["data"]
    assert "Mem" in names(after)
    api.put("/api/profile", json={"share_with_teams": False}, headers=member)
    assert "Mem" not in names(formation(api, owner, team_id=team_id, team_size=2).get_json()["data"])


def test_formation_still_uses_skills_a_member_typed_for_the_team_and_labels_them(team_ctx):
    api, team_id, owner, member = team_ctx
    api.put("/api/profile", json=MEMBER_PROFILE, headers=member)
    api.post(f"/api/teams/{team_id}/skills", json={"skills": ["postgres"]}, headers=member)
    body = formation(api, owner, team_id=team_id, team_size=1).get_json()["data"]
    mem = next(m for t in body["teams"] for m in t["members"] if m["name"] == "Mem")
    assert mem["source"] == "manual" and [c["skill"] for c in mem["contributes"]] == ["PostgreSQL"]
    assert all(c["level"] is None for c in mem["contributes"]) and SECRET_SKILL not in str(body)


def test_the_caller_is_always_matched_on_their_own_profile(team_ctx):
    api, team_id, owner, member = team_ctx
    api.put("/api/profile", json={"skills": [{"name": "React", "level": "Advanced"}], "share_with_teams": False}, headers=member)
    for kwargs in ({}, {"team_id": team_id}):
        body = formation(api, member, team_size=1, **kwargs).get_json()["data"]
        mem = next(m for t in body["teams"] for m in t["members"] if m["name"] == "Mem")
        assert mem["source"] == "profile" and [c["skill"] for c in mem["contributes"]] == ["React"]


def test_manual_candidates_are_unaffected_and_source_labelled(team_ctx):
    api, team_id, owner, member = team_ctx
    api.put("/api/profile", json=MEMBER_PROFILE, headers=member)
    body = formation(api, owner, team_id=team_id, include_self=False, team_size=1,
                     candidates=[{"name": "Friend", "skills": ["nodejs", "react"]}]).get_json()["data"]
    friend = next(m for t in body["teams"] for m in t["members"] if m["name"] == "Friend")
    assert friend["source"] == "manual" and friend["user_id"] is None
    assert {c["skill"] for c in friend["contributes"]} == {"Node.js", "React"}


def test_no_leak_through_alternatives_or_comparisons(team_ctx):
    api, team_id, owner, member = team_ctx
    api.put("/api/profile", json=MEMBER_PROFILE, headers=member)
    api.put("/api/profile", json={"skills": [{"name": "Node.js", "level": "Advanced"}], "share_with_teams": True}, headers=owner)
    body = formation(api, owner, team_id=team_id, candidates=[{"name": "F1", "skills": ["react"]}, {"name": "F2", "skills": ["postgres"]}]).get_json()["data"]
    assert len(body["teams"]) >= 1
    for t in body["teams"]:
        blob = str(t)
        assert SECRET_SKILL not in blob and "secret" not in blob and "Mem" not in [m["name"] for m in t["members"]]
    assert SECRET_SKILL not in str(body["notes"]) + str(body["limitations"]) + str(body["pool"])


def test_errors_do_not_reveal_consent_or_profile_details(team_ctx):
    api, team_id, owner, member = team_ctx
    api.put("/api/profile", json=MEMBER_PROFILE, headers=member)
    outsider = signup(api, "x@example.com", "X")
    for res in (formation(api, outsider, team_id=team_id), formation(api, owner, team_id="nope"), formation(api, owner, team_id=team_id, team_size=0)):
        assert res.status_code in (400, 404)
        text = res.get_data(as_text=True)
        assert SECRET_SKILL not in text and "share" not in text.lower() and "consent" not in text.lower()


def test_formation_with_consenting_members_matches_previous_behaviour(team_ctx):
    api, team_id, owner, member = team_ctx
    api.put("/api/profile", json={"skills": [{"name": "React", "level": "Advanced"}], "share_with_teams": True}, headers=owner)
    api.put("/api/profile", json={"skills": [{"name": "Node.js", "level": "Advanced"}], "share_with_teams": True}, headers=member)
    body = formation(api, owner, team_id=team_id, team_size=2).get_json()["data"]
    best = next(t for t in body["teams"] if t["key"] == "best_coverage")
    assert sorted(m["name"] for m in best["members"]) == ["Mem", "Owner"] and body["pool"]["not_matched"] == []
    assert best["requirements"]["solid"] == 2
