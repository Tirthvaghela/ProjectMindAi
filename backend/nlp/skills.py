"""One place that decides when two skill/technology names are the same thing.

Before this module the app compared skills only by lemmatised word tokens
(nlp/preprocess.py:keyword_set), so "sklearn" never matched "scikit-learn" and
"node" never matched "Node.js", while the technology filter compared lowercased
strings and the explanation text showed WordNet lemmas ("panda" for "pandas").
Everything that needs to answer "is this the same technology?" or "how should
this technology be written?" now asks here.

Rules, in order of importance:

* Matching is on whole entries. An alias applies to an entire skill/technology
  name ("node", "Node.js", "node js"), never to a substring or a word inside a
  longer phrase, so "Java" can never match "JavaScript" and a project skill such
  as "Graph traversal over node degree" is untouched.
* Names are compared after squashing case, spaces and punctuation
  ("scikit-learn" == "scikit learn" == "Scikit_Learn"); `+` and `#` are kept so
  C, C++ and C# stay distinct.
* An alias is only listed when it is the overwhelmingly common meaning of that
  whole entry in a skills list. Anything with a second plausible reading is
  left out on purpose (see `_DELIBERATELY_NOT_ALIASED`).
* Unknown names are never guessed at: they keep their own squashed form and
  display exactly as written.
"""

from __future__ import annotations

import re
from typing import Optional

# canonical display name -> aliases (the canonical name itself is implicit).
_CANONICAL_ALIASES: dict[str, tuple[str, ...]] = {
    # Languages
    "JavaScript": ("js", "ecmascript"),
    "TypeScript": (),
    "Python": ("python3",),
    "Java": (),
    "C": (),
    "C++": ("cpp",),
    "C#": ("csharp",),
    "Go": ("golang",),
    "Kotlin": (),
    "Swift": (),
    "R": (),
    "SQL": (),
    "HTML": ("html5",),
    "CSS": ("css3",),
    # Web
    "React": ("reactjs",),
    "React Native": (),
    "Vue.js": ("vue", "vuejs"),
    "Angular": (),
    "Next.js": ("nextjs",),
    "Node.js": ("node", "nodejs"),
    "Express.js": ("express", "expressjs"),
    "Flask": (),
    "Django": (),
    "FastAPI": (),
    "Tailwind CSS": ("tailwind", "tailwindcss"),
    # Data / ML
    "pandas": (),
    "NumPy": (),
    "SciPy": (),
    "Matplotlib": (),
    "scikit-learn": ("sklearn",),
    "TensorFlow": (),
    "TensorFlow Lite": ("tflite",),  # distinct from TensorFlow: a runtime, not the framework
    "PyTorch": (),
    "Keras": (),
    "OpenCV": ("cv2",),
    "Machine Learning": ("ml",),
    "Deep Learning": ("dl",),
    "Natural Language Processing": ("nlp",),
    "Computer Vision": (),
    "Artificial Intelligence": ("ai",),
    # Data stores / infra
    "MongoDB": ("mongo",),
    "PostgreSQL": ("postgres",),
    "MySQL": (),
    "SQLite": ("sqlite3",),
    "Redis": (),
    "Docker": (),
    "Kubernetes": ("k8s",),
    "GitHub Actions": ("gh actions",),
    "Terraform": (),
    "Raspberry Pi": ("rpi",),
    "Transformers": ("huggingface transformers",),  # the library; not the Sentence Transformers package
    "Sentence Transformers": ("sbert",),
    "D3.js": ("d3",),
    "Git": (),
    "GitHub": (),
    "AWS": ("amazon web services",),
    "GCP": ("google cloud", "google cloud platform"),
    "Azure": ("microsoft azure",),
}

# Considered and rejected, kept here so nobody re-adds them without thinking.
# Each has a second plausible meaning in *this* catalogue or product:
#   tf      TensorFlow, but also Terraform (".tf") — both are in the catalogue;
#           an earlier version aliased it to TensorFlow, which the alias audit
#           (scripts/alias_audit.py) showed would match Terraform skills wrongly
#   cv      computer vision, but also curriculum vitae in a product with a
#           resume matcher; "cv2" -> OpenCV is unambiguous and kept
#   ts      TypeScript, but also TensorShape/typesetting — too short to trust
#   np      NumPy, but also "noun phrase" in an NLP skills list
#   torch   PyTorch, but also the older Lua Torch
#   py      Python, but also a file extension / PyPI shorthand
#   next    a plain English word; only "nextjs"/"next.js" count
#   web3    web3.js (JavaScript) and web3.py are different libraries
#   yolo    YOLOv5/v8/... are different models; only an exact version matches
#   ros2    ROS 2 is a different system from ROS 1, not a spelling of it
#   esp8266 a different chip from ESP32
#   .net    the leading dot is lost when punctuation is squashed ("net")
# Pairs that must stay distinct (tests/test_skills.py asserts each):
#   Java / JavaScript, React / React Native, TensorFlow / TensorFlow Lite,
#   Transformers / Sentence Transformers, Python / GitPython, pandas / GeoPandas,
#   PyTorch / PyTorch Geometric, C / C++ / C#
_DELIBERATELY_NOT_ALIASED = ("tf", "cv", "ts", "np", "torch", "py", "next", "web3", "yolo", "ros2", "esp8266", ".net")

_SQUASH_RE = re.compile(r"[^a-z0-9+#]+")


def _squash(text: str) -> str:
    """Case/space/punctuation-insensitive form, keeping + and #."""
    return _SQUASH_RE.sub("", text.lower())


_KEY_TO_NAME: dict[str, str] = {}
for _name, _aliases in _CANONICAL_ALIASES.items():
    for _form in (_name, *_aliases):
        _key = _squash(_form)
        # A key owned by two canonical names would silently merge them.
        assert _KEY_TO_NAME.setdefault(_key, _name) == _name, f"alias collision on {_form!r}"


def canonical_name(text: str) -> Optional[str]:
    """The canonical display name when `text` as a whole is a known skill or
    technology (or one of its aliases), else None."""
    if not isinstance(text, str) or not text.strip():
        return None
    return _KEY_TO_NAME.get(_squash(text))


def display_name(text: str) -> str:
    """How to show a skill/technology: the canonical spelling when known,
    otherwise exactly what was given (trimmed)."""
    text = text.strip() if isinstance(text, str) else ""
    return canonical_name(text) or text


def normalize_key(text: str) -> str:
    """A comparison key: identical for every spelling of one known technology,
    and the squashed text itself for anything unknown."""
    name = canonical_name(text)
    return _squash(name) if name else _squash(text if isinstance(text, str) else "")


def same_skill(a: str, b: str) -> bool:
    """True when two whole skill/technology names are the same thing."""
    key = normalize_key(a)
    return bool(key) and key == normalize_key(b)


def canonical_keys(skills: list[str]) -> set[str]:
    """normalize_key for each known (canonical) entry, ignoring unknown text —
    the set a project's required entries are matched against."""
    return {normalize_key(s) for s in skills if canonical_name(s) is not None}
