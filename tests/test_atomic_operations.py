"""Tests for atomic saga operations in add/remove_inbound_to_subscription."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.xui_client.exceptions import XUIError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_inbound(inbound_type: str = "xui_inbound") -> MagicMock:
    inbound = MagicMock()
    inbound.id = 10
    inbound.type = inbound_type
    inbound.xui_id = 10
    server = MagicMock()
    server.id = 1
    inbound.server = server
    return inbound


def _make_subscription() -> MagicMock:
    sub = MagicMock()
    sub.id = 5
    sub.name = "TestSub"
    sub.total_gb = 0
    sub.expiry_date = None
    sub.subscription_token = "tok123"
    client = MagicMock()
    client.name = "Alice"
    client.telegram_id = 0
    sub.client = client
    return sub


def _make_connection(inbound_type: str = "xui_inbound") -> MagicMock:
    conn = MagicMock()
    conn.id = 99
    conn.inbound_id = 10
    conn.subscription_id = 5
    conn.email = "alice@test"
    conn.uuid = "uuid-abc"
    conn.public_key = "pubkey-abc"
    conn.secret = "secret-abc"
    conn.provider_payload = {"email": "alice@test", "uuid": "uuid-abc"}
    conn.sync_status = "synced"
    conn.is_enabled = True
    return conn


def _make_service(session: MagicMock):
    from app.services.new_subscription_service import NewSubscriptionService

    svc = NewSubscriptionService.__new__(NewSubscriptionService)
    svc.session = session
    svc._providers = {}
    return svc


# ---------------------------------------------------------------------------
# add_inbound_to_subscription tests
# ---------------------------------------------------------------------------


class TestAddInboundAtomicity:
    """Saga compensation in add_inbound_to_subscription."""

    def _mock_session_for_add(self, flush_side_effect=None):
        """Return a session mock wired for the add-inbound flow.

        The session's execute is called several times:
          1. duplicate-check query → returns nothing
          2. get_subscription reload → returns subscription
          3. inbound query → returns inbound

        We keep it simple: every scalar_one_or_none() returns the right value
        by calling side_effect in sequence.
        """
        session = MagicMock()

        inbound = _make_inbound("xui_inbound")
        subscription = _make_subscription()

        # execute().scalar_one_or_none() chain
        no_result = MagicMock()
        no_result.scalar_one_or_none.return_value = None
        sub_result = MagicMock()
        sub_result.scalar_one_or_none.return_value = subscription
        sub_scalars = MagicMock()
        sub_scalars.scalar_one_or_none.return_value = subscription
        inbound_result = MagicMock()
        inbound_result.scalar_one_or_none.return_value = inbound

        execute_results = [
            no_result,       # duplicate check
            sub_result,      # get_subscription (called inside the method)
            sub_scalars,     # second get_subscription (reload)
            inbound_result,  # inbound query
        ]
        call_count = [0]

        async def fake_execute(*args, **kwargs):
            idx = call_count[0]
            call_count[0] += 1
            if idx < len(execute_results):
                return execute_results[idx]
            return no_result

        session.execute = fake_execute

        # begin_nested returns an async context manager
        nested_cm = MagicMock()
        nested_cm.__aenter__ = AsyncMock(return_value=None)
        nested_cm.__aexit__ = AsyncMock(return_value=False)
        session.begin_nested = MagicMock(return_value=nested_cm)

        session.add = MagicMock()

        if flush_side_effect is not None:
            # The only flush inside add_inbound_to_subscription (inside begin_nested)
            # should raise immediately.  Any previous flush calls would come from
            # other code paths that don't apply here.
            session.flush = AsyncMock(side_effect=flush_side_effect)
        else:
            session.flush = AsyncMock()

        return session, inbound, subscription

    @pytest.mark.asyncio
    async def test_db_fail_triggers_compensation(self):
        """add_client succeeds, DB flush raises → remove_client called (compensation)."""
        db_exc = Exception("DB constraint violated")
        session, inbound, subscription = self._mock_session_for_add(
            flush_side_effect=db_exc
        )

        svc = _make_service(session)

        provider = AsyncMock()
        provider.add_client = AsyncMock(
            return_value={"uuid": "u1", "email": "alice@test", "xui_client_id": "u1"}
        )
        provider.remove_client = AsyncMock(return_value=True)

        svc._providers[(1, "xui_inbound")] = provider

        with patch.object(svc, "_get_provider", AsyncMock(return_value=provider)), pytest.raises(XUIError):
            await svc.add_inbound_to_subscription(
                subscription_id=5, inbound_id=10
            )

        provider.remove_client.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_compensation_failure_logs_critical_and_reraises(self):
        """add_client ok, DB fails, compensation also fails → critical log + original error raised."""
        db_exc = Exception("DB down")
        session, inbound, subscription = self._mock_session_for_add(
            flush_side_effect=db_exc
        )

        svc = _make_service(session)

        provider = AsyncMock()
        provider.add_client = AsyncMock(
            return_value={"uuid": "u2", "email": "bob@test", "xui_client_id": "u2"}
        )
        provider.remove_client = AsyncMock(side_effect=Exception("panel also down"))

        critical_messages: list[str] = []

        import app.services.new_subscription_service as svc_module

        mock_logger = MagicMock()
        mock_logger.error = MagicMock()
        mock_logger.info = MagicMock()
        mock_logger.critical = MagicMock(side_effect=lambda msg, *a, **kw: critical_messages.append(msg))

        with (
            patch.object(svc_module, "logger", mock_logger),
            patch.object(svc, "_get_provider", AsyncMock(return_value=provider)),
            pytest.raises(XUIError),
        ):
            await svc.add_inbound_to_subscription(
                subscription_id=5, inbound_id=10
            )

        assert critical_messages, "Expected at least one logger.critical() call"
        assert any(
            "zombie" in m.lower() or "Zombie" in m for m in critical_messages
        ), f"Expected zombie mention in critical log, got: {critical_messages}"

    @pytest.mark.asyncio
    async def test_happy_path_no_compensation(self):
        """Happy path: add_client and DB both succeed → remove_client NOT called."""
        session, inbound, subscription = self._mock_session_for_add()

        svc = _make_service(session)

        provider = AsyncMock()
        provider.add_client = AsyncMock(
            return_value={"uuid": "u3", "email": "carol@test", "xui_client_id": "u3"}
        )
        provider.remove_client = AsyncMock(return_value=True)

        with patch.object(svc, "_get_provider", AsyncMock(return_value=provider)):
            result = await svc.add_inbound_to_subscription(
                subscription_id=5, inbound_id=10
            )

        provider.remove_client.assert_not_awaited()
        assert result is not None


# ---------------------------------------------------------------------------
# remove_inbound_from_subscription tests
# ---------------------------------------------------------------------------


class TestRemoveInboundAtomicity:
    """Saga / error-isolation in remove_inbound_from_subscription."""

    def _mock_session_for_remove(
        self,
        panel_side_effect=None,
        delete_side_effect=None,
    ):
        session = MagicMock()
        inbound = _make_inbound("xui_inbound")
        connection = _make_connection()

        conn_result = MagicMock()
        conn_result.scalar_one_or_none.return_value = connection
        inbound_result = MagicMock()
        inbound_result.scalar_one_or_none.return_value = inbound

        execute_results = [conn_result, inbound_result]
        call_count = [0]

        async def fake_execute(*args, **kwargs):
            idx = call_count[0]
            call_count[0] += 1
            if idx < len(execute_results):
                return execute_results[idx]
            return MagicMock()

        session.execute = fake_execute

        if delete_side_effect is not None:
            delete_call = [0]

            async def fake_flush():
                delete_call[0] += 1
                if delete_call[0] >= 1:
                    raise delete_side_effect

            session.flush = fake_flush
        else:
            session.flush = AsyncMock()

        session.delete = MagicMock()

        return session, inbound, connection

    @pytest.mark.asyncio
    async def test_panel_ok_db_delete_fails_sets_sync_status_error(self):
        """Panel remove succeeds, DB delete raises → sync_status set to 'error', method returns False."""
        db_exc = Exception("FK constraint")
        session, inbound, connection = self._mock_session_for_remove(
            delete_side_effect=db_exc
        )

        svc = _make_service(session)

        provider = AsyncMock()
        provider.remove_client = AsyncMock(return_value=True)

        with patch.object(svc, "_get_provider", AsyncMock(return_value=provider)):
            result = await svc.remove_inbound_from_subscription(
                subscription_id=5, inbound_id=10
            )

        # The method must not raise
        assert result is False
        # sync_status must be set to "error" on the connection object
        assert connection.sync_status == "error"

    @pytest.mark.asyncio
    async def test_panel_fails_propagates_exception(self):
        """Panel remove raises → exception is re-raised, DB delete NOT called."""
        session, inbound, connection = self._mock_session_for_remove()

        svc = _make_service(session)

        provider = AsyncMock()
        provider.remove_client = AsyncMock(side_effect=Exception("panel unreachable"))

        with patch.object(svc, "_get_provider", AsyncMock(return_value=provider)), pytest.raises(Exception, match="panel unreachable"):
            await svc.remove_inbound_from_subscription(
                subscription_id=5, inbound_id=10
            )

        # DB delete must NOT have been called
        session.delete.assert_not_called()
