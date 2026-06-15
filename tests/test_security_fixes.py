"""Tests for S2 (_sql_str) and S7 (generate_random_string via secrets)."""

import string

from app.services.installers.base import BaseInstaller
from app.services.installers.xui_installer import _sql_str  # noqa: PLC0415

# ── S2: _sql_str ──────────────────────────────────────────────────────────────

def test_sql_str_no_quotes():
    """Plain strings pass through unchanged."""
    assert _sql_str("admin") == "admin"
    assert _sql_str("/web/path/") == "/web/path/"


def test_sql_str_single_quote_doubled():
    """Single quotes are doubled (SQLite literal escaping)."""
    assert _sql_str("it's") == "it''s"
    assert _sql_str("a'b'c") == "a''b''c"


def test_sql_str_injection_neutralised():
    """Classic injection payload becomes an inert literal."""
    payload = "x'); DROP TABLE users; --"
    escaped = _sql_str(payload)
    # The single quote is doubled, so the payload cannot break out of the literal.
    assert "''" in escaped
    assert escaped == "x''); DROP TABLE users; --"


def test_sql_str_bcrypt_hash_safe():
    """bcrypt hashes contain $, /, . — none of which need SQL escaping."""
    bcrypt_hash = "$2b$10$abcdefghijklmnopqrstuuVwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ01"
    assert _sql_str(bcrypt_hash) == bcrypt_hash


# ── S7: generate_random_string ────────────────────────────────────────────────

def test_generate_random_string_default_length():
    result = BaseInstaller.generate_random_string()
    assert len(result) == 16


def test_generate_random_string_custom_length():
    for n in (1, 8, 32, 64):
        assert len(BaseInstaller.generate_random_string(n)) == n


def test_generate_random_string_alphabet():
    allowed = set(string.ascii_letters + string.digits)
    for _ in range(20):
        result = BaseInstaller.generate_random_string(50)
        assert set(result) <= allowed, f"Unexpected chars in: {result!r}"


def test_generate_random_string_not_deterministic():
    """Two calls should almost never produce the same value (birthday bound ~negligible for 16 chars)."""
    results = {BaseInstaller.generate_random_string() for _ in range(50)}
    assert len(results) > 1
