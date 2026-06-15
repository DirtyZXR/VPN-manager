"""Tests for XUIClient v3.1.0 client CRUD methods (/panel/api/clients/...)."""

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.xui_client.client import XUIClient
from app.xui_client.exceptions import XUIError
from app.xui_client.models import XUIAddClientRequest

# ---------------------------------------------------------------------------
# Helpers (mirrors test_xui_client_csrf.py conventions)
# ---------------------------------------------------------------------------

BASE_URL = "http://xui.example.com"

_CLIENT_UUID = "11111111-2222-3333-4444-555555555555"
_CLIENT_EMAIL = "sub-alice"


def _make_response(status: int, json_body: dict[str, Any]) -> Any:
    """Build a fake aiohttp response usable as a context manager."""
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


def _make_client(*, api_token: str | None = "tok") -> XUIClient:
    """Return an XUIClient with a pre-attached mock session (Bearer, so no CSRF noise)."""
    client = XUIClient(BASE_URL, username="admin", password="secret", api_token=api_token)
    session = MagicMock()
    session.closed = False
    session.cookie_jar = MagicMock()
    session.cookie_jar.__iter__ = MagicMock(return_value=iter([]))
    client._session = session
    return client


def _make_req(**overrides: Any) -> XUIAddClientRequest:
    defaults: dict[str, Any] = {
        "id": _CLIENT_UUID,
        "email": _CLIENT_EMAIL,
        "enable": True,
        "flow": "xtls-rprx-vision",
        "totalGB": 10 * 1024**3,
        "expiryTime": 0,
        "subId": "sub_token",
        "tgId": 0,
    }
    defaults.update(overrides)
    return XUIAddClientRequest(**defaults)


def _simple_fake(method_url_to_body: dict[tuple[str, str], dict]) -> Any:
    """
    Build a fake ``session.request`` that dispatches on (METHOD, path-suffix).
    Unrecognised calls return 200 success.
    """

    @asynccontextmanager
    async def fake_request(method: str, url: str, **kwargs: Any):
        for (m, suffix), body in method_url_to_body.items():
            if method == m and url.endswith(suffix):
                resp = MagicMock()
                resp.status = 200
                resp.json = AsyncMock(return_value=body)
                resp.text = AsyncMock(return_value=str(body))
                resp.headers = {}
                resp.request_info = MagicMock()
                resp.request_info.headers = {}
                yield resp
                return
        # fallback success
        resp = MagicMock()
        resp.status = 200
        resp.json = AsyncMock(return_value={"success": True, "obj": None, "msg": ""})
        resp.text = AsyncMock(return_value="")
        resp.headers = {}
        resp.request_info = MagicMock()
        resp.request_info.headers = {}
        yield resp

    return fake_request


# ---------------------------------------------------------------------------
# add_client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_client_correct_url_and_body():
    """add_client POSTs to /panel/api/clients/add with client+inboundIds body."""
    xui = _make_client()
    req = _make_req()

    captured: dict[str, Any] = {}

    @asynccontextmanager
    async def fake_request(method: str, url: str, **kwargs: Any):
        captured["method"] = method
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        resp = MagicMock()
        resp.status = 200
        resp.json = AsyncMock(return_value={"success": True, "obj": None, "msg": "added"})
        resp.text = AsyncMock(return_value="")
        resp.headers = {}
        resp.request_info = MagicMock()
        resp.request_info.headers = {}
        yield resp

    xui._session.request = fake_request

    result = await xui.add_client(req, [5, 7])

    assert result is True
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/panel/api/clients/add")
    body = captured["json"]
    assert body["inboundIds"] == [5, 7]
    assert body["client"]["email"] == _CLIENT_EMAIL
    assert body["client"]["id"] == _CLIENT_UUID
    # camelCase fields must be present (by_alias=True)
    assert "totalGB" in body["client"]
    assert "expiryTime" in body["client"]
    assert "subId" in body["client"]


@pytest.mark.asyncio
async def test_add_client_raises_on_failure():
    """add_client raises XUIError when success=False."""
    xui = _make_client()
    req = _make_req()

    xui._session.request = _simple_fake(
        {("POST", "/panel/api/clients/add"): {"success": False, "msg": "panel error", "obj": None}}
    )

    with pytest.raises(XUIError, match="panel error"):
        await xui.add_client(req, [3])


# ---------------------------------------------------------------------------
# update_client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_client_url_and_body():
    """update_client POSTs to /panel/api/clients/update/{email} with full client body."""
    xui = _make_client()
    req = _make_req()

    captured: dict[str, Any] = {}

    @asynccontextmanager
    async def fake_request(method: str, url: str, **kwargs: Any):
        captured["method"] = method
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        resp = MagicMock()
        resp.status = 200
        resp.json = AsyncMock(return_value={"success": True, "obj": None, "msg": "updated"})
        resp.text = AsyncMock(return_value="")
        resp.headers = {}
        resp.request_info = MagicMock()
        resp.request_info.headers = {}
        yield resp

    xui._session.request = fake_request

    result = await xui.update_client(_CLIENT_EMAIL, req)

    assert result is True
    assert captured["method"] == "POST"
    assert captured["url"].endswith(f"/panel/api/clients/update/{_CLIENT_EMAIL}")
    body = captured["json"]
    assert body["email"] == _CLIENT_EMAIL
    assert body["id"] == _CLIENT_UUID
    assert "totalGB" in body


# ---------------------------------------------------------------------------
# delete_client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_client_url():
    """delete_client POSTs to /panel/api/clients/del/{email} without extra params."""
    xui = _make_client()
    captured: dict[str, Any] = {}

    @asynccontextmanager
    async def fake_request(method: str, url: str, **kwargs: Any):
        captured["method"] = method
        captured["url"] = url
        captured["params"] = kwargs.get("params")
        resp = MagicMock()
        resp.status = 200
        resp.json = AsyncMock(return_value={"success": True, "obj": None, "msg": "deleted"})
        resp.text = AsyncMock(return_value="")
        resp.headers = {}
        resp.request_info = MagicMock()
        resp.request_info.headers = {}
        yield resp

    xui._session.request = fake_request

    result = await xui.delete_client(_CLIENT_EMAIL)

    assert result is True
    assert captured["method"] == "POST"
    assert captured["url"].endswith(f"/panel/api/clients/del/{_CLIENT_EMAIL}")
    assert captured["params"] is None


@pytest.mark.asyncio
async def test_delete_client_keep_traffic_param():
    """delete_client passes keepTraffic=1 query param when keep_traffic=True."""
    xui = _make_client()
    captured: dict[str, Any] = {}

    @asynccontextmanager
    async def fake_request(method: str, url: str, **kwargs: Any):
        captured["params"] = kwargs.get("params")
        resp = MagicMock()
        resp.status = 200
        resp.json = AsyncMock(return_value={"success": True, "obj": None, "msg": "deleted"})
        resp.text = AsyncMock(return_value="")
        resp.headers = {}
        resp.request_info = MagicMock()
        resp.request_info.headers = {}
        yield resp

    xui._session.request = fake_request

    await xui.delete_client(_CLIENT_EMAIL, keep_traffic=True)

    assert captured["params"] == {"keepTraffic": 1}


# ---------------------------------------------------------------------------
# get_client_traffic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_client_traffic_url_and_return():
    """get_client_traffic GETs /panel/api/clients/traffic/{email} and returns obj."""
    xui = _make_client()
    traffic_obj = {
        "id": 42,
        "email": _CLIENT_EMAIL,
        "uuid": _CLIENT_UUID,
        "up": 1024,
        "down": 2048,
        "total": 0,
        "expiryTime": 0,
    }
    captured: dict[str, Any] = {}

    @asynccontextmanager
    async def fake_request(method: str, url: str, **kwargs: Any):
        captured["method"] = method
        captured["url"] = url
        resp = MagicMock()
        resp.status = 200
        resp.json = AsyncMock(return_value={"success": True, "obj": traffic_obj, "msg": ""})
        resp.text = AsyncMock(return_value="")
        resp.headers = {}
        resp.request_info = MagicMock()
        resp.request_info.headers = {}
        yield resp

    xui._session.request = fake_request

    result = await xui.get_client_traffic(_CLIENT_EMAIL)

    assert result == traffic_obj
    assert captured["method"] == "GET"
    assert captured["url"].endswith(f"/panel/api/clients/traffic/{_CLIENT_EMAIL}")


@pytest.mark.asyncio
async def test_get_client_traffic_returns_none_on_failure():
    """get_client_traffic returns None when success=False."""
    xui = _make_client()

    xui._session.request = _simple_fake(
        {("GET", f"/panel/api/clients/traffic/{_CLIENT_EMAIL}"): {"success": False, "obj": None, "msg": "not found"}}
    )

    result = await xui.get_client_traffic(_CLIENT_EMAIL)
    assert result is None


# ---------------------------------------------------------------------------
# get_clients (panel-wide list)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_clients_url_and_return():
    """get_clients GETs /panel/api/clients/list and returns obj list."""
    xui = _make_client()
    panel_clients = [
        {"id": 1, "uuid": _CLIENT_UUID, "email": _CLIENT_EMAIL, "inboundIds": [5]},
        {"id": 2, "uuid": "aaaa-bbbb", "email": "other", "inboundIds": [3]},
    ]
    captured: dict[str, Any] = {}

    @asynccontextmanager
    async def fake_request(method: str, url: str, **kwargs: Any):
        captured["method"] = method
        captured["url"] = url
        resp = MagicMock()
        resp.status = 200
        resp.json = AsyncMock(return_value={"success": True, "obj": panel_clients, "msg": ""})
        resp.text = AsyncMock(return_value="")
        resp.headers = {}
        resp.request_info = MagicMock()
        resp.request_info.headers = {}
        yield resp

    xui._session.request = fake_request

    result = await xui.get_clients()

    assert result == panel_clients
    assert captured["method"] == "GET"
    assert captured["url"].endswith("/panel/api/clients/list")


@pytest.mark.asyncio
async def test_get_clients_returns_empty_on_failure():
    """get_clients returns [] when success=False."""
    xui = _make_client()

    xui._session.request = _simple_fake(
        {("GET", "/panel/api/clients/list"): {"success": False, "obj": None, "msg": "err"}}
    )

    result = await xui.get_clients()
    assert result == []


# ---------------------------------------------------------------------------
# reset_client_traffic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_client_traffic_url():
    """reset_client_traffic POSTs to /panel/api/clients/resetTraffic/{email}."""
    xui = _make_client()
    captured: dict[str, Any] = {}

    @asynccontextmanager
    async def fake_request(method: str, url: str, **kwargs: Any):
        captured["method"] = method
        captured["url"] = url
        resp = MagicMock()
        resp.status = 200
        resp.json = AsyncMock(return_value={"success": True, "obj": None, "msg": "reset"})
        resp.text = AsyncMock(return_value="")
        resp.headers = {}
        resp.request_info = MagicMock()
        resp.request_info.headers = {}
        yield resp

    xui._session.request = fake_request

    result = await xui.reset_client_traffic(_CLIENT_EMAIL)

    assert result is True
    assert captured["method"] == "POST"
    assert captured["url"].endswith(f"/panel/api/clients/resetTraffic/{_CLIENT_EMAIL}")


@pytest.mark.asyncio
async def test_reset_client_traffic_raises_on_failure():
    """reset_client_traffic raises XUIError on success=False."""
    xui = _make_client()

    xui._session.request = _simple_fake(
        {("POST", f"/panel/api/clients/resetTraffic/{_CLIENT_EMAIL}"): {"success": False, "msg": "oops", "obj": None}}
    )

    with pytest.raises(XUIError, match="oops"):
        await xui.reset_client_traffic(_CLIENT_EMAIL)
