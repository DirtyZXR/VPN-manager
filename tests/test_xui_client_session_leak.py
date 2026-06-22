"""Регресс: XUIClient.connect() не оставляет незакрытых aiohttp-сессий.

1) Повторный connect() закрывает прежнюю сессию (идемпотентность).
2) Ошибка после создания сессии (проверка токена/cookie/логин) закрывает сессию,
   а не оставляет её утекать ("Unclosed client session").
"""

from unittest.mock import AsyncMock

import pytest

from app.xui_client.client import XUIClient


class _FakeSession:
    """Минимальная замена aiohttp.ClientSession для отслеживания close()."""

    created: list["_FakeSession"] = []

    def __init__(self, *args, **kwargs):
        self.closed = False
        _FakeSession.created.append(self)

    async def close(self):
        self.closed = True


@pytest.fixture
def _patch_aiohttp(monkeypatch):
    _FakeSession.created = []
    monkeypatch.setattr("aiohttp.ClientSession", _FakeSession)
    monkeypatch.setattr("aiohttp.TCPConnector", lambda **k: object())
    monkeypatch.setattr("aiohttp.CookieJar", lambda **k: object())


@pytest.mark.asyncio
async def test_reconnect_closes_previous_session(_patch_aiohttp, monkeypatch):
    client = XUIClient(base_url="http://x", api_token="t", verify_ssl=True)
    monkeypatch.setattr(client, "_test_bearer_token", AsyncMock(return_value=True))

    await client.connect()
    first = client._session
    assert first in _FakeSession.created
    assert first.closed is False

    await client.connect()  # повторный connect()
    assert first.closed is True, "прежняя сессия должна быть закрыта"
    assert client._session is not first


@pytest.mark.asyncio
async def test_connect_closes_session_on_failure(_patch_aiohttp, monkeypatch):
    client = XUIClient(base_url="http://x", api_token="t", verify_ssl=True)
    # Проверка токена падает — сессия уже создана и должна быть закрыта.
    monkeypatch.setattr(
        client, "_test_bearer_token", AsyncMock(side_effect=RuntimeError("boom"))
    )

    with pytest.raises(RuntimeError):
        await client.connect()

    assert _FakeSession.created, "сессия должна была создаться"
    assert _FakeSession.created[-1].closed is True, "сессия должна быть закрыта при ошибке"
