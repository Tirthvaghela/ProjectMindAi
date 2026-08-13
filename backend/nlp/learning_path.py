"""Learning-path resource links for a list of skills.

No content API and no scraping: every link is a stable, pre-filled search URL
on a well-known platform (YouTube, freeCodeCamp, Coursera) plus, where the
skill matches a known technology, that technology's own official docs — the
same "point at the real thing" principle db/schema.py already uses for
github_url ("A *reference* repository, not the project's own"). Nothing here
is a specific fabricated video or article, because there is no way to verify
one actually exists.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

# skill keyword (lowercase, matched as a substring) -> (label, official docs URL).
# Checked in order, first match wins, so more specific keywords are listed
# before the generic ones they'd otherwise shadow (e.g. "deep learning" before
# "machine learning" would not matter here since neither is a substring of the
# other, but "nlp" is listed near "natural language processing" for the same
# reason "js" is a bad substring key to trust — kept as whole meaningful terms).
_OFFICIAL_DOCS: list[tuple[str, str, str]] = [
    ("python", "Python", "https://docs.python.org/3/tutorial/"),
    ("typescript", "TypeScript", "https://www.typescriptlang.org/docs/"),
    ("javascript", "MDN", "https://developer.mozilla.org/en-US/docs/Web/JavaScript"),
    ("react", "React", "https://react.dev/learn"),
    ("vue", "Vue.js", "https://vuejs.org/guide/introduction.html"),
    ("angular", "Angular", "https://angular.dev/tutorials"),
    ("node", "Node.js", "https://nodejs.org/en/learn"),
    ("flask", "Flask", "https://flask.palletsprojects.com/en/stable/"),
    ("django", "Django", "https://docs.djangoproject.com/en/stable/"),
    ("fastapi", "FastAPI", "https://fastapi.tiangolo.com/tutorial/"),
    ("mongodb", "MongoDB", "https://www.mongodb.com/docs/manual/tutorial/getting-started/"),
    ("sql", "PostgreSQL", "https://www.postgresql.org/docs/current/tutorial.html"),
    ("docker", "Docker", "https://docs.docker.com/get-started/"),
    ("kubernetes", "Kubernetes", "https://kubernetes.io/docs/tutorials/"),
    ("tensorflow", "TensorFlow", "https://www.tensorflow.org/tutorials"),
    ("pytorch", "PyTorch", "https://pytorch.org/tutorials/"),
    ("scikit", "scikit-learn", "https://scikit-learn.org/stable/tutorial/index.html"),
    ("pandas", "pandas", "https://pandas.pydata.org/docs/getting_started/index.html"),
    ("opencv", "OpenCV", "https://docs.opencv.org/4.x/d9/df8/tutorial_root.html"),
    ("computer vision", "OpenCV", "https://docs.opencv.org/4.x/d9/df8/tutorial_root.html"),
    ("aws", "AWS", "https://docs.aws.amazon.com/getting-started/"),
    ("solidity", "Solidity", "https://docs.soliditylang.org/en/latest/"),
    ("git", "Git", "https://git-scm.com/doc"),
    ("rest api", "MDN", "https://developer.mozilla.org/en-US/docs/Glossary/REST"),
    ("deep learning", "PyTorch", "https://pytorch.org/tutorials/"),
    ("machine learning", "scikit-learn", "https://scikit-learn.org/stable/tutorial/index.html"),
    ("natural language processing", "Hugging Face", "https://huggingface.co/learn/nlp-course"),
    ("nlp", "Hugging Face", "https://huggingface.co/learn/nlp-course"),
]


def _official_doc(skill_lower: str) -> dict[str, str] | None:
    for keyword, label, url in _OFFICIAL_DOCS:
        if keyword in skill_lower:
            return {"platform": f"{label} docs", "title": f"Official {label} documentation", "url": url}
    return None


def resources_for(skill: str) -> list[dict[str, str]]:
    """Every resource link for one skill — official docs first if known, then search links."""
    resources: list[dict[str, str]] = []

    doc = _official_doc(skill.lower())
    if doc:
        resources.append(doc)

    resources.append(
        {
            "platform": "YouTube",
            "title": f'"{skill}" video tutorials',
            "url": f"https://www.youtube.com/results?search_query={quote_plus(skill + ' tutorial')}",
        }
    )
    resources.append(
        {
            "platform": "freeCodeCamp",
            "title": f'"{skill}" articles on freeCodeCamp',
            "url": f"https://www.freecodecamp.org/news/search/?query={quote_plus(skill)}",
        }
    )
    resources.append(
        {
            "platform": "Coursera",
            "title": f'"{skill}" courses on Coursera',
            "url": f"https://www.coursera.org/search?query={quote_plus(skill)}",
        }
    )

    return resources


def learning_path_for(skills: list[str]) -> list[dict[str, Any]]:
    """One resource bundle per skill, de-duplicated and in the given order."""
    seen: set[str] = set()
    ordered: list[str] = []
    for skill in skills:
        clean = skill.strip()
        key = clean.lower()
        if key and key not in seen:
            seen.add(key)
            ordered.append(clean)

    return [{"skill": skill, "resources": resources_for(skill)} for skill in ordered]


# --- Technology learning sequence -------------------------------------------
#
# Coarse learning-order tiers: a term matching an earlier tier should
# generally be learned before one matching a later tier. Keyword-matched
# against whatever real technologies/skills the caller passes in — same
# substring-matching technique nlp/team_builder.py already uses for its own
# role categories, just tuned for "what order to teach this in" rather than
# "who on a team is good at this". This is a heuristic ordering, not a
# dependency solver: ties (same tier) keep the caller's original order rather
# than inventing a finer-grained ranking there's no real basis for.
_SEQUENCE_TIERS: list[tuple[str, list[str]]] = [
    (
        "Programming language — everything else in this stack is written in it.",
        [
            "python", "javascript", "typescript", "java", "c++", "c#", "golang", " go",
            "dart", "solidity", "php", "ruby", "swift", "kotlin", "rust",
        ],
    ),
    (
        "Core domain concepts the rest of the stack builds on.",
        [
            "machine learning", "deep learning", "nlp", "natural language processing",
            "computer vision", "data structures", "algorithms", "statistics",
            "reinforcement learning", "blockchain", "cryptography", "networking",
        ],
    ),
    (
        "The main library/framework the project's core logic is built with.",
        [
            "tensorflow", "pytorch", "scikit", "sklearn", "keras", "opencv", "transformers",
            "spacy", "nltk", "huggingface", "yolo", "mediapipe", "pandas", "numpy",
        ],
    ),
    (
        "Backend/API layer that exposes the core logic to a client.",
        [
            "flask", "django", "fastapi", "express", "node", "spring", "rest api",
            "graphql", "websocket", "api development",
        ],
    ),
    (
        "User-facing interface built on top of the backend.",
        [
            "react", "vue", "angular", "flutter", "react native", "swiftui", "html",
            "css", "tailwind", "next.js", "frontend",
        ],
    ),
    (
        "Where the application's data lives — needed once there's an API to serve it.",
        [
            "mongodb", "postgresql", "postgres", "mysql", "sqlite", "redis", "firebase",
            "firestore", "database", "sql",
        ],
    ),
    (
        "Packaging, hosting and shipping the finished system — last, once there's something to ship.",
        [
            "docker", "kubernetes", "aws", "azure", "gcp", "ci/cd", "cicd", "deployment",
            "cloud", "terraform",
        ],
    ),
]
_UNRECOGNISED_REASON = "Supporting tool/technology for this project."


def sequence_technologies(technologies: list[str]) -> list[dict[str, str]]:
    """Order a technology/skill list into a sensible learn-this-before-that
    sequence — language, then domain foundations, then the core framework,
    then backend, frontend, database, and deployment last. Never alphabetical
    and never invented: every item is one the caller passed in, just
    reordered, each with the reason its tier is taught at that point.
    De-duplicates case-insensitively, keeping the first-seen spelling.
    """
    seen: set[str] = set()
    tiered: list[tuple[int, str, str]] = []
    for tech in technologies:
        clean = (tech or "").strip()
        key = clean.lower()
        if not clean or key in seen:
            continue
        seen.add(key)

        tier_index, reason = len(_SEQUENCE_TIERS), _UNRECOGNISED_REASON
        for index, (tier_reason, keywords) in enumerate(_SEQUENCE_TIERS):
            if any(keyword in key for keyword in keywords):
                tier_index, reason = index, tier_reason
                break
        tiered.append((tier_index, clean, reason))

    # Stable sort: within a tier, and among unrecognised terms, the caller's
    # original order is preserved rather than re-ranked without real basis.
    tiered.sort(key=lambda item: item[0])
    return [{"skill": tech, "reason": reason} for _tier, tech, reason in tiered]


def sequenced_learning_path(skills: list[str]) -> list[dict[str, Any]]:
    """learning_path_for(), reordered by sequence_technologies() first, so
    the result reads as "learn this, then this" — each bundle also carries
    `reason`, the same one-line explanation sequence_technologies() gives for
    teaching it at that point. Reuses both existing functions as-is; this is
    purely a combination of the two, not a new resource or ranking engine.
    """
    sequence = sequence_technologies(skills)
    resourced = learning_path_for([entry["skill"] for entry in sequence])
    reason_by_skill = {entry["skill"].lower(): entry["reason"] for entry in sequence}
    for bundle in resourced:
        bundle["reason"] = reason_by_skill.get(bundle["skill"].lower(), "")
    return resourced
