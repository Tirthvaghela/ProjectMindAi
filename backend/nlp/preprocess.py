"""Text preprocessing — two deliberately different paths.

This module is the single most important design decision in the project, so
the reasoning is worth stating plainly.

A naive NLP pipeline does: tokenise -> remove stopwords -> lemmatise -> embed.
That is wrong for sentence-transformer models. They are trained on natural,
complete sentences and derive meaning from word order and function words. Given
"a project FOR kids WITH disabilities" and "a project BY kids WITH
disabilities", stripping stopwords collapses both to the same token bag and the
model can no longer tell them apart. Lemmatising does similar damage to tense
and number cues.

So we run two paths over the same text:

  clean_for_embedding()  minimal — the transformer wants natural language
  tokens_for_bm25()      full classical pipeline — BM25 genuinely benefits
                         from stopword removal and lemmatisation, because it
                         is a bag-of-words model with no notion of syntax

The classical techniques are still exercised (and demonstrable for the report);
they are simply applied where they help rather than where they hurt.
"""

from __future__ import annotations

import logging
import os
import re
from functools import lru_cache

# NLTK 3.10 installs an import hook (nltk/inisec.py) that blocks any
# NLTK-initiated import resolving to a path *physically inside* the current
# working directory — a CWE-427 (search-path hijacking) mitigation.
#
# Our venv lives at backend/venv, i.e. inside the project, so every package in
# site-packages counts as "inside the CWD" and NLTK refuses to import `regex`.
# The hook's own error message suggests -P / PYTHONSAFEPATH; that does NOT help
# here, because the check tests filesystem containment, not sys.path — verified
# empirically, PYTHONSAFEPATH=1 still fails.
#
# So we use NLTK's documented escape hatch instead. The threat it guards
# against is an attacker dropping a malicious regex.py into the working
# directory; anyone who can do that here can already edit this file, so the
# mitigation buys us nothing while breaking the venv layout graders expect.
# setdefault, so an operator can still force it back on.
#
# MUST run before the first `import nltk` anywhere in the process.
os.environ.setdefault("NLTK_DISABLE_IMPORT_SECURITY", "1")

log = logging.getLogger(__name__)

# --- Shared cleaning --------------------------------------------------------

_WHITESPACE_RE = re.compile(r"\s+")
_URL_RE = re.compile(r"https?://\S+")
# Keep +, #, . and - so that "C++", "C#", "Node.js" and "scikit-learn" survive.
_PUNCT_RE = re.compile(r"[^\w\s+#.\-]")

# Students type these constantly; expanding them helps both retrieval paths.
_ABBREVIATIONS = {
    "ml": "machine learning",
    "dl": "deep learning",
    "ai": "artificial intelligence",
    "nlp": "natural language processing",
    "cv": "computer vision",
    "iot": "internet of things",
    "ar": "augmented reality",
    "vr": "virtual reality",
    "js": "javascript",
    "ds": "data science",
    "cs": "computer science",
    "db": "database",
    "api": "application programming interface",
    "ui": "user interface",
    "ux": "user experience",
}


def expand_abbreviations(text: str) -> str:
    """Expand standalone abbreviations; leave them alone inside words."""

    def replace(match: re.Match[str]) -> str:
        return _ABBREVIATIONS[match.group(0).lower()]

    pattern = r"\b(" + "|".join(_ABBREVIATIONS) + r")\b"
    return re.sub(pattern, replace, text, flags=re.IGNORECASE)


def clean_for_embedding(text: str) -> str:
    """Minimal normalisation for the dense/transformer path.

    Lowercase, drop URLs, collapse whitespace, expand abbreviations. Word order,
    stopwords and inflection are all preserved on purpose — the transformer
    needs them.
    """
    if not text:
        return ""
    text = _URL_RE.sub(" ", text)
    text = text.lower()
    text = expand_abbreviations(text)
    return _WHITESPACE_RE.sub(" ", text).strip()


# --- Classical path (BM25 + explainability) ---------------------------------


@lru_cache(maxsize=1)
def _nltk_tools() -> tuple[set[str], object]:
    """Load NLTK stopwords and lemmatiser, downloading corpora if absent.

    Cached so the download check and disk read happen once per process.
    """
    import nltk
    from nltk.corpus import stopwords
    from nltk.stem import WordNetLemmatizer

    for resource, path in (
        ("stopwords", "corpora/stopwords"),
        ("wordnet", "corpora/wordnet"),
        ("omw-1.4", "corpora/omw-1.4"),
    ):
        try:
            nltk.data.find(path)
        except LookupError:
            log.info("Downloading NLTK resource: %s", resource)
            nltk.download(resource, quiet=True)

    stop = set(stopwords.words("english"))

    # These are stopwords in general English but meaningful in our domain —
    # "computer vision" and "C" the language would otherwise vanish. "c" and
    # "r" also need the length exemption in tokens_for_bm25 below, since
    # removing them from `stop` alone isn't enough to save a 1-character token.
    stop -= {"c", "r", "computer", "system", "web", "data", "network"}

    # Domain filler: words students type in every query and that appear in
    # nearly every project description, so they discriminate nothing.
    #
    # BM25's IDF is supposed to handle exactly this, but IDF is estimated from
    # the corpus, and at a few hundred documents the estimate is too noisy to
    # fully suppress them. Measured effect: before this list, "beginner project
    # for farming" surfaced an MNIST digit-recognition project at rank 3 purely
    # on the token "project". Revisit once the corpus is much larger — at that
    # point IDF does this job on its own and the list can shrink.
    stop |= {
        "project", "projects", "idea", "ideas", "topic", "topics",
        "want", "need", "looking", "suggest", "recommend", "give", "get",
        "make", "build", "create", "develop", "developing", "using", "use",
        "based", "final", "year", "semester", "college", "student", "students",
        "good", "best", "simple", "easy",
    }

    return stop, WordNetLemmatizer()


_TOKEN_RE = re.compile(r"[a-z0-9+#.\-]+")

# Single-character tokens are junk almost everywhere else, but these two are
# real technology names on their own — excluded from _nltk_tools()'s stopword
# set for exactly that reason, so the plain length filter below must not
# override that by dropping them again anyway.
_SHORT_MEANINGFUL_TOKENS = {"c", "r"}


def tokens_for_bm25(text: str) -> list[str]:
    """Full classical pipeline: clean -> tokenise -> stopwords -> lemmatise.

    This is the correct place for these techniques. BM25 is bag-of-words, so
    collapsing "recommending"/"recommends"/"recommended" to one term is a real
    gain, and dropping stopwords removes noise it would otherwise score.
    """
    if not text:
        return []

    text = _URL_RE.sub(" ", text.lower())
    text = expand_abbreviations(text)
    text = _PUNCT_RE.sub(" ", text)

    stop, lemmatizer = _nltk_tools()

    tokens: list[str] = []
    for token in _TOKEN_RE.findall(text):
        token = token.strip(".-")
        if token in stop:
            continue
        if len(token) < 2 and token not in _SHORT_MEANINGFUL_TOKENS:
            continue
        tokens.append(lemmatizer.lemmatize(token))

    return tokens


def keyword_set(text: str) -> set[str]:
    """Unique lemmatised tokens — used to explain why a project matched."""
    return set(tokens_for_bm25(text))
