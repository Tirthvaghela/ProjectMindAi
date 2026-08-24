"""HTTP-level tests for routes/search.py — the request/response contract
(validation, status codes, envelope shape, device isolation, error mapping)
rather than the ranking/scoring logic underneath it, which is already
covered directly against nlp/recommend.py (test_recommend.py,
test_evaluation_engine.py) and nlp/similarity.py (test_similarity.py).

Two of these routes (skill_gap, similar) resolve their project doc from the
in-memory retriever's own `.documents` (nlp/recommend.py:get_retriever()) —
a module-level singleton built lazily on first use, once, for the whole test
process. Relying on it reflecting the real catalogue is NOT safe here: the
`mongo_test_db` fixture repoints config.MONGO_DB at a throwaway, per-session
database before most tests run, so whichever test in the whole suite happens
to trigger the retriever's first build may build it against an empty/unlike
database rather than the real 500-project catalogue — exactly the pitfall
test_recommend.py's own module docstring calls out. Their success-path cases
below monkeypatch `recommend.get_retriever`/`recommend.similar` directly,
the same way test_recommend.py does, rather than depending on that build
order. The rest (team-builder, timeline-predict, resume-suggest's
vocabulary) do a direct `db.projects().find_one(...)`, which *is* redirected
to the test database by `mongo_test_db` — those use an inserted fixture
project instead.
"""

from __future__ import annotations

import pytest

from db import client as db
from nlp import recommend
from nlp.similarity import ScoredProject

PROJECT = {
    "project_id": "pm-route-search-001",
    "title": "Campus Lost & Found Matcher",
    "description": "Matches lost-item reports against found-item reports using text similarity.",
    "domain": "Machine Learning",
    "difficulty": "Beginner",
    "technologies": ["Python", "Flask"],
    "skills": ["Text similarity", "Flask"],
    "duration_weeks": 6,
}

OTHER_PROJECT = {
    "project_id": "pm-route-search-002",
    "title": "Study Group Finder",
    "domain": "Web Development",
    "difficulty": "Beginner",
    "technologies": ["React"],
    "skills": ["React"],
    "duration_weeks": 5,
}


@pytest.fixture
def seeded_project(mongo_test_db):
    db.projects().insert_one(dict(PROJECT))
    return PROJECT


class _FakeRetriever:
    """Only what skill_gap()/similar()'s own 404 check need from the real
    HybridRetriever — mirrors test_recommend.py's own fixture of the same
    name and purpose."""

    def __init__(self, documents):
        self.documents = documents


@pytest.fixture
def fake_retriever(monkeypatch):
    documents = {PROJECT["project_id"]: PROJECT, OTHER_PROJECT["project_id"]: OTHER_PROJECT}
    monkeypatch.setattr(recommend, "get_retriever", lambda: _FakeRetriever(documents))
    return documents


def _hdr(device: str) -> dict[str, str]:
    return {"X-Device-Id": device}


# --- POST /api/search ---------------------------------------------------


def test_search_requires_a_query(client):
    resp = client.post("/api/search", json={})
    assert resp.status_code == 400


def test_search_rejects_a_query_over_500_chars(client):
    resp = client.post("/api/search", json={"query": "x" * 501})
    assert resp.status_code == 400


def test_search_rejects_a_whitespace_only_query(client):
    resp = client.post("/api/search", json={"query": "   "})
    assert resp.status_code == 400


def test_search_works_without_a_device_id(client):
    """device_id is optional here (device_id(required=False)) — search must
    still work for a caller sending none, just without history/personalization."""
    resp = client.post("/api/search", json={"query": "machine learning project"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["personalization"]["applied"] is False


def test_search_returns_the_documented_envelope_shape(client):
    resp = client.post("/api/search", json={"query": "machine learning"})
    assert resp.status_code == 200
    body = resp.get_json()
    for key in ("data", "query", "filters", "count", "weights", "personalization"):
        assert key in body
    assert body["count"] == len(body["data"])
    assert set(body["weights"]) == {"dense", "sparse"}


def test_search_with_a_device_id_records_history(client):
    device = "device-search-route-001"
    resp = client.post("/api/search", json={"query": "iot project"}, headers=_hdr(device))
    assert resp.status_code == 200
    history = list(db.history().find({"device_id": device}))
    assert len(history) == 1
    assert history[0]["query"] == "iot project"


def test_search_without_a_device_id_records_no_history(client):
    before = db.history().count_documents({})
    resp = client.post("/api/search", json={"query": "blockchain project"})
    assert resp.status_code == 200
    assert db.history().count_documents({}) == before


def test_search_applies_domain_filter_to_the_echoed_filters(client):
    resp = client.post("/api/search", json={"query": "project", "domain": "Blockchain"})
    assert resp.status_code == 200
    assert resp.get_json()["filters"]["domain"] == "Blockchain"


def test_search_rejects_a_non_string_domain(client):
    resp = client.post("/api/search", json={"query": "project", "domain": 123})
    assert resp.status_code == 400


def test_search_never_returns_more_than_the_requested_top_k(client):
    """Hybrid ranking has no minimum-relevance floor — even a low-signal
    query still returns its best-available top_k matches rather than an
    empty list (there's no threshold anywhere in the fusion to cross). The
    one real, deterministic guarantee at the HTTP layer is the result count
    bound itself."""
    resp = client.post("/api/search", json={"query": "zzzzzzz qqqqqqq nonexistent gibberish", "top_k": 3})
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["data"]) <= 3
    assert body["count"] == len(body["data"])


def test_search_with_a_domain_no_project_has_returns_an_empty_but_well_formed_result(client):
    """Unlike relevance ranking above, filtering is a hard pre-filter mask
    (see nlp/similarity.py) — a domain string matching no project is a
    genuine, deterministic empty result, not a ranking question."""
    resp = client.post("/api/search", json={"query": "project", "domain": "Not A Real Domain At All"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["data"] == []
    assert body["count"] == 0


# --- POST /api/recommend -------------------------------------------------


def test_recommend_requires_at_least_one_real_input(client):
    resp = client.post("/api/recommend", json={})
    assert resp.status_code == 400


def test_recommend_works_with_only_known_skills(client):
    resp = client.post("/api/recommend", json={"known_skills": ["Python", "Flask"]})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["known_skills"] == ["Python", "Flask"]


def test_recommend_rejects_non_string_known_skills(client):
    resp = client.post("/api/recommend", json={"known_skills": [1, 2, 3]})
    assert resp.status_code == 400


def test_recommend_rejects_an_invalid_experience_level(client):
    resp = client.post("/api/recommend", json={"known_skills": ["Python"], "experience_level": "Expert"})
    assert resp.status_code == 400


def test_recommend_clamps_an_out_of_range_team_size_instead_of_erroring(client):
    resp = client.post("/api/recommend", json={"known_skills": ["Python"], "team_size": 999})
    assert resp.status_code == 200
    assert resp.get_json()["team_size"] == 20  # clamped to get_int's hi=20, not rejected


# --- GET /api/similar/<id> ------------------------------------------------


def test_similar_404s_for_an_unknown_project(client):
    resp = client.get("/api/similar/definitely-not-a-real-project-id")
    assert resp.status_code == 404


def test_similar_returns_results_for_a_known_project(client, fake_retriever, monkeypatch):
    scored = ScoredProject(
        project_id=OTHER_PROJECT["project_id"],
        score=0.8,
        dense_score=0.8,
        sparse_score=0.0,
        matched_terms=[],
        document=OTHER_PROJECT,
    )
    monkeypatch.setattr(recommend, "similar", lambda project_id, top_k=5: [scored])

    resp = client.get(f"/api/similar/{PROJECT['project_id']}?top_k=3")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["project_id"] == PROJECT["project_id"]
    assert body["count"] == 1 == len(body["data"])
    assert body["data"][0]["project_id"] == OTHER_PROJECT["project_id"]


def test_similar_returns_an_empty_but_200_result_for_a_known_project_with_no_matches(client, fake_retriever, monkeypatch):
    """Known project, genuinely no similar ones (e.g. a near-empty index) —
    distinct from the unknown-project 404 case above: the route's own check
    is `not results AND project_id not in documents`, so a known project with
    zero results must still be 200, not 404."""
    monkeypatch.setattr(recommend, "similar", lambda project_id, top_k=5: [])
    resp = client.get(f"/api/similar/{PROJECT['project_id']}")
    assert resp.status_code == 200
    assert resp.get_json()["data"] == []


# --- POST /api/skill-gap --------------------------------------------------


def test_skill_gap_requires_a_project_id(client):
    resp = client.post("/api/skill-gap", json={"skills": ["Python"]})
    assert resp.status_code == 400


def test_skill_gap_rejects_non_string_skills(client):
    resp = client.post("/api/skill-gap", json={"project_id": "pm-001", "skills": [1]})
    assert resp.status_code == 400


def test_skill_gap_404s_for_an_unknown_project(client):
    resp = client.post("/api/skill-gap", json={"project_id": "not-a-real-id", "skills": ["Python"]})
    assert resp.status_code == 404


def test_skill_gap_succeeds_for_a_known_project(client, fake_retriever):
    resp = client.post(
        "/api/skill-gap", json={"project_id": PROJECT["project_id"], "skills": ["Flask"]}
    )
    assert resp.status_code == 200
    body = resp.get_json()["data"]
    assert "readiness_percent" in body
    assert "Flask" in body["skills_you_have"]


# --- POST /api/uniqueness -------------------------------------------------


def test_uniqueness_requires_a_title_or_description(client):
    resp = client.post("/api/uniqueness", json={})
    assert resp.status_code == 400


def test_uniqueness_accepts_a_title_only(client):
    resp = client.post("/api/uniqueness", json={"title": "A brand new kind of campus app"})
    assert resp.status_code == 200
    assert "is_unique" in resp.get_json()["data"]


# --- POST /api/team-builder (uses direct db.projects() lookup) -----------


def test_team_builder_requires_a_project_id(client, seeded_project):
    resp = client.post("/api/team-builder", json={"members": [{"skills": ["Python"]}]})
    assert resp.status_code == 400


def test_team_builder_requires_a_non_empty_members_list(client, seeded_project):
    resp = client.post(
        "/api/team-builder", json={"project_id": seeded_project["project_id"], "members": []}
    )
    assert resp.status_code == 400


def test_team_builder_rejects_more_than_20_members(client, seeded_project):
    members = [{"skills": ["Python"]} for _ in range(21)]
    resp = client.post(
        "/api/team-builder", json={"project_id": seeded_project["project_id"], "members": members}
    )
    assert resp.status_code == 400


def test_team_builder_allows_a_member_with_no_skills_key(client, seeded_project):
    """'skills' defaults to [] in the route's own isinstance check — a
    missing key is fine, only a wrong-typed one is rejected (below)."""
    resp = client.post(
        "/api/team-builder",
        json={"project_id": seeded_project["project_id"], "members": [{"name": "Alex"}]},
    )
    assert resp.status_code == 200


def test_team_builder_rejects_a_member_with_a_non_list_skills(client, seeded_project):
    resp = client.post(
        "/api/team-builder",
        json={"project_id": seeded_project["project_id"], "members": [{"name": "Alex", "skills": "Python"}]},
    )
    assert resp.status_code == 400


def test_team_builder_404s_for_an_unknown_project(client):
    resp = client.post(
        "/api/team-builder", json={"project_id": "not-a-real-id", "members": [{"skills": ["Python"]}]}
    )
    assert resp.status_code == 404


def test_team_builder_succeeds_for_a_seeded_project(client, seeded_project):
    resp = client.post(
        "/api/team-builder",
        json={"project_id": seeded_project["project_id"], "members": [{"name": "Alex", "skills": ["Python"]}]},
    )
    assert resp.status_code == 200
    assert "roles" in resp.get_json()["data"]


# --- POST /api/learning-path ----------------------------------------------


def test_learning_path_requires_a_non_empty_skills_list(client):
    resp = client.post("/api/learning-path", json={"skills": []})
    assert resp.status_code == 400


def test_learning_path_rejects_more_than_20_skills(client):
    resp = client.post("/api/learning-path", json={"skills": [f"skill-{i}" for i in range(21)]})
    assert resp.status_code == 400


def test_learning_path_succeeds(client):
    resp = client.post("/api/learning-path", json={"skills": ["Python", "React"]})
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert [entry["skill"] for entry in data] == ["Python", "React"]


# --- POST /api/timeline-predict (direct db.projects() lookup) ------------


def test_timeline_predict_requires_a_project_id(client):
    resp = client.post("/api/timeline-predict", json={})
    assert resp.status_code == 400


def test_timeline_predict_404s_for_an_unknown_project(client):
    resp = client.post("/api/timeline-predict", json={"project_id": "not-a-real-id"})
    assert resp.status_code == 404


def test_timeline_predict_rejects_an_invalid_experience_level(client, seeded_project):
    resp = client.post(
        "/api/timeline-predict",
        json={"project_id": seeded_project["project_id"], "experience_level": "Expert"},
    )
    assert resp.status_code == 400


def test_timeline_predict_succeeds_for_a_seeded_project(client, seeded_project):
    resp = client.post(
        "/api/timeline-predict",
        json={"project_id": seeded_project["project_id"], "team_size": 3, "experience_level": "Beginner"},
    )
    assert resp.status_code == 200
    assert "predicted_weeks" in resp.get_json()["data"]


# --- POST /api/resume-suggest ---------------------------------------------
# Deep file-parsing edge cases (corrupt PDF, image-only PDF, DOCX, unsupported
# type, ...) live in test_resume_parsing.py against nlp/resume.py directly —
# this only covers the route's own input contract.


def test_resume_suggest_requires_a_file_or_text(client):
    resp = client.post("/api/resume-suggest", data={})
    assert resp.status_code == 400


def test_resume_suggest_accepts_plain_text_json(client):
    resp = client.post(
        "/api/resume-suggest", json={"text": "Experienced with Python, Flask, and MongoDB."}
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert "detected_skills" in body
    assert "query_used" in body


def test_resume_suggest_rejects_whitespace_only_text(client):
    resp = client.post("/api/resume-suggest", json={"text": "   "})
    assert resp.status_code == 400
