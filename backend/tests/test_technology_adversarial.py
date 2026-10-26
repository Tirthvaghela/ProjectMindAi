"""Adversarial review of the technology signal (nlp/similarity.py).

Covers the distinctions the fix must preserve (React vs React Native vs
"reactive", Java vs JavaScript, Node.js vs "sensor node", capitalised names
that are also English words) and the property that matters most for ranking: a
project that merely *lists* a technology is helped by it, but a technology
mention is a bounded nudge and never makes an irrelevant project a strong result.
"""

from __future__ import annotations

import json
import re
import time

import numpy as np
import pytest

import config
from nlp import embeddings, similarity, skills
from nlp.similarity import HybridRetriever, query_technologies

from .test_technology_match import QUERY, catalogue, vocab  # noqa: F401  (fixtures shared with the main file)

SEED_LIST = json.loads(config.SEED_FILE.read_text(encoding="utf-8"))

# A vocabulary that contains the confusable names, independent of the catalogue.
INJECTED = {
    skills.normalize_key(t): skills.display_name(t)
    for t in [
        "Java", "JavaScript", "React", "React Native", "Flask", "Node.js", "Express", "Go", "Swift", "Unity", "C", "C++",
        "C#", "R", "Python", "TensorFlow", "TensorFlow Lite", "Terraform", "Sentence Transformers", "Transformers",
        "scikit-learn", "Flask-Limiter",
    ]
}


def named(query):
    return query_technologies(query, INJECTED)


@pytest.mark.parametrize(
    "query,expected",
    [
        # React / React Native / "reactive"
        ("React", {"react"}),
        ("react native", {"reactnative"}),
        ("React-Native app", {"reactnative"}),
        ("React Native and React", {"reactnative", "react"}),
        ("native React", {"react"}),
        ("react and native apps", {"react"}),
        ("React.js dashboard", {"react"}),
        ("reactjs", {"react"}),
        ("reactive programming with RxJS", set()),
        ("overreact", set()),
        # Java is never JavaScript
        ("Java developer", {"java"}),
        ("JavaScript developer", {"javascript"}),
        ("java and javascript", {"java", "javascript"}),
        ("javascripting", set()),
        # Flask
        ("Flask API", {"flask"}),
        ("Flask-Limiter rate limiting", {"flasklimiter"}),
        ("flasks of liquid", set()),
        # Node.js and "node"
        ("Node.js", {"nodejs"}),
        ("nodejs", {"nodejs"}),
        ("node.js", {"nodejs"}),
        ("Node JS", {"nodejs"}),
        ("Node API", {"nodejs"}),
        ("node", set()),
        ("sensor node placement", set()),
        ("graph node classification", set()),
        # ambiguous English words count only when capitalised
        ("Express", {"expressjs"}),
        ("express delivery", set()),
        ("Go", {"go"}),
        ("go to market", set()),
        ("Swift app", {"swift"}),
        ("swift response", set()),
        ("Unity AR", {"unity"}),
        ("unity of purpose", set()),
        # single letters and symbols
        ("C++ and C# projects", {"c++", "c#"}),
        ("a C project", {"c"}),
        ("c is a letter", set()),
        ("R statistics", {"r"}),
        ("r squared", set()),
        # aliases and near-collisions
        ("sklearn", {"scikitlearn"}),
        ("TensorFlow Lite", {"tensorflowlite"}),
        ("TFLite", {"tensorflowlite"}),
        ("TensorFlow", {"tensorflow"}),
        ("tf", set()),  # deliberately not an alias: TensorFlow and Terraform both use it
        ("Transformers", {"transformers"}),
        ("sentence-transformers", {"sentencetransformers"}),
        # case and punctuation
        ("REACT FLASK", {"react", "flask"}),
        ("(React, Flask)", {"react", "flask"}),
        ("react/flask", {"react", "flask"}),
        # junk
        ("", set()),
        ("   ", set()),
        ("!!!", set()),
        ("12345", set()),
        ("a b c d e f", set()),
    ],
)
def test_adversarial_technology_detection(query, expected):
    assert named(query) == expected


def test_a_long_noisy_query_is_handled_quickly():
    query = " ".join(["react native flask java node banana"] * 400)
    started = time.perf_counter()
    result = named(query)
    assert time.perf_counter() - started < 0.5
    assert {"reactnative", "flask", "java"} <= result


def test_english_word_technologies_never_fire_on_the_catalogues_own_lowercase_prose(vocab):
    """Scanned across every project's sentences — the real source of the names
    found to collide ('requests' 13x, 'node', 'dice') — in lowercase, as most
    students type."""
    gated = {skills.normalize_key(w) for w in similarity._AMBIGUOUS_TECH_NAMES}
    hits = set()
    for doc in SEED_LIST:
        for sentence in re.split(r"(?<=[.!?])\s+", doc["title"] + ". " + doc["description"]):
            hits |= query_technologies(sentence.lower(), vocab) & gated
    assert hits == set()


def test_capitalised_sentence_starts_are_the_only_residual_collisions_and_stay_rare(vocab):
    gated = {skills.normalize_key(w) for w in similarity._AMBIGUOUS_TECH_NAMES}
    collisions = 0
    for doc in SEED_LIST:
        own = {skills.normalize_key(t) for t in doc["technologies"]}
        for sentence in re.split(r"(?<=[.!?])\s+", doc["title"] + ". " + doc["description"]):
            collisions += len((query_technologies(sentence, vocab) & gated) - own)
    assert collisions <= 3  # currently 1: "Dice overlap" in a segmentation project


# --- retrieval behaviour --------------------------------------------------------------------


def _synthetic(monkeypatch, specs):
    """specs: [(title, technologies, cosine)] -> a retriever whose dense score for each project is exactly its cosine."""
    documents, cosines = {}, []
    for i, (title, techs, cos) in enumerate(specs):
        pid = f"t-{i:03d}"
        documents[pid] = {
            "project_id": pid, "title": title, "description": f"{title} project description for the retrieval tests.",
            "domain": "Web Development", "difficulty": "Beginner", "technologies": techs, "skills": ["Testing"], "duration_weeks": 6,
        }
        cosines.append(cos)
    c = np.array(cosines, dtype=np.float32)
    matrix = np.stack([c, np.sqrt(1 - c**2)], axis=1)
    monkeypatch.setattr(embeddings, "encode_one", lambda text: np.array([1.0, 0.0], dtype=np.float32))
    monkeypatch.setattr(config, "TECHNOLOGY_WEIGHT", 0.25)
    return HybridRetriever(matrix, list(documents), documents)


def test_java_projects_get_no_credit_for_a_javascript_query_and_vice_versa(monkeypatch):
    r = _synthetic(monkeypatch, [("Server app", ["Java"], 0.3), ("Browser app", ["JavaScript"], 0.3), ("Other", ["Rust"], 0.0), ("Other two", ["Go"], 0.1)])
    js = {x.document["title"]: x.technology_score for x in r.search("JavaScript app", top_k=4)}
    java = {x.document["title"]: x.technology_score for x in r.search("Java app", top_k=4)}
    assert js["Browser app"] == 1.0 and js["Server app"] == 0.0
    assert java["Server app"] == 1.0 and java["Browser app"] == 0.0


def test_the_blend_is_exactly_the_documented_convex_combination(catalogue):  # noqa: F811
    """final = (1 - w) * base + w * technology, for every result, so a technology
    mention adds at most w and the score can never exceed 1."""
    w = config.TECHNOLOGY_WEIGHT
    n = len(catalogue.ids)
    blended = {r.project_id: r for r in catalogue.search(QUERY, top_k=n)}
    base = {r.project_id: r.score for r in catalogue.search(QUERY, top_k=n, technology_match=False)}
    for pid, result in blended.items():
        assert result.score == pytest.approx((1 - w) * base[pid] + w * result.technology_score, abs=1e-6)
        assert result.score <= 1.0 + 1e-9


def test_a_much_more_relevant_project_beats_one_that_only_lists_the_technology(monkeypatch):
    """The bound: technology lifts a project by at most w, so a project whose
    base relevance is higher by more than w/(1-w) always wins."""
    r = _synthetic(
        monkeypatch,
        [
            ("Medical diagnosis assistant", ["Python", "Flask"], 0.50),
            ("Chess engine with a web board", ["Python", "Flask", "React"], 0.02),
            ("Garden journal", ["Ruby"], 0.10), ("Weather widget", ["Swift"], 0.12), ("Sudoku", ["Kotlin"], 0.08), ("Forum", ["PHP"], 0.05),
        ],
    )
    query = "React Flask medical diagnosis"
    results = r.search(query, top_k=6)
    assert results[0].document["title"] == "Medical diagnosis assistant"
    chess = next(x for x in results if x.document["title"].startswith("Chess"))
    base = next(x for x in r.search(query, top_k=6, technology_match=False) if x.document["title"].startswith("Chess"))
    w = config.TECHNOLOGY_WEIGHT
    assert chess.score <= w + (1 - w) * base.score + 1e-9
    assert chess.score < results[0].score - 0.2  # nowhere near a strong result despite listing both technologies


def test_a_listed_technology_helps_a_borderline_project_but_cannot_rescue_an_irrelevant_one(monkeypatch):
    r = _synthetic(
        monkeypatch,
        [
            ("Close semantic match, no technology", ["Rust"], 0.40),
            ("Borderline match, lists the technology", ["Flask"], 0.33),
            ("Irrelevant, lists the technology", ["Flask"], -0.10),
            ("Irrelevant", ["Ruby"], -0.12), ("Filler a", ["PHP"], 0.0), ("Filler b", ["Perl"], 0.05),
        ],
    )
    order = [x.document["title"] for x in r.search("Flask dashboard", top_k=6)]
    assert order.index("Borderline match, lists the technology") < order.index("Close semantic match, no technology")
    assert order.index("Close semantic match, no technology") < order.index("Irrelevant, lists the technology")


def test_two_named_technologies_need_both_for_full_credit(monkeypatch):
    r = _synthetic(monkeypatch, [("Both", ["React", "Flask"], 0.1), ("One", ["React"], 0.1), ("None", ["Rust"], 0.1), ("Pad", ["PHP"], 0.0)])
    scores = {x.document["title"]: x.technology_score for x in r.search("React Flask", top_k=4)}
    assert scores == {"Both": 1.0, "One": 0.5, "None": 0.0, "Pad": 0.0}


def test_a_technology_not_in_the_catalogue_changes_nothing(monkeypatch):
    r = _synthetic(monkeypatch, [("A", ["React"], 0.2), ("B", ["Flask"], 0.1), ("C", ["Go"], 0.0)])
    assert all(x.technology_score is None for x in r.search("COBOL mainframe app", top_k=3))


def test_filters_and_the_blend_compose(monkeypatch):
    # A and C are equal on meaning, so the technology share decides between them.
    r = _synthetic(monkeypatch, [("A", ["React", "Flask"], 0.15), ("B", ["React"], 0.2), ("C", ["Flask"], 0.15), ("D", ["Rust"], 0.0)])
    results = r.search("React Flask", filters={"technologies": ["Flask"]}, top_k=4)
    assert {x.document["title"] for x in results} == {"A", "C"}
    assert results[0].document["title"] == "A"


def test_ranking_is_deterministic_including_exact_ties(monkeypatch):
    r = _synthetic(monkeypatch, [(f"Same {i}", ["React"], 0.2) for i in range(12)] + [("Other", ["Rust"], 0.0)])
    first = [x.project_id for x in r.search("React app", top_k=12)]
    assert first == [x.project_id for x in r.search("React app", top_k=12)]


def test_fusion_weights_and_the_technology_weight_are_the_documented_values():
    assert (config.DENSE_WEIGHT, config.SPARSE_WEIGHT) == (0.80, 0.20)
    assert config.TECHNOLOGY_WEIGHT == 0.25
