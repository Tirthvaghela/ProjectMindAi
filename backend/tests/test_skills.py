"""nlp/skills.py — the shared skill/technology alias layer — and the places that
now use it: skill-gap matching, the technology filter, and the readable
keyword display ("pandas", not the lemma "panda").
"""

from __future__ import annotations

import numpy as np
import pytest

from nlp import embeddings, preprocess, recommend, skills
from nlp.similarity import HybridRetriever, doc_matches

# --- aliases ------------------------------------------------------------------


@pytest.mark.parametrize(
    "a,b",
    [
        ("JS", "JavaScript"),
        ("Javascript", "JavaScript"),
        ("java script", "JavaScript"),
        ("sklearn", "scikit-learn"),
        ("scikit learn", "scikit-learn"),
        ("Scikit_Learn", "scikit-learn"),
        ("SCIKIT-LEARN", "sklearn"),
        ("node", "Node.js"),
        ("nodejs", "Node.js"),
        (" Node JS ", "Node.js"),
        ("tflite", "TensorFlow Lite"),
        ("TF Lite", "TensorFlow Lite"),
        ("sbert", "Sentence Transformers"),
        ("sentence-transformers", "Sentence Transformers"),
        ("Hugging Face Transformers", "Transformers"),
        ("gh actions", "GitHub Actions"),
        ("rpi", "Raspberry Pi"),
        ("sqlite3", "SQLite"),
        ("d3", "D3.js"),
        ("cv2", "OpenCV"),
        ("postgres", "PostgreSQL"),
        ("mongo", "MongoDB"),
        ("k8s", "Kubernetes"),
        ("cpp", "C++"),
        ("csharp", "C#"),
        ("golang", "Go"),
        ("ml", "Machine Learning"),
        ("react.js", "React"),
        ("Vue", "Vue.js"),
    ],
)
def test_known_aliases_are_the_same_skill_in_any_case_or_punctuation(a, b):
    assert skills.same_skill(a, b)
    assert skills.same_skill(b, a)


@pytest.mark.parametrize(
    "a,b",
    [
        ("Java", "JavaScript"),  # the case that must never merge
        ("JavaScript", "TypeScript"),
        ("React", "React Native"),
        ("C", "C++"),
        ("C++", "C#"),
        ("Go", "Google Cloud"),
        ("MySQL", "PostgreSQL"),
        ("Python", "PyTorch"),
        ("TensorFlow", "TensorFlow Lite"),
        ("Transformers", "Sentence Transformers"),
        ("Python", "GitPython"),
        ("pandas", "GeoPandas"),
        ("PyTorch", "PyTorch Geometric"),
        ("tf", "Terraform"),
        ("tf", "TensorFlow"),
        ("cv", "Computer Vision"),
        ("yolo", "YOLOv8"),
        ("ROS", "ROS2"),
        ("ESP32", "ESP8266"),
        ("web3", "Web3.js"),
        ("Angular", "React"),
        ("pandas", "NumPy"),
    ],
)
def test_distinct_technologies_are_never_merged(a, b):
    assert not skills.same_skill(a, b)


@pytest.mark.parametrize("risky", ["tf", "cv", "ts", "np", "torch", "py", "next", "web3", "yolo", "ros2", "esp8266", ".net"])
def test_ambiguous_abbreviations_are_deliberately_not_aliases(risky):
    # Each has a second plausible meaning, so it must not silently map to one
    # technology (see _DELIBERATELY_NOT_ALIASED in nlp/skills.py).
    assert skills.canonical_name(risky) is None


def test_aliases_apply_to_whole_names_not_substrings():
    assert skills.canonical_name("node degree analysis") is None
    assert skills.canonical_name("tf-idf weighting") is None
    assert skills.canonical_name("Javascript frameworks") is None
    assert not skills.same_skill("Java", "JavaScript")


def test_unknown_names_keep_their_own_form_and_never_collide():
    assert skills.canonical_name("Haskell") is None
    assert skills.display_name("  Haskell ") == "Haskell"
    assert skills.same_skill("Haskell", "haskell")
    assert not skills.same_skill("Haskell", "Erlang")


@pytest.mark.parametrize("junk", ["", "   ", None, 7, [], {}])
def test_junk_input_is_handled_without_raising(junk):
    assert skills.canonical_name(junk) is None
    assert skills.display_name(junk) == ""
    assert skills.same_skill(junk, "Python") is False
    assert skills.same_skill(junk, junk) is False


def test_display_name_uses_the_canonical_spelling():
    assert skills.display_name("sklearn") == "scikit-learn"
    assert skills.display_name("JS") == "JavaScript"
    assert skills.display_name("node") == "Node.js"
    assert skills.display_name("pandas") == "pandas"


# --- skill-gap matching ---------------------------------------------------------

DOC = {
    "skills": ["Node.js", "Scikit Learn", "REST API development"],
    "technologies": ["TensorFlow", "JavaScript"],
}


def test_skill_gap_credits_aliases_and_keeps_the_projects_own_names():
    gap = recommend.skill_gap_for_doc(DOC, ["node", "sklearn"])
    assert gap["skills_you_have"] == ["Node.js", "Scikit Learn"]
    assert gap["skills_to_learn"] == ["REST API development"]


def test_skill_gap_alias_matching_does_not_create_java_javascript_false_positives():
    gap = recommend.skill_gap_for_doc({"skills": ["JavaScript"]}, ["Java"])
    assert gap["skills_you_have"] == []
    assert gap["skills_to_learn"] == ["JavaScript"]


def test_best_fit_skill_fit_credits_tech_aliases_once():
    fit = recommend._skill_fit(DOC, ["tensorflow", "js"])
    assert set(fit["skills_you_have"]) == {"TensorFlow", "JavaScript"}
    # "Node.js" appears as a skill; had it also been a technology it must not
    # be double counted under a different spelling.
    doc = {"skills": ["Node.js"], "technologies": ["nodejs", "Express"]}
    assert recommend._skill_fit(doc, [])["required_skills"] == ["Node.js", "Express"]


def test_existing_phrase_matching_is_unchanged():
    # The token-overlap path must keep crediting reworded phrases.
    gap = recommend.skill_gap_for_doc({"skills": ["REST API development"]}, ["developing REST APIs"])
    assert gap["skills_you_have"] == ["REST API development"]


# --- technology filter ------------------------------------------------------------


def test_technology_filter_uses_the_alias_table():
    doc = {"technologies": ["scikit-learn", "Node.js"], "duration_weeks": 4}
    assert doc_matches(doc, {"technologies": ["sklearn"]})
    assert doc_matches(doc, {"technologies": ["NODE"]})
    assert not doc_matches(doc, {"technologies": ["java"]})
    assert not doc_matches({"technologies": ["JavaScript"]}, {"technologies": ["Java"]})


# --- readable keyword display --------------------------------------------------------


def test_display_map_restores_readable_technology_names():
    shown = preprocess.token_display_map("Python, pandas, scikit-learn, JS, node.js, C++ and C#")
    assert shown["panda"] == "pandas"
    assert shown["scikit-learn"] == "scikit-learn"
    assert shown["javascript"] == "JavaScript"
    assert shown["node.javascript"] == "Node.js"  # the expander's internal form is never shown
    assert shown["c++"] == "C++" and shown["c#"] == "C#"
    assert "panda" not in shown.values() and "node.javascript" not in shown.values()


def test_display_map_leaves_matching_tokens_alone():
    assert "panda" in preprocess.tokens_for_bm25("pandas")  # lemma is still what matches


def test_display_map_handles_empty_input():
    assert preprocess.token_display_map("") == {}
    assert preprocess.token_display_map("   ") == {}


def test_matched_terms_shown_to_the_user_are_readable_not_lemmas(monkeypatch):
    docs = {
        "p": {
            "project_id": "p",
            "title": "Data pipeline",
            "description": "A pipeline built with pandas and scikit-learn and JavaScript.",
            "domain": "Data Science",
            "difficulty": "Beginner",
            "technologies": ["pandas", "scikit-learn", "JavaScript"],
            "skills": ["Data wrangling"],
            "duration_weeks": 4,
        },
        "q": {
            "project_id": "q",
            "title": "Garden diary",
            "description": "A diary for plants and watering schedules.",
            "domain": "Mobile Development",
            "difficulty": "Beginner",
            "technologies": ["Kotlin"],
            "skills": ["Android"],
            "duration_weeks": 4,
        },
    }
    matrix = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    monkeypatch.setattr(embeddings, "encode_one", lambda text: np.array([1.0, 0.0], dtype=np.float32))
    retriever = HybridRetriever(matrix, ["p", "q"], docs)

    [first, *_] = retriever.search("pandas, scikit-learn and JS", top_k=2)

    assert first.project_id == "p"
    assert {"pandas", "scikit-learn", "JavaScript"} <= set(first.matched_terms)
    assert "panda" not in first.matched_terms
    explanation = recommend.explain(first, "pandas, scikit-learn and JS")
    assert "pandas" in explanation and "panda," not in explanation


# --- the alias audit itself --------------------------------------------------------


def test_alias_audit_finds_no_alias_that_collides_with_a_different_catalogue_technology():
    import json

    import config
    from scripts import alias_audit

    report = alias_audit.audit(json.loads(config.SEED_FILE.read_text(encoding="utf-8")))
    assert report["alias_collisions"] == []


def test_alias_audit_flags_distinct_technologies_as_near_variants_rather_than_merging_them():
    from scripts import alias_audit

    docs = [
        {"technologies": ["React", "React Native", "Transformers", "Sentence Transformers", "pypdf", "PyPDF"]},
    ]
    report = alias_audit.audit(docs)
    pairs = {frozenset((p["a"], p["b"])) for p in report["near_variants"]}
    assert frozenset(("React", "React Native")) in pairs
    assert frozenset(("Transformers", "Sentence Transformers")) in pairs
    assert report["spellings_already_unified"] == {"pypdf": ["PyPDF", "pypdf"]} or "pypdf" in report["spellings_already_unified"]
    # flagged for a human; the alias table itself still keeps them apart
    assert not skills.same_skill("React", "React Native")
    assert not skills.same_skill("Transformers", "Sentence Transformers")


def test_every_alias_resolves_to_exactly_one_canonical_name():
    seen: dict[str, str] = {}
    for canonical, aliases in skills._CANONICAL_ALIASES.items():
        for form in (canonical, *aliases):
            key = skills._squash(form)
            assert seen.setdefault(key, canonical) == canonical, form
