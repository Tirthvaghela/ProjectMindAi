"""The Project Evaluation Engine: nlp/recommend.py:check_uniqueness/skill_gap
plus nlp/chat_tools.py:recommend_decision/compare_projects — the orchestration
layer over them. No new similarity/skill-gap/timeline engine is exercised
here that test_similarity.py, test_timeline.py or test_recommend.py don't
already cover directly; this file is about how the Evaluation Engine
combines those existing signals into uniqueness/comparison/decision output.

check_uniqueness() is tested against a small synthetic in-memory retriever
(same style as tests/test_similarity.py) rather than a real embedding model —
`embeddings.encode_one` is monkeypatched to a hand-picked vector so the
resulting cosine similarities are exact and deterministic.

recommend_decision()/compare_projects() go through db.projects() and Mongo
in production; here db.projects() is monkeypatched to a tiny fake collection
supporting just the .find_one/.find calls these functions actually make, so
these tests never need a live MongoDB (same "fully mocked" approach
tests/test_ideation.py already uses for this codebase's LLM-backed pieces).
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from db import client as db
from nlp import chat_tools, recommend

# --- check_uniqueness --------------------------------------------------------

UNIQ_DOCS = {
    "p1": {
        "project_id": "p1",
        "title": "Face Recognition Attendance System",
        "domain": "Computer Vision",
        "difficulty": "Intermediate",
        "duration_weeks": 10,
        "technologies": ["Python", "OpenCV"],
        "skills": ["Face Recognition", "OpenCV"],
    },
    "p2": {
        "project_id": "p2",
        "title": "Customer Support Chatbot",
        "domain": "Natural Language Processing",
        "difficulty": "Beginner",
        "duration_weeks": 6,
        "technologies": ["Python", "NLTK"],
        "skills": ["NLP", "Chatbot Development"],
    },
    "p3": {
        "project_id": "p3",
        "title": "Smart Attendance Tracker",
        "domain": "Computer Vision",
        "difficulty": "Intermediate",
        "duration_weeks": 9,
        "technologies": ["Python", "OpenCV", "Flask"],
        "skills": ["Face Recognition", "Flask"],
    },
}
UNIQ_IDS = ["p1", "p2", "p3"]
# Unit vectors: p1 is identical to the query vector used below (similarity
# 1.0, above DUPLICATE_THRESHOLD -> "high"), p3 sits between
# UNIQUENESS_THRESHOLD and DUPLICATE_THRESHOLD (similarity 0.85 -> "moderate"),
# p2 is orthogonal to both (similarity 0.0 -> "low") — one fixture exercising
# all three similarity_level tiers at once.
UNIQ_MATRIX = np.array(
    [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.85, 0.5268937, 0.0],
    ],
    dtype=np.float32,
)


@pytest.fixture
def uniqueness_retriever(monkeypatch):
    retriever = SimpleNamespace(matrix=UNIQ_MATRIX, ids=UNIQ_IDS, documents=UNIQ_DOCS)
    monkeypatch.setattr(recommend, "get_retriever", lambda: retriever)
    return retriever


def _fixed_vector(vector):
    return lambda text: np.array(vector, dtype=np.float32)


def test_check_uniqueness_flags_a_near_duplicate(monkeypatch, uniqueness_retriever):
    monkeypatch.setattr(recommend.embeddings, "encode_one", _fixed_vector([1.0, 0.0, 0.0]))

    result = recommend.check_uniqueness(
        "Face ID Attendance", "Marks attendance automatically using face recognition.",
        domain="Computer Vision", technologies=["Python", "OpenCV"],
    )

    assert result["is_unique"] is False
    assert result["highest_similarity"] == pytest.approx(1.0, abs=1e-4)
    assert result["originality_score"] == 0
    assert result["similar_projects"][0]["project_id"] == "p1"


def test_check_uniqueness_originality_score_is_the_inverse_of_similarity(monkeypatch, uniqueness_retriever):
    monkeypatch.setattr(recommend.embeddings, "encode_one", _fixed_vector([1.0, 0.0, 0.0]))

    result = recommend.check_uniqueness("Anything", "Anything at all.")

    # The backend computes this number — it is never asked of, or invented
    # by, an LLM (architecture rule: originality_score is real, not guessed).
    assert result["originality_score"] == round((1 - result["highest_similarity"]) * 100)


def test_check_uniqueness_reports_a_genuinely_original_idea(monkeypatch, uniqueness_retriever):
    # Orthogonal to every catalogue vector (all of which live in the xy-plane).
    monkeypatch.setattr(recommend.embeddings, "encode_one", _fixed_vector([0.0, 0.0, 1.0]))

    result = recommend.check_uniqueness("Something new", "A concept unlike the catalogue.")

    assert result["is_unique"] is True
    assert result["highest_similarity"] == 0.0
    assert result["originality_score"] == 100
    assert result["closest_matches"] == []
    # Wording is scoped to the catalogue, never a claim of global uniqueness.
    assert "catalogue" in result["suggestions"][0]


def test_check_uniqueness_similarity_level_distinguishes_three_tiers(monkeypatch, uniqueness_retriever):
    monkeypatch.setattr(recommend.embeddings, "encode_one", _fixed_vector([1.0, 0.0, 0.0]))

    result = recommend.check_uniqueness("Face ID Attendance", "Marks attendance using face recognition.")
    levels = {m["project_id"]: m["similarity_level"] for m in result["similar_projects"]}

    assert levels["p1"] == "high"       # similarity 1.0 >= DUPLICATE_THRESHOLD
    assert levels["p3"] == "moderate"   # ~0.949 >= UNIQUENESS_THRESHOLD, < DUPLICATE_THRESHOLD
    assert levels["p2"] == "low"        # similarity 0.0


def test_check_uniqueness_overlapping_concepts_are_grounded_in_catalogue_vocabulary(monkeypatch, uniqueness_retriever):
    monkeypatch.setattr(recommend.embeddings, "encode_one", _fixed_vector([1.0, 0.0, 0.0]))

    result = recommend.check_uniqueness(
        "Face ID Attendance", "Uses Python and OpenCV to recognise faces for attendance.",
    )

    # Every overlap must be a real technology/skill that's actually in the
    # dataset (db.schema.embedding_text vocabulary), never invented.
    catalogue_vocab = {t for doc in UNIQ_DOCS.values() for t in doc["technologies"] + doc["skills"]}
    assert result["overlapping_concepts"]
    assert set(result["overlapping_concepts"]) <= catalogue_vocab


def test_check_uniqueness_suggests_combining_domains_when_not_unique(monkeypatch, uniqueness_retriever):
    monkeypatch.setattr(recommend.embeddings, "encode_one", _fixed_vector([1.0, 0.0, 0.0]))

    result = recommend.check_uniqueness("Face ID Attendance", "Marks attendance using face recognition.")

    # p2 (Natural Language Processing) is a different domain from the top
    # match (p1, Computer Vision) and shows up in the closest-3 — a real,
    # grounded cross-domain differentiator, not an invented one.
    assert any("Combining" in s and "Natural Language Processing" in s for s in result["suggestions"])


def test_check_uniqueness_handles_empty_catalogue(monkeypatch):
    monkeypatch.setattr(recommend, "get_retriever", lambda: SimpleNamespace(matrix=np.zeros((0, 3), dtype=np.float32), ids=[], documents={}))
    monkeypatch.setattr(recommend.embeddings, "encode_one", _fixed_vector([1.0, 0.0, 0.0]))

    result = recommend.check_uniqueness("Anything", "Anything.")

    assert result["is_unique"] is True
    assert result["similar_projects"] == []
    assert result["suggestions"] == ["The catalogue has no projects to compare against yet."]


# --- skill_gap ---------------------------------------------------------------


def test_skill_gap_credits_only_distinctive_shared_tokens(monkeypatch):
    doc = {"project_id": "p1", "skills": ["React development", "Smart contract development"]}
    monkeypatch.setattr(recommend, "get_retriever", lambda: SimpleNamespace(documents={"p1": doc}))

    # Sharing only the generic word "development" must not credit a skill —
    # this is the exact regression test the module's own comment calls out.
    result = recommend.skill_gap("p1", ["React"])

    assert result["skills_you_have"] == ["React development"]
    assert result["skills_to_learn"] == ["Smart contract development"]
    assert result["readiness_percent"] == 50.0


def test_skill_gap_missing_project_raises_keyerror():
    with pytest.raises(KeyError):
        recommend.skill_gap("does-not-exist", ["Python"])


# --- chat_tools.compare_projects / recommend_decision ------------------------

DECISION_DOCS = {
    "d1": {
        "project_id": "d1",
        "title": "Beginner Web Dashboard",
        "domain": "Web Development",
        "difficulty": "Beginner",
        "duration_weeks": 4,
        "technologies": ["React"],
        "skills": ["HTML", "CSS"],
        "description": "A simple dashboard.",
    },
    "d2": {
        "project_id": "d2",
        "title": "Advanced AI Research System",
        "domain": "Artificial Intelligence",
        "difficulty": "Advanced",
        "duration_weeks": 16,
        "technologies": ["Python", "PyTorch"],
        "skills": ["Deep learning"],
        "description": "A research-grade AI system.",
    },
}


class _FakeCursor(list):
    """db.projects().find(...) returns a Mongo cursor; a plain list satisfies
    every iteration/consumption pattern recommend_decision/compare_projects
    actually use."""


class _FakeProjects:
    def __init__(self, docs):
        self._docs = docs

    def find_one(self, query, *_args, **_kwargs):
        return self._docs.get(query.get("project_id"))

    def find(self, query, *_args, **_kwargs):
        ids = set(query.get("project_id", {}).get("$in", []))
        return _FakeCursor(doc for pid, doc in self._docs.items() if pid in ids)


@pytest.fixture
def fake_projects(monkeypatch):
    fake = _FakeProjects(DECISION_DOCS)
    monkeypatch.setattr(db, "projects", lambda: fake)
    # recommend.skill_gap() reads documents off the shared retriever, not
    # Mongo directly — patch it alongside db.projects() so a known_skills
    # candidate resolves against the same DECISION_DOCS the rest of this
    # fixture uses, instead of KeyError-ing against the real (unbuilt) index.
    monkeypatch.setattr(recommend, "get_retriever", lambda: SimpleNamespace(documents=DECISION_DOCS))
    return fake


@pytest.fixture(autouse=True)
def fake_similar(monkeypatch):
    """recommend.similar() backs _uniqueness_percent() — stub it to a fixed,
    known peer score rather than needing a real retriever/index."""
    from nlp.similarity import ScoredProject

    def fake(project_id, top_k=1):
        return [ScoredProject(project_id="other", score=0.4, dense_score=0.4, sparse_score=0.0)]

    monkeypatch.setattr(recommend, "similar", fake)


def test_compare_projects_requires_at_least_two_ids(fake_projects):
    for_model, block = chat_tools.compare_projects(["d1"])
    assert "error" in for_model
    assert block is None


def test_compare_projects_reports_missing_ids(fake_projects):
    for_model, block = chat_tools.compare_projects(["d1", "does-not-exist"])
    assert for_model["missing_ids"] == ["does-not-exist"]
    assert block is None  # fewer than 2 real projects resolved


def test_compare_projects_includes_uniqueness_percent(fake_projects):
    for_model, block = chat_tools.compare_projects(["d1", "d2"])
    assert block["type"] == "comparison"
    for project in block["projects"]:
        assert project["uniqueness_percent"] == 60  # round((1 - 0.4) * 100)


def test_recommend_decision_requires_a_project_id():
    for_model, block = chat_tools.recommend_decision([])
    assert "error" in for_model
    assert block is None


def test_recommend_decision_rejects_unknown_ids(fake_projects):
    for_model, block = chat_tools.recommend_decision(["does-not-exist"])
    assert "error" in for_model
    assert block is None


def test_recommend_decision_skill_fit_is_unavailable_without_known_skills(fake_projects):
    for_model, _block = chat_tools.recommend_decision(["d1"])
    [candidate] = for_model["candidates"]
    assert candidate["skill_fit"] is None  # never guessed


def test_recommend_decision_skill_fit_uses_real_readiness_percent(fake_projects):
    for_model, _block = chat_tools.recommend_decision(["d1"], known_skills=["HTML"])
    [candidate] = for_model["candidates"]
    assert candidate["skill_fit"] == 50.0  # 1 of 2 required skills (HTML, CSS)
    assert candidate["skills_you_have"] == ["HTML"]
    assert candidate["skills_to_learn"] == ["CSS"]


def test_recommend_decision_difficulty_fit_is_unavailable_without_experience_level(fake_projects):
    for_model, _block = chat_tools.recommend_decision(["d1"])
    [candidate] = for_model["candidates"]
    assert candidate["difficulty_fit"] is None


def test_recommend_decision_difficulty_fit_rewards_a_matching_level(fake_projects):
    for_model, _block = chat_tools.recommend_decision(["d1"], experience_level="Beginner")
    [candidate] = for_model["candidates"]
    assert candidate["difficulty_fit"] == 100  # Beginner student, Beginner project


def test_recommend_decision_difficulty_fit_penalizes_a_level_gap(fake_projects):
    for_model, _block = chat_tools.recommend_decision(["d2"], experience_level="Beginner")
    [candidate] = for_model["candidates"]
    # d2 is Advanced; a Beginner is two levels behind.
    assert candidate["difficulty_fit"] < 100


def test_recommend_decision_timeline_fit_uses_target_weeks_when_given(fake_projects):
    for_model, _block = chat_tools.recommend_decision(["d1"], target_weeks=2, team_size=1)
    [candidate] = for_model["candidates"]
    # d1's baseline is 4 weeks solo — overruns a 2-week target.
    assert candidate["target_weeks"] == 2
    assert candidate["timeline_fit"] < 100


def test_recommend_decision_timeline_fit_is_perfect_within_target(fake_projects):
    for_model, _block = chat_tools.recommend_decision(["d1"], target_weeks=52, team_size=1)
    [candidate] = for_model["candidates"]
    assert candidate["timeline_fit"] == 100


def test_recommend_decision_ranks_higher_skill_fit_first(fake_projects):
    # Same project catalogue entries aside from skills matched — give d1 (easy
    # to fully match) real skill coverage and leave d2 with none, all other
    # factors equal (no target_weeks/experience_level given).
    for_model, block = chat_tools.recommend_decision(
        ["d1", "d2"], known_skills=["HTML", "CSS"],
    )
    assert block["recommended"]["project_id"] == "d1"
    assert for_model["candidates"][0]["overall_fit"] >= for_model["candidates"][1]["overall_fit"]


def test_recommend_decision_prefers_unique_increases_uniqueness_weight(fake_projects):
    _for_model, block = chat_tools.recommend_decision(["d1"], prefers_unique=True)
    assert block["recommended"]["project_id"] == "d1"
    # The weight actually used is echoed back, transparently, not hidden.
    assert _for_model["weights"]["uniqueness"] == chat_tools.UNIQUENESS_WEIGHT_PREFERRED


def test_recommend_decision_weights_are_centralized_constants():
    # Guards against the weighting silently drifting into scattered magic
    # numbers again — every weight recommend_decision uses must trace back
    # to one of these module-level constants.
    assert chat_tools.SKILL_FIT_WEIGHT > 0
    assert chat_tools.UNIQUENESS_WEIGHT_PREFERRED > chat_tools.UNIQUENESS_WEIGHT_DEFAULT


def test_recommend_decision_single_project_is_a_straight_suitability_check(fake_projects):
    for_model, block = chat_tools.recommend_decision(["d1"], known_skills=["HTML", "CSS"])
    assert len(for_model["candidates"]) == 1
    assert block["alternative"] is None


# --- chat_tools.check_project_uniqueness (generated-idea evaluation) --------


def test_check_project_uniqueness_wraps_check_uniqueness(monkeypatch):
    captured = {}

    def fake_check_uniqueness(title, description, **kwargs):
        captured["title"] = title
        return {
            "is_unique": True,
            "originality_score": 91,
            "similar_projects": [],
            "overlapping_concepts": [],
            "suggestions": ["Your idea looks fairly distinct."],
        }

    monkeypatch.setattr(recommend, "check_uniqueness", fake_check_uniqueness)

    for_model, block = chat_tools.check_project_uniqueness("An AI codebase explainer")

    assert captured["title"] == "An AI codebase explainer"
    assert block["type"] == "uniqueness"
    assert block["originality_score"] == 91


def test_check_project_uniqueness_rejects_empty_idea():
    for_model, block = chat_tools.check_project_uniqueness("   ")
    assert "error" in for_model
    assert block is None
