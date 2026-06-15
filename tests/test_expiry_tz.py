"""Tests for expiry_date timezone-aware handling.

Covers:
- ensure_utc helper function
- Subscription.is_expired / remaining_days with aware and naive expiry_date
- InboundConnection.is_expired / remaining_days with aware and naive expiry_date
- No TypeError when comparing aware vs naive datetimes
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.utils.date_utils import ensure_utc

# Minimal Fernet key used across tests that need encryption (AWG-derived models)
_FERNET_KEY = "SpWH-ifTebQwpAlasE5SvZsgUwi0onGmILmSrm7G1BQ="
_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


def _mock_settings():
    s = MagicMock()
    s.encryption_key = _FERNET_KEY
    s.database_url = _TEST_DB_URL
    s.log_level = "INFO"
    return s


def _make_subscription(expiry_date):
    """Construct a Subscription via SQLAlchemy constructor (no DB flush)."""
    with patch("app.config.get_settings", return_value=_mock_settings()):
        from app.database.models.subscription import Subscription

        sub = Subscription(
            client_id=1,
            name="Test",
            subscription_token="tok",
            total_gb=100,
            expiry_date=expiry_date,
            is_active=True,
        )
    return sub


def _make_connection(expiry_date, is_enabled=True):
    """Construct an InboundConnection via SQLAlchemy constructor (no DB flush)."""
    with patch("app.config.get_settings", return_value=_mock_settings()):
        from app.database.models.inbound_connection import InboundConnection

        conn = InboundConnection(
            subscription_id=1,
            inbound_id=1,
            type="inbound_connection",
            is_enabled=is_enabled,
            total_gb=0,
            expiry_date=expiry_date,
        )
    return conn


# ---------------------------------------------------------------------------
# ensure_utc
# ---------------------------------------------------------------------------


class TestEnsureUtc:
    def test_none_returns_none(self):
        assert ensure_utc(None) is None

    def test_naive_gets_utc_tzinfo(self):
        naive = datetime(2026, 6, 1, 12, 0, 0)
        result = ensure_utc(naive)
        assert result is not None
        assert result.tzinfo is UTC
        # Wall time is preserved
        assert result.year == 2026
        assert result.month == 6
        assert result.day == 1
        assert result.hour == 12
        assert result.minute == 0

    def test_aware_utc_returned_as_is(self):
        aware_utc = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
        result = ensure_utc(aware_utc)
        assert result is aware_utc  # same object, not a copy

    def test_aware_non_utc_returned_as_is_not_shifted(self):
        """ensure_utc must NOT convert or shift non-UTC aware datetimes."""
        tz_plus3 = timezone(timedelta(hours=3))
        aware_plus3 = datetime(2026, 6, 1, 15, 0, 0, tzinfo=tz_plus3)
        result = ensure_utc(aware_plus3)
        assert result is aware_plus3
        assert result.tzinfo == tz_plus3
        assert result.hour == 15  # wall time unchanged


# ---------------------------------------------------------------------------
# Subscription model (constructor-only, no DB needed)
# ---------------------------------------------------------------------------


class TestSubscriptionExpiry:
    # --- is_expired ---

    def test_is_expired_none(self):
        sub = _make_subscription(None)
        assert sub.is_expired is False

    def test_is_expired_aware_past(self):
        sub = _make_subscription(datetime.now(UTC) - timedelta(days=1))
        assert sub.is_expired is True

    def test_is_expired_aware_future(self):
        sub = _make_subscription(datetime.now(UTC) + timedelta(days=30))
        assert sub.is_expired is False

    def test_is_expired_naive_past_treated_as_utc(self):
        """Legacy naive values must be treated as UTC - no TypeError."""
        naive_past = datetime(2026, 1, 1, 0, 0, 0)  # well in the past
        assert naive_past.tzinfo is None
        sub = _make_subscription(naive_past)
        # Should not raise and should be expired
        assert sub.is_expired is True

    def test_is_expired_naive_future_treated_as_utc(self):
        naive_future = datetime(2099, 1, 1, 0, 0, 0)  # well in the future
        assert naive_future.tzinfo is None
        sub = _make_subscription(naive_future)
        assert sub.is_expired is False

    # --- remaining_days ---

    def test_remaining_days_none(self):
        sub = _make_subscription(None)
        assert sub.remaining_days is None

    def test_remaining_days_aware_future(self):
        sub = _make_subscription(datetime.now(UTC) + timedelta(days=10))
        rd = sub.remaining_days
        assert rd is not None
        assert 9 <= rd <= 10

    def test_remaining_days_aware_past(self):
        sub = _make_subscription(datetime.now(UTC) - timedelta(days=1))
        assert sub.remaining_days == 0

    def test_remaining_days_naive_no_type_error(self):
        """Naive expiry_date must not raise TypeError on comparison."""
        naive_future = datetime(2099, 1, 1, 0, 0, 0)
        sub = _make_subscription(naive_future)
        rd = sub.remaining_days  # must not raise
        assert rd is not None
        assert rd > 0


# ---------------------------------------------------------------------------
# InboundConnection model (constructor-only, no DB needed)
# ---------------------------------------------------------------------------


class TestInboundConnectionExpiry:
    def test_is_expired_none(self):
        conn = _make_connection(None)
        assert conn.is_expired is False

    def test_is_expired_aware_past(self):
        conn = _make_connection(datetime.now(UTC) - timedelta(hours=1))
        assert conn.is_expired is True

    def test_is_expired_aware_future(self):
        conn = _make_connection(datetime.now(UTC) + timedelta(days=7))
        assert conn.is_expired is False

    def test_is_expired_naive_no_type_error(self):
        naive_past = datetime(2026, 1, 1, 0, 0, 0)
        assert naive_past.tzinfo is None
        conn = _make_connection(naive_past)
        assert conn.is_expired is True  # no TypeError

    def test_remaining_days_naive_no_type_error(self):
        naive_future = datetime(2099, 1, 1, 0, 0, 0)
        conn = _make_connection(naive_future)
        rd = conn.remaining_days
        assert rd is not None
        assert rd > 0

    def test_remaining_days_with_sign_negative(self):
        past = datetime.now(UTC) - timedelta(days=2)
        conn = _make_connection(past)
        rds = conn.remaining_days_with_sign
        assert rds is not None
        assert rds < 0

    def test_is_connection_active_expired_disabled(self):
        past = datetime.now(UTC) - timedelta(days=1)
        conn = _make_connection(past, is_enabled=False)
        assert conn.is_connection_active is False

    def test_is_connection_active_future_enabled(self):
        future = datetime.now(UTC) + timedelta(days=1)
        conn = _make_connection(future, is_enabled=True)
        assert conn.is_connection_active is True
