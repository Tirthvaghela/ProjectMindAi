"""routes/helpers.py — the shared ApiError/ok() plumbing every blueprint
uses. `to_response()` itself (the jsonify call) needs a Flask app context —
exercised end-to-end through the real routes in tests/test_assistant_routes.py
(the LLM-failure `code` tests) rather than duplicated here; this file covers
the plain attribute contract that backs it.
"""

from __future__ import annotations

from routes.helpers import ApiError


def test_api_error_defaults_to_no_code():
    error = ApiError("Something went wrong.")
    assert error.message == "Something went wrong."
    assert error.status == 400
    assert error.details is None
    assert error.code is None


def test_api_error_stores_a_code_when_given():
    error = ApiError("AI assistant is not configured.", status=503, code="LLM_UNAVAILABLE")
    assert error.status == 503
    assert error.code == "LLM_UNAVAILABLE"


def test_api_error_code_is_independent_of_details():
    error = ApiError("Bad input.", status=400, details={"field": "email"}, code="VALIDATION_ERROR")
    assert error.details == {"field": "email"}
    assert error.code == "VALIDATION_ERROR"
