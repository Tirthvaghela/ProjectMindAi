"""Tests for the on-disk vector index in nlp/embeddings.py — save_index(),
load_index(), and their failure modes — which had zero coverage before this
file (every other test either monkeypatches embeddings.encode_one entirely,
e.g. test_similarity.py, or never touches this module at all).

`load_index()` is `@lru_cache(maxsize=1)` — one slot, shared by the whole
process, including the real app's own retriever (nlp/recommend.py). Every
test below must leave that cache pointed at nothing so the *next* real
caller rebuilds fresh from the real config paths, rather than serving this
test's throwaway data to the rest of the suite (or the real app) afterward.
The `isolated_index` fixture does both halves of that: redirect
config.DATA_DIR/EMBEDDINGS_FILE/IDS_FILE at a tmp_path for the duration of
the test, and clear the cache both before (in case an earlier test already
populated it) and after (so nothing of this test's fake data survives it).

Does not touch scripts/build_index.py's own CLI — these test the underlying
functions it calls, the same way the task's "index rebuild behavior" ask is
about save_index()/load_index() agreeing after a rebuild, not the script's
argument parsing.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

import config
from nlp import embeddings


@pytest.fixture
def isolated_index(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    embeddings_file = data_dir / "embeddings.npy"
    ids_file = data_dir / "ids.json"
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "EMBEDDINGS_FILE", embeddings_file)
    monkeypatch.setattr(config, "IDS_FILE", ids_file)

    embeddings.load_index.cache_clear()
    try:
        yield embeddings_file, ids_file
    finally:
        # Ensure nothing built against this test's tmp_path outlives it — the
        # next real caller (this suite's own retriever, or another test)
        # must rebuild from the real index, not keep serving this one.
        embeddings.load_index.cache_clear()


def _matrix(n: int, dim: int = 4) -> np.ndarray:
    rng = np.random.default_rng(0)
    vecs = rng.normal(size=(n, dim)).astype(np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs / norms  # L2-normalised, matching encode()'s own contract


# --- save_index --------------------------------------------------------------


def test_save_index_writes_both_files(isolated_index):
    embeddings_file, ids_file = isolated_index
    embeddings.save_index(_matrix(3), ["a", "b", "c"])
    assert embeddings_file.exists()
    assert ids_file.exists()


def test_save_index_rejects_a_row_count_id_count_mismatch(isolated_index):
    with pytest.raises(ValueError, match="index corrupt"):
        embeddings.save_index(_matrix(3), ["a", "b"])  # 3 rows, 2 ids


def test_save_index_creates_the_data_directory_if_missing(isolated_index, tmp_path):
    assert not (tmp_path / "data").exists()
    embeddings.save_index(_matrix(2), ["a", "b"])
    assert (tmp_path / "data").is_dir()


def test_save_index_ids_are_stored_as_readable_json(isolated_index):
    _, ids_file = isolated_index
    embeddings.save_index(_matrix(2), ["pm-001", "pm-002"])
    assert json.loads(ids_file.read_text(encoding="utf-8")) == ["pm-001", "pm-002"]


# --- index_exists --------------------------------------------------------


def test_index_exists_is_false_before_saving(isolated_index):
    assert embeddings.index_exists() is False


def test_index_exists_is_true_after_saving(isolated_index):
    embeddings.save_index(_matrix(2), ["a", "b"])
    assert embeddings.index_exists() is True


def test_index_exists_is_false_if_only_one_file_is_present(isolated_index):
    embeddings_file, _ids_file = isolated_index
    embeddings.save_index(_matrix(2), ["a", "b"])
    embeddings_file.unlink()  # simulate a partial/interrupted write
    assert embeddings.index_exists() is False


# --- load_index: happy path + rebuild behavior ----------------------------


def test_load_index_round_trips_a_saved_index(isolated_index):
    matrix = _matrix(4)
    embeddings.save_index(matrix, ["a", "b", "c", "d"])

    loaded_matrix, loaded_ids = embeddings.load_index()

    assert loaded_ids == ["a", "b", "c", "d"]
    assert loaded_matrix.dtype == np.float32
    np.testing.assert_allclose(loaded_matrix, matrix, atol=1e-6)


def test_load_index_is_cached_and_does_not_reread_a_changed_file(isolated_index):
    """Documents the real, current behaviour: load_index() is a process-
    singleton cache, so a file changed on disk without an explicit
    cache_clear() is invisible until the next clear+reload — exactly why
    scripts/build_index.py's own docs (and the live process) call
    load_index.cache_clear() after a rebuild rather than assuming a plain
    re-call would pick it up."""
    embeddings.save_index(_matrix(2), ["a", "b"])
    first_ids = embeddings.load_index()[1]

    embeddings.save_index(_matrix(3), ["x", "y", "z"])
    still_cached_ids = embeddings.load_index()[1]

    assert first_ids == still_cached_ids == ["a", "b"]


def test_load_index_rebuild_behavior_cache_clear_picks_up_new_data(isolated_index):
    embeddings.save_index(_matrix(2), ["a", "b"])
    embeddings.load_index()

    embeddings.save_index(_matrix(3), ["x", "y", "z"])
    embeddings.load_index.cache_clear()
    rebuilt_ids = embeddings.load_index()[1]

    assert rebuilt_ids == ["x", "y", "z"]


# --- load_index: failure modes --------------------------------------------


def test_load_index_missing_files_raises_file_not_found_with_a_fix_command(isolated_index):
    with pytest.raises(FileNotFoundError, match="python -m scripts.build_index"):
        embeddings.load_index()


def test_load_index_missing_ids_file_only_raises_file_not_found(isolated_index):
    """index_exists() (and therefore load_index()'s guard) requires BOTH
    files — a matrix with no ids file is exactly as unusable as neither."""
    embeddings_file, _ids_file = isolated_index
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    np.save(embeddings_file, _matrix(2))
    with pytest.raises(FileNotFoundError):
        embeddings.load_index()


def test_load_index_mismatched_row_and_id_counts_raises_value_error(isolated_index):
    """A corruption load_index() itself must catch — unlike save_index()'s
    check (which prevents writing a mismatch in the first place), this is
    for a file pair that became inconsistent some other way (a hand-edited
    ids.json, a partial rewrite, ...)."""
    embeddings_file, ids_file = isolated_index
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    np.save(embeddings_file, _matrix(3))
    ids_file.write_text(json.dumps(["a", "b"]), encoding="utf-8")  # only 2, not 3

    with pytest.raises(ValueError, match="index corrupt"):
        embeddings.load_index()


def test_load_index_mismatched_dimensions_across_saves_is_still_readable(isolated_index):
    """load_index() itself has no fixed-dimension check (config.EMBEDDING_DIM
    is enforced only by build_index.py's own warning at build time, per
    nlp/embeddings.py's module docstring) — a matrix of a different width
    than expected still loads; a *row/id count* mismatch is the only
    corruption load_index() itself rejects. Documents that boundary rather
    than assuming a dimension check exists where it doesn't."""
    embeddings.save_index(_matrix(2, dim=8), ["a", "b"])
    matrix, ids = embeddings.load_index()
    assert matrix.shape == (2, 8)
    assert ids == ["a", "b"]


def test_load_index_corrupt_npy_file_raises(isolated_index):
    embeddings_file, ids_file = isolated_index
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    embeddings_file.write_bytes(b"not a real .npy file")
    ids_file.write_text(json.dumps(["a"]), encoding="utf-8")

    with pytest.raises(Exception):  # noqa: B017 - numpy's own load error, not this module's
        embeddings.load_index()


def test_load_index_corrupt_ids_json_raises(isolated_index):
    embeddings_file, ids_file = isolated_index
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    np.save(embeddings_file, _matrix(1))
    ids_file.write_text("not valid json {{{", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        embeddings.load_index()


# --- cosine_scores -----------------------------------------------------------


def test_cosine_scores_is_a_plain_dot_product_against_normalised_vectors():
    matrix = np.array([[1.0, 0.0], [0.0, 1.0], [0.7071, 0.7071]], dtype=np.float32)
    query = np.array([1.0, 0.0], dtype=np.float32)
    scores = embeddings.cosine_scores(query, matrix)
    np.testing.assert_allclose(scores, [1.0, 0.0, 0.7071], atol=1e-4)
