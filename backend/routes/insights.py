"""Skill progress & profile insights (read-only).

Account-scoped like routes/profile.py and routes/roadmap.py: the data is always
the session-resolved user's own, and no route takes a user id from the URL, query
or body. The endpoint takes no parameters at all, so any query string is rejected
rather than silently ignored.
"""

from __future__ import annotations

from flask import Blueprint, request

from extensions import limiter
from profiles import insights
from routes.helpers import ApiError, current_user, ok

bp = Blueprint("insights", __name__, url_prefix="/api/insights")


@bp.get("/me")
@limiter.limit("60 per minute")
def my_insights():
    user = current_user()
    if request.args:
        raise ApiError("This endpoint takes no parameters.", status=400)
    return ok(insights.build_insights(user["user_id"]))
