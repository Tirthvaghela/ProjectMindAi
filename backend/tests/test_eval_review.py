"""The independent-review workflow (scripts/eval_review.py).

Every reviewer in this file is a SYNTHETIC test fixture. Nothing here is, or
stands in for, a real human review: the real labels remain single-annotator
until a person fills in dataset/eval/review/review_sheet_v2.csv.
"""

from __future__ import annotations

import csv
import json
import re

import pytest

import config
from scripts import eval_dataset as ed
from scripts import eval_review as er

SENTINEL_IDS = [f"pm-9{n:03d}" for n in range(1, 41)]


def _doc(pid, n):
    return {
        "project_id": pid,
        "title": f"Project number {n}",
        "description": f"A description of project {n} that is long enough to be a realistic record for review.",
        "domain": "Robotics",
        "difficulty": "Beginner",
        "technologies": ["Python", "ROS"],
        "duration_weeks": 5,
        "skills": ["x"],
        "keywords": ["k"],
    }


DOCS = {pid: _doc(pid, i) for i, pid in enumerate(SENTINEL_IDS)}


def _dataset():
    """Two queries, 20 judged projects each; grades follow a fixed pattern and
    every fifth item is marked uncertain."""
    queries = []
    for q in range(2):
        pids = SENTINEL_IDS[q * 20 : (q + 1) * 20]
        grades = {pid: (i * 7 + q) % 3 for i, pid in enumerate(pids)}
        queries.append(
            {
                "query": f"query {q}",
                "criteria": {"2": "two means yes", "1": "one means maybe"},
                "grades": grades,
                "uncertain": pids[::5],
                "v1_relevant": pids[:3],
            }
        )
    return {"version": "v2", "queries": queries}


@pytest.fixture
def export():
    dataset = _dataset()
    rows, key = er.build_export(dataset, DOCS, "deadbeef")
    return dataset, rows, key


# --- nothing the AI knows reaches the reviewer ---------------------------------------


def test_the_sheet_has_exactly_the_documented_columns_and_blank_reviewer_fields(export):
    _, rows, _ = export
    assert list(rows[0]) == er.SHEET_COLUMNS
    assert all(not r[c] for r in rows for c in er.REVIEWER_COLUMNS)


def test_no_project_id_ai_grade_flag_or_label_appears_anywhere_in_the_sheet(tmp_path, export):
    dataset, rows, key = export
    sheet = tmp_path / "sheet.csv"
    er.write_export(rows, key, sheet, tmp_path / "key.json")
    text = sheet.read_text(encoding="utf-8")
    assert not re.search(r"pm-9\d{3}", text)
    for forbidden in ("uncertain\"", "v1_relevant", "stratum", "sampled", "project_id", "dataset_sha256", "grades"):
        assert forbidden not in text.replace("reviewer_uncertain", "")
    assert re.fullmatch(r"R\d{3}", rows[0]["row_id"])


def test_row_ids_and_order_do_not_reveal_the_stratum(export):
    _, rows, key = export
    ids = [r["row_id"] for r in rows]
    assert ids == [f"R{n:03d}" for n in range(1, len(rows) + 1)]
    uncertain_positions = [i for i, r in enumerate(rows) if key["rows"][r["row_id"]]["stratum"] == "uncertain"]
    n = len(uncertain_positions)
    assert uncertain_positions not in (list(range(n)), list(range(len(rows) - n, len(rows))))  # not first/last blocks


def test_the_private_key_alone_maps_rows_back_to_projects_and_is_marked_private(export):
    _, _, key = export
    assert "PRIVATE" in key["warning"]
    assert {v["project_id"] for v in key["rows"].values()} <= set(SENTINEL_IDS)
    assert all("grade" not in v for v in key["rows"].values())  # the key holds no AI grades either


def test_the_export_is_deterministic(export):
    dataset, rows, key = export
    rows2, key2 = er.build_export(dataset, DOCS, "deadbeef")
    assert rows == rows2 and key == key2


# --- the sample ------------------------------------------------------------------------


def test_every_uncertain_item_is_included_and_every_query_is_represented(export):
    dataset, _, key = export
    chosen = {(v["query_index"], v["project_id"]) for v in key["rows"].values()}
    for index, query in enumerate(dataset["queries"], 1):
        assert {(index, p) for p in query["uncertain"]} <= chosen
        assert sum(1 for v in key["rows"].values() if v["query_index"] == index and v["stratum"] == "sampled") >= er.MIN_PER_QUERY
    assert key["strata"]["uncertain"] == sum(len(q["uncertain"]) for q in dataset["queries"])


def test_the_two_strata_are_disjoint_and_the_sample_comes_from_confident_items(export):
    dataset, _, key = export
    for entry in key["rows"].values():
        q = dataset["queries"][entry["query_index"] - 1]
        assert (entry["project_id"] in q["uncertain"]) == (entry["stratum"] == "uncertain")


def test_everything_mode_exports_every_judged_item_exactly_once():
    dataset = _dataset()
    rows, key = er.build_export(dataset, DOCS, "x", everything=True)
    assert len(rows) == sum(len(q["grades"]) for q in dataset["queries"])
    assert len({(v["query_index"], v["project_id"]) for v in key["rows"].values()}) == len(rows)


# --- reading a reviewer's sheet -----------------------------------------------------------


def _fill(tmp_path, rows, grades, name="rev.csv", uncertain=(), comments=()):
    """A SYNTHETIC reviewer: writes the sheet back with the given grades."""
    path = tmp_path / name
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=er.SHEET_COLUMNS)
        writer.writeheader()
        for row in rows:
            out = dict(row)
            if row["row_id"] in grades:
                out["reviewer_grade"] = str(grades[row["row_id"]])
            if row["row_id"] in uncertain:
                out["reviewer_uncertain"] = "y"
            if row["row_id"] in comments:
                out["reviewer_comment"] = "borderline"
            writer.writerow(out)
    return path


def _ai(dataset, key, row_id):
    return er._ai_grade(dataset, key["rows"][row_id])


def test_a_complete_valid_sheet_is_read_with_grades_uncertainty_and_comments(tmp_path, export):
    dataset, rows, key = export
    path = _fill(tmp_path, rows, {r["row_id"]: 1 for r in rows}, uncertain={"R001"}, comments={"R002", "R003"})
    data = er.read_reviewer("a", path, key)
    assert data.ok and len(data.grades) == len(rows)
    assert data.uncertain == {"R001"} and data.comments == 2


def test_a_partial_sheet_is_valid_but_reports_its_real_coverage(tmp_path, export):
    dataset, rows, key = export
    path = _fill(tmp_path, rows, {r["row_id"]: 2 for r in rows[:10]})
    data = er.read_reviewer("a", path, key)
    assert data.ok and len(data.grades) == 10


@pytest.mark.parametrize("bad", ["3", "-1", "two", "1.5", "2x"])
def test_invalid_grades_are_reported_never_silently_dropped(tmp_path, export, bad):
    dataset, rows, key = export
    path = _fill(tmp_path, rows, {})
    crlf = chr(13) + chr(10)
    raw = path.read_bytes().replace(f",,,{crlf}".encode(), f",{bad},,{crlf}".encode(), 1)
    path.write_bytes(raw)
    data = er.read_reviewer("a", path, key)
    assert any("reviewer_grade must be 0, 1 or 2" in p for p in data.problems)


def test_an_edited_project_text_is_rejected(tmp_path, export):
    dataset, rows, key = export
    tampered = [dict(r) for r in rows]
    tampered[0]["description"] += " (edited by the reviewer)"
    data = er.read_reviewer("a", _fill(tmp_path, tampered, {}), key)
    assert any("was edited" in p for p in data.problems)


def test_unknown_duplicate_and_missing_rows_and_wrong_columns_are_reported(tmp_path, export):
    dataset, rows, key = export
    extra = [dict(rows[0], row_id="R999")]
    assert any("unknown row id" in p for p in er.read_reviewer("a", _fill(tmp_path, rows + extra, {}, "a.csv"), key).problems)
    assert any("twice" in p for p in er.read_reviewer("b", _fill(tmp_path, rows + [rows[0]], {}, "b.csv"), key).problems)
    assert any("absent" in p for p in er.read_reviewer("c", _fill(tmp_path, rows[:-3], {}, "c.csv"), key).problems)
    wrong = tmp_path / "wrong.csv"
    wrong.write_text("a,b\n1,2\n", encoding="utf-8")
    assert any("columns differ" in p for p in er.read_reviewer("d", wrong, key).problems)
    assert any("cannot read" in p for p in er.read_reviewer("e", tmp_path / "missing.csv", key).problems)


def test_a_utf8_bom_from_a_spreadsheet_program_is_tolerated(tmp_path, export):
    dataset, rows, key = export
    path = _fill(tmp_path, rows, {r["row_id"]: 0 for r in rows})
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    assert er.read_reviewer("a", path, key).ok


# --- statistics: synthetic reviewers ----------------------------------------------------------


def _agrees(dataset, key, rows, flip=lambda ai, row_id: ai):
    return {r["row_id"]: flip(_ai(dataset, key, r["row_id"]), r["row_id"]) for r in rows}


def test_a_reviewer_who_matches_the_ai_exactly_gives_perfect_agreement(tmp_path, export):
    dataset, rows, key = export
    data = er.read_reviewer("perfect", _fill(tmp_path, rows, _agrees(dataset, key, rows)), key)
    report = er.compare(dataset, key, [data])
    r = report["reviewers"]["perfect"]
    assert r["vs_ai_confident_items"]["exact_agreement"] == 1.0
    assert r["vs_ai_confident_items"]["weighted_kappa"] == pytest.approx(1.0)
    assert r["vs_ai_uncertain_items"]["n"] == key["strata"]["uncertain"]
    assert "single reviewer" in report["note"].lower() or "one reviewer" in report["note"].lower()


def test_strata_are_reported_separately_never_pooled(tmp_path, export):
    dataset, rows, key = export
    # agree on confident items, always disagree (by one grade) on AI-uncertain ones
    flip = lambda ai, row_id: ai if key["rows"][row_id]["stratum"] == "sampled" else (ai + 1) % 3  # noqa: E731
    data = er.read_reviewer("mixed", _fill(tmp_path, rows, _agrees(dataset, key, rows, flip)), key)
    r = er.compare(dataset, key, [data])["reviewers"]["mixed"]
    assert r["vs_ai_confident_items"]["exact_agreement"] == 1.0
    assert r["vs_ai_uncertain_items"]["exact_agreement"] == 0.0
    assert "pooled" not in json.dumps(r)


def test_a_reviewer_who_uses_one_grade_throughout_has_undefined_kappa_not_a_fake_number(tmp_path, export):
    dataset, rows, key = export
    data = er.read_reviewer("flat", _fill(tmp_path, rows, {r["row_id"]: 1 for r in rows}), key)
    r = er.compare(dataset, key, [data])["reviewers"]["flat"]["vs_ai_confident_items"]
    assert 0.0 <= r["exact_agreement"] <= 1.0
    assert r["weighted_kappa"] is not None  # the AI varies, so chance agreement is not total
    assert er.weighted_kappa([(1, 1), (1, 1), (1, 1)]) is None
    assert er.weighted_kappa([]) is None


def test_inter_reviewer_agreement_and_majority_consensus_with_two_reviewers(tmp_path, export):
    dataset, rows, key = export
    ai = _agrees(dataset, key, rows)
    a = er.read_reviewer("a", _fill(tmp_path, rows, ai, "a.csv"), key)
    b = er.read_reviewer("b", _fill(tmp_path, rows, ai, "b.csv"), key)
    report = er.compare(dataset, key, [a, b])
    pair = report["inter_reviewer"]["a vs b"]
    assert pair["n"] == len(rows) and pair["exact_agreement"] == 1.0
    assert report["consensus_vs_ai"]["rows_with_a_majority"] == len(rows)
    assert report["consensus_vs_ai"]["confident_items"]["exact_agreement"] == 1.0


def test_a_two_reviewer_tie_has_no_consensus_rather_than_an_arbitrary_one(tmp_path, export):
    dataset, rows, key = export
    a = er.read_reviewer("a", _fill(tmp_path, rows, {r["row_id"]: 0 for r in rows}, "a.csv"), key)
    b = er.read_reviewer("b", _fill(tmp_path, rows, {r["row_id"]: 2 for r in rows}, "b.csv"), key)
    report = er.compare(dataset, key, [a, b])
    assert report["consensus_vs_ai"]["rows_with_a_majority"] == 0
    assert report["inter_reviewer"]["a vs b"]["disagreements_by_two_grades"] == len(rows)


def test_inter_reviewer_agreement_uses_only_rows_both_graded(tmp_path, export):
    dataset, rows, key = export
    a = er.read_reviewer("a", _fill(tmp_path, rows, {r["row_id"]: 1 for r in rows[:30]}, "a.csv"), key)
    b = er.read_reviewer("b", _fill(tmp_path, rows, {r["row_id"]: 1 for r in rows[20:50]}, "b.csv"), key)
    assert er.compare(dataset, key, [a, b])["inter_reviewer"]["a vs b"]["n"] == 10


def test_with_no_reviewers_the_report_says_nothing_rather_than_inventing_results(export):
    dataset, _, key = export
    report = er.compare(dataset, key, [])
    assert report["reviewers"] == {} and report["inter_reviewer"] == {}
    assert "No completed reviewer sheet" in report["note"]
    assert er.interpretation(report) == ["No interpretation available yet."]


def test_an_invalid_sheet_is_excluded_from_inter_reviewer_statistics(tmp_path, export):
    dataset, rows, key = export
    good = er.read_reviewer("good", _fill(tmp_path, rows, _agrees(dataset, key, rows), "g.csv"), key)
    bad = er.read_reviewer("bad", _fill(tmp_path, rows[:-5], {}, "b.csv"), key)
    report = er.compare(dataset, key, [good, bad])
    assert not report["reviewers"]["bad"]["valid"] and report["inter_reviewer"] == {}


def test_interpretation_refuses_to_call_agreement_on_too_few_items(tmp_path, export):
    dataset, rows, key = export
    data = er.read_reviewer("tiny", _fill(tmp_path, rows, {r["row_id"]: 2 for r in rows[:6]}), key)
    report = er.compare(dataset, key, [data])
    assert any("too few" in line for line in er.interpretation(report))


# --- the real files --------------------------------------------------------------------------


def test_the_committed_sheet_is_exactly_what_a_fresh_export_produces():
    dataset = json.loads(ed.V2_FILE.read_text(encoding="utf-8"))
    rows, _ = er.build_export(dataset, ed.load_documents(), er.file_sha256(ed.V2_FILE))
    with er.SHEET_FILE.open(encoding="utf-8", newline="") as handle:
        committed = list(csv.DictReader(handle))
    assert committed == rows


def test_the_committed_sheet_leaks_no_ids_grades_or_labels():
    text = er.SHEET_FILE.read_text(encoding="utf-8")
    assert not re.search(r"pm-\d", text)
    with er.SHEET_FILE.open(encoding="utf-8", newline="") as handle:
        header = next(csv.reader(handle))
    assert header == er.SHEET_COLUMNS
    assert not any(c in header for c in ("project_id", "grade", "uncertain", "stratum", "v1_relevant", "opaque_id", "score", "rank"))


def test_the_private_key_is_ignored_by_git_and_the_instructions_are_grade_free():
    ignore = (config.BASE_DIR.parent / ".gitignore").read_text(encoding="utf-8")
    assert "backend/dataset/eval/review/PRIVATE_*" in ignore
    instructions = (er.REVIEW_DIR / "REVIEWER_INSTRUCTIONS.md").read_text(encoding="utf-8")
    assert not re.search(r"pm-\d|v1_relevant|AI grade", instructions)


def test_the_cli_refuses_a_sheet_made_for_a_different_dataset_version(tmp_path, monkeypatch, export, capsys):
    dataset, rows, key = export
    dataset_file = tmp_path / "eval_queries_v2.json"
    dataset_file.write_text(json.dumps(dataset), encoding="utf-8")
    key["dataset_sha256"] = "not-the-current-hash"
    key_file = tmp_path / "key.json"
    key_file.write_text(json.dumps(key), encoding="utf-8")
    monkeypatch.setattr(er, "V2_FILE", dataset_file)
    monkeypatch.setattr(er, "KEY_FILE", key_file)
    monkeypatch.setattr(er, "load_documents", lambda: DOCS)
    assert er.main(["validate", str(tmp_path / "whatever.csv")]) == 2
    assert "changed after this sheet was exported" in capsys.readouterr().err
