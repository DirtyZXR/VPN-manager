"""Tests for XUIClient CSRF token behaviour (cookie-based POST requests)."""

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.xui_client.client import XUIClient
from app.xui_client.exceptions import XUIAuthError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_URL = "http://xui.example.com"


def _make_response(status: int, json_body: dict[str, Any]) -> MagicMock:
    """Build a fake aiohttp response context-manager."""
    response = MagicMock()
    response.status = status
    response.json = AsyncMock(return_value=json_body)
    response.text = AsyncMock(return_value=str(json_body))
    response.headers = {}
    response.request_info = MagicMock()
    response.request_info.headers = {}

    @asynccontextmanager
    async def _ctx(*args: Any, **kwargs: Any):
        yield response

    return _ctx


def _make_client(*, api_token: str | None = None) -> XUIClient:
    """Create an XUIClient with a fake session already attached."""
    client = XUIClient(BASE_URL, username="admin", password="secret", api_token=api_token)

    # Attach a real-looking mock session
    session = MagicMock()
    session.closed = False
    session.cookie_jar = MagicMock()
    session.cookie_jar.__iter__ = MagicMock(return_value=iter([]))
    client._session = session
    return client


# ---------------------------------------------------------------------------
# Test 1: Cookie path — first POST fetches CSRF and sends X-CSRF-Token header
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cookie_post_fetches_csrf_token():
    """Cookie-based POST: GET /csrf-token is called and X-CSRF-Token header is set."""
    client = _make_client(api_token=None)

    csrf_response = _make_response(200, {"success": True, "obj": "tok-abc"})
    post_response = _make_response(200, {"success": True, "obj": {}})

    call_log: list[tuple[str, str]] = []

    @asynccontextmanager
    async def fake_request(method: str, url: str, **kwargs: Any):
        call_log.append((method, url))
        if method == "GET" and url.endswith("/csrf-token"):
            async with csrf_response(method, url) as r:
                yield r
        else:
            async with post_response(method, url) as r:
                yield r

    client._session.request = fake_request  # type: ignore[assignment]
    result = await client._request("POST", "/panel/api/inbounds/addClient", json={})

    assert result == {"success": True, "obj": {}}

    methods_and_paths = [(m, u.split(BASE_URL)[-1]) for m, u in call_log]
    assert ("GET", "/csrf-token") in methods_and_paths, f"csrf-token GET not seen in {methods_and_paths}"
    assert ("POST", "/panel/api/inbounds/addClient") in methods_and_paths


@pytest.mark.asyncio
async def test_cookie_post_sends_csrf_header():
    """Cookie-based POST: the actual POST carries the X-CSRF-Token header."""
    client = _make_client(api_token=None)

    csrf_response = _make_response(200, {"success": True, "obj": "MY-CSRF-TOKEN"})
    post_response = _make_response(200, {"success": True, "obj": {}})

    captured_headers: dict[str, str] = {}

    @asynccontextmanager
    async def fake_request(method: str, url: str, **kwargs: Any):
        if method == "GET" and url.endswith("/csrf-token"):
            async with csrf_response(method, url) as r:
                yield r
        else:
            captured_headers.update(kwargs.get("headers") or {})
            async with post_response(method, url) as r:
                yield r

    client._session.request = fake_request  # type: ignore[assignment]

    await client._request("POST", "/panel/api/inbounds/addClient", json={})

    assert captured_headers.get("X-CSRF-Token") == "MY-CSRF-TOKEN"


# ---------------------------------------------------------------------------
# Test 2: Bearer path — no CSRF call and no X-CSRF-Token header
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bearer_post_skips_csrf():
    """Bearer-token POST: /csrf-token is NOT fetched and X-CSRF-Token is NOT sent."""
    client = _make_client(api_token="bearer-secret")

    post_response = _make_response(200, {"success": True, "obj": {}})
    call_log: list[tuple[str, str]] = []
    captured_headers: dict[str, str] = {}

    @asynccontextmanager
    async def fake_request(method: str, url: str, **kwargs: Any):
        call_log.append((method, url))
        captured_headers.update(kwargs.get("headers") or {})
        async with post_response(method, url) as r:
            yield r

    client._session.request = fake_request  # type: ignore[assignment]

    await client._request("POST", "/panel/api/inbounds/addClient", json={})

    urls = [u for _, u in call_log]
    assert not any("/csrf-token" in u for u in urls), "Should not call /csrf-token with Bearer"
    assert "X-CSRF-Token" not in captured_headers


# ---------------------------------------------------------------------------
# Test 3: GET request with cookie path — no CSRF call, no X-CSRF-Token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cookie_get_skips_csrf():
    """Cookie-based GET: CSRF is NOT involved (only unsafe methods need it)."""
    client = _make_client(api_token=None)

    get_response = _make_response(200, {"success": True, "obj": []})
    call_log: list[tuple[str, str]] = []

    @asynccontextmanager
    async def fake_request(method: str, url: str, **kwargs: Any):
        call_log.append((method, url))
        async with get_response(method, url) as r:
            yield r

    client._session.request = fake_request  # type: ignore[assignment]

    await client._request("GET", "/panel/api/inbounds/list")

    urls = [u for _, u in call_log]
    assert not any("/csrf-token" in u for u in urls), "GET should not trigger csrf-token fetch"


# ---------------------------------------------------------------------------
# Test 4: 403 on cookie POST → refresh token, retry once; second attempt succeeds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cookie_post_403_refreshes_token_and_retries():
    """On 403, CSRF token is refreshed and the POST is retried once successfully."""
    client = _make_client(api_token=None)

    csrf_call_count = 0
    post_call_count = 0

    @asynccontextmanager
    async def fake_request(method: str, url: str, **kwargs: Any):
        nonlocal csrf_call_count, post_call_count
        if method == "GET" and url.endswith("/csrf-token"):
            csrf_call_count += 1
            token = f"fresh-tok-{csrf_call_count}"
            resp = MagicMock()
            resp.status = 200
            resp.json = AsyncMock(return_value={"success": True, "obj": token})
            resp.text = AsyncMock(return_value="")
            resp.headers = {}
            resp.request_info = MagicMock()
            resp.request_info.headers = {}
            yield resp
        else:
            post_call_count += 1
            status = 403 if post_call_count == 1 else 200
            resp = MagicMock()
            resp.status = status
            resp.json = AsyncMock(return_value={"success": True, "obj": {}})
            resp.text = AsyncMock(return_value="forbidden")
            resp.headers = {}
            resp.request_info = MagicMock()
            resp.request_info.headers = {}
            yield resp

    client._session.request = fake_request  # type: ignore[assignment]

    result = await client._request("POST", "/panel/api/inbounds/addClient", json={})

    assert result == {"success": True, "obj": {}}
    assert csrf_call_count == 2, f"Expected 2 CSRF fetches (initial + refresh), got {csrf_call_count}"
    assert post_call_count == 2, f"Expected 2 POST attempts (original + retry), got {post_call_count}"


# ---------------------------------------------------------------------------
# Test 5: 403 on cookie POST twice → XUIAuthError raised
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cookie_post_403_twice_raises_auth_error():
    """On persistent 403 (after token refresh), XUIAuthError is raised."""
    client = _make_client(api_token=None)

    @asynccontextmanager
    async def fake_request(method: str, url: str, **kwargs: Any):
        if method == "GET" and url.endswith("/csrf-token"):
            resp = MagicMock()
            resp.status = 200
            resp.json = AsyncMock(return_value={"success": True, "obj": "some-token"})
            resp.text = AsyncMock(return_value="")
            resp.headers = {}
            resp.request_info = MagicMock()
            resp.request_info.headers = {}
            yield resp
        else:
            resp = MagicMock()
            resp.status = 403
            resp.json = AsyncMock(return_value={"success": False})
            resp.text = AsyncMock(return_value="forbidden")
            resp.headers = {}
            resp.request_info = MagicMock()
            resp.request_info.headers = {}
            yield resp

    client._session.request = fake_request  # type: ignore[assignment]

    with pytest.raises(XUIAuthError):
        await client._request("POST", "/panel/api/inbounds/addClient", json={})


# ---------------------------------------------------------------------------
# Test 6: CSRF token is cached — second POST does NOT re-fetch /csrf-token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_csrf_token_is_cached_between_requests():
    """Cookie-based: /csrf-token is only fetched once across multiple POSTs."""
    client = _make_client(api_token=None)

    csrf_call_count = 0

    @asynccontextmanager
    async def fake_request(method: str, url: str, **kwargs: Any):
        nonlocal csrf_call_count
        if method == "GET" and url.endswith("/csrf-token"):
            csrf_call_count += 1
            resp = MagicMock()
            resp.status = 200
            resp.json = AsyncMock(return_value={"success": True, "obj": "cached-token"})
            resp.text = AsyncMock(return_value="")
            resp.headers = {}
            resp.request_info = MagicMock()
            resp.request_info.headers = {}
            yield resp
        else:
            resp = MagicMock()
            resp.status = 200
            resp.json = AsyncMock(return_value={"success": True, "obj": {}})
            resp.text = AsyncMock(return_value="")
            resp.headers = {}
            resp.request_info = MagicMock()
            resp.request_info.headers = {}
            yield resp

    client._session.request = fake_request  # type: ignore[assignment]

    await client._request("POST", "/panel/api/inbounds/addClient", json={})
    await client._request("POST", "/panel/api/inbounds/addClient", json={})

    assert csrf_call_count == 1, f"CSRF token should be fetched once and cached; got {csrf_call_count} fetches"
