"""Project document schema and validation.

Deliberately hand-rolled rather than pulled from a validation library: the
rules are simple, and the error messages here are what the dataset validator
prints to the user, so we want them phrased for a human fixing a JSON file.
"""

from __future__ import annotations

from typing import Any

DIFFICULTIES = ("Beginner", "Intermediate", "Advanced")

DOMAINS = (
    "Artificial Intelligence",
    "Machine Learning",
    "Deep Learning",
    "Natural Language Processing",
    "Computer Vision",
    "Data Science",
    "Web Development",
    "Mobile Development",
    "Internet of Things",
    "Blockchain",
    "Cybersecurity",
    "Cloud & DevOps",
    "Augmented & Virtual Reality",
    "Robotics",
)

# field -> (python type, required)
FIELDS: dict[str, tuple[type | tuple[type, ...], bool]] = {
    "project_id": (str, True),
    "title": (str, True),
    "description": (str, True),
    "domain": (str, True),
    "technologies": (list, True),
    "difficulty": (str, True),
    "duration_weeks": (int, True),
    "skills": (list, True),
    "keywords": (list, True),
    # A *reference* repository, not the project's own — these are project briefs
    # that a student has yet to build, so there is no canonical repo to point
    # at. Each URL is the upstream project for the brief's core technology
    # (YOLOv8 -> ultralytics, face recognition -> ageitgey/face_recognition),
    # which is what a student would actually read first. The UI labels it
    # "Reference repo" so this is not mistaken for a finished solution.
    #
    # Every URL is verified to resolve; re-check after edits with:
    #     python -m scripts.validate_dataset --check-links
    "github_url": ((str, type(None)), False),
    "learning_resources": (list, False),
}

MIN_DESCRIPTION_CHARS = 80


def validate(doc: dict[str, Any]) -> list[str]:
    """Return a list of human-readable problems. Empty list means valid."""
    problems: list[str] = []

    for field, (expected_type, required) in FIELDS.items():
        if field not in doc:
            if required:
                problems.append(f"missing required field '{field}'")
            continue

        value = doc[field]
        if not isinstance(value, expected_type):
            type_name = getattr(expected_type, "__name__", str(expected_type))
            problems.append(
                f"field '{field}' should be {type_name}, got {type(value).__name__}"
            )

    if isinstance(doc.get("domain"), str) and doc["domain"] not in DOMAINS:
        problems.append(
            f"domain '{doc['domain']}' is not one of the {len(DOMAINS)} allowed domains"
        )

    if isinstance(doc.get("difficulty"), str) and doc["difficulty"] not in DIFFICULTIES:
        problems.append(
            f"difficulty '{doc['difficulty']}' must be one of {', '.join(DIFFICULTIES)}"
        )

    description = doc.get("description")
    if isinstance(description, str) and len(description) < MIN_DESCRIPTION_CHARS:
        # Short descriptions produce weak embeddings — the model has too little
        # signal to place the project meaningfully in vector space.
        problems.append(
            f"description is {len(description)} chars; needs at least "
            f"{MIN_DESCRIPTION_CHARS} for a usable embedding"
        )

    for list_field in ("technologies", "skills", "keywords"):
        value = doc.get(list_field)
        if isinstance(value, list):
            if not value:
                problems.append(f"'{list_field}' is empty")
            elif not all(isinstance(item, str) for item in value):
                problems.append(f"'{list_field}' must contain only strings")

    duration = doc.get("duration_weeks")
    if isinstance(duration, int) and not 1 <= duration <= 52:
        problems.append(f"duration_weeks={duration} is outside the sane range 1-52")

    return problems


def known_duration(doc: dict[str, Any]) -> float | None:
    """The documented duration in weeks, or None when it is missing, null, zero,
    negative or not a number. A deadline can only be confirmed against a real
    duration, so every deadline check (search, recommend) goes through this
    instead of treating "unknown" as 0 weeks."""
    weeks = doc.get("duration_weeks")
    if isinstance(weeks, bool) or not isinstance(weeks, (int, float)) or weeks <= 0:
        return None
    return weeks


def embedding_text(doc: dict[str, Any]) -> str:
    """Build the string that gets embedded for a project.

    Title and description carry the semantics; technologies and skills are
    appended so that a query naming a stack still lands near the right
    projects. Kept as natural language on purpose — see nlp/preprocess.py for
    why we do NOT strip stopwords or lemmatise before embedding.
    """
    parts = [
        doc.get("title", ""),
        doc.get("description", ""),
        "Technologies: " + ", ".join(doc.get("technologies", [])),
        "Skills: " + ", ".join(doc.get("skills", [])),
        "Domain: " + doc.get("domain", ""),
    ]
    return ". ".join(part for part in parts if part).strip()


def public_view(doc: dict[str, Any]) -> dict[str, Any]:
    """Strip Mongo internals before sending a document over the API."""
    return {k: v for k, v in doc.items() if k != "_id"}
