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
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

import numpy as np

import config
from nlp import embeddings, preprocess

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
        return payload


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

        domain = filters.get("domain")
        difficulty = filters.get("difficulty")
        technologies = filters.get("technologies") or []
        max_weeks = filters.get("max_duration_weeks")

        # Case-insensitive so "python" from a URL query matches "Python".
        wanted_tech = {t.lower() for t in technologies if t}

        for i, pid in enumerate(self.ids):
            doc = self.documents[pid]

            if domain and doc.get("domain") != domain:
                mask[i] = False
                continue

            if difficulty and doc.get("difficulty") != difficulty:
                mask[i] = False
                continue

            if wanted_tech:
                doc_tech = {t.lower() for t in doc.get("technologies", [])}
                # ANY rather than ALL: a student picking three technologies
                # wants projects using any of them, not only projects using
                # every one — the latter is almost always empty.
                if not wanted_tech & doc_tech:
                    mask[i] = False
                    continue

            if max_weeks is not None and doc.get("duration_weeks", 0) > max_weeks:
                mask[i] = False

        return mask

    # --- search -----------------------------------------------------------

    def search(
        self,
        query: str,
        filters: Optional[dict[str, Any]] = None,
        top_k: int = config.DEFAULT_TOP_K,
        profile: Optional[np.ndarray] = None,
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
        results: list[ScoredProject] = []
        for local in top_local:
            corpus_index = int(candidates[local])
            pid = self.ids[corpus_index]
            matched = sorted(query_terms & set(self._corpus_tokens[corpus_index]))
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

        top_k = max(1, min(top_k, config.MAX_TOP_K, len(self.ids) - 1))
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
