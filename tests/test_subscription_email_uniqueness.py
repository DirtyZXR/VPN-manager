"""Test email uniqueness dedup logic in XUIProvider.add_client."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.vpn_providers.xui_provider import XUIProvider
from app.xui_client import XUIError


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


def _make_provider_with_mock_client(mock_add_client_coro) -> tuple[XUIProvider, AsyncMock]:
    """
    Build an XUIProvider with a pre-injected mock XUIClient.

    *mock_add_client_coro* is the side_effect for mock_client.add_client.
    Returns (provider, mock_client).
    """
    server = MagicMock()
    provider = XUIProvider(server)

    mock_client = AsyncMock()
    mock_client.add_client = AsyncMock(side_effect=mock_add_client_coro)
    # Inject directly so _get_client() is never called (avoids real network / encryption)
    provider._client = mock_client

    return provider, mock_client


# ---------------------------------------------------------------------------
# Test 1 – success on first attempt (no duplicate at all)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_client_no_collision():
    """When XUI accepts the email on the first call, the returned email has no suffix."""
    inbound = _make_inbound(xui_id=3)
    subscription = _make_subscription(name="Sub", client_name="Alice")

    provider, mock_client = _make_provider_with_mock_client(None)
    # add_client succeeds immediately (returns None by default for AsyncMock)

    result = await provider.add_client(inbound, subscription, email="Alice-Sub")

    assert result["email"] == "Alice-Sub"
    mock_client.add_client.assert_called_once()


# ---------------------------------------------------------------------------
# Test 2 – success after exactly 1 duplicate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_client_one_duplicate_then_success():
    """When the first call raises a duplicate-email XUIError the provider retries with '-1' suffix."""
    inbound = _make_inbound(xui_id=3)
    subscription = _make_subscription(name="Sub", client_name="Alice")
    base_email = "Alice-Sub"

    call_count = 0

    async def side_effect(x_id, req):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise XUIError("Failed to add client: duplicate email")
        # second call succeeds

    provider, mock_client = _make_provider_with_mock_client(side_effect)

    result = await provider.add_client(inbound, subscription, email=base_email)

    assert result["email"] == f"{base_email}-1"
    assert mock_client.add_client.call_count == 2


# ---------------------------------------------------------------------------
# Test 3 – success after multiple duplicates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_client_multiple_duplicates_then_success():
    """After N duplicate errors the provider accepts the email with '-N' suffix."""
    inbound = _make_inbound(xui_id=7)
    subscription = _make_subscription(name="MySub", client_name="Bob")
    base_email = "Bob-MySub"
    fail_times = 5

    call_count = 0

    async def side_effect(x_id, req):
        nonlocal call_count
        call_count += 1
        if call_count <= fail_times:
            raise XUIError("duplicate email detected")
        # succeeds on attempt fail_times+1

    provider, mock_client = _make_provider_with_mock_client(side_effect)

    result = await provider.add_client(inbound, subscription, email=base_email)

    assert result["email"] == f"{base_email}-{fail_times}"
    assert mock_client.add_client.call_count == fail_times + 1


# ---------------------------------------------------------------------------
# Test 4 – all 100 attempts exhausted → ValueError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_client_exhausts_all_attempts_raises_value_error():
    """When every attempt raises a duplicate-email error the provider raises ValueError."""
    inbound = _make_inbound(xui_id=2, internal_id=9)
    subscription = _make_subscription(name="ExhSub", client_name="Carol")
    base_email = "Carol-ExhSub"

    async def always_duplicate(x_id, req):
        raise XUIError("duplicate email conflict")

    provider, mock_client = _make_provider_with_mock_client(always_duplicate)

    with pytest.raises(ValueError, match="Unable to find an email accepted by XUI panel"):
        await provider.add_client(inbound, subscription, email=base_email)

    # The loop runs exactly 100 times
    assert mock_client.add_client.call_count == 100


# ---------------------------------------------------------------------------
# (kept skipped) integration smoke-test stub
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_inbound_creates_unique_email():
    """Placeholder kept for future integration test with a real XUI panel."""
    pytest.skip("Requires a running XUI panel — integration test only")
