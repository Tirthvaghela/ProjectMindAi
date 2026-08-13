"""Build the embedding index from MongoDB.

    cd backend
    venv\\Scripts\\python -m scripts.build_index

Embeddings are computed here, offline, and written to disk. The API only ever
encodes the user's query at request time — encoding 1000 project descriptions
per search would make the endpoint unusable.

Re-run this whenever the project collection changes.
"""

from __future__ import annotations

import logging
import sys

import config
from db import client as db
from db import schema
from nlp import embeddings

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
log = logging.getLogger("build_index")


def main() -> int:
    if not db.ping():
        log.error("Cannot reach MongoDB at %s", config.MONGO_URI)
        return 1

    documents = list(db.projects().find({}, {"_id": 0}).sort("project_id", 1))
    if not documents:
        log.error("No projects in the database. Run: python -m scripts.seed_db")
        return 1

    log.info("Encoding %d projects with %s", len(documents), config.EMBEDDING_MODEL)
    log.info("(first run downloads the model, ~90 MB)")

    ids = [doc["project_id"] for doc in documents]
    texts = [schema.embedding_text(doc) for doc in documents]

    matrix = embeddings.encode(texts, show_progress=True)

    if matrix.shape[1] != config.EMBEDDING_DIM:
        # Guard against a config/model mismatch silently producing a corrupt
        # index that only fails much later, at query time.
        log.warning(
            "Model produced dim=%d but config.EMBEDDING_DIM=%d. Update your .env.",
            matrix.shape[1],
            config.EMBEDDING_DIM,
        )

    embeddings.save_index(matrix, ids)

    log.info("Index built: %d vectors of dim %d", matrix.shape[0], matrix.shape[1])
    log.info("Size on disk: %.1f KB", config.EMBEDDINGS_FILE.stat().st_size / 1024)
    log.info("Next: venv\\Scripts\\python app.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
