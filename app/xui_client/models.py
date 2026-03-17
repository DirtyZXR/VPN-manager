"""Pydantic models for XUI API."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class XUILoginRequest(BaseModel):
    """Login request model."""

    username: str
    password: str


class XUIResponse(BaseModel):
    """Base XUI API response."""

    success: bool = True
    msg: str | None = None


class XUIInboundSettings(BaseModel):
    """Inbound settings."""

    clients: list[dict[str, Any]] = Field(default_factory=list)


class XUIStreamSettings(BaseModel):
    """Stream settings for inbound."""

    network: str = "tcp"
    security: str = "reality"
    reality_settings: dict[str, Any] | None = None
    tls_settings: dict[str, Any] | None = None


class XUIInbound(BaseModel):
    """Inbound model from XUI API."""

    id: int
    enable: bool = True
    remark: str
    listen: str | None = None
    port: int
    protocol: str
    settings: str | None = None  # JSON string
    stream_settings: str | None = None  # JSON string
    tag: str | None = None
    sniffing: str | None = None


class XUIClient(BaseModel):
    """Client model for XUI."""

    id: str = Field(..., description="UUID")
    email: str = Field(..., description="Unique email")
    enable: bool = True
    flow: str = "xtls-rprx-vision"
    total_gb: int = Field(default=0, description="Total traffic in bytes, 0 = unlimited")
    expiry_time: int = Field(default=0, description="Expiry timestamp in ms, 0 = never")
    sub_id: str = Field(default="", description="Subscription ID")
    limit_ip: int = 0
    tg_id: str = ""
    reset: int = 0

    @property
    def is_unlimited(self) -> bool:
        """Check if client has unlimited traffic."""
        return self.total_gb == 0

    @property
    def expiry_datetime(self) -> datetime | None:
        """Get expiry as datetime."""
        if self.expiry_time == 0:
            return None
        return datetime.fromtimestamp(self.expiry_time / 1000)


class XUIClientSettings(BaseModel):
    """Client settings for inbound."""

    clients: list[XUIClient] = Field(default_factory=list)


class XUIAddClientRequest(BaseModel):
    """Request to add client to inbound."""

    id: str  # UUID
    email: str
    enable: bool = True
    flow: str = "xtls-rprx-vision"
    total_gb: int = 0
    expiry_time: int = 0
    sub_id: str = ""
    limit_ip: int = 0
    tg_id: str = ""
    reset: int = 0


class XUIInboundResponse(XUIResponse):
    """Response with inbound data."""

    obj: XUIInbound | None = None


class XUIInboundsListResponse(XUIResponse):
    """Response with list of inbounds."""

    obj: list[XUIInbound] = Field(default_factory=list)


class XUIClientListResponse(XUIResponse):
    """Response with client list from inbound."""

    obj: list[dict[str, Any]] = Field(default_factory=list)


class XUIOnlineClientsResponse(XUIResponse):
    """Response with online clients."""

    obj: list[dict[str, Any]] = Field(default_factory=list)
