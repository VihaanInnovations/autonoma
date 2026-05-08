"""
Regression tests for SEC002 value-side gates.

False positives that must NOT produce SEC002:
  token = "is not"
  token = "not in"
  token_source = "POST"
  INTERNAL_RESET_SESSION_TOKEN = "_password_reset_token"
  tokenUrl = "token"
  apiKey = "apiKey"

True positives that MUST still produce SEC002:
  api_key = "stk_live_51N7ZQyqI7JBjRSfFxEJqNzgk51N7"
  github_token = "ghp_abcdefghijklmnopqrstuvwxyz123456"
  auth_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyIn0.abc"
"""
import pytest

from autonoma._internal.ast_engine import ASTEngine, _looks_like_identifier_or_word, _mirrors_variable_name
from autonoma._internal.heuristics import HeuristicsEngine


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("is not", True),
    ("not in", True),
    ("POST", True),
    ("GET", True),
    ("token", True),
    ("apiKey", True),
    ("api_key", True),
    ("_password_reset_token", True),
    ("bearer", True),
    ("set-password", True),
    # "Secret" is in _PLAIN_WORD_VALUES; short generic words without _ prefix are not excluded
    ("abc", False),
    ("Secret", True),
    # NOT identifier-like (contains digits or special chars)
    ("stk_live_51N7ZQyqI7JBjRSfFxEJqNzgk", False),
    ("ghp_abcdefghijklmnopqrstuvwxyz123456", False),
    ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", False),
    ("AIzaSyD_abc123XYZ", False),
])
def test_looks_like_identifier_or_word(value, expected):
    assert _looks_like_identifier_or_word(value) == expected, (
        f"_looks_like_identifier_or_word({value!r}) expected {expected}"
    )


@pytest.mark.parametrize("name,value,expected", [
    ("apiKey", "apiKey", True),
    ("tokenUrl", "token", True),
    ("API_KEY", "api_key", True),
    ("MyToken", "mytoken", True),
    # No mirror
    ("github_token", "ghp_abcdefghijklmnopqrstuvwxyz123456", False),
    ("api_key", "sk_live_51N7ZQ", False),
    ("auth_token", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", False),
])
def test_mirrors_variable_name(name, value, expected):
    assert _mirrors_variable_name(name, value) == expected, (
        f"_mirrors_variable_name({name!r}, {value!r}) expected {expected}"
    )


# ---------------------------------------------------------------------------
# Integration tests: false positives that must NOT fire SEC002
# ---------------------------------------------------------------------------

def _has_sec002(code: str) -> bool:
    engine = HeuristicsEngine()
    result = engine.analyze(code, "test_file.py")
    return any(i["id"] == "SEC002" for i in result.issues)


@pytest.mark.parametrize("code,description", [
    ('token = "is not"', 'Python operator string'),
    ('token = "not in"', 'Python operator string'),
    ('token_source = "POST"', 'HTTP method'),
    ('INTERNAL_RESET_SESSION_TOKEN = "_password_reset_token"', 'identifier-like value'),
    ('tokenUrl = "token"', 'value mirrors variable name'),
    ('apiKey = "apiKey"', 'value equals variable name'),
])
def test_sec002_false_positive_suppressed(code, description):
    assert not _has_sec002(code), (
        f"SEC002 must NOT fire on: {code!r} ({description})"
    )


# ---------------------------------------------------------------------------
# Integration tests: true positives that MUST still fire SEC002
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("code,description", [
    (
        'api_key = "stk_live_51N7ZQyqI7JBjRSfFxEJqNzgk51N7"',
        'Stripe live key',
    ),
    (
        'github_token = "ghp_abcdefghijklmnopqrstuvwxyz123456"',
        'GitHub personal access token',
    ),
    (
        'auth_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyIn0.abc123"',
        'JWT token',
    ),
])
def test_sec002_true_positive_still_fires(code, description):
    assert _has_sec002(code), (
        f"SEC002 MUST fire on: {code!r} ({description})"
    )
