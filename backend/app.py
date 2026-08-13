"""Flask application factory and entry point.

Run locally:
    cd backend
    venv\\Scripts\\python app.py
"""

from __future__ import annotations

import logging
import os
import re

from flask import Flask, jsonify
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

import config
from db import client as db
from extensions import limiter
from nlp import embeddings, recommend
from routes.helpers import ApiError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("projectmind")


def create_app() -> Flask:
    app = Flask(__name__)

    # 5 MB covers any real résumé with headroom; nothing else in this API
    # accepts a body anywhere near that size, so one global cap is enough.
    app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

    CORS(
        app,
        origins=config.CORS_ORIGINS,
        # X-Device-Id and X-Auth-Token are our identity headers; without
        # allowing them the browser preflight rejects every request that
        # sends one.
        allow_headers=["Content-Type", "X-Device-Id", "X-Auth-Token"],
        # PATCH is here for PATCH /api/teams/<id> (rename a team) — every
        # other mutation in this app is POST/DELETE, but a partial update is
        # a PATCH by convention, and an unlisted method fails CORS preflight
        # silently in the browser even though a same-origin test client
        # never notices.
        methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    )

    from routes.assistant import bp as assistant_bp
    from routes.auth import bp as auth_bp
    from routes.notifications import bp as notifications_bp
    from routes.projects import bp as projects_bp
    from routes.search import bp as search_bp
    from routes.teams import bp as teams_bp
    from routes.user import bp as user_bp

    limiter.init_app(app)

    app.register_blueprint(search_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(assistant_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(teams_bp)
    app.register_blueprint(notifications_bp)

    _register_error_handlers(app)
    _register_health(app)

    try:
        db.ensure_indexes()
    except Exception:  # noqa: BLE001
        # A missing mongod should not stop the process from starting — /api/health
        # will report it, which is far easier to diagnose than a crash on boot.
        log.exception("Could not ensure MongoDB indexes; is mongod running?")

    # With the reloader (FLASK_DEBUG=1), create_app() runs once in the watcher
    # process and again in the spawned server subprocess, which is the only one
    # with WERKZEUG_RUN_MAIN set. Without the reloader there's only one process
    # and no such env var, so this reduces to "always run".
    if not config.FLASK_DEBUG or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        try:
            recommend.warmup()
        except Exception:  # noqa: BLE001
            # Same reasoning as db.ensure_indexes() above: an unbuilt index or
            # unreachable NLTK mirror shouldn't stop the process from starting.
            # The existing per-request FileNotFoundError handler covers it from here.
            log.exception("Could not warm up the NLP retriever/model")

    return app


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def handle_api_error(error: ApiError):
        return error.to_response()

    @app.errorhandler(FileNotFoundError)
    def handle_missing_index(error: FileNotFoundError):
        # Almost always the embedding index; give the exact fix, not a stack trace.
        log.error("Missing artifact: %s", error)
        return (
            jsonify(
                {
                    "error": "Search index not built.",
                    "fix": "Run: python -m scripts.seed_db && python -m scripts.build_index",
                }
            ),
            503,
        )

    @app.errorhandler(HTTPException)
    def handle_http_error(error: HTTPException):
        return jsonify({"error": error.description}), error.code

    @app.errorhandler(Exception)
    def handle_unexpected(error: Exception):
        log.exception("Unhandled error")
        return jsonify({"error": "Internal server error."}), 500


def _redact_uri(uri: str) -> str:
    """Hide credentials before a connection string reaches an unauthenticated response.

    Harmless for mongodb://localhost:27017, but the moment MONGO_URI points at
    Atlas with mongodb+srv://user:pass@cluster..., leaving this unredacted
    would hand out real database credentials to anyone who requests /api/health.
    """
    return re.sub(r"//([^:@/]+):([^@/]+)@", r"//\1:***@", uri)


def _register_health(app: Flask) -> None:
    @app.get("/api/health")
    def health():
        """Report every dependency separately.

        A single boolean would hide *which* piece is broken, which is the only
        thing worth knowing when the app misbehaves.
        """
        mongo_up = db.ping()
        index_built = embeddings.index_exists()

        project_count = db.projects().count_documents({}) if mongo_up else 0

        healthy = mongo_up and index_built and project_count > 0
        return (
            jsonify(
                {
                    "status": "ok" if healthy else "degraded",
                    "mongodb": {
                        "connected": mongo_up,
                        "uri": _redact_uri(config.MONGO_URI),
                        "database": config.MONGO_DB,
                        "projects": project_count,
                    },
                    "search_index": {
                        "built": index_built,
                        "model": config.EMBEDDING_MODEL,
                    },
                    "ai_assistant": {
                        # Deliberately not degraded/unhealthy when this is off — every
                        # other feature works without it; see nlp/ai_assistant.py.
                        "enabled": config.AI_ASSISTANT_ENABLED,
                        "model": config.GROQ_MODEL if config.AI_ASSISTANT_ENABLED else None,
                    },
                }
            ),
            200 if healthy else 503,
        )


app = create_app()


if __name__ == "__main__":
    log.info("Starting ProjectMind AI on http://%s:%s", config.FLASK_HOST, config.FLASK_PORT)
    app.run(host=config.FLASK_HOST, port=config.FLASK_PORT, debug=config.FLASK_DEBUG)
