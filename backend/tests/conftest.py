"""Shared pytest fixtures.

Most of this codebase is deliberately deterministic functions over plain
dicts (see nlp/generator.py, nlp/team_builder.py, nlp/timeline.py,
nlp/learning_path.py) — those tests need no fixture at all. `mongo_test_db`
exists only for the handful of tests that genuinely touch MongoDB (auth),
and redirects to a throwaway database on the same server so tests never
read or write the real `projectmind` database.
"""

from __future__ import annotations

import os

import pytest

import config
from db import client as db

# Suffixed with the interpreter's own pid so two pytest processes running at
# once (this happened for real — a second session's test run interleaved
# drop_database()/insert calls with this one's against a bare
# "projectmind_test", producing intermittent NoneType/KeyError failures with
# no code defect behind them) get fully separate throwaway databases instead
# of silently sharing — and colliding on — the same one.
TEST_DB_NAME = f"projectmind_test_{os.getpid()}"


@pytest.fixture
def mongo_test_db(monkeypatch):
    if not db.ping():
        pytest.skip("MongoDB is not reachable — start mongod to run this test.")

    monkeypatch.setattr(config, "MONGO_DB", TEST_DB_NAME)
    try:
        yield
    finally:
        db.get_client().drop_database(TEST_DB_NAME)


@pytest.fixture
def client(mongo_test_db):
    """Flask test client for route-level persistence tests (routes/assistant.py,
    routes/user.py) — everything it touches lands in the same throwaway
    `mongo_test_db` database as the rest of the suite, since db.get_db() reads
    config.MONGO_DB fresh on every call.

    `app` is imported lazily (inside the fixture, not at module scope) so its
    module-level `create_app()` — which calls db.ensure_indexes() and
    recommend.warmup() — runs at most once per test session, against
    whatever config.MONGO_DB is at first import (the real database; harmless
    and idempotent), rather than racing the per-test monkeypatch above.

    Deliberately does NOT (re)build indexes on the throwaway test database
    itself here — a fresh `mongo_test_db` has none, and building them on
    every single test raced the previous test's drop_database() call often
    enough to be flaky (Mongo's "database is currently being dropped").
    A test that genuinely depends on a unique-index constraint (see
    test_user_routes.py's duplicate-favourite test) calls
    ensure_indexes_for_test() below itself, once, rather than paying that
    cost — and that race — on every test in this file.

    Resets flask-limiter's storage before every test so accumulated calls
    from earlier tests in this same process (the limiter is a module-level
    singleton reused across the whole session) never trip a route's
    `@limiter.limit(...)` — see extensions.py.
    """
    from app import app as flask_app
    from extensions import limiter

    limiter.reset()
    return flask_app.test_client()


def ensure_indexes_for_test() -> None:
    """db.ensure_indexes(), retried past Mongo's transient "database is
    currently being dropped" error — the previous test's mongo_test_db
    teardown drops this same-named throwaway database, and occasionally is
    still finishing when the next test's index build starts. Only needed by
    tests that actually depend on a unique-index constraint being enforced
    (not just present in code), so this is opt-in rather than run for every
    `client`-using test — see the `client` fixture above.
    """
    import time

    from pymongo.errors import OperationFailure

    for attempt in range(5):
        try:
            db.ensure_indexes()
            return
        except OperationFailure as error:
            if error.code == 215 and attempt < 4:  # DatabaseDropPending
                time.sleep(0.05)
                continue
            raise
