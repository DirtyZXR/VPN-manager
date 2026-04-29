"""Utility functions."""

import base64
import re
import secrets
import uuid as uuid_lib

from cryptography.fernet import Fernet

from app.config import get_settings


def encrypt_password(password: str) -> str:
    settings = get_settings()
    cipher = Fernet(settings.encryption_key.encode())
    return cipher.encrypt(password.encode()).decode()


def generate_uuid() -> str:
    return str(uuid_lib.uuid4())


def generate_subscription_token() -> str:
    return secrets.token_urlsafe(12)


def generate_email(prefix: str, server_name: str, group_name: str) -> str:
    clean_prefix = prefix.lower().replace(" ", "_").replace("@", "_at_")
    clean_server = server_name.lower().replace(" ", "_")
    clean_group = group_name.lower().replace(" ", "_")
    unique_suffix = str(uuid_lib.uuid4())[:8]
    return f"{clean_prefix}_{clean_server}_{clean_group}_{unique_suffix}@vpn"


def extract_mtproxy_domain(secret: str) -> str | None:
    import contextlib

    raw = None
    with contextlib.suppress(Exception):
        raw = base64.b64decode(secret + "==")
    if raw is None:
        with contextlib.suppress(Exception):
            raw = bytes.fromhex(secret)
    if raw is None:
        return None
    text = ""
    for i in range(len(raw) - 1, -1, -1):
        c = chr(raw[i])
        if c.isascii() and bool(re.match(r"[a-z0-9.\-]", c)):
            text = c + text
        else:
            break
    if "." in text and len(text) > 3:
        return text
    return None
