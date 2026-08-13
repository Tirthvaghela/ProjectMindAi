"""Résumé text extraction and skill detection.

No résumé-parsing API and no LLM: skills are detected by matching the
résumé's text against a vocabulary this app already has — every distinct
technology and skill string that appears anywhere in the project dataset,
the same list /api/filters derives. The detected skills become a query
string fed straight into the existing hybrid search (nlp/recommend.search),
so a résumé is just another natural-language query, not a second ranking
algorithm to build and tune.
"""

from __future__ import annotations

import io
import re

MAX_RESUME_CHARS = 20_000  # a résumé is a page or two; this is generous headroom


class UnreadableResume(Exception):
    """Raised when the uploaded file can't be parsed as PDF/DOCX/text."""


def extract_text(file_storage) -> str:
    """Best-effort text extraction from an uploaded PDF/DOCX/TXT file."""
    filename = (file_storage.filename or "").lower()
    raw = file_storage.read()

    try:
        if filename.endswith(".pdf"):
            return _extract_pdf(raw)
        if filename.endswith(".docx"):
            return _extract_docx(raw)
        # Anything else (.txt, no extension) is treated as plain text.
        return raw.decode("utf-8", errors="ignore")[:MAX_RESUME_CHARS]
    except UnreadableResume:
        raise
    except Exception as error:  # noqa: BLE001
        raise UnreadableResume(str(error)) from error


def _extract_pdf(raw: bytes) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(raw))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except PdfReadError as error:
        raise UnreadableResume(str(error)) from error

    if not text.strip():
        # A common failure mode: a scanned/image-only PDF has no text layer
        # at all. pypdf succeeds and returns "", which would silently produce
        # an empty query rather than a clear error.
        raise UnreadableResume("This PDF has no extractable text (it may be a scanned image).")
    return text[:MAX_RESUME_CHARS]


def _extract_docx(raw: bytes) -> str:
    from docx import Document

    document = Document(io.BytesIO(raw))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    return text[:MAX_RESUME_CHARS]


# Common spelling/spacing/punctuation variants of catalogue technology names,
# rewritten to the exact form the catalogue itself uses ("ReactJS" / "React.js"
# -> "React") before detect_skills' own word-boundary matching runs. This is
# not a second skill vocabulary — a canonical form here only ever produces a
# detected skill if it is *also* present in the vocabulary detect_skills() is
# given, which is always the catalogue's own real technologies/skills. Kept
# small and literal on purpose (no fuzzy matching) so it can never merge two
# genuinely different technologies.
_SKILL_VARIANT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?<![a-z0-9])react[\s.]?js(?![a-z0-9])", re.IGNORECASE), "React"),
    (re.compile(r"(?<![a-z0-9])react[\s]?native(?![a-z0-9])", re.IGNORECASE), "React Native"),
    (re.compile(r"(?<![a-z0-9])node[\s.]?js(?![a-z0-9])", re.IGNORECASE), "Node.js"),
    (re.compile(r"(?<![a-z0-9])express[\s.]?js(?![a-z0-9])", re.IGNORECASE), "Express"),
    (re.compile(r"(?<![a-z0-9])next[\s.]?js(?![a-z0-9])", re.IGNORECASE), "Next.js"),
    (re.compile(r"(?<![a-z0-9])mongo[\s]?db(?![a-z0-9])", re.IGNORECASE), "MongoDB"),
    (re.compile(r"(?<![a-z0-9])postgres(?:ql)?(?![a-z0-9])", re.IGNORECASE), "PostgreSQL"),
    (re.compile(r"(?<![a-z0-9])scikit[\s-]?learn(?![a-z0-9])", re.IGNORECASE), "scikit-learn"),
    (re.compile(r"(?<![a-z0-9])sklearn(?![a-z0-9])", re.IGNORECASE), "scikit-learn"),
    (re.compile(r"(?<![a-z0-9])tensor[\s]?flow(?![a-z0-9])", re.IGNORECASE), "TensorFlow"),
    (re.compile(r"(?<![a-z0-9])py[\s]?torch(?![a-z0-9])", re.IGNORECASE), "PyTorch"),
    (re.compile(r"(?<![a-z0-9])open[\s]?cv(?![a-z0-9])", re.IGNORECASE), "OpenCV"),
    (re.compile(r"(?<![a-z0-9])num[\s]?py(?![a-z0-9])", re.IGNORECASE), "NumPy"),
]


def normalize_skill_variants(text: str) -> str:
    """Rewrite known spelling/spacing/punctuation variants to their canonical
    catalogue form — e.g. "ReactJS" and "React.js" both become "React", so
    detect_skills() recognises them the same as a résumé that already spells
    it "React". Terms with no variant issue ("Machine Learning", "Node.js")
    pass through untouched.
    """
    for pattern, canonical in _SKILL_VARIANT_PATTERNS:
        text = pattern.sub(canonical, text)
    return text


def detect_skills(resume_text: str, vocabulary: list[str]) -> list[str]:
    """Vocabulary terms that appear in the résumé text, case-insensitive.

    Whole-term matching on word boundaries — good enough for the concrete
    nouns this vocabulary is made of ("React", "REST API"), and specifically
    avoids "Java" false-matching inside "JavaScript". Preserves the
    vocabulary's own casing and first-seen order rather than the résumé's.
    Runs normalize_skill_variants() first so common spelling variants
    ("ReactJS", "Mongo DB") match the same as the canonical spelling.
    """
    text_lower = normalize_skill_variants(resume_text).lower()
    found = []
    seen: set[str] = set()
    for term in vocabulary:
        term_lower = term.lower().strip()
        if not term_lower or term_lower in seen:
            continue
        pattern = r"(?<![a-z0-9])" + re.escape(term_lower) + r"(?![a-z0-9])"
        if re.search(pattern, text_lower):
            seen.add(term_lower)
            found.append(term)

    # Drop a bare single-word match once a longer match already covers the
    # same word (e.g. "Evaluation" once "Model evaluation" is also present)
    # — the more specific phrasing is the useful signal, the bare word is
    # noise repeating it.
    words_in_multi_word_terms = {
        word for term in found if " " in term for word in term.lower().split()
    }
    return [t for t in found if " " in t or t.lower() not in words_in_multi_word_terms]
