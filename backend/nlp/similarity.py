"""Hybrid retrieval: dense embeddings + BM25, fused and filtered.

Why hybrid rather than pure cosine similarity:

Dense embeddings are excellent at meaning ("healthcare AI" finds "medical
diagnosis system") but weak at exact rare tokens. Search "YOLOv8" against a
pure-embedding index and you get generic computer-vision projects while the
project literally titled "YOLOv8 Traffic Detection" ranks mid-pack, because
"YOLOv8" is a low-frequency token the encoder barely distinguishes from other
model names.

BM25 has the mirror-image strengths and weaknesses. Fusing them fixes both
failure modes and costs very little.

Filtering happens BEFORE ranking. The naive order — rank first, filter the top
N afterwards — routinely returns zero results, because the requested
difficulty or domain may simply not appear in the top 10 of an unfiltered
ranking. Here we build a boolean mask over the corpus first and rank only the
surviving rows.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

import numpy as np

import config
from db.schema import known_duration
from nlp import embeddings, preprocess, skills

log = logging.getLogger(__name__)


@dataclass
class ScoredProject:
    project_id: str
    score: float
    dense_score: float
    sparse_score: float
    matched_terms: list[str] = field(default_factory=list)
    document: dict[str, Any] = field(default_factory=dict)
    # Cosine against the caller's taste profile, or None when the search was
    # not personalised. None and 0.0 mean different things — "no profile" vs
    # "profile exists and this project is unlike it" — so the field is optional
    # rather than defaulting to zero.
    personal_score: Optional[float] = None
    # Share of the technologies the query named that this project lists, or
    # None when the query named none (the signal was not applied).
    technology_score: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        from db.schema import public_view

        payload = public_view(self.document)
        payload["relevance"] = {
            # Rounded for a stable, readable API surface — callers should not
            # depend on float noise in the 12th decimal place.
            "score": round(float(self.score), 4),
            "semantic": round(float(self.dense_score), 4),
            "keyword": round(float(self.sparse_score), 4),
            "matched_terms": self.matched_terms,
        }
        if self.personal_score is not None:
            payload["relevance"]["personal"] = round(float(self.personal_score), 4)
        if self.technology_score is not None:
            payload["relevance"]["technology"] = round(float(self.technology_score), 4)
        return payload


def doc_matches(doc: dict[str, Any], filters: Optional[dict[str, Any]], ignore_duration: bool = False) -> bool:
    """Whether one project satisfies every filter — the single definition used
    by the retriever's mask and by anything that has to count what a filter
    excluded.

    A deadline (`max_duration_weeks`) is only satisfied by a *known* duration
    within it: a project with no documented duration is never reported as
    fitting, and a null/zero duration can no longer slip through as "0 weeks".
    """
    if not filters:
        return True

    domain = filters.get("domain")
    if domain and doc.get("domain") != domain:
        return False

    difficulty = filters.get("difficulty")
    if difficulty and doc.get("difficulty") != difficulty:
        return False

    # Compared as normalised technology names, so "sklearn" finds a project
    # built with "scikit-learn" and "python" finds "Python" (nlp/skills.py).
    wanted_tech = {skills.normalize_key(t) for t in (filters.get("technologies") or []) if t}
    if wanted_tech:
        doc_tech = {skills.normalize_key(t) for t in doc.get("technologies", []) if isinstance(t, str)}
        # ANY rather than ALL: a student picking three technologies wants
        # projects using any of them, not only projects using every one — the
        # latter is almost always empty.
        if not wanted_tech & doc_tech:
            return False

    max_weeks = filters.get("max_duration_weeks")
    if max_weeks is not None and not ignore_duration:
        weeks = known_duration(doc)
        if weeks is None or weeks > max_weeks:
            return False

    return True


# Technology names that are also ordinary English words or single letters. In a
# lowercase query ("express delivery", "go to market", "sensor node", "banking
# requests") they are almost never the technology, so they only count when the
# user typed them capitalised ("Express", "Go", "Node", "Unity", "R"), the way a
# proper name is written. The second group was found by scanning the catalogue's
# own prose for technologies detected in projects that do not list them (e.g.
# "requests" 13x, "node", "dice"), and the rest by reading the vocabulary for
# words a student could type for another reason.
_AMBIGUOUS_TECH_NAMES = {
    "c", "r", "go", "express", "swift", "spark", "unity", "blender", "prophet",
    "surprise", "gazebo", "hardhat", "expo", "dart", "leaflet",
    "node", "requests", "dice", "river", "mesa", "stripe", "helm", "lighthouse",
    "whisper", "locust", "airflow", "gymnasium", "retrofit", "evidently",
    "foundry", "pillow", "jellyfish", "lifelines", "tesseract", "cryptography",
}

_QUERY_WORD_RE = re.compile(r"[A-Za-z0-9+#]+(?:[.\-][A-Za-z0-9+#]+)*")


def query_technologies(query: str, vocabulary: dict[str, str]) -> set[str]:
    """Normalised keys of the catalogue technologies a query names.

    `vocabulary` maps nlp.skills.normalize_key -> display name for every
    technology some project lists. The longest phrase wins, so "React Native"
    is matched as that one technology and does not also count as "React";
    spellings are resolved through the shared alias table ("sklearn" finds
    scikit-learn). Ambiguous English-word names need their own capitalisation.
    """
    words = _QUERY_WORD_RE.findall(query or "")
    found: set[str] = set()
    used = [False] * len(words)
    for size in (3, 2, 1):
        for start in range(len(words) - size + 1):
            if any(used[start : start + size]):
                continue
            phrase = " ".join(words[start : start + size])
            key = skills.normalize_key(phrase)
            if key not in vocabulary:
                continue
            if size == 1 and phrase.lower() in _AMBIGUOUS_TECH_NAMES and not (
                phrase == phrase.capitalize() or phrase.isupper()
            ):
                continue
            found.add(key)
            for i in range(start, start + size):
                used[i] = True
    return found


def _minmax(scores: np.ndarray) -> np.ndarray:
    """Scale scores to [0, 1] so dense and sparse are comparable.

    Cosine lives in [-1, 1]; BM25 is unbounded and corpus-dependent. Without
    rescaling, a weighted sum would be dominated by whichever happens to have
    the larger raw magnitude, making the configured weights meaningless.
    """
    if scores.size == 0:
        return scores

    lo = float(scores.min())
    hi = float(scores.max())
    if hi - lo < 1e-9:
        # Every candidate scored identically — this signal carries no ranking
        # information, so contribute nothing rather than an arbitrary constant.
        return np.zeros_like(scores)

    return (scores - lo) / (hi - lo)


class HybridRetriever:
    """Holds the in-memory index and answers queries against it."""

    def __init__(self, matrix: np.ndarray, ids: Sequence[str], documents: dict[str, dict]):
        self.matrix = matrix
        self.ids = list(ids)
        self.documents = documents
        self.position = {pid: i for i, pid in enumerate(self.ids)}
        # Technology identity index: each project's normalised technology keys,
        # and the catalogue-wide vocabulary queries are matched against.
        self._tech_keys: list[set[str]] = []
        self.technology_vocabulary: dict[str, str] = {}
        for pid in self.ids:
            keys = set()
            for tech in self.documents[pid].get("technologies", []):
                if isinstance(tech, str) and tech.strip():
                    key = skills.normalize_key(tech)
                    keys.add(key)
                    self.technology_vocabulary.setdefault(key, skills.display_name(tech))
            self._tech_keys.append(keys)
        self._bm25 = None
        self._corpus_tokens: list[list[str]] = []
        self._build_sparse_index()

    # --- construction -----------------------------------------------------

    def _build_sparse_index(self) -> None:
        from rank_bm25 import BM25Okapi
        from db.schema import embedding_text

        self._corpus_tokens = [
            preprocess.tokens_for_bm25(embedding_text(self.documents[pid]))
            for pid in self.ids
        ]
        # BM25Okapi rejects an empty corpus; guard so an unseeded DB produces a
        # clear "no projects" result instead of an opaque library error.
        if self._corpus_tokens:
            self._bm25 = BM25Okapi(self._corpus_tokens)
        log.info("BM25 index built over %d documents", len(self._corpus_tokens))

    # --- filtering --------------------------------------------------------

    def _mask(self, filters: Optional[dict[str, Any]]) -> np.ndarray:
        """Boolean mask of corpus rows that satisfy every filter."""
        mask = np.ones(len(self.ids), dtype=bool)
        if not filters:
            return mask

        for i, pid in enumerate(self.ids):
            mask[i] = doc_matches(self.documents[pid], filters)

        return mask

    # --- search -----------------------------------------------------------

    def search(
        self,
        query: str,
        filters: Optional[dict[str, Any]] = None,
        top_k: int = config.DEFAULT_TOP_K,
        profile: Optional[np.ndarray] = None,
        technology_match: bool = True,
    ) -> list[ScoredProject]:
        """Rank the corpus against a query.

        `profile` is an optional unit vector describing what this caller has
        previously saved and searched for. When supplied it contributes a
        bounded fraction of the final score — see PERSONALIZATION_WEIGHT for
        why it is deliberately small.
        """
        if not self.ids:
            return []

        mask = self._mask(filters)
        candidates = np.flatnonzero(mask)
        if candidates.size == 0:
            return []

        clean_query = preprocess.clean_for_embedding(query)
        query_tokens = preprocess.tokens_for_bm25(query)

        # Dense half.
        query_vector = embeddings.encode_one(clean_query)
        dense_raw = embeddings.cosine_scores(query_vector, self.matrix)[candidates]

        # Sparse half.
        if self._bm25 is not None and query_tokens:
            sparse_raw = np.asarray(self._bm25.get_scores(query_tokens))[candidates]
        else:
            sparse_raw = np.zeros(candidates.size, dtype=np.float32)

        relevance = (
            config.DENSE_WEIGHT * _minmax(dense_raw)
            + config.SPARSE_WEIGHT * _minmax(sparse_raw)
        )

        # Technology identity. Only when the query names technologies the
        # catalogue knows; a convex blend like personalisation below, so the
        # score stays in [0, 1] and queries with no technology are untouched.
        technology_raw = None
        if technology_match and config.TECHNOLOGY_WEIGHT > 0:
            named = query_technologies(query, self.technology_vocabulary)
            if named:
                technology_raw = np.array(
                    [len(named & self._tech_keys[i]) / len(named) for i in candidates], dtype=np.float32
                )
                relevance = (1.0 - config.TECHNOLOGY_WEIGHT) * relevance + config.TECHNOLOGY_WEIGHT * technology_raw

        # Personalisation half. Blended as a convex combination rather than
        # added on top, so the fused score stays in the same [0, 1] range the
        # UI renders as a match percentage, and so affinity can never do more
        # than PERSONALIZATION_WEIGHT of the work.
        personal_raw = None
        if profile is not None and config.PERSONALIZATION_WEIGHT > 0:
            personal_raw = embeddings.cosine_scores(profile, self.matrix)[candidates]
            weight = config.PERSONALIZATION_WEIGHT
            fused = (1.0 - weight) * relevance + weight * _minmax(personal_raw)
        else:
            fused = relevance

        top_k = max(1, min(top_k, config.MAX_TOP_K, candidates.size))
        # argpartition is O(n) vs argsort's O(n log n); we only sort the winners.
        top_local = np.argpartition(-fused, top_k - 1)[:top_k]
        top_local = top_local[np.argsort(-fused[top_local])]

        query_terms = set(query_tokens)
        # Shown to the student, so map lemmas back to readable words.
        readable = preprocess.token_display_map(query)
        results: list[ScoredProject] = []
        for local in top_local:
            corpus_index = int(candidates[local])
            pid = self.ids[corpus_index]
            matched = sorted(
                (readable.get(t, t) for t in query_terms & set(self._corpus_tokens[corpus_index])),
                key=str.lower,
            )
            results.append(
                ScoredProject(
                    project_id=pid,
                    score=float(fused[local]),
                    dense_score=float(dense_raw[local]),
                    sparse_score=float(sparse_raw[local]),
                    matched_terms=matched,
                    document=self.documents[pid],
                    personal_score=(
                        float(personal_raw[local]) if personal_raw is not None else None
                    ),
                    technology_score=(
                        float(technology_raw[local]) if technology_raw is not None else None
                    ),
                )
            )
        return results

    def similar(self, project_id: str, top_k: int = 5) -> list[ScoredProject]:
        """Projects nearest to a given project, excluding itself.

        Pure dense similarity here — we are comparing two full documents rather
        than a short query to a document, so BM25's keyword bias adds nothing.
        """
        if project_id not in self.position:
            return []

        index = self.position[project_id]
        scores = embeddings.cosine_scores(self.matrix[index], self.matrix)
        scores[index] = -np.inf  # never recommend the project itself

        # No other project exists to recommend — max(1, ...) below would
        # otherwise still force a request for 1 neighbour and argpartition
        # would hand back the excluded project itself (its -inf score and
        # all), since a 1-project corpus has nothing else to return.
        available = len(self.ids) - 1
        if available <= 0:
            return []

        top_k = max(1, min(top_k, config.MAX_TOP_K, available))
        top = np.argpartition(-scores, top_k - 1)[:top_k]
        top = top[np.argsort(-scores[top])]

        return [
            ScoredProject(
                project_id=self.ids[i],
                score=float(scores[i]),
                dense_score=float(scores[i]),
                sparse_score=0.0,
                document=self.documents[self.ids[i]],
            )
            for i in top
        ]

    def find_duplicates(self, threshold: float = config.DUPLICATE_THRESHOLD):
        """Yield (id_a, id_b, similarity) for near-identical project pairs.

        Powers both the dataset validator and the user-facing uniqueness
        checker.
        """
        similarity = self.matrix @ self.matrix.T
        n = similarity.shape[0]
        for i in range(n):
            for j in range(i + 1, n):
                value = float(similarity[i, j])
                if value >= threshold:
                    yield self.ids[i], self.ids[j], value
