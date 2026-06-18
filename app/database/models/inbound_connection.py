"""InboundConnection model for unique inbound connections."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base, SyncMixin, TimestampMixin
from app.utils import decrypt_password, encrypt_password
from app.utils.date_utils import ensure_utc

if TYPE_CHECKING:
    from app.database.models.inbound import Inbound
    from app.database.models.subscription import Subscription


class InboundConnection(Base, TimestampMixin, SyncMixin):
    """Base unique connection to an inbound (within a subscription)."""

    __tablename__ = "inbound_connections"
    __table_args__ = (
        UniqueConstraint(
            "subscription_id",
            "inbound_id",
            name="uq_subscription_inbound",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subscription_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=False,
    )
    inbound_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("inbounds.id", ondelete="CASCADE"),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Per-connection traffic and expiry settings (can differ per inbound)
    total_gb: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 0 = unlimited
    expiry_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __mapper_args__ = {
        "polymorphic_on": "type",
        "polymorphic_identity": "inbound_connection",
        "with_polymorphic": "*",
    }

    # Relationships
    subscription: Mapped["Subscription"] = relationship(
        "Subscription",
        back_populates="inbound_connections",
    )
    inbound: Mapped["Inbound"] = relationship("Inbound", back_populates="client_connections")

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(id={self.id}, enabled={self.is_enabled})>"

    @property
    def is_unlimited(self) -> bool:
        """Check if connection has unlimited traffic."""
        return self.total_gb == 0

    @property
    def is_expired(self) -> bool:
        """Check if connection has expired."""
        expiry = ensure_utc(self.expiry_date)
        if expiry is None:
            return False
        return datetime.now(UTC) > expiry

    @property
    def remaining_days(self) -> int | None:
        """Calculate remaining days until expiry."""
        expiry = ensure_utc(self.expiry_date)
        if expiry is None:
            return None

        import math

        now = datetime.now(UTC)
        delta = expiry - now
        return max(0, math.ceil(delta.total_seconds() / 86400))

    @property
    def is_connection_active(self) -> bool:
        """Check if connection is active (enabled and not expired)."""
        return self.is_enabled and not self.is_expired

    @property
    def remaining_days_with_sign(self) -> int | None:
        """Calculate remaining days until expiry (can be negative)."""
        expiry = ensure_utc(self.expiry_date)
        if expiry is None:
            return None

        import math

        now = datetime.now(UTC)
        delta = expiry - now
        return math.ceil(delta.total_seconds() / 86400)


class XUIInboundConnection(InboundConnection):
    """3x-ui specific inbound connection."""

    __tablename__ = "xui_inbound_connections"

    id: Mapped[int] = mapped_column(
        Integer, ForeignKey("inbound_connections.id", ondelete="CASCADE"), primary_key=True
    )

    __mapper_args__ = {
        "polymorphic_identity": "xui_inbound_connection",
    }

    xui_client_id: Mapped[str | None] = mapped_column(String(100), nullable=True)  # UUID from XUI
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)  # Email from XUI
    uuid: Mapped[str | None] = mapped_column(String(100), nullable=True)  # UUID from XUI
    provider_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class AWGInboundConnection(InboundConnection):
    """AmneziaWG specific inbound connection.

    ``private_key`` and ``psk`` are stored encrypted (Fernet) in the DB.
    The Python properties transparently encrypt on write and decrypt on read,
    so all consumers continue to use ``connection.private_key`` / ``connection.psk``
    without any changes.
    """

    __tablename__ = "awg_inbound_connections"

    id: Mapped[int] = mapped_column(
        Integer, ForeignKey("inbound_connections.id", ondelete="CASCADE"), primary_key=True
    )
    client_ip: Mapped[str | None] = mapped_column(String(50), nullable=True)
    public_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    _private_key_encrypted: Mapped[str | None] = mapped_column(
        "private_key", String(250), nullable=True
    )
    _psk_encrypted: Mapped[str | None] = mapped_column(
        "psk", String(250), nullable=True
    )

    __mapper_args__ = {
        "polymorphic_identity": "awg_inbound_connection",
    }

    @property
    def private_key(self) -> str | None:
        """Return decrypted private key."""
        if self._private_key_encrypted is None:
            return None
        try:
            return decrypt_password(self._private_key_encrypted)
        except Exception:
            # Already plaintext (pre-migration rows) — return as-is
            return self._private_key_encrypted

    @private_key.setter
    def private_key(self, value: str | None) -> None:
        """Encrypt and store private key."""
        if value is None:
            self._private_key_encrypted = None
        else:
            self._private_key_encrypted = encrypt_password(value)

    @property
    def psk(self) -> str | None:
        """Return decrypted PSK."""
        if self._psk_encrypted is None:
            return None
        try:
            return decrypt_password(self._psk_encrypted)
        except Exception:
            # Already plaintext (pre-migration rows) — return as-is
            return self._psk_encrypted

    @psk.setter
    def psk(self, value: str | None) -> None:
        """Encrypt and store PSK."""
        if value is None:
            self._psk_encrypted = None
        else:
            self._psk_encrypted = encrypt_password(value)


class MTProxyInboundConnection(InboundConnection):
    """MTProxy specific inbound connection."""

    __tablename__ = "mtproxy_inbound_connections"

    id: Mapped[int] = mapped_column(
        Integer, ForeignKey("inbound_connections.id", ondelete="CASCADE"), primary_key=True
    )
    secret: Mapped[str | None] = mapped_column(String(100), nullable=True)
    domain: Mapped[str | None] = mapped_column(String(200), nullable=True)

    __mapper_args__ = {
        "polymorphic_identity": "mtproxy_inbound_connection",
    }
