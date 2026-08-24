"""nlp/recommend.py:_build_retriever() — catalogue/index drift detection.

Needs a real mongo_test_db (unlike test_recommend.py's own tests, which
monkeypatch get_retriever entirely) since this function's whole job is
comparing MongoDB's actual contents against the on-disk index — faking one
side away would test nothing. embeddings.load_index() is monkeypatched
instead, so this never touches the real embedding index file on disk.
"""

from __future__ import annotations

import logging

import numpy as np

from db import client as db
from nlp import embeddings, recommend


def _fake_index(ids: list[str], dim: int = 4):
    matrix = np.zeros((len(ids), dim), dtype=np.float32)
    return matrix, list(ids)


def test_drops_and_warns_about_indexed_projects_no_longer_in_mongo(mongo_test_db, monkeypatch, caplog):
    db.projects().insert_one({"project_id": "pm-real-1", "title": "Still here"})
    monkeypatch.setattr(embeddings, "load_index", lambda: _fake_index(["pm-real-1", "pm-ghost-2"]))

    with caplog.at_level(logging.WARNING, logger="nlp.recommend"):
        retriever = recommend._build_retriever()

    assert retriever.ids == ["pm-real-1"]  # the orphan was dropped, not just warned about
    assert "no longer in MongoDB" in caplog.text


def test_warns_about_mongo_projects_missing_from_the_index(mongo_test_db, monkeypatch, caplog):
    db.projects().insert_one({"project_id": "pm-indexed-1", "title": "Indexed"})
    db.projects().insert_one({"project_id": "pm-unindexed-2", "title": "Just added, not indexed yet"})
    monkeypatch.setattr(embeddings, "load_index", lambda: _fake_index(["pm-indexed-1"]))

    with caplog.at_level(logging.WARNING, logger="nlp.recommend"):
        retriever = recommend._build_retriever()

    # The un-indexed project is still a real catalogue document (routes like
    # get_project_details must still find it) — it's just absent from search,
    # which `.ids` (not `.documents`) is what actually drives.
    assert "pm-indexed-1" in retriever.ids
    assert "pm-unindexed-2" not in retriever.ids
    assert "pm-unindexed-2" in retriever.documents
    assert "not in the search index yet" in caplog.text
    assert "pm-unindexed-2" in caplog.text


def test_no_warning_when_mongo_and_the_index_agree(mongo_test_db, monkeypatch, caplog):
    db.projects().insert_one({"project_id": "pm-agree-1", "title": "In sync"})
    monkeypatch.setattr(embeddings, "load_index", lambda: _fake_index(["pm-agree-1"]))

    with caplog.at_level(logging.WARNING, logger="nlp.recommend"):
        recommend._build_retriever()

    assert caplog.text == ""
