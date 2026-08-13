"""HybridRetriever tests against a small synthetic corpus.

The query-encoding step is monkeypatched to a hand-picked vector rather than
loading the real sentence-transformer model — these tests are about the
retriever's *logic* (filter-before-rank, similarity, deduplication), which
doesn't need real embeddings to verify, and skipping the model load keeps
this file fast and independent of a model download being cached.
"""

from __future__ import annotations

import numpy as np
import pytest

from nlp import embeddings
from nlp.similarity import HybridRetriever

DOCS = {
    "a": {
        "project_id": "a",
        "title": "Beginner web dashboard",
        "description": "A simple web project for beginners learning the basics.",
        "domain": "Web Development",
        "difficulty": "Beginner",
        "technologies": ["React"],
        "skills": ["HTML", "CSS"],
        "duration_weeks": 4,
    },
    "b": {
        "project_id": "b",
        "title": "Advanced AI research system",
        "description": "An advanced AI project using deep learning techniques.",
        "domain": "Artificial Intelligence",
        "difficulty": "Advanced",
        "technologies": ["Python", "PyTorch"],
        "skills": ["Deep learning"],
        "duration_weeks": 16,
    },
    "c": {
        "project_id": "c",
        "title": "Intermediate web app with Node",
        "description": "An intermediate full-stack web project with a REST API.",
        "domain": "Web Development",
        "difficulty": "Intermediate",
        "technologies": ["React", "Node.js"],
        "skills": ["APIs"],
        "duration_weeks": 8,
    },
}
IDS = ["a", "b", "c"]
# Orthogonal unit vectors — doc "b" is the closest match to the query vector
# used below, so the filter-before-rank test below has real teeth: an
# unfiltered search must return "b" first, and a filtered one must never
# return it at all.
MATRIX = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], dtype=np.float32)


@pytest.fixture
def retriever():
    return HybridRetriever(MATRIX, IDS, DOCS)


def test_mask_filters_by_domain(retriever):
    assert list(retriever._mask({"domain": "Web Development"})) == [True, False, True]


def test_mask_filters_by_difficulty(retriever):
    assert list(retriever._mask({"difficulty": "Beginner"})) == [True, False, False]


def test_mask_filters_by_technology_any_semantics(retriever):
    assert list(retriever._mask({"technologies": ["React"]})) == [True, False, True]


def test_mask_filters_by_max_duration(retriever):
    assert list(retriever._mask({"max_duration_weeks": 6})) == [True, False, False]


def test_mask_with_no_filters_keeps_everything(retriever):
    assert list(retriever._mask(None)) == [True, True, True]


def test_search_filters_before_ranking(monkeypatch, retriever):
    monkeypatch.setattr(
        embeddings, "encode_one", lambda text: np.array([0.0, 1.0, 0.0], dtype=np.float32)
    )

    results = retriever.search("anything", filters={"domain": "Web Development"}, top_k=5)

    # "b" is the best unfiltered match by a wide margin, but it's not a Web
    # Development project — it must never appear once that filter is applied.
    assert {r.project_id for r in results} == {"a", "c"}


def test_search_ranks_by_dense_similarity_when_unfiltered(monkeypatch, retriever):
    monkeypatch.setattr(
        embeddings, "encode_one", lambda text: np.array([0.0, 1.0, 0.0], dtype=np.float32)
    )
    results = retriever.search("anything", top_k=1)
    assert results[0].project_id == "b"


def test_similar_excludes_the_project_itself(retriever):
    results = retriever.similar("a", top_k=2)
    assert all(r.project_id != "a" for r in results)


def test_find_duplicates_flags_near_identical_vectors():
    matrix = np.array([[1.0, 0.0], [0.999, 0.0447], [0.0, 1.0]], dtype=np.float32)
    matrix = matrix / np.linalg.norm(matrix, axis=1, keepdims=True)
    docs = {pid: {"project_id": pid} for pid in ("x", "y", "z")}
    retriever = HybridRetriever(matrix, ["x", "y", "z"], docs)

    pairs = list(retriever.find_duplicates(threshold=0.99))
    flagged = {pid for pair in pairs for pid in pair[:2]}
    assert flagged == {"x", "y"}
