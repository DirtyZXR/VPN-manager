"""Utility functions."""

import secrets
import uuid as uuid_lib


def generate_uuid() -> str:
    """Generate a random UUID v4."""
    return str(uuid_lib.uuid4())


def generate_subscription_token() -> str:
    """Generate a random subscription token (16 chars)."""
    return secrets.token_urlsafe(12)


def generate_email(prefix: str, server_name: str, group_name: str) -> str:
    """Generate unique email for XUI client.

    Args:
        prefix: User identifier (e.g., username or id)
        server_name: Server name
        group_name: Subscription group name

    Returns:
        Email string like "prefix_server_group_uuid@vpn"
    """
    # Clean up names for email
    clean_prefix = prefix.lower().replace(" ", "_").replace("@", "_at_")
    clean_server = server_name.lower().replace(" ", "_")
    clean_group = group_name.lower().replace(" ", "_")

    # Add UUID for uniqueness
    unique_suffix = str(uuid_lib.uuid4())[:8]

    return f"{clean_prefix}_{clean_server}_{clean_group}_{unique_suffix}@vpn"
