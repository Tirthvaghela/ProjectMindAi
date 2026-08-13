"""Shared request/response helpers for the blueprints."""

from __future__ import annotations

from typing import Any, Optional

from flask import jsonify, request

import config


class ApiError(Exception):
    """Raised anywhere in a route to produce a clean JSON error response.

    `code` is an optional, stable, machine-readable string ("LLM_UNAVAILABLE",
    "LLM_RATE_LIMITED", ...) for callers that want to branch on *why* a
    request failed without parsing `message` — additive on top of the
    existing `{"error": "..."}` shape every route and the frontend's
    services/api.js already rely on, so passing nothing here (the default,
    and every pre-existing call site) is byte-for-byte the same response as
    before. Not every ApiError needs one; most 400s are self-explanatory
    from `message` alone.
    """

    def __init__(self, message: str, status: int = 400, details: Any = None, code: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.details = details
        self.code = code

    def to_response(self):
        payload: dict[str, Any] = {"error": self.message}
        if self.details is not None:
            payload["details"] = self.details
        if self.code is not None:
            payload["code"] = self.code
        return jsonify(payload), self.status


def ok(data: Any, **extra: Any):
    """Uniform success envelope so the frontend never has to guess a shape."""
    payload = {"data": data}
    payload.update(extra)
    return jsonify(payload)


def device_id(required: bool = True) -> Optional[str]:
    """Identify the caller without accounts.

    The frontend generates a UUID once and stores it in localStorage, then
    sends it on every request. That is enough to key favourites and history,
    and it avoids building an entire auth system this project does not need.
    """
    value = request.headers.get("X-Device-Id") or (
        request.json.get("device_id") if request.is_json and request.json else None
    )
    # A dict/list here (e.g. {"$ne": null} sent as JSON "device_id") would be
    # handed straight to a Mongo filter — {"device_id": value} — and match
    # every device instead of one. Reject anything that isn't the plain
    # string every real caller sends, before it ever reaches a query.
    if value is not None and not isinstance(value, str):
        raise ApiError("Invalid device identifier.", status=400)
    if not value and required:
        raise ApiError(
            "Missing device identifier. Send an 'X-Device-Id' header.", status=400
        )
    return value


def current_user(required: bool = True) -> Optional[dict[str, Any]]:
    """Resolve the caller's account from the X-Auth-Token header.

    Distinct from device_id(): device_id identifies an anonymous browser and
    drives favourites/history/personalisation everywhere in this app; this
    identifies a signed-in person and is used only by teams and
    notifications. Most routes need at most one of the two, never both.
    """
    from auth.service import user_from_token

    token = request.headers.get("X-Auth-Token")
    user = user_from_token(token) if token else None
    if user is None and required:
        raise ApiError("Sign in required.", status=401)
    return user


def json_body() -> dict[str, Any]:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError("Request body must be a JSON object.", status=400)
    return body


def get_int(source: dict[str, Any], key: str, default: int, lo: int, hi: int) -> int:
    """Read an int and clamp it. Never raises on junk input — clamping a bad
    'limit' is friendlier than a 400, and it prevents a caller from requesting
    the entire collection."""
    raw = source.get(key, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(value, hi))


def parse_filters(source: dict[str, Any]) -> dict[str, Any]:
    """Normalise filter inputs from either query string or JSON body."""
    technologies = source.get("technologies") or source.get("tech") or []
    if isinstance(technologies, str):
        technologies = [t.strip() for t in technologies.split(",") if t.strip()]

    max_weeks = source.get("max_duration_weeks")
    try:
        max_weeks = int(max_weeks) if max_weeks not in (None, "") else None
    except (TypeError, ValueError):
        max_weeks = None

    filters = {
        "domain": (source.get("domain") or "").strip() or None,
        "difficulty": (source.get("difficulty") or "").strip() or None,
        "technologies": technologies,
        "max_duration_weeks": max_weeks,
    }
    return {k: v for k, v in filters.items() if v not in (None, [], "")}


def top_k_from(source: dict[str, Any]) -> int:
    return get_int(source, "top_k", config.DEFAULT_TOP_K, 1, config.MAX_TOP_K)
