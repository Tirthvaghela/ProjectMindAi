"""routes/helpers.py — the shared ApiError/ok() plumbing every blueprint
uses. `to_response()` itself (the jsonify call) needs a Flask app context —
exercised end-to-end through the real routes in tests/test_assistant_routes.py
(the LLM-failure `code` tests) rather than duplicated here; this file covers
the plain attribute contract that backs it.
"""

from __future__ import annotations

import pytest

from routes.helpers import ApiError, parse_filters


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


# --- parse_filters ------------------------------------------------------
# A wrong-typed domain/difficulty/technologies used to reach .strip()/a set
# comprehension downstream and crash with an unhandled 500 (AttributeError/
# TypeError) instead of the clean 400 every other bad input in this app
# gets — reachable straight from a JSON POST body (search, recommend).


def test_parse_filters_rejects_a_non_string_domain():
    with pytest.raises(ApiError, match="'domain' must be a string"):
        parse_filters({"domain": 123})


def test_parse_filters_rejects_a_non_string_difficulty():
    with pytest.raises(ApiError, match="'difficulty' must be a string"):
        parse_filters({"difficulty": ["Intermediate"]})


def test_parse_filters_rejects_a_non_string_technologies_value():
    with pytest.raises(ApiError, match="'technologies' must be"):
        parse_filters({"technologies": 123})


def test_parse_filters_rejects_a_technologies_list_with_a_non_string_item():
    with pytest.raises(ApiError, match="'technologies' must be"):
        parse_filters({"technologies": ["Python", 123]})


def test_parse_filters_still_accepts_valid_input():
    result = parse_filters({"domain": "AI", "difficulty": "Intermediate", "technologies": ["Python", "React"]})
    assert result == {"domain": "AI", "difficulty": "Intermediate", "technologies": ["Python", "React"]}


def test_parse_filters_still_accepts_a_comma_separated_technologies_string():
    result = parse_filters({"technologies": "Python, React"})
    assert result["technologies"] == ["Python", "React"]
