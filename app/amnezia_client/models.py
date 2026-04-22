from typing import Any

from pydantic import BaseModel, ConfigDict


class AmneziaAuthResponse(BaseModel):
    token: str


class AmneziaProtocol(BaseModel):
    id: int
    slug: str
    name: str
    description: str | None = None


class AmneziaServer(BaseModel):
    id: int
    user_id: int
    name: str
    host: str
    port: int
    username: str
    password: str | None = None
    container_name: str | None = None
    install_protocol: str | None = None
    install_options: Any | None = None
    vpn_port: int | None = None
    vpn_subnet: str | None = None
    server_public_key: str | None = None
    preshared_key: str | None = None
    awg_params: Any | None = None
    status: str
    deployed_at: str | None = None
    last_check_at: str | None = None
    error_message: str | None = None
    created_at: str
    updated_at: str
    ssh_key: str | None = None
    dns_servers: str | None = None
    protocols: list[AmneziaProtocol] = []

    model_config = ConfigDict(extra="ignore")


class AmneziaClientStats(BaseModel):
    sent: str
    received: str
    total: str
    last_seen: str
    is_online: bool


class AmneziaClient(BaseModel):
    id: int
    name: str
    server_id: int
    client_ip: str | None = None
    status: str
    created_at: str

    model_config = ConfigDict(extra="ignore")


class AmneziaClientDetails(AmneziaClient):
    stats: AmneziaClientStats | None = None
    bytes_sent: int | None = 0
    bytes_received: int | None = 0
    last_handshake: str | None = None
    config: str | None = None
    qr_code: str | None = None


class AmneziaClientCreateResponse(BaseModel):
    success: bool
    client: AmneziaClient
