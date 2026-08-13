"""Shared Flask extension instances.

Created here, unbound, so route modules can import and decorate with them
(`@limiter.limit(...)`) without a circular import on the app factory in
app.py, which is what actually calls `limiter.init_app(app)`.
"""

from __future__ import annotations

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# No default_limits: only the routes that call an external, cost-bearing API,
# or that are otherwise expensive (search, uniqueness, résumé upload) or
# security-sensitive (auth), opt in explicitly.
#
# Known dev-only quirk: under `python app.py` (Werkzeug's debug reloader +
# interactive debugger together), limits measurably fail to persist between
# requests in this environment — verified NOT a bug in the limiting code
# itself: a bare-bones reproduction of this exact module structure enforces
# correctly, and so does this real app when served via waitress (the
# documented production path, see backend/README.md). Test rate limiting
# through waitress, not the dev server.
limiter = Limiter(get_remote_address, default_limits=[])
