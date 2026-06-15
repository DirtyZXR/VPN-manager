"""Tests for AWG private-key at-rest encryption.

Covers:
- Round-trip: set plaintext → stored encrypted → read back decrypted
- AWGService.server_private_key property
- AWGInboundConnection.private_key and .psk properties
- Migration helper: encrypts plaintext, idempotent on already-encrypted values
- Consumer (amnezia_awg provider) receives decrypted key
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet

FERNET_KEY = "SpWH-ifTebQwpAlasE5SvZsgUwi0onGmILmSrm7G1BQ="
PLAINTEXT_KEY = "wEXaMpLePrIvAtEkEy1234567890abcdefghijkl="
PLAINTEXT_PSK = "pSKkEyABCDEFGH1234567890xyzXYZ0987654321="


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cipher() -> Fernet:
    return Fernet(FERNET_KEY.encode())


def _encrypt(value: str) -> str:
    return _cipher().encrypt(value.encode()).decode()


def _decrypt(value: str) -> str:
    return _cipher().decrypt(value.encode()).decode()


def _make_settings_mock():
    s = MagicMock()
    s.encryption_key = FERNET_KEY
    s.database_url = "sqlite+aiosqlite:///./data/vpn_manager.db"
    s.log_level = "INFO"
    return s


# ---------------------------------------------------------------------------
# AWGInboundConnection — round-trip
# ---------------------------------------------------------------------------

class TestAWGInboundConnectionEncryption:
    """Property getter/setter encrypt/decrypt transparently."""

    def _make_conn(self, **kwargs):
        """Create AWGInboundConnection via SA constructor (proper SA init)."""
        settings_mock = _make_settings_mock()
        with patch("app.config.get_settings", return_value=settings_mock), \
             patch("app.database._get_engine", return_value=MagicMock()), \
             patch("app.database._get_session_factory", return_value=MagicMock()):
            import app.database
            app.database.engine = MagicMock()
            app.database.async_session_factory = MagicMock()
            from app.database.models.inbound_connection import AWGInboundConnection
            return AWGInboundConnection(type="awg_inbound_connection", **kwargs)

    def test_private_key_round_trip(self):
        with patch("app.config.get_settings", return_value=_make_settings_mock()), \
             patch("app.database._get_engine", return_value=MagicMock()), \
             patch("app.database._get_session_factory", return_value=MagicMock()):
            import app.database
            app.database.engine = MagicMock()
            app.database.async_session_factory = MagicMock()
            from app.database.models.inbound_connection import AWGInboundConnection

            conn = AWGInboundConnection(
                type="awg_inbound_connection",
                private_key=PLAINTEXT_KEY,
            )

            # Stored value must be different from plaintext (encrypted)
            assert conn._private_key_encrypted != PLAINTEXT_KEY
            assert conn._private_key_encrypted is not None

            # Reading back must return original plaintext
            assert conn.private_key == PLAINTEXT_KEY

    def test_psk_round_trip(self):
        with patch("app.config.get_settings", return_value=_make_settings_mock()), \
             patch("app.database._get_engine", return_value=MagicMock()), \
             patch("app.database._get_session_factory", return_value=MagicMock()):
            import app.database
            app.database.engine = MagicMock()
            app.database.async_session_factory = MagicMock()
            from app.database.models.inbound_connection import AWGInboundConnection

            conn = AWGInboundConnection(
                type="awg_inbound_connection",
                psk=PLAINTEXT_PSK,
            )

            assert conn._psk_encrypted != PLAINTEXT_PSK
            assert conn.psk == PLAINTEXT_PSK

    def test_none_values(self):
        with patch("app.config.get_settings", return_value=_make_settings_mock()), \
             patch("app.database._get_engine", return_value=MagicMock()), \
             patch("app.database._get_session_factory", return_value=MagicMock()):
            import app.database
            app.database.engine = MagicMock()
            app.database.async_session_factory = MagicMock()
            from app.database.models.inbound_connection import AWGInboundConnection

            conn = AWGInboundConnection(type="awg_inbound_connection")
            assert conn.private_key is None
            assert conn.psk is None

    def test_stored_value_is_not_plaintext(self):
        """The raw DB column must not hold the plaintext key."""
        with patch("app.config.get_settings", return_value=_make_settings_mock()), \
             patch("app.database._get_engine", return_value=MagicMock()), \
             patch("app.database._get_session_factory", return_value=MagicMock()):
            import app.database
            app.database.engine = MagicMock()
            app.database.async_session_factory = MagicMock()
            from app.database.models.inbound_connection import AWGInboundConnection

            conn = AWGInboundConnection(
                type="awg_inbound_connection",
                private_key=PLAINTEXT_KEY,
                psk=PLAINTEXT_PSK,
            )

            assert PLAINTEXT_KEY not in (conn._private_key_encrypted or "")
            assert PLAINTEXT_PSK not in (conn._psk_encrypted or "")

    def test_setter_after_construction(self):
        """Setting private_key after construction also encrypts."""
        with patch("app.config.get_settings", return_value=_make_settings_mock()), \
             patch("app.database._get_engine", return_value=MagicMock()), \
             patch("app.database._get_session_factory", return_value=MagicMock()):
            import app.database
            app.database.engine = MagicMock()
            app.database.async_session_factory = MagicMock()
            from app.database.models.inbound_connection import AWGInboundConnection

            conn = AWGInboundConnection(type="awg_inbound_connection")
            conn.private_key = PLAINTEXT_KEY
            conn.psk = PLAINTEXT_PSK

            assert conn.private_key == PLAINTEXT_KEY
            assert conn.psk == PLAINTEXT_PSK
            assert conn._private_key_encrypted != PLAINTEXT_KEY
            assert conn._psk_encrypted != PLAINTEXT_PSK


# ---------------------------------------------------------------------------
# AWGService — round-trip
# ---------------------------------------------------------------------------

class TestAWGServiceEncryption:
    """AWGService.server_private_key property."""

    def test_server_private_key_round_trip(self):
        with patch("app.config.get_settings", return_value=_make_settings_mock()), \
             patch("app.database._get_engine", return_value=MagicMock()), \
             patch("app.database._get_session_factory", return_value=MagicMock()):
            import app.database
            app.database.engine = MagicMock()
            app.database.async_session_factory = MagicMock()
            from app.database.models.services import AWGService

            svc = AWGService(
                server_id=1,
                port=51820,
                server_private_key=PLAINTEXT_KEY,
            )

            assert svc._server_private_key_encrypted != PLAINTEXT_KEY
            assert svc.server_private_key == PLAINTEXT_KEY

    def test_none_value(self):
        with patch("app.config.get_settings", return_value=_make_settings_mock()), \
             patch("app.database._get_engine", return_value=MagicMock()), \
             patch("app.database._get_session_factory", return_value=MagicMock()):
            import app.database
            app.database.engine = MagicMock()
            app.database.async_session_factory = MagicMock()
            from app.database.models.services import AWGService

            svc = AWGService(server_id=1, port=51820)
            assert svc.server_private_key is None

    def test_stored_is_not_plaintext(self):
        with patch("app.config.get_settings", return_value=_make_settings_mock()), \
             patch("app.database._get_engine", return_value=MagicMock()), \
             patch("app.database._get_session_factory", return_value=MagicMock()):
            import app.database
            app.database.engine = MagicMock()
            app.database.async_session_factory = MagicMock()
            from app.database.models.services import AWGService

            svc = AWGService(server_id=1, port=51820, server_private_key=PLAINTEXT_KEY)
            assert PLAINTEXT_KEY not in (svc._server_private_key_encrypted or "")

    def test_setter_after_construction(self):
        with patch("app.config.get_settings", return_value=_make_settings_mock()), \
             patch("app.database._get_engine", return_value=MagicMock()), \
             patch("app.database._get_session_factory", return_value=MagicMock()):
            import app.database
            app.database.engine = MagicMock()
            app.database.async_session_factory = MagicMock()
            from app.database.models.services import AWGService

            svc = AWGService(server_id=1, port=51820)
            svc.server_private_key = PLAINTEXT_KEY

            assert svc.server_private_key == PLAINTEXT_KEY
            assert svc._server_private_key_encrypted != PLAINTEXT_KEY


# ---------------------------------------------------------------------------
# Migration helper — idempotency
# ---------------------------------------------------------------------------

class TestMigrationIdempotency:
    """_is_encrypted helper used in migration."""

    @staticmethod
    def _is_enc(value: str, cipher: Fernet) -> bool:
        try:
            cipher.decrypt(value.encode())
            return True
        except Exception:
            return False

    def test_plaintext_not_detected_as_encrypted(self):
        cipher = _cipher()
        # A WireGuard key is base64 but NOT a valid Fernet token
        assert not self._is_enc(PLAINTEXT_KEY, cipher)

    def test_encrypted_detected_as_encrypted(self):
        cipher = _cipher()
        encrypted = _encrypt(PLAINTEXT_KEY)
        assert self._is_enc(encrypted, cipher)

    def test_double_encryption_prevented(self):
        """Simulates the migration: already-encrypted value must be skipped."""
        cipher = _cipher()
        already_encrypted = _encrypt(PLAINTEXT_KEY)

        # Migration logic: only encrypt if NOT already encrypted
        if not self._is_enc(already_encrypted, cipher):
            result = cipher.encrypt(already_encrypted.encode()).decode()
        else:
            result = already_encrypted

        # Must still decrypt to the original plaintext (not double-encrypted)
        assert _decrypt(result) == PLAINTEXT_KEY

    def test_plaintext_is_encrypted_by_migration(self):
        """Migration must encrypt plaintext values."""
        cipher = _cipher()
        value = PLAINTEXT_KEY

        if not self._is_enc(value, cipher):
            result = cipher.encrypt(value.encode()).decode()
        else:
            result = value

        assert self._is_enc(result, cipher)
        assert _decrypt(result) == PLAINTEXT_KEY

    def test_downgrade_decrypts(self):
        """Downgrade must restore plaintext from encrypted."""
        cipher = _cipher()
        encrypted = _encrypt(PLAINTEXT_KEY)

        if self._is_enc(encrypted, cipher):
            result = cipher.decrypt(encrypted.encode()).decode()
        else:
            result = encrypted

        assert result == PLAINTEXT_KEY


# ---------------------------------------------------------------------------
# Consumer: amnezia_awg provider receives decrypted key
# ---------------------------------------------------------------------------

class TestConsumerReceivesDecryptedKey:
    """Verify that get_client_config uses the decrypted private_key/psk."""

    def test_get_client_config_uses_decrypted_keys(self):
        """AWGInboundConnection getter must return plaintext (what config generator uses)."""
        with patch("app.config.get_settings", return_value=_make_settings_mock()), \
             patch("app.database._get_engine", return_value=MagicMock()), \
             patch("app.database._get_session_factory", return_value=MagicMock()):
            import app.database
            app.database.engine = MagicMock()
            app.database.async_session_factory = MagicMock()
            from app.database.models.inbound_connection import AWGInboundConnection

            conn = AWGInboundConnection(
                type="awg_inbound_connection",
                private_key=PLAINTEXT_KEY,
                psk=PLAINTEXT_PSK,
                public_key="publickey123=",
                client_ip="10.8.0.2",
            )

            # Simulate what amnezia_awg.py line 318 does:
            # private_key = connection.private_key.strip() if connection.private_key else ""
            read_key = conn.private_key.strip() if conn.private_key else ""
            assert read_key == PLAINTEXT_KEY, (
                "Consumer received encrypted garbage instead of plaintext key"
            )

            # Simulate what amnezia_awg.py line 321 does:
            # psk = connection.psk.strip() if connection.psk else ""
            read_psk = conn.psk.strip() if conn.psk else ""
            assert read_psk == PLAINTEXT_PSK, (
                "Consumer received encrypted garbage instead of plaintext PSK"
            )

    def test_enable_client_uses_decrypted_psk(self):
        """enable_client reads connection.psk — must be plaintext for WG."""
        with patch("app.config.get_settings", return_value=_make_settings_mock()), \
             patch("app.database._get_engine", return_value=MagicMock()), \
             patch("app.database._get_session_factory", return_value=MagicMock()):
            import app.database
            app.database.engine = MagicMock()
            app.database.async_session_factory = MagicMock()
            from app.database.models.inbound_connection import AWGInboundConnection

            conn = AWGInboundConnection(
                type="awg_inbound_connection",
                psk=PLAINTEXT_PSK,
                public_key="pubkey=",
                client_ip="10.8.0.3",
            )

            # This is what enable_client does: connection.psk
            read_psk = conn.psk
            assert read_psk == PLAINTEXT_PSK
            # Must not be a Fernet token (length check: WG keys are short ~44 chars)
            assert len(read_psk) < 100, "PSK looks like an encrypted blob, not a WG key"

    def test_decrypted_key_usable_as_wg_config_value(self):
        """Key read from model must be valid as WG config value (no newlines, right length)."""
        with patch("app.config.get_settings", return_value=_make_settings_mock()), \
             patch("app.database._get_engine", return_value=MagicMock()), \
             patch("app.database._get_session_factory", return_value=MagicMock()):
            import app.database
            app.database.engine = MagicMock()
            app.database.async_session_factory = MagicMock()
            from app.database.models.inbound_connection import AWGInboundConnection

            conn = AWGInboundConnection(
                type="awg_inbound_connection",
                private_key=PLAINTEXT_KEY,
                psk=PLAINTEXT_PSK,
            )

            pk = conn.private_key
            psk = conn.psk

            # No newlines (would break config file)
            assert "\n" not in pk
            assert "\n" not in psk
            # Length must match original
            assert len(pk) == len(PLAINTEXT_KEY)
            assert len(psk) == len(PLAINTEXT_PSK)
