"""Tests for configuration."""

import pytest

from app.config import Settings

# Valid Fernet key used across all Settings() constructions in this test module.
VALID_FERNET_KEY = "Ajhsod-TO6ML70nIZlKZ3PI8tPI5kNSKk45EESbRHK0="


def test_settings_default_values():
    """Test default settings values."""
    settings = Settings(
        bot_token="test_token",
        encryption_key=VALID_FERNET_KEY,
    )

    assert settings.bot_token == "test_token"
    assert settings.encryption_key == VALID_FERNET_KEY
    assert settings.log_level == "INFO"
    assert settings.xui_timeout == 30
    assert settings.database_url == "sqlite+aiosqlite:///./data/vpn_manager.db"


def test_settings_admin_ids_parsing():
    """Test parsing admin Telegram IDs."""
    settings = Settings(
        bot_token="test_token",
        encryption_key=VALID_FERNET_KEY,
        admin_telegram_ids="123456789,987654321",
    )

    admin_ids = settings.admin_ids
    assert len(admin_ids) == 2
    assert 123456789 in admin_ids
    assert 987654321 in admin_ids


def test_settings_admin_ids_empty():
    """Test empty admin IDs."""
    settings = Settings(
        bot_token="test_token",
        encryption_key=VALID_FERNET_KEY,
        admin_telegram_ids="",
    )

    admin_ids = settings.admin_ids
    assert len(admin_ids) == 0


def test_settings_admin_ids_single():
    """Test single admin ID."""
    settings = Settings(
        bot_token="test_token",
        encryption_key=VALID_FERNET_KEY,
        admin_telegram_ids="123456789",
    )

    admin_ids = settings.admin_ids
    assert len(admin_ids) == 1
    assert 123456789 in admin_ids


def test_settings_is_admin():
    """Test admin check."""
    settings = Settings(
        bot_token="test_token",
        encryption_key=VALID_FERNET_KEY,
        admin_telegram_ids="123456789,987654321",
    )

    assert settings.is_admin(123456789) is True
    assert settings.is_admin(987654321) is True
    assert settings.is_admin(111222333) is False


def test_settings_custom_database_url():
    """Test custom database URL."""
    settings = Settings(
        bot_token="test_token",
        encryption_key=VALID_FERNET_KEY,
        database_url="sqlite+aiosqlite:///./custom.db",
    )

    assert settings.database_url == "sqlite+aiosqlite:///./custom.db"


def test_settings_custom_log_level():
    """Test custom log level."""
    settings = Settings(
        bot_token="test_token",
        encryption_key=VALID_FERNET_KEY,
        log_level="DEBUG",
    )

    assert settings.log_level == "DEBUG"


def test_settings_custom_timeout():
    """Test custom timeout."""
    settings = Settings(
        bot_token="test_token",
        encryption_key=VALID_FERNET_KEY,
        xui_timeout=60,
    )

    assert settings.xui_timeout == 60


def test_encryption_key_valid_fernet_key_accepted():
    """A proper Fernet key must be accepted without error."""
    settings = Settings(
        bot_token="test_token",
        encryption_key=VALID_FERNET_KEY,
    )
    assert settings.encryption_key == VALID_FERNET_KEY


def test_encryption_key_invalid_raises_value_error():
    """An invalid key string must raise ValueError on Settings construction."""
    with pytest.raises(Exception) as exc_info:
        Settings(
            bot_token="test_token",
            encryption_key="not-a-key",
        )
    # pydantic wraps field errors in ValidationError, which chains the ValueError message
    assert "ENCRYPTION_KEY" in str(exc_info.value)
