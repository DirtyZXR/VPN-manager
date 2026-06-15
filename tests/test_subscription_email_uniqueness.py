"""Test email uniqueness dedup logic in XUIProvider.add_client (proactive approach).

With the v3.1.0 /panel/api/clients/add endpoint, duplicate email does NOT produce
an error.  The provider now proactively checks existence via get_client_traffic()
before each add attempt:
  - non-None return → email taken, try next suffix
  - None return     → email free, proceed with add_client
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.vpn_providers.xui_provider import XUIProvider


def _make_inbound(xui_id: int = 5, internal_id: int = 1) -> SimpleNamespace:
    """Return a minimal Inbound stub that XUIProvider.add_client accesses."""
    return SimpleNamespace(id=internal_id, xui_id=xui_id)


def _make_subscription(
    name: str = "TestSub",
    client_name: str = "TestClient",
    telegram_id: int = 123456789,
    total_gb: int = 10,
    subscription_token: str = "tok_abc",
    expiry_date: datetime | None = None,
) -> SimpleNamespace:
    """Return a minimal Subscription stub."""
    if expiry_date is None:
        expiry_date = datetime.now(UTC) + timedelta(days=30)
    client = SimpleNamespace(name=client_name, telegram_id=telegram_id)
    return SimpleNamespace(
        name=name,
        client=client,
        total_gb=total_gb,
        subscription_token=subscription_token,
        expiry_date=expiry_date,
    )


def _make_provider_with_mock_client(
    get_traffic_side_effect,
    add_client_side_effect=None,
) -> tuple[XUIProvider, AsyncMock]:
    """
    Build an XUIProvider with a pre-injected mock XUIClient.

    *get_traffic_side_effect* is the side_effect for mock_client.get_client_traffic.
    *add_client_side_effect* is the side_effect for mock_client.add_client
      (defaults to None, i.e. always succeeds).
    Returns (provider, mock_client).
    """
    server = MagicMock()
    provider = XUIProvider(server)

    mock_client = AsyncMock()
    mock_client.get_client_traffic = AsyncMock(side_effect=get_traffic_side_effect)
    mock_client.add_client = AsyncMock(side_effect=add_client_side_effect)
    provider._client = mock_client

    return provider, mock_client


# ---------------------------------------------------------------------------
# Test 1 – success on first attempt (email is free)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_client_no_collision():
    """When the base email is free, add_client is called once with the unsuffixed email."""
    inbound = _make_inbound(xui_id=3)
    subscription = _make_subscription(name="Sub", client_name="Alice")

    # get_client_traffic is called twice for the chosen email:
    #   call 1 (pre-add existence check) → None (email free)
    #   call 2 (post-add real-uuid fetch) → dict with panel-assigned uuid
    traffic_calls: dict[str, int] = {}

    async def probe_side_effect(email: str):
        traffic_calls[email] = traffic_calls.get(email, 0) + 1
        if traffic_calls[email] == 1:
            # First call: existence check — email is free
            return None
        # Second call: post-add fetch — return panel-assigned uuid
        return {"uuid": "real-panel-uuid", "email": email}

    provider, mock_client = _make_provider_with_mock_client(
        get_traffic_side_effect=probe_side_effect
    )

    result = await provider.add_client(inbound, subscription, email="Alice-Sub")

    assert result["email"] == "Alice-Sub"
    assert result["uuid"] == "real-panel-uuid"
    assert result["xui_client_id"] == "real-panel-uuid"
    # Traffic probed twice: existence check + post-add uuid fetch
    assert mock_client.get_client_traffic.call_count == 2
    # add_client called exactly once
    mock_client.add_client.assert_called_once()
    # Verify the call used the new signature: (req, [xui_id])
    call_args = mock_client.add_client.call_args
    assert call_args[0][1] == [3]  # inbound_ids positional arg


# ---------------------------------------------------------------------------
# Test 2 – success after exactly 1 collision (suffix -1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_client_one_collision_then_success():
    """When the base email is taken, the provider retries with '-1' suffix."""
    inbound = _make_inbound(xui_id=3)
    subscription = _make_subscription(name="Sub", client_name="Alice")
    base_email = "Alice-Sub"
    chosen_email = f"{base_email}-1"

    # Per-email call counters: the chosen email (suffix -1) is called twice:
    #   call 1: pre-add existence check → None (free)
    #   call 2: post-add uuid fetch → dict with panel uuid
    traffic_calls: dict[str, int] = {}

    async def probe_side_effect(email: str):
        traffic_calls[email] = traffic_calls.get(email, 0) + 1
        if email == base_email:
            # Base email is always taken (only one call expected here)
            return {"uuid": "existing-uuid", "email": email}
        # Chosen (suffixed) email: free on first probe, panel data on second
        if traffic_calls[email] == 1:
            return None
        return {"uuid": "real-panel-uuid", "email": email}

    provider, mock_client = _make_provider_with_mock_client(
        get_traffic_side_effect=probe_side_effect
    )

    result = await provider.add_client(inbound, subscription, email=base_email)

    assert result["email"] == chosen_email
    assert result["uuid"] == "real-panel-uuid"
    assert result["xui_client_id"] == "real-panel-uuid"
    # Probed base (taken) + suffix-1 (free) + suffix-1 (post-add fetch) = 3 calls
    assert mock_client.get_client_traffic.call_count == 3
    mock_client.add_client.assert_called_once()


# ---------------------------------------------------------------------------
# Test 3 – success after multiple collisions (suffix -N)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_client_multiple_collisions_then_success():
    """After N taken emails the provider uses the '-N' suffix."""
    inbound = _make_inbound(xui_id=7)
    subscription = _make_subscription(name="MySub", client_name="Bob")
    base_email = "Bob-MySub"
    taken_count = 5  # base + suffixes 1..4 are taken; suffix-5 is free
    chosen_email = f"{base_email}-{taken_count}"

    # Per-email call counters: the chosen email (suffix-5) is called twice:
    #   call 1: pre-add existence check → None (free)
    #   call 2: post-add uuid fetch → dict with panel uuid
    traffic_calls: dict[str, int] = {}

    async def probe_side_effect(email: str):
        traffic_calls[email] = traffic_calls.get(email, 0) + 1
        # base → taken
        if email == base_email:
            return {"email": email}
        suffix = int(email.rsplit("-", 1)[-1])
        # suffixes 1..taken_count-1 are always taken
        if suffix < taken_count:
            return {"email": email}
        # The chosen email (suffix == taken_count): free on first call, panel data on second
        if traffic_calls[email] == 1:
            return None
        return {"uuid": "real-panel-uuid", "email": email}

    provider, mock_client = _make_provider_with_mock_client(
        get_traffic_side_effect=probe_side_effect
    )

    result = await provider.add_client(inbound, subscription, email=base_email)

    assert result["email"] == chosen_email
    assert result["uuid"] == "real-panel-uuid"
    assert result["xui_client_id"] == "real-panel-uuid"
    # Probed taken_count+1 times (pre-add: base + suffixes 1..taken_count)
    # plus 1 post-add fetch = taken_count + 2 total
    assert mock_client.get_client_traffic.call_count == taken_count + 2
    mock_client.add_client.assert_called_once()


# ---------------------------------------------------------------------------
# Test 4 – all 100 attempts exhausted → ValueError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_client_exhausts_all_attempts_raises_value_error():
    """When every candidate email is taken the provider raises ValueError."""
    inbound = _make_inbound(xui_id=2, internal_id=9)
    subscription = _make_subscription(name="ExhSub", client_name="Carol")
    base_email = "Carol-ExhSub"

    async def always_taken(email: str):
        return {"email": email, "uuid": "x"}

    provider, mock_client = _make_provider_with_mock_client(
        get_traffic_side_effect=always_taken
    )

    with pytest.raises(ValueError, match="Unable to find an email accepted by XUI panel"):
        await provider.add_client(inbound, subscription, email=base_email)

    # 100 probes (i=0..99), add_client never called
    assert mock_client.get_client_traffic.call_count == 100
    mock_client.add_client.assert_not_called()


# ---------------------------------------------------------------------------
# (kept skipped) integration smoke-test stub
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_inbound_creates_unique_email():
    """Placeholder kept for future integration test with a real XUI panel."""
    pytest.skip("Requires a running XUI panel — integration test only")
