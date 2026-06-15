"""Tests for XUIClient.login(): CSRF token, JSON→form fallback, 403 retry."""

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.xui_client.client import XUIClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_URL = "http://xui.example.com"

SUCCESS_BODY = {"success": True, "msg": "ok"}
FAIL_BODY = {"success": False, "msg": "bad credentials"}


def _make_client(*, two_factor_code: str | None = None) -> XUIClient:
    """Return an XUIClient with a fake session already attached."""
    client = XUIClient(
        BASE_URL,
        username="admin",
        password="secret",
        two_factor_code=two_factor_code,
    )
    session = MagicMock()
    session.closed = False
    session.cookie_jar = MagicMock()
    session.cookie_jar.__iter__ = MagicMock(return_value=iter([]))
    client._session = session
    return client


def _post_ctx(status: int, body: dict[str, Any]) -> Any:
    """Return an async context-manager that yields a fake response."""
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=body)
    resp.text = AsyncMock(return_value=str(body))
    resp.headers = {}
    resp.request_info = MagicMock()
    resp.request_info.headers = {}

    @asynccontextmanager
    async def _ctx(*args: Any, **kwargs: Any):
        yield resp

    return _ctx


# ---------------------------------------------------------------------------
# Test 1: login fetches a CSRF token before POSTing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_fetches_csrf_token():
    """login() calls _get_csrf_token when _csrf_token is None."""
    client = _make_client()

    csrf_fetched = False

    async def fake_get_csrf_token() -> str | None:
        nonlocal csrf_fetched
        csrf_fetched = True
        return "tok-login"

    client._get_csrf_token = fake_get_csrf_token  # type: ignore[method-assign]

    # Mock session.post to succeed
    client._session.post = _post_ctx(200, SUCCESS_BODY)

    result = await client.login()

    assert result is True
    assert csrf_fetched, "_get_csrf_token should have been called"


# ---------------------------------------------------------------------------
# Test 2: login sends X-CSRF-Token header on the POST
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_sends_csrf_header():
    """The login POST carries X-CSRF-Token equal to the fetched token."""
    client = _make_client()
    client._csrf_token = "pre-set-token"  # already have one — no fetch needed

    captured: dict[str, Any] = {}

    @asynccontextmanager
    async def fake_post(url: str, *, headers: Any = None, **kwargs: Any):
        captured["headers"] = headers or {}
        resp = MagicMock()
        resp.status = 200
        resp.json = AsyncMock(return_value=SUCCESS_BODY)
        resp.headers = {}
        resp.request_info = MagicMock()
        resp.request_info.headers = {}
        yield resp

    client._session.post = fake_post  # type: ignore[method-assign]

    await client.login()

    assert captured["headers"].get("X-CSRF-Token") == "pre-set-token"


# ---------------------------------------------------------------------------
# Test 3: JSON success path returns True and stores cookies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_json_success_stores_cookies():
    """Successful JSON login returns True and fills _cookies from the cookie jar."""
    client = _make_client()
    client._csrf_token = "tok"

    fake_cookie = MagicMock()
    fake_cookie.key = "session"
    fake_cookie.value = "abc123"
    client._session.cookie_jar.__iter__ = MagicMock(return_value=iter([fake_cookie]))

    client._session.post = _post_ctx(200, SUCCESS_BODY)

    result = await client.login()

    assert result is True
    assert client._cookies == {"session": "abc123"}


# ---------------------------------------------------------------------------
# Test 4: JSON failure triggers form-data fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_json_failure_falls_back_to_form():
    """XUIAuthError from JSON path causes login() to retry with form-data."""
    client = _make_client()
    client._csrf_token = "tok"

    post_call_kwargs: list[dict[str, Any]] = []

    @asynccontextmanager
    async def fake_post(url: str, **kwargs: Any):
        post_call_kwargs.append(dict(kwargs))
        # First call (json=) → 401 to trigger auth error; second call (data=) → 200
        if "json" in kwargs:
            resp = MagicMock()
            resp.status = 401
            resp.json = AsyncMock(return_value=FAIL_BODY)
            resp.headers = {}
            resp.request_info = MagicMock()
            resp.request_info.headers = {}
            yield resp
        else:
            resp = MagicMock()
            resp.status = 200
            resp.json = AsyncMock(return_value=SUCCESS_BODY)
            resp.headers = {}
            resp.request_info = MagicMock()
            resp.request_info.headers = {}
            yield resp

    client._session.post = fake_post  # type: ignore[method-assign]

    result = await client.login()

    assert result is True
    # First attempt used json=, second used data=
    assert any("json" in kw for kw in post_call_kwargs), "First POST should use json="
    assert any("data" in kw for kw in post_call_kwargs), "Fallback POST should use data="


# ---------------------------------------------------------------------------
# Test 5: twoFactorCode included in payload when set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_includes_two_factor_code():
    """When two_factor_code is set, twoFactorCode appears in the POST payload."""
    client = _make_client(two_factor_code="654321")
    client._csrf_token = "tok"

    captured_payload: dict[str, Any] = {}

    @asynccontextmanager
    async def fake_post(url: str, *, json: Any = None, data: Any = None, **kwargs: Any):
        captured_payload.update(json or data or {})
        resp = MagicMock()
        resp.status = 200
        resp.json = AsyncMock(return_value=SUCCESS_BODY)
        resp.headers = {}
        resp.request_info = MagicMock()
        resp.request_info.headers = {}
        yield resp

    client._session.post = fake_post  # type: ignore[method-assign]

    await client.login()

    assert captured_payload.get("twoFactorCode") == "654321"


# ---------------------------------------------------------------------------
# Test 6: 403 → CSRF token is refreshed and POST is retried once
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_403_refreshes_csrf_and_retries():
    """A 403 on the login POST causes _get_csrf_token() to be called again and the POST retried."""
    client = _make_client()

    csrf_fetch_count = 0

    async def fake_get_csrf_token() -> str | None:
        nonlocal csrf_fetch_count
        csrf_fetch_count += 1
        return f"tok-{csrf_fetch_count}"

    client._get_csrf_token = fake_get_csrf_token  # type: ignore[method-assign]

    post_attempt = 0

    @asynccontextmanager
    async def fake_post(url: str, **kwargs: Any):
        nonlocal post_attempt
        post_attempt += 1
        status = 403 if post_attempt == 1 else 200
        resp = MagicMock()
        resp.status = status
        resp.json = AsyncMock(return_value=SUCCESS_BODY)
        resp.headers = {}
        resp.request_info = MagicMock()
        resp.request_info.headers = {}
        yield resp

    client._session.post = fake_post  # type: ignore[method-assign]

    result = await client.login()

    assert result is True
    assert post_attempt == 2, f"Expected 2 POST attempts, got {post_attempt}"
    # Initial fetch + one refresh = 2 total
    assert csrf_fetch_count == 2, f"Expected 2 CSRF fetches (initial + refresh), got {csrf_fetch_count}"
