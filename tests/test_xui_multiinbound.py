from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.vpn_providers.xui_provider import XUIProvider


def _inbound(xui_id, internal_id):
    return SimpleNamespace(id=internal_id, xui_id=xui_id, type="xui_inbound")


def _subscription():
    return SimpleNamespace(
        name="Sub",
        client=SimpleNamespace(name="Alice", telegram_id=111),
        total_gb=10,
        subscription_token="tok_multi",
        expiry_date=datetime.now(UTC) + timedelta(days=30),
    )


def _provider_with_client(get_traffic_side_effect):
    provider = XUIProvider(MagicMock())
    mock_client = AsyncMock()
    mock_client.get_client_traffic = AsyncMock(side_effect=get_traffic_side_effect)
    mock_client.add_client = AsyncMock(return_value=True)
    provider._client = mock_client
    return provider, mock_client


@pytest.mark.asyncio
async def test_add_client_to_inbounds_single_call_all_ids():
    """Один add на панель со ВСЕМИ xui_id и общим subId."""
    inbounds = [_inbound(3, 1), _inbound(5, 2), _inbound(7, 3)]
    sub = _subscription()

    async def probe(email):
        if probe.calls.get(email, 0) == 0:
            probe.calls[email] = 1
            return None
        return {"uuid": "panel-uuid", "email": email}
    probe.calls = {}

    provider, mock_client = _provider_with_client(probe)

    result = await provider.add_client_to_inbounds(inbounds, sub)

    mock_client.add_client.assert_called_once()
    req, inbound_ids = mock_client.add_client.call_args[0]
    assert inbound_ids == [3, 5, 7]
    assert req.subId == "tok_multi"
    assert result["uuid"] == "panel-uuid"
    assert result["email"]


@pytest.mark.asyncio
async def test_add_client_wrapper_maps_to_single_inbound_id():
    """add_client(inbound) делегирует в add_client_to_inbounds с одним xui_id."""
    sub = _subscription()

    async def probe(email):
        if probe.calls.get(email, 0) == 0:
            probe.calls[email] = 1
            return None
        return {"uuid": "panel-uuid", "email": email}
    probe.calls = {}

    provider, mock_client = _provider_with_client(probe)

    await provider.add_client(_inbound(9, 42), sub)

    mock_client.add_client.assert_called_once()
    _req, inbound_ids = mock_client.add_client.call_args[0]
    assert inbound_ids == [9]
