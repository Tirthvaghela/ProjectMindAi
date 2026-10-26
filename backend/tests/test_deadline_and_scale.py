"""Deadline consistency, documented recommendation semantics, catalogue-audit
tooling, and behaviour at 2,000-4,000 projects (synthetic fixtures only — no
fake project is ever added to the real catalogue).
"""

from __future__ import annotations

import json
import random
import time

import numpy as np
import pytest

import config
from db.schema import known_duration
from nlp import embeddings, recommend
from nlp.similarity import HybridRetriever, ScoredProject, doc_matches
from scripts import catalogue_audit


def _doc(pid, difficulty="Beginner", weeks=6, **extra):
    return {
        "project_id": pid,
        "title": f"Project {pid}",
        "description": "A project description long enough to be a realistic record for ranking tests.",
        "domain": "Machine Learning",
        "difficulty": difficulty,
        "technologies": ["Python"],
        "skills": ["Modelling"],
        "duration_weeks": weeks,
        **extra,
    }


# --- known_duration --------------------------------------------------------------


@pytest.mark.parametrize("value", [None, 0, 0.0, -3, "8", True, False, [], {}])
def test_unusable_durations_are_unknown(value):
    assert known_duration({"duration_weeks": value}) is None


def test_a_missing_duration_key_is_unknown():
    assert known_duration({}) is None


@pytest.mark.parametrize("value", [1, 6, 6.5, 52])
def test_real_durations_are_known(value):
    assert known_duration({"duration_weeks": value}) == value


# --- one deadline rule for search and recommend -------------------------------------


BOUNDARY_DOCS = {
    "exact": _doc("exact", weeks=6),
    "over": _doc("over", weeks=7),
    "under": _doc("under", weeks=1),
    "missing": {k: v for k, v in _doc("missing").items() if k != "duration_weeks"},
    "null": _doc("null", weeks=None),
    "zero": _doc("zero", weeks=0),
    "negative": _doc("negative", weeks=-4),
    "text": _doc("text", weeks="six"),
}


@pytest.mark.parametrize(
    "pid,fits",
    [("exact", True), ("under", True), ("over", False), ("missing", False), ("null", False),
     ("zero", False), ("negative", False), ("text", False)],
)
def test_a_deadline_only_admits_projects_with_a_known_duration_within_it(pid, fits):
    assert doc_matches(BOUNDARY_DOCS[pid], {"max_duration_weeks": 6}) is fits


@pytest.mark.parametrize("pid", list(BOUNDARY_DOCS))
def test_without_a_deadline_unknown_duration_never_excludes_anything(pid):
    assert doc_matches(BOUNDARY_DOCS[pid], None) is True
    assert doc_matches(BOUNDARY_DOCS[pid], {"difficulty": "Beginner"}) is True


def test_the_retriever_mask_no_longer_crashes_on_a_null_duration_or_passes_unknowns():
    ids = list(BOUNDARY_DOCS)
    retriever = HybridRetriever(np.eye(len(ids), dtype=np.float32), ids, BOUNDARY_DOCS)
    mask = dict(zip(ids, retriever._mask({"max_duration_weeks": 6})))
    assert [pid for pid, ok in mask.items() if ok] == ["exact", "under"]


def test_search_with_a_deadline_leaves_unknown_durations_out_and_without_one_keeps_them(monkeypatch):
    ids = list(BOUNDARY_DOCS)
    monkeypatch.setattr(embeddings, "encode_one", lambda text: np.ones(len(ids), dtype=np.float32) / len(ids) ** 0.5)
    retriever = HybridRetriever(np.eye(len(ids), dtype=np.float32), ids, BOUNDARY_DOCS)

    capped = {r.project_id for r in retriever.search("project", filters={"max_duration_weeks": 6}, top_k=50)}
    uncapped = {r.project_id for r in retriever.search("project", top_k=50)}

    assert capped == {"exact", "under"}
    assert uncapped == set(ids)


class _Retriever:
    def __init__(self, documents):
        self.documents = documents


def test_unknown_duration_count_reports_what_a_deadline_had_to_leave_out(monkeypatch):
    monkeypatch.setattr(recommend, "get_retriever", lambda: _Retriever(BOUNDARY_DOCS))
    # missing, null, zero, negative and text are unknown; exact/over/under are not.
    assert recommend.unknown_duration_count({"max_duration_weeks": 6}) == 5
    # Only counts projects that pass the *other* filters.
    assert recommend.unknown_duration_count({"max_duration_weeks": 6, "difficulty": "Advanced"}) == 0


def test_recommend_also_excludes_every_kind_of_unknown_duration(monkeypatch):
    monkeypatch.setattr(recommend, "get_retriever", lambda: _Retriever(BOUNDARY_DOCS))
    scored = [
        ScoredProject(project_id=p, score=0.5, dense_score=0.5, sparse_score=0.0, matched_terms=[], document=d)
        for p, d in BOUNDARY_DOCS.items()
    ]
    monkeypatch.setattr(recommend, "search", lambda *a, **k: scored)

    ids = [r["project_id"] for r in recommend.personalized_recommend(known_skills=["Python"], max_duration_weeks=6)]
    assert sorted(ids) == ["exact", "under"]


def test_search_and_recommend_routes_report_the_exclusion_count(client, monkeypatch):
    monkeypatch.setattr(recommend, "get_retriever", lambda: _Retriever(BOUNDARY_DOCS))
    monkeypatch.setattr(recommend, "search", lambda *a, **k: [])

    with_deadline = client.post("/api/search", json={"query": "anything", "max_duration_weeks": 6}).get_json()
    assert with_deadline["excluded_unknown_duration"] == 5
    without = client.post("/api/search", json={"query": "anything"}).get_json()
    assert without["excluded_unknown_duration"] is None

    rec = client.post("/api/recommend", json={"known_skills": ["Python"], "max_duration_weeks": 6}).get_json()
    assert rec["excluded_unknown_duration"] == 5


@pytest.mark.parametrize("bad", ["soon", 0, -1, True, 2.5])
def test_invalid_deadlines_on_recommend_are_rejected(client, bad):
    resp = client.post("/api/recommend", json={"known_skills": ["Python"], "max_duration_weeks": bad})
    assert resp.status_code == 400


# --- documented recommendation semantics --------------------------------------------

SEM_DOCS = {
    "beg": _doc("beg", "Beginner", 6),
    "int": _doc("int", "Intermediate", 8),
    "adv": _doc("adv", "Advanced", 10),
}


@pytest.fixture
def sem_pool(monkeypatch):
    monkeypatch.setattr(recommend, "get_retriever", lambda: _Retriever(SEM_DOCS))
    scored = [
        ScoredProject(project_id=p, score=0.5, dense_score=0.5, sparse_score=0.0, matched_terms=[], document=d)
        for p, d in SEM_DOCS.items()
    ]
    monkeypatch.setattr(recommend, "search", lambda *a, **k: list(scored))


def _ids(**kw):
    return [r["project_id"] for r in recommend.personalized_recommend(known_skills=["Python"], **kw)]


def test_rule_experience_is_a_ranking_preference_not_a_hard_filter(sem_pool):
    assert sorted(_ids(experience_level="Advanced")) == ["adv", "beg", "int"]
    assert sorted(_ids(experience_level="Beginner")) == ["adv", "beg", "int"]


def test_rule_difficulty_fit_is_100_75_50_by_distance():
    assert [recommend.difficulty_fit(p, "Advanced")[0] for p in ("Advanced", "Intermediate", "Beginner")] == [100, 75, 50]
    assert [recommend.difficulty_fit(p, "Beginner")[0] for p in ("Beginner", "Intermediate", "Advanced")] == [100, 75, 50]
    assert recommend.difficulty_fit("Advanced", None)[0] is None


def test_rule_difficulty_weight_is_controlled_by_config(sem_pool, monkeypatch):
    spread = lambda: (lambda r: r[0]["overall_score"] - r[-1]["overall_score"])(  # noqa: E731
        recommend.personalized_recommend(known_skills=["Python"], experience_level="Advanced")
    )
    monkeypatch.setattr(config, "RECOMMEND_DIFFICULTY_WEIGHT", 0.0)
    assert spread() == pytest.approx(0.0, abs=1e-9)  # equal relevance, difficulty ignored
    monkeypatch.setattr(config, "RECOMMEND_DIFFICULTY_WEIGHT", 0.3)
    modest = spread()
    monkeypatch.setattr(config, "RECOMMEND_DIFFICULTY_WEIGHT", 3.0)
    assert spread() > modest > 0


def test_rule_max_weeks_is_checked_against_the_estimate_not_the_solo_baseline(sem_pool):
    assert "adv" not in _ids(max_duration_weeks=6, team_size=1)  # 10 weeks solo
    assert "adv" in _ids(max_duration_weeks=6, team_size=2)  # ~6 weeks for two people


def test_rule_team_size_only_changes_the_estimate_there_is_no_team_metadata(sem_pool):
    assert not any("team" in key.lower() for doc in SEM_DOCS.values() for key in doc)
    solo = recommend.personalized_recommend(known_skills=["Python"], team_size=1)
    team = recommend.personalized_recommend(known_skills=["Python"], team_size=6)
    # Without a deadline, a different team size changes the displayed estimate
    # but cannot change scores or order.
    assert [(r["project_id"], r["overall_score"]) for r in solo] == [(r["project_id"], r["overall_score"]) for r in team]
    assert solo[0]["timeline"]["predicted_weeks"] > team[0]["timeline"]["predicted_weeks"]


def test_rule_skill_readiness_and_keyword_matching_are_separate_signals(monkeypatch):
    doc = _doc("s", technologies=["scikit-learn"], skills=["Classification"])
    monkeypatch.setattr(recommend, "get_retriever", lambda: _Retriever({"s": doc}))
    monkeypatch.setattr(
        recommend,
        "search",
        lambda *a, **k: [ScoredProject(project_id="s", score=0.5, dense_score=0.5, sparse_score=0.0, matched_terms=[], document=doc)],
    )
    [result] = recommend.personalized_recommend(known_skills=["sklearn"])
    # The alias is credited by the skill-readiness signal...
    assert "scikit-learn" in result["skill_gap"]["skills_you_have"]
    # ...while the keyword signal comes only from the retriever (none here).
    assert not any(f.startswith("Keyword match") for f in result["matching_factors"])


# --- determinism ------------------------------------------------------------------


def test_equal_scores_are_ordered_by_project_id_regardless_of_input_order(monkeypatch):
    docs = {p: _doc(p, weeks=5) for p in ("c", "a", "b")}
    monkeypatch.setattr(recommend, "get_retriever", lambda: _Retriever(docs))

    def run(order):
        scored = [ScoredProject(project_id=p, score=0.5, dense_score=0.5, sparse_score=0.0, matched_terms=[], document=docs[p]) for p in order]
        monkeypatch.setattr(recommend, "search", lambda *a, **k: scored)
        return [r["project_id"] for r in recommend.personalized_recommend(known_skills=["Python"])]

    assert run(["c", "a", "b"]) == run(["b", "c", "a"]) == ["a", "b", "c"]


# --- catalogue audit tooling ------------------------------------------------------------


def test_audit_reports_ids_duplicates_gaps_and_missing_metadata():
    records = [
        _doc("pm-001", weeks=4),
        _doc("pm-002", weeks=None),
        _doc("pm-002", weeks=5),  # duplicate id
        _doc("pm-005", weeks=6, title="project  PM-001!"),  # gap + normalised-title dup of "Project pm-001"
        {**_doc("custom-9"), "technologies": []},  # off-convention id, no technologies
        "not an object",
    ]
    records[3]["title"] = "Project pm-001"
    report = catalogue_audit.audit_records(records)

    assert report["total_records"] == 6 and report["non_object_records"] == 1
    assert report["duplicate_project_ids"] == ["pm-002"]
    assert report["ids_off_convention"] == ["custom-9"]
    assert report["id_gaps"] == [3, 4]
    assert report["next_free_id"] == "pm-006"
    assert any(set(p) >= {"pm-001", "pm-005"} for p in report["duplicate_titles"].values())
    assert "pm-002" in report["unknown_or_invalid_duration"]
    assert "custom-9" in report["missing"]["technologies"]
    assert report["technology_names_in_alias_table"] >= 1
    assert "Records" in catalogue_audit.format_report(report)


def test_audit_runs_on_an_empty_catalogue():
    report = catalogue_audit.audit_records([])
    assert report["next_free_id"] == "pm-001" and report["id_number_range"] is None


def test_audit_is_read_only(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps([_doc("pm-001")]), encoding="utf-8")
    before = path.read_bytes()
    catalogue_audit.audit_records(json.loads(path.read_text(encoding="utf-8")))
    assert path.read_bytes() == before


def test_the_real_seed_catalogue_has_stable_unique_ids_and_known_durations():
    records = json.loads(config.SEED_FILE.read_text(encoding="utf-8"))
    report = catalogue_audit.audit_records(records)
    assert report["duplicate_project_ids"] == [] and report["ids_off_convention"] == []
    assert report["unknown_or_invalid_duration"] == [] and report["schema_problems"] == {}
    assert report["duplicate_titles"] == {}


# --- scale: 2,000-4,000 synthetic projects ------------------------------------------------

DOMAINS = ("Machine Learning", "Web Development", "Data Science", "Cybersecurity", "Robotics")
LEVELS = ("Beginner", "Intermediate", "Advanced")
TECHS = ("Python", "React", "scikit-learn", "Node.js", "TensorFlow", "Docker", "Flask", "MongoDB")
WORDS = "sensor dashboard classifier pipeline recommender scheduler tracker analyzer detector planner monitor forecaster".split()


def _synthetic(n, seed=7):
    rng = random.Random(seed)
    docs = {}
    for i in range(n):
        pid = f"syn-{i:05d}"
        words = rng.sample(WORDS, 3)
        weeks = rng.choice([None, *range(3, 15)]) if rng.random() < 0.02 else rng.randint(3, 14)
        docs[pid] = _doc(
            pid,
            rng.choice(LEVELS),
            weeks,
            title=" ".join(words).title(),
            description=f"{' '.join(words)} built with {', '.join(rng.sample(TECHS, 2))} for {rng.choice(DOMAINS)}.",
            domain=rng.choice(DOMAINS),
            technologies=rng.sample(TECHS, rng.randint(1, 3)),
            skills=[" ".join(rng.sample(WORDS, 2)) for _ in range(3)],
        )
    return docs


@pytest.fixture(scope="module")
def big_retriever():
    mp = pytest.MonkeyPatch()
    docs = _synthetic(4000)
    ids = list(docs)
    rng = np.random.default_rng(1)
    matrix = rng.normal(size=(len(ids), 384)).astype(np.float32)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    query_vec = matrix[0]
    mp.setattr(embeddings, "encode_one", lambda text: query_vec)
    retriever = HybridRetriever(matrix, ids, docs)
    mp.setattr(recommend, "get_retriever", lambda: retriever)
    yield retriever
    mp.undo()


def test_scale_filters_are_exact_at_4000_projects(big_retriever):
    filters = {"difficulty": "Advanced", "technologies": ["sklearn"], "max_duration_weeks": 8}
    results = big_retriever.search("classifier pipeline", filters=filters, top_k=50)
    assert results, "the synthetic catalogue should contain matches"
    for r in results:
        doc = r.document
        assert doc["difficulty"] == "Advanced"
        assert "scikit-learn" in doc["technologies"]
        assert known_duration(doc) is not None and doc["duration_weeks"] <= 8
    expected = sum(doc_matches(d, filters) for d in big_retriever.documents.values())
    assert len(results) == min(50, expected)


def test_scale_recommend_is_deterministic_and_respects_every_constraint(big_retriever):
    kwargs = dict(known_skills=["sklearn", "python"], experience_level="Advanced", team_size=2, max_duration_weeks=7, top_k=10)
    first = recommend.personalized_recommend(**kwargs)
    second = recommend.personalized_recommend(**kwargs)
    assert [r["project_id"] for r in first] == [r["project_id"] for r in second]
    assert [r["overall_score"] for r in first] == [r["overall_score"] for r in second]
    assert first and all(r["timeline"]["predicted_weeks"] <= 7 for r in first)
    assert all(known_duration(r) is not None for r in first)
    scores = [r["overall_score"] for r in first]
    assert scores == sorted(scores, reverse=True)


def test_scale_response_time_stays_interactive_at_4000_projects(big_retriever, capsys):
    started = time.perf_counter()
    for _ in range(5):
        big_retriever.search("sensor dashboard", filters={"difficulty": "Beginner", "max_duration_weeks": 10}, top_k=12)
    search_ms = (time.perf_counter() - started) / 5 * 1000

    started = time.perf_counter()
    for _ in range(3):
        recommend.personalized_recommend(known_skills=["python", "react"], experience_level="Intermediate", team_size=3, max_duration_weeks=8, top_k=6)
    recommend_ms = (time.perf_counter() - started) / 3 * 1000

    with capsys.disabled():
        print(f"\n[scale] 4000 synthetic projects: search {search_ms:.0f} ms, best-fit recommend {recommend_ms:.0f} ms")
    # Generous ceilings: this guards against an accidental O(n^2) or per-project
    # model call, not against normal machine-to-machine variation.
    assert search_ms < 1500
    assert recommend_ms < 3000


# --- shared deadline validation on /api/search ----------------------------------------


@pytest.mark.parametrize("bad", ["soon", 0, -1, True, 2.5, "2.5", [], {}])
def test_search_rejects_an_unusable_deadline_instead_of_ignoring_or_truncating_it(client, bad):
    resp = client.post("/api/search", json={"query": "anything", "max_duration_weeks": bad})
    assert resp.status_code == 400
    assert "max_duration_weeks" in resp.get_json()["error"]


@pytest.mark.parametrize("good", [6, "6", 6.0, None, ""])
def test_search_accepts_whole_week_deadlines_and_no_deadline(client, monkeypatch, good):
    monkeypatch.setattr(recommend, "get_retriever", lambda: _Retriever({}))
    monkeypatch.setattr(recommend, "search", lambda *a, **k: [])
    resp = client.post("/api/search", json={"query": "anything", "max_duration_weeks": good})
    assert resp.status_code == 200


def test_timeline_prediction_survives_a_malformed_stored_duration():
    from nlp import timeline

    for bad in (None, 0, -2, "six", True):
        estimate = timeline.predict({"duration_weeks": bad, "difficulty": "Beginner", "domain": "Machine Learning"})
        assert estimate["predicted_weeks"] >= 1.0
