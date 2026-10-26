"""scripts/import_catalogue.py — validation, duplicate handling, id assignment,
the dry-run/apply split, idempotency, and rollback.

Embeddings are replaced by a deterministic bag-of-words hash so similarity is
controllable without loading the model; database tests use the throwaway
`mongo_test_db` and a temporary seed file, never the real catalogue.
"""

from __future__ import annotations

import copy
import json
import zlib

import numpy as np
import pytest

from db import client as db
from db import schema
from scripts import import_catalogue as ic


def fake_encode(texts):
    vectors = np.zeros((len(texts), 128), dtype=np.float32)
    for row, text in enumerate(texts):
        for word in text.lower().split():
            vectors[row, zlib.crc32(word.encode()) % 128] += 1.0
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.where(norms == 0, 1, norms)


def existing_record(n, title, description, **kw):
    return {
        "project_id": f"pm-{n:03d}",
        "title": title,
        "description": description,
        "domain": "Machine Learning",
        "technologies": ["Python", "scikit-learn"],
        "difficulty": "Intermediate",
        "duration_weeks": 8,
        "skills": ["Classification", "Feature engineering", "Evaluation"],
        "keywords": ["classification", "tabular", "features"],
        "github_url": "https://example.org/x",
        "learning_resources": ["https://example.org/docs"],
        **kw,
    }


def candidate(_title, _description, **overrides):
    record = {
        "title": _title,
        "description": _description,
        "domain": "Data Science",
        "technologies": ["Python", "Pandas"],
        "difficulty": "Intermediate",
        "duration_weeks": 7,
        "skills": ["Data cleaning", "Visualisation", "Statistics"],
        "keywords": ["analysis", "dashboard", "trends"],
    }
    record.update(overrides)
    return record


A_DESC = (
    "Builds a pipeline that ingests irregular tide-gauge readings, repairs sensor dropouts and reports "
    "which harbours will exceed safe water levels in the next 48 hours for port planners."
)
B_DESC = (
    "Analyses library lending records to find which shelf placements shorten borrowing queues, and "
    "presents the recommended rearrangement as a floor plan for librarians to approve or reject."
)
EXISTING = [existing_record(1, "Existing Alpha Project", "An existing project about forecasting energy demand across households using weather and calendar features and gradient boosting models.")]


def plan(cands, existing=EXISTING):
    wrapped = [{"source": "t.json", "index": i, "record": r} for i, r in enumerate(cands)]
    return ic.plan_batch(wrapped, existing, encode=fake_encode, batch="t")


# --- planning ------------------------------------------------------------------


def test_valid_distinct_candidates_get_sequential_ids_after_the_existing_ones():
    result = plan([candidate("Tide Gauge Flood Planner", A_DESC), candidate("Library Shelf Optimiser Study", B_DESC)])
    assert [r["project_id"] for r in result["approved"]] == ["pm-002", "pm-003"]
    assert result["counts"]["approved"] == 2 and result["counts"]["rejected"] == 0
    assert result["projected"]["unique_project_ids"] == 3
    assert list(result["approved"][0]) == [  # the existing key order, no optional URL fields invented
        "project_id", "title", "description", "domain", "technologies", "difficulty",
        "duration_weeks", "skills", "keywords",
    ]


def test_existing_ids_are_never_reused_even_with_gaps():
    existing = [existing_record(1, "One", "x" * 90), existing_record(40, "Forty", "y" * 90)]
    assert plan([candidate("Tide Gauge Flood Planner", A_DESC)], existing)["approved"][0]["project_id"] == "pm-041"


@pytest.mark.parametrize(
    "mutation,fragment",
    [
        ({"project_id": "pm-999"}, "must not carry a project_id"),
        ({"surprise": 1}, "unexpected field"),
        ({"domain": "Gardening"}, "not one of the"),
        ({"difficulty": "Expert"}, "must be one of"),
        ({"duration_weeks": 0}, "outside the sane range"),
        ({"difficulty": "Beginner", "duration_weeks": 12}, "implausible"),
        ({"difficulty": "Advanced", "duration_weeks": 3}, "implausible"),
        ({"description": "too short"}, "chars"),
        ({"description": A_DESC + " TBD later."}, "placeholder"),
        ({"technologies": ["Python"]}, "expected 2-6"),
        ({"skills": ["a", "a", "b"]}, "duplicates"),
        ({"keywords": ["Mixed", "case", "words"]}, "lowercase"),
        ({"title": "Tiny"}, "title is"),
    ],
)
def test_invalid_candidates_are_rejected_with_the_specific_reason(mutation, fragment):
    result = plan([candidate("Tide Gauge Flood Planner", A_DESC, **mutation)])
    assert result["counts"]["approved"] == 0
    assert any(fragment in reason for reason in result["rejected"][0]["reasons"]), result["rejected"][0]["reasons"]


def test_a_non_object_record_is_rejected_not_crashed_on():
    result = ic.plan_batch([{"source": "t", "index": 0, "record": "oops"}], EXISTING, encode=fake_encode)
    assert result["counts"]["rejected"] == 1


def test_exact_title_duplicates_are_rejected_against_existing_and_within_the_batch():
    result = plan([
        candidate("existing   ALPHA project!", A_DESC),
        candidate("Tide Gauge Flood Planner", A_DESC),
        candidate("tide gauge flood planner", B_DESC),
    ])
    reasons = [r["reasons"][0] for r in result["rejected"]]
    assert any("duplicates existing pm-001" in r for r in reasons)
    assert any("earlier candidate" in r for r in reasons)
    assert [r["title"] for r in result["approved"]] == ["Tide Gauge Flood Planner"]


def test_semantic_near_duplicates_are_rejected_and_the_earlier_record_wins():
    reworded = A_DESC.replace("ingests", "collects").replace("repairs", "fixes")
    result = plan([candidate("Tide Gauge Flood Planner", A_DESC), candidate("Harbour Water Level Warning Tool", reworded)])
    assert [r["title"] for r in result["approved"]] == ["Tide Gauge Flood Planner"]
    assert "semantic near-duplicate" in result["rejected"][0]["reasons"][0]


def test_semantic_near_duplicates_of_the_existing_catalogue_are_rejected():
    clone = EXISTING[0]["description"] + " Also reports a confidence interval for each forecast period."
    same_shape = {k: EXISTING[0][k] for k in ("domain", "technologies", "skills", "keywords")}
    result = plan([candidate("Existing Alpha Project Variant", clone, **same_shape)])
    assert result["counts"]["rejected"] == 1 and "pm-001" in result["rejected"][0]["reasons"][0]


def test_distinct_projects_pass_and_unknown_technologies_only_warn():
    result = plan([candidate("Tide Gauge Flood Planner", A_DESC, technologies=["Python", "BrandNewTool"])])
    assert result["counts"]["approved"] == 1
    assert "BrandNewTool" in " ".join(result["warnings"]["Tide Gauge Flood Planner"])


def test_known_aliases_do_not_warn_as_unknown_technologies():
    result = plan([candidate("Tide Gauge Flood Planner", A_DESC, technologies=["sklearn", "Postgres"])])
    assert "Tide Gauge Flood Planner" not in result["warnings"]


def test_planning_is_deterministic_and_writes_nothing(tmp_path):
    cands = [candidate("Tide Gauge Flood Planner", A_DESC), candidate("Library Shelf Optimiser Study", B_DESC)]
    before = copy.deepcopy(EXISTING)
    first, second = plan(cands), plan(cands)
    assert first["approved"] == second["approved"] and first["content_hash"] == second["content_hash"]
    assert EXISTING == before
    assert not list(tmp_path.iterdir())


def test_a_record_already_imported_is_reported_not_duplicated():
    first = plan([candidate("Tide Gauge Flood Planner", A_DESC)])
    existing_after = [*EXISTING, first["approved"][0]]
    again = plan([candidate("Tide Gauge Flood Planner", A_DESC)], existing_after)
    assert again["counts"]["approved"] == 0 and again["counts"]["already_present"] == 1 and again["counts"]["rejected"] == 0


# --- apply / idempotency / rollback ---------------------------------------------------


@pytest.fixture
def workspace(tmp_path, mongo_test_db):
    seed = tmp_path / "projects_seed.json"
    ic.write_seed(seed, EXISTING)
    db.projects().insert_one(copy.deepcopy(EXISTING[0]))
    idx = tmp_path / "embeddings.npy"
    idx.write_bytes(b"old-index")
    return tmp_path, seed, idx


def test_apply_appends_inserts_backs_up_and_preserves_existing_documents(workspace):
    tmp_path, seed, idx = workspace
    original_doc = db.projects().find_one({"project_id": "pm-001"}, {"_id": 0})
    result = plan([candidate("Tide Gauge Flood Planner", A_DESC), candidate("Library Shelf Optimiser Study", B_DESC)])

    manifest = ic.apply_plan(result, seed, db.projects(), tmp_path / "reports", extra_backup_files=(idx,))

    assert manifest["inserted"] == 2 and manifest["database_count_after"] == 3
    assert [r["project_id"] for r in ic.read_seed(seed)] == ["pm-001", "pm-002", "pm-003"]
    assert db.projects().find_one({"project_id": "pm-001"}, {"_id": 0}) == original_doc
    assert all(not schema.validate(r) for r in ic.read_seed(seed))
    assert len(list((tmp_path / "backups").glob("projects_seed.*.json"))) == 1
    assert len(list((tmp_path / "backups").glob("embeddings.*.npy"))) == 1
    assert (tmp_path / "batches" / "t.manifest.json").exists()


def test_apply_is_idempotent(workspace):
    tmp_path, seed, _ = workspace
    result = plan([candidate("Tide Gauge Flood Planner", A_DESC)])
    ic.apply_plan(result, seed, db.projects(), tmp_path / "reports")
    after_first = seed.read_bytes()

    second = ic.apply_plan(result, seed, db.projects(), tmp_path / "reports")

    assert second["inserted"] == 0 and second["skipped_already_present"] == 1
    assert second["backups"] == []  # a no-op re-run takes no new backups
    assert len(list((tmp_path / "backups").glob("projects_seed.*.json"))) == 1
    assert seed.read_bytes() == after_first
    assert db.projects().count_documents({}) == 2


def test_apply_never_overwrites_an_existing_database_document(workspace):
    tmp_path, seed, _ = workspace
    db.projects().update_one({"project_id": "pm-001"}, {"$set": {"title": "Edited in the database"}})
    clashing = plan([candidate("Tide Gauge Flood Planner", A_DESC)])
    clashing["approved"][0]["project_id"] = "pm-001"  # even a forged id cannot overwrite
    clashing["approved"][0]["title"] = "Totally Different Title"

    ic.apply_plan(clashing, seed, db.projects(), tmp_path / "reports")

    assert db.projects().find_one({"project_id": "pm-001"})["title"] == "Edited in the database"


def test_apply_refuses_records_that_no_longer_validate(workspace):
    tmp_path, seed, _ = workspace
    result = plan([candidate("Tide Gauge Flood Planner", A_DESC)])
    result["approved"][0]["difficulty"] = "Expert"
    before = seed.read_bytes()
    with pytest.raises(ValueError):
        ic.apply_plan(result, seed, db.projects(), tmp_path / "reports")
    assert seed.read_bytes() == before and db.projects().count_documents({}) == 1


def test_rollback_is_a_dry_run_by_default_and_removes_exactly_the_batch(workspace):
    tmp_path, seed, _ = workspace
    result = plan([candidate("Tide Gauge Flood Planner", A_DESC), candidate("Library Shelf Optimiser Study", B_DESC)])
    ic.apply_plan(result, seed, db.projects(), tmp_path / "reports")
    manifest = tmp_path / "batches" / "t.manifest.json"

    dry = ic.rollback_batch(manifest, seed, db.projects(), apply=False)
    assert dry["applied"] is False and dry["in_seed_file"] == 2 and dry["in_database"] == 2
    assert db.projects().count_documents({}) == 3

    done = ic.rollback_batch(manifest, seed, db.projects(), apply=True)
    assert done["applied"] is True
    assert [r["project_id"] for r in ic.read_seed(seed)] == ["pm-001"]
    assert [d["project_id"] for d in db.projects().find({}, {"project_id": 1})] == ["pm-001"]


def test_seed_writer_matches_the_format_of_the_real_seed_file():
    import config

    raw = config.SEED_FILE.read_text(encoding="utf-8")
    assert json.dumps(json.loads(raw), indent=2, ensure_ascii=False) + "\n" == raw


def test_a_batch_can_demand_longer_descriptions_than_the_default():
    record = candidate("Tide Gauge Flood Planner", A_DESC)  # ~170 characters
    assert plan([record])["counts"]["approved"] == 1
    wrapped = [{"source": "t.json", "index": 0, "record": record}]
    strict = ic.plan_batch(wrapped, EXISTING, encode=fake_encode, batch="t", min_description=len(A_DESC) + 50)
    assert strict["counts"]["rejected"] == 1
    assert f"expected {len(A_DESC) + 50}-450" in strict["rejected"][0]["reasons"][0]
    assert strict["thresholds"]["min_description"] == len(A_DESC) + 50
