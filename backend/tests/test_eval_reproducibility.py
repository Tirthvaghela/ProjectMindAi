"""Reproducibility and version safety for the evaluation datasets.

Covers: the frozen-input manifest, byte-for-byte rebuild of v2, refusing v2 on a
changed catalogue, the report-comparability rules, and the next-version (v3)
workflow — using synthetic catalogues only. No v3 label exists or is invented.
"""

from __future__ import annotations

import json

import pytest

import config
from scripts import eval_dataset as ed
from scripts import eval_next_version as nv
from scripts import evaluate as ev


def _doc(pid, title="T", description="d"):
    return {
        "project_id": pid, "title": title, "description": description, "domain": "Robotics",
        "technologies": ["Python"], "difficulty": "Beginner", "duration_weeks": 5, "skills": ["s"], "keywords": ["k"],
    }


# --- v2 stays reproducible ---------------------------------------------------------------------


def test_v2_rebuilds_byte_for_byte_from_its_frozen_pools_and_judgments():
    v1 = json.loads(ed.V1_FILE.read_text(encoding="utf-8"))
    criteria = json.loads((ed.JUDGMENTS_DIR / "criteria.json").read_text(encoding="utf-8"))
    pools = [p["candidates"] for p in json.loads(ed.POOLS_FILE.read_text(encoding="utf-8"))["pools"]]
    judgments = [ed.parse_judgments((ed.JUDGMENTS_DIR / f"q{i:02d}.txt").read_text(encoding="utf-8")) for i in range(1, len(v1) + 1)]
    committed = json.loads(ed.V2_FILE.read_text(encoding="utf-8"))
    manifest = json.loads(ed.MANIFEST_FILE.read_text(encoding="utf-8"))

    # build_dataset needs the catalogue only for its fingerprint, which the manifest holds.
    rebuilt = ed.build_dataset({}, v1, pools, judgments, criteria)
    assert rebuilt["queries"] == committed["queries"]
    assert committed["catalogue"] == manifest["catalogue"]


def test_every_frozen_input_still_matches_the_manifest():
    manifest = json.loads(ed.MANIFEST_FILE.read_text(encoding="utf-8"))
    problems = ed.verify_manifest(manifest, ed.load_documents())
    frozen_problems = [p for p in problems if not p.startswith("catalogue changed")]
    assert frozen_problems == [], frozen_problems


def test_the_manifest_covers_the_v1_baseline_the_pools_the_criteria_and_every_judgment_file():
    files = json.loads(ed.MANIFEST_FILE.read_text(encoding="utf-8"))["files"]
    assert "eval_queries.json" in files and "eval/eval_queries_v2.json" in files
    assert "eval/judgments_v2/pools.json" in files and "eval/judgments_v2/criteria.json" in files
    assert sum(1 for f in files if f.startswith("eval/judgments_v2/q")) == 25


def test_verify_detects_a_changed_a_missing_and_a_catalogue_that_moved_on(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATASET_DIR", tmp_path)
    (tmp_path / "a.json").write_text("one", encoding="utf-8")
    docs = {"p": _doc("p")}
    manifest = {"files": {"a.json": ed._sha256(tmp_path / "a.json"), "gone.json": "x"}, "catalogue": ed.catalogue_snapshot(docs)}
    assert ed.verify_manifest(manifest, docs) == ["missing frozen input: gone.json"]
    (tmp_path / "a.json").write_text("edited", encoding="utf-8")
    problems = ed.verify_manifest(manifest, {**docs, "q": _doc("q")})
    assert "frozen input changed: a.json" in problems
    assert any(p.startswith("catalogue changed since v2 was labelled (1 -> 2 projects)") for p in problems)


def test_the_manifest_records_a_text_fingerprint_for_every_project():
    manifest = json.loads(ed.MANIFEST_FILE.read_text(encoding="utf-8"))
    assert len(manifest["project_text_sha1"]) == manifest["catalogue"]["project_count"]


def test_project_text_hash_changes_with_the_searchable_text_only():
    base = _doc("p")
    assert ed.project_text_hash(base) == ed.project_text_hash({**base, "duration_weeks": 9, "github_url": "x"})
    assert ed.project_text_hash(base) != ed.project_text_hash({**base, "description": "different"})


# --- using v2 on a changed catalogue -------------------------------------------------------------


def test_v2_is_refused_on_any_other_catalogue():
    dataset = json.loads(ed.V2_FILE.read_text(encoding="utf-8"))
    docs = ed.load_documents()
    grown = {**docs, "pm-9999": _doc("pm-9999")}
    message = ev.snapshot_problem(dataset, ed.catalogue_snapshot(grown))
    assert message and "build a new dataset version" in message and str(dataset["catalogue"]["project_count"]) in message


def test_a_single_edited_description_is_enough_to_invalidate_the_labels():
    dataset = json.loads(ed.V2_FILE.read_text(encoding="utf-8"))
    docs = {pid: dict(d) for pid, d in ed.load_documents().items()}
    first = next(iter(docs))
    docs[first]["description"] += " Edited."
    assert ev.snapshot_problem(dataset, ed.catalogue_snapshot(docs)) is not None


# --- comparing saved reports -----------------------------------------------------------------------


def _report(dataset, count, sha, **cfg):
    return {"dataset": dataset, "catalogue": {"project_count": count, "sha256": sha}, "configuration": {"technology_weight": 0.0, **cfg}}


def test_reports_on_the_same_labels_and_catalogue_are_comparable_even_if_configuration_differs():
    verdict = ev.compare_reports(_report("v2", 868, "a"), _report("v2", 868, "a", technology_weight=0.25))
    assert verdict["comparable"] and verdict["reasons"] == []
    assert verdict["configuration_differences"] == {"technology_weight": (0.0, 0.25)}


@pytest.mark.parametrize(
    "a,b,fragment",
    [
        (_report("v1", 500, "a"), _report("v2", 868, "b"), "different label sets"),
        (_report("v1", 500, "a"), _report("v1", 868, "b"), "different catalogues"),
        (_report("v2", 868, "a"), _report("v3", 868, "a"), "different label sets"),
        (_report("v2", 868, "a"), _report("v2", 1100, "c"), "counted as not relevant"),
    ],
)
def test_reports_across_label_sets_or_catalogues_are_not_comparable(a, b, fragment):
    verdict = ev.compare_reports(a, b)
    assert not verdict["comparable"]
    assert any(fragment in r for r in verdict["reasons"])
    assert "Do not subtract" in verdict["advice"]


def test_the_stored_historical_and_current_reports_are_correctly_judged_incomparable():
    reports = config.DATASET_DIR / "reports"
    old = json.loads((reports / "eval_v1_500_baseline.json").read_text(encoding="utf-8"))
    new = json.loads((reports / "eval_v2_tech_0.25.json").read_text(encoding="utf-8"))
    assert not ev.compare_reports(old, new)["comparable"]
    assert ev.compare_reports(json.loads((reports / "eval_v2_tech_0.json").read_text(encoding="utf-8")), new)["comparable"]


# --- the next dataset version ------------------------------------------------------------------------


PREVIOUS = {
    "version": "v2",
    "catalogue": {"project_count": 4, "sha256": "old"},
    "relevance_scale": {"2": "a"},
    "pooling": {"depth": 10},
    "annotation": {"annotator": "single AI annotator"},
    "queries": [
        {"query": "q1", "v1_note": "n", "criteria": {"2": "x", "1": "y"}, "grades": {"a": 2, "b": 1, "c": 0, "d": 2}, "uncertain": ["b"], "v1_relevant": ["a"]},
    ],
}
OLD_DOCS = {p: _doc(p, title=f"Title {p}") for p in "abcd"}
OLD_HASHES = {p: ed.project_text_hash(d) for p, d in OLD_DOCS.items()}


def test_prepare_refuses_while_the_catalogue_is_unchanged_and_writes_nothing(tmp_path, monkeypatch, capsys):
    snapshot = ed.catalogue_snapshot(OLD_DOCS)
    previous = {**PREVIOUS, "catalogue": snapshot}
    monkeypatch.setattr(nv, "EVAL_DIR", tmp_path)
    monkeypatch.setattr(nv, "_load_previous", lambda version: previous)
    monkeypatch.setattr(nv.ed, "load_documents", lambda: OLD_DOCS)
    assert nv.main(["prepare", "--version", "v3"]) == 3
    assert "Nothing to prepare" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_unchanged_projects_carry_their_labels_and_new_candidates_need_judging():
    docs = {**OLD_DOCS, "e": _doc("e", "New one"), "f": _doc("f", "Another new one")}
    pools = [{"a": ["s"], "b": ["s"], "e": ["s"], "f": ["s"]}]
    plan = nv.plan_next_version(PREVIOUS, OLD_HASHES, docs, pools)
    q = plan["queries"][0]
    assert q["carried"] == {"a": [2, False], "b": [1, True], "c": [0, False], "d": [2, False]}  # incl. items outside the new pool
    assert q["to_judge"] == ["e", "f"]
    assert plan["totals"] == {"carried": 4, "to_judge": 2, "text_changed": 0, "removed": 0}


def test_a_project_whose_text_changed_or_was_removed_loses_its_old_label():
    docs = {p: dict(d) for p, d in OLD_DOCS.items()}
    docs["a"]["description"] = "rewritten"
    del docs["d"]
    plan = nv.plan_next_version(PREVIOUS, OLD_HASHES, docs, [{"a": ["s"], "b": ["s"]}])
    q = plan["queries"][0]
    assert q["text_changed"] == ["a"] and q["removed"] == ["d"]
    assert "a" not in q["carried"] and "d" not in q["carried"]
    assert q["to_judge"] == ["a"]  # a changed project that is still a candidate is judged again


def _plan_and_docs():
    docs = {**OLD_DOCS, "e": _doc("e", "New one")}
    return docs, nv.plan_next_version(PREVIOUS, OLD_HASHES, docs, [{"a": ["s"], "e": ["s"]}])


def test_build_merges_carried_and_new_labels_and_records_provenance():
    docs, plan = _plan_and_docs()
    key = nv.opaque_id("v3", 1, "e")
    dataset = nv.build_next_dataset(PREVIOUS, plan, [{key: (2, True)}], docs, {"q1": {"2": "x", "1": "y"}}, "v3", "Reviewer A (human)")
    q = dataset["queries"][0]
    assert q["grades"] == {"a": 2, "b": 1, "c": 0, "d": 2, "e": 2}
    assert q["uncertain"] == ["b", "e"]
    assert q["provenance"]["carried"] == 4 and q["provenance"]["newly_judged"] == 1
    assert dataset["annotation"]["annotator_of_new_labels"] == "Reviewer A (human)"
    assert "NOT directly comparable" in dataset["annotation"]["comparability"]
    assert dataset["catalogue"] == ed.catalogue_snapshot(docs) and dataset["version"] == "v3"


def test_build_refuses_unjudged_candidates_unknown_ids_and_an_unnamed_annotator():
    docs, plan = _plan_and_docs()
    criteria = {"q1": {"2": "x", "1": "y"}}
    with pytest.raises(ValueError, match="unjudged"):
        nv.build_next_dataset(PREVIOUS, plan, [{}], docs, criteria, "v3", "A")
    with pytest.raises(ValueError, match="unknown"):
        nv.build_next_dataset(PREVIOUS, plan, [{nv.opaque_id("v3", 1, "e"): (1, False), "ffffff": (0, False)}], docs, criteria, "v3", "A")
    for blank in ("", "   "):
        with pytest.raises(ValueError, match="annotator"):
            nv.build_next_dataset(PREVIOUS, plan, [{nv.opaque_id("v3", 1, "e"): (1, False)}], docs, criteria, "v3", blank)


def test_blinding_ids_differ_per_version_so_old_sheets_reveal_nothing():
    assert nv.opaque_id("v3", 1, "pm-001") != nv.opaque_id("v4", 1, "pm-001")
    assert nv.opaque_id("v3", 1, "pm-001") != ed.opaque_id(1, "pm-001")
    assert len({nv.opaque_id("v3", 2, f"pm-{n:03d}") for n in range(1, 900)}) == 899


def test_no_v3_artifacts_exist_before_the_catalogue_changes():
    assert not (config.DATASET_DIR / "eval" / "eval_queries_v3.json").exists()
    assert not (config.DATASET_DIR / "eval" / "judgments_v3").exists()
