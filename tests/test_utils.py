"""Tests for utility functions."""

from app.utils import generate_email, generate_subscription_token, generate_uuid


def test_generate_uuid():
    """Test UUID generation."""
    uuid = generate_uuid()

    assert isinstance(uuid, str)
    assert len(uuid) == 36  # UUID v4 format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx


def test_generate_subscription_token():
    """Test subscription token generation."""
    token = generate_subscription_token()

    assert isinstance(token, str)
    assert 12 <= len(token) <= 20  # token_urlsafe(12) produces ~16 chars


def test_generate_email():
    """Test email generation."""
    email = generate_email("John Doe", "Server-1", "Main Group")

    assert isinstance(email, str)
    assert "@vpn" in email
    assert "john_doe" in email.lower()
    assert "server_1" in email.lower().replace("-", "_")  # Replace - with _ for comparison
    assert "main_group" in email.lower()
    # Check for UUID suffix for uniqueness (last part after @)
    email_parts = email.split("@")
    assert len(email_parts) == 2
    uuid_part = email_parts[0].split("_")[-1]
    assert len(uuid_part) == 8  # UUID should be 8 chars


def test_generate_email_special_chars():
    """Test email generation with special characters."""
    email = generate_email("User@Email", "Server Name", "Group Name")

    assert "@vpn" in email
    assert "@" not in email.split("@")[0]  # @ in prefix should be replaced
    assert "user_at_email" in email.lower()
    assert "server_name" in email.lower()
