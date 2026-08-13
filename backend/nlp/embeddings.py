"""Sentence embeddings and the on-disk vector index.

Design notes:

* The model is loaded lazily and cached. Loading MiniLM costs ~2s and ~90 MB
  of RAM; doing it per request would be unusable.
* Project embeddings are computed OFFLINE by scripts/build_index.py and stored
  as a .npy matrix. At request time we encode only the user's query (one short
  sentence, ~10ms) and do a single matrix multiply.
* Vectors are L2-normalised at build time, which makes cosine similarity a
  plain dot product. For 1000 projects that is a (1000, 384) @ (384,) product —
  well under a millisecond. A vector database would add operational complexity
  and network latency for no measurable gain at this scale.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import TYPE_CHECKING, Iterable

import numpy as np

import config

if TYPE_CHECKING:  # pragma: no cover
    from sentence_transformers import SentenceTransformer

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_model() -> "SentenceTransformer":
    """Load and cache the sentence-transformer model."""
    from sentence_transformers import SentenceTransformer

    log.info("Loading embedding model: %s", config.EMBEDDING_MODEL)
    model = SentenceTransformer(config.EMBEDDING_MODEL)
    log.info("Model loaded (dim=%d)", model.get_sentence_embedding_dimension())
    return model


def encode(texts: Iterable[str], show_progress: bool = False) -> np.ndarray:
    """Encode texts into L2-normalised float32 vectors.

    Returns shape (n, EMBEDDING_DIM). Normalising here means every downstream
    cosine similarity is just a dot product.
    """
    texts = list(texts)
    if not texts:
        return np.zeros((0, config.EMBEDDING_DIM), dtype=np.float32)

    vectors = get_model().encode(
        texts,
        batch_size=32,
        show_progress_bar=show_progress,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    return np.asarray(vectors, dtype=np.float32)


def encode_one(text: str) -> np.ndarray:
    """Encode a single string into a 1-D normalised vector."""
    return encode([text])[0]


def save_index(matrix: np.ndarray, ids: list[str]) -> None:
    """Persist the embedding matrix and its row->project_id mapping.

    The two files must always be written together — row i of the matrix
    corresponds to ids[i], and a mismatch silently corrupts every result.
    """
    if matrix.shape[0] != len(ids):
        raise ValueError(
            f"index corrupt: {matrix.shape[0]} vectors but {len(ids)} ids"
        )

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    np.save(config.EMBEDDINGS_FILE, matrix)
    config.IDS_FILE.write_text(json.dumps(ids, indent=2), encoding="utf-8")
    log.info("Saved index: %d vectors -> %s", len(ids), config.EMBEDDINGS_FILE)


def index_exists() -> bool:
    return config.EMBEDDINGS_FILE.exists() and config.IDS_FILE.exists()


@lru_cache(maxsize=1)
def load_index() -> tuple[np.ndarray, list[str]]:
    """Load the embedding matrix and id list from disk, cached per process.

    Call load_index.cache_clear() after rebuilding the index in a live process.
    """
    if not index_exists():
        raise FileNotFoundError(
            "Embedding index not found. Build it first:\n"
            "    python -m scripts.build_index"
        )

    matrix = np.load(config.EMBEDDINGS_FILE).astype(np.float32)
    ids = json.loads(config.IDS_FILE.read_text(encoding="utf-8"))

    if matrix.shape[0] != len(ids):
        raise ValueError(
            f"index corrupt: {matrix.shape[0]} vectors but {len(ids)} ids. "
            "Rebuild with: python -m scripts.build_index"
        )

    log.info("Loaded index: %d vectors, dim=%d", matrix.shape[0], matrix.shape[1])
    return matrix, ids


def cosine_scores(query_vector: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Cosine similarity of one query against every row.

    Both sides are already L2-normalised, so the dot product IS the cosine.
    """
    return matrix @ query_vector
