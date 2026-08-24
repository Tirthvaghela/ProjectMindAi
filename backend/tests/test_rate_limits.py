"""Rate-limit configuration tests.

Deliberately does NOT try to trigger a real 429 by hammering a route through
the test client — extensions.py's own module docstring documents that
Flask-Limiter's in-memory counters measurably fail to persist between
requests under Werkzeug's dev server (which is what the test client runs
against here too), and are only verified to enforce correctly under
waitress. Asserting "hit the route N+1 times, expect 429" against this
client would therefore be a flaky test of the test environment, not of the
application.

Instead these assert the *configuration* itself — that the expected
`@limiter.limit(...)` decorator is actually attached to each route, with the
exact limit string intended — via Flask-Limiter's own `limit_manager`
registry. This is exactly what actually matters: that a route opted in, and
opted in to the right number, regardless of whether this test process can
observe enforcement.
"""

from __future__ import annotations

import pytest

from extensions import limiter


def _configured_limits(app, endpoint: str) -> list[str]:
    _exemptions, limits = limiter.limit_manager.resolve_limits(app, endpoint)
    return [str(item.limit) for item in limits]


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        # New this pass — see routes/teams.py, routes/search.py,
        # routes/ideas.py, routes/notifications.py for the rationale
        # comment on each.
        ("teams.post_message_route", "30 per 1 hour"),
        ("search.team_builder", "30 per 1 minute"),
        ("ideas.idea_team_builder", "30 per 1 minute"),
        ("notifications.list_notifications", "60 per 1 minute"),
        ("notifications.mark_read", "60 per 1 minute"),
        ("notifications.mark_all_read", "60 per 1 minute"),
        # Pre-existing limits — regression guards so a future refactor can't
        # silently drop one of these while this file's own new assertions
        # stay green.
        ("auth.signup_route", "10 per 1 hour"),
        ("auth.login_route", "20 per 1 hour"),
        ("search.search", "30 per 1 minute"),
        ("search.personalized_recommend", "30 per 1 minute"),
        ("search.uniqueness", "20 per 1 minute"),
        ("search.resume_suggest", "10 per 1 minute"),
        ("assistant.chat", "20 per 1 hour"),
        ("assistant.send_conversation_message", "30 per 1 hour"),
        ("ideas.idea_chat", "20 per 1 hour"),
    ],
)
def test_route_has_expected_rate_limit(client, endpoint, expected):
    app = client.application
    assert _configured_limits(app, endpoint) == [expected]


@pytest.mark.parametrize(
    "endpoint",
    [
        # Deliberately NOT rate-limited: authenticated, ownership-checked,
        # cheap Mongo reads/writes with no external side effect — same
        # category as favorites/history, which the app has never limited.
        # Listed explicitly so a future "just add a limit everywhere" pass
        # doesn't quietly change this app's own established policy (see
        # extensions.py: only expensive/external/security-sensitive routes
        # opt in).
        "teams.create",
        "teams.join",
        "teams.mine",
        "teams.get_one",
        "teams.update",
        "teams.remove_member_route",
        "teams.set_my_skills",
        "teams.roles",
        "teams.messages",
    ],
)
def test_cheap_authenticated_team_routes_remain_unlimited(client, endpoint):
    app = client.application
    assert _configured_limits(app, endpoint) == []


def test_analytics_route_was_removed():
    """GET /api/analytics was dead backend code (its frontend page/route was
    already deleted) — removed rather than rate-limited. Regression guard so
    it isn't silently reintroduced without a real caller."""
    from app import app as flask_app

    assert "projects.analytics" not in flask_app.view_functions
    rules = [str(rule) for rule in flask_app.url_map.iter_rules()]
    assert "/api/analytics" not in rules
