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


# ---------------------------------------------------------------------------
# rebuild_subscription tests
# ---------------------------------------------------------------------------


class TestRebuildSubscription:
    """rebuild_subscription surfaces partial failures and keeps sync_status."""

    def _make_kept_conn(self, inbound_id: int = 10):
        conn = MagicMock()
        conn.id = 100 + inbound_id
        conn.inbound_id = inbound_id
        conn.subscription_id = 5
        conn.uuid = "uuid-kept"
        conn.email = f"kept_{inbound_id}@test"
        conn.total_gb = 0
        conn.expiry_date = None
        conn.sync_status = "synced"
        conn.is_enabled = True
        inbound = _make_inbound("xui_inbound")
        inbound.id = inbound_id
        conn.inbound = inbound
        return conn

    def _make_rebuild_service(self, kept_conns, raise_on_update=False, raise_on_add=False):
        """Return (svc, session, provider_mock) wired for rebuild."""
        session = MagicMock()
        session.flush = AsyncMock()
        session.add = MagicMock()
        session.delete = MagicMock()

        # subscription with kept connections
        sub = MagicMock()
        sub.id = 5
        sub.name = "Sub"
        sub.total_gb = 0
        sub.expiry_date = None
        sub.template_id = None
        sub.notes = None
        sub.inbound_connections = kept_conns
        sub.client = MagicMock()

        # get_subscription returns the same object
        reload_result = MagicMock()
        reload_result.scalar_one_or_none.return_value = sub
        sub_scalars = MagicMock()
        sub_scalars.scalars.return_value.all.return_value = [sub]

        call_count = [0]

        async def fake_execute(*args, **kwargs):
            call_count[0] += 1
            r = MagicMock()
            r.scalar_one_or_none.return_value = sub
            r.scalars.return_value.all.return_value = [sub]
            return r

        session.execute = fake_execute

        svc = _make_service(session)

        # Patch get_subscription to return our sub
        async def fake_get_sub(sub_id):
            return sub

        svc.get_subscription = fake_get_sub

        provider = AsyncMock()
        provider.reset_client_traffic = AsyncMock()
        if raise_on_update:
            provider.update_client = AsyncMock(side_effect=Exception("panel unreachable"))
        else:
            provider.update_client = AsyncMock()

        # Patch internal helpers
        svc._get_provider = AsyncMock(return_value=provider)

        if raise_on_add:
            svc.add_inbound_to_subscription = AsyncMock(side_effect=Exception("add failed"))
        else:
            svc.add_inbound_to_subscription = AsyncMock(return_value=MagicMock())

        svc.remove_inbound_from_subscription = AsyncMock()

        return svc, session, provider

    @pytest.mark.asyncio
    async def test_kept_update_failure_raises_aggregated_error_and_sets_sync_status_error(self):
        """If a kept-inbound panel update fails, rebuild raises XUIError and marks sync_status='error'."""
        from app.xui_client.exceptions import XUIError

        conn = self._make_kept_conn(inbound_id=10)
        svc, session, provider = self._make_rebuild_service(
            kept_conns=[conn],
            raise_on_update=True,
        )

        with pytest.raises(XUIError, match="partially failed"):
            await svc.rebuild_subscription(
                subscription_id=5,
                new_name="Sub",
                new_total_gb=0,
                new_expiry_days=None,
                new_inbound_ids=[10],  # 10 is "kept" (was already in sub)
            )

        # sync_status must be marked error on the failing connection
        assert conn.sync_status == "error"

    @pytest.mark.asyncio
    async def test_add_failure_raises_aggregated_error(self):
        """If add_inbound_to_subscription raises for a new inbound, rebuild raises XUIError."""
        from app.xui_client.exceptions import XUIError

        # No existing connections → adding inbound 20 is "add" (not "kept")
        svc, session, provider = self._make_rebuild_service(
            kept_conns=[],
            raise_on_add=True,
        )

        with pytest.raises(XUIError, match="partially failed"):
            await svc.rebuild_subscription(
                subscription_id=5,
                new_name="Sub",
                new_total_gb=0,
                new_expiry_days=None,
                new_inbound_ids=[20],  # 20 is new → goes to add path
            )

    @pytest.mark.asyncio
    async def test_happy_path_returns_tuple_no_exception(self):
        """Happy path: all operations succeed → returns (subscription, connections) without raising."""
        conn = self._make_kept_conn(inbound_id=10)
        conn_list = [conn]
        svc, session, provider = self._make_rebuild_service(
            kept_conns=conn_list,
            raise_on_update=False,
        )

        # Patch get_subscription to return sub with fresh conn list
        sub = MagicMock()
        sub.id = 5
        sub.inbound_connections = conn_list
        svc.get_subscription = AsyncMock(return_value=sub)

        result = await svc.rebuild_subscription(
            subscription_id=5,
            new_name="Sub",
            new_total_gb=0,
            new_expiry_days=None,
            new_inbound_ids=[10],
        )

        updated_sub, connections = result
        assert updated_sub is sub
        assert connections == conn_list
        # sync_status must NOT be set to error
        assert conn.sync_status == "synced"


# ---------------------------------------------------------------------------
# delete_subscription tests
# ---------------------------------------------------------------------------


class TestDeleteSubscription:
    """delete_subscription always deletes from DB even when panel removal fails."""

    def _make_delete_service_and_sub(self, panel_raises=False):
        session = MagicMock()
        session.flush = AsyncMock()
        session.delete = AsyncMock()
        session.expire_all = MagicMock()

        conn = _make_connection("xui_inbound")
        inbound = _make_inbound("xui_inbound")
        conn.inbound = inbound
        conn.inbound_id = inbound.id

        sub = MagicMock()
        sub.id = 5
        sub.inbound_connections = [conn]

        svc = _make_service(session)

        provider = AsyncMock()
        if panel_raises:
            provider.remove_client = AsyncMock(side_effect=Exception("panel down"))
        else:
            provider.remove_client = AsyncMock(return_value=True)

        svc._get_provider = AsyncMock(return_value=provider)

        return svc, session, sub, conn

    @pytest.mark.asyncio
    async def test_panel_failure_still_deletes_from_db(self):
        """Panel removal fails → DB subscription still deleted, warning logged."""
        import app.services.new_subscription_service as svc_module

        svc, session, sub, conn = self._make_delete_service_and_sub(panel_raises=True)

        warning_messages: list[str] = []
        mock_logger = MagicMock()
        mock_logger.warning = MagicMock(
            side_effect=lambda msg, *a, **kw: warning_messages.append(msg)
        )

        with patch.object(svc_module, "logger", mock_logger):
            result = await svc.delete_subscription(sub)

        assert result is True
        # session.delete must have been called with the subscription
        session.delete.assert_called_once_with(sub)
        # A warning about zombie must have been logged
        assert warning_messages, "Expected at least one warning"
        assert any("zombie" in m.lower() for m in warning_messages), (
            f"Expected zombie mention in warning, got: {warning_messages}"
        )

    @pytest.mark.asyncio
    async def test_happy_path_deletes_from_db(self):
        """Happy path: panel removal succeeds → DB deleted normally."""
        svc, session, sub, conn = self._make_delete_service_and_sub(panel_raises=False)

        result = await svc.delete_subscription(sub)

        assert result is True
        session.delete.assert_called_once_with(sub)
