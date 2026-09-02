from src.config import _env_int
from src.services.memes import get_day_index


def test_env_int_valid(monkeypatch):
    monkeypatch.setenv("TEST_INT", "42")
    assert _env_int("TEST_INT") == 42


def test_env_int_default(monkeypatch):
    monkeypatch.delenv("TEST_INT_MISSING", raising=False)
    assert _env_int("TEST_INT_MISSING", 7) == 7


def test_env_int_invalid_returns_default(monkeypatch):
    monkeypatch.setenv("TEST_INT_BAD", "abc")
    assert _env_int("TEST_INT_BAD", 9) == 9


def test_env_int_whitespace(monkeypatch):
    monkeypatch.setenv("TEST_INT_SPACE", " 123 ")
    assert _env_int("TEST_INT_SPACE") == 123


def test_env_int_empty(monkeypatch):
    monkeypatch.setenv("TEST_INT_EMPTY", "   ")
    assert _env_int("TEST_INT_EMPTY", 5) == 5


def test_get_day_index_positive():
    assert get_day_index() > 0
