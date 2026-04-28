"""AmneziaWG (AWG/AWG2) Provider implementation."""

import base64
import io
import ipaddress
import logging
import re
import uuid
from datetime import datetime
from typing import Any

import qrcode

from app.database.models import Inbound, InboundConnection, Server, Subscription
from app.services.ssh_service import SSHManager
from app.services.vpn_providers.base import BaseVPNProvider

logger = logging.getLogger(__name__)


class AmneziaAWGProvider(BaseVPNProvider):
    """Provider for AmneziaWG via direct SSH and Docker execution.

    Client lifecycle:
    - add_client: generates keys, allocates IP, adds peer to config + kernel
    - enable_client: re-adds peer to config + kernel (keys/IP from DB, same config for user)
    - disable_client: removes peer from kernel only (config entry + IP preserved)
    - remove_client: removes peer from kernel + config, frees IP
    """

    def __init__(self, server: Server) -> None:
        super().__init__(server)
        self.ssh = SSHManager(server)
        self.container_name = "amnezia-awg"
        self.interface_name = "awg0"
        self.config_path = f"/opt/amnezia/awg/{self.interface_name}.conf"

    async def _get_server_psk(self) -> str:
        cmd = f"docker exec -i {self.container_name} cat /opt/amnezia/awg/wireguard_psk.key"
        try:
            return await self.ssh.run_command(cmd)
        except Exception:
            logger.warning("Failed to read PSK from server, generating a new one.")
            return await self.ssh.run_command(f"docker exec -i {self.container_name} awg genpsk")

    async def _get_server_public_key(self) -> str:
        cmd = f"docker exec -i {self.container_name} cat /opt/amnezia/awg/wireguard_server_public_key.key"
        return await self.ssh.run_command(cmd)

    async def _find_next_free_ip(self, inbound: Inbound) -> str:
        cmd = f"docker exec -i {self.container_name} cat {self.config_path}"
        config_text = await self.ssh.run_command(cmd)

        file_ips = re.findall(r"AllowedIPs\s*=\s*([0-9\.]+)/32", config_text)

        db_ips = []

        from sqlalchemy import select

        from app.database.models import AWGInboundConnection

        if hasattr(self, "_session") and self._session:
            result = await self._session.execute(
                select(AWGInboundConnection).where(AWGInboundConnection.inbound_id == inbound.id)
            )
            connections = result.scalars().all()
        else:
            from app.database import async_session_factory

            async with async_session_factory() as session:
                result = await session.execute(
                    select(AWGInboundConnection).where(AWGInboundConnection.inbound_id == inbound.id)
                )
                connections = result.scalars().all()

        for conn in connections:
            if ip := conn.client_ip:
                db_ips.append(ip)

        all_used_ips = set(file_ips + db_ips)

        if not all_used_ips:
            iface_match = re.search(r"Address\s*=\s*([0-9\.]+)/[0-9]+", config_text)
            base_ip = iface_match.group(1) if iface_match else "10.8.1.1"
            next_ip_obj = ipaddress.IPv4Address(base_ip) + 1
        else:
            ip_objs = sorted([ipaddress.IPv4Address(ip) for ip in all_used_ips])
            next_ip_obj = ip_objs[-1] + 1

        return str(next_ip_obj)

    async def _get_awg_server_params(self) -> dict[str, str]:
        cmd = f"docker exec -i {self.container_name} cat {self.config_path}"
        config_text = await self.ssh.run_command(cmd)

        params = {}
        for line in config_text.splitlines():
            if "=" in line:
                key, val = [x.strip() for x in line.split("=", 1)]
                params[key] = val
        return params

    async def _sync_config(self) -> None:
        sync_cmd = (
            f"docker exec -i {self.container_name} bash -c "
            f"'awg syncconf {self.interface_name} <(awg-quick strip {self.config_path})'"
        )
        await self.ssh.run_command(sync_cmd)

    async def _add_peer_to_config(self, public_key: str, psk: str, client_ip: str) -> None:
        peer_block = f"\\n[Peer]\\nPublicKey = {public_key}\\nPresharedKey = {psk}\\nAllowedIPs = {client_ip}/32\\n"
        append_cmd = f"docker exec -i {self.container_name} bash -c 'echo -e \"{peer_block}\" >> {self.config_path}'"
        await self.ssh.run_command(append_cmd)

    async def _remove_peer_from_config(self, public_key: str) -> None:
        config_text = await self.ssh.run_command(
            f"docker exec -i {self.container_name} cat {self.config_path}"
        )

        blocks = config_text.split("[Peer]")
        new_blocks = [blocks[0]]

        for block in blocks[1:]:
            if public_key not in block:
                new_blocks.append(block)

        new_config_text = "[Peer]".join(new_blocks)

        write_cmd = f"docker exec -i {self.container_name} bash -c 'cat > {self.config_path}'"
        await self.ssh.run_command(write_cmd, input_data=new_config_text)

    async def _peer_in_config(self, public_key: str) -> bool:
        check_cmd = f"docker exec -i {self.container_name} grep -q {public_key} {self.config_path} && echo 'EXISTS' || echo 'MISSING'"
        status = await self.ssh.run_command(check_cmd)
        return "EXISTS" in status

    async def _kick_peer_from_kernel(self, public_key: str) -> None:
        kick_cmd = f"docker exec -i {self.container_name} awg set {self.interface_name} peer {public_key} remove"
        await self.ssh.run_command(kick_cmd)

    # ── CRUD ──────────────────────────────────────────────────────────

    async def add_client(
        self,
        inbound: Inbound,
        subscription: Subscription,
        client_uuid: str | None = None,
        email: str | None = None,
    ) -> dict[str, Any]:
        priv_key_cmd = f"docker exec -i {self.container_name} awg genkey"
        private_key = await self.ssh.run_command(priv_key_cmd)

        pub_key_cmd = (
            f"docker exec -i {self.container_name} bash -c 'echo \"{private_key}\" | awg pubkey'"
        )
        public_key = await self.ssh.run_command(pub_key_cmd)

        psk = await self._get_server_psk()
        next_ip = await self._find_next_free_ip(inbound)

        await self._add_peer_to_config(public_key, psk, next_ip)
        await self._sync_config()

        srv_params = await self._get_awg_server_params()

        return {
            "uuid": client_uuid or str(uuid.uuid4()),
            "public_key": public_key,
            "private_key": private_key,
            "psk": psk,
            "client_ip": next_ip,
            "server_params": srv_params,
        }

    async def remove_client(self, inbound: Inbound, connection: InboundConnection) -> bool:
        public_key = connection.public_key
        if not public_key:
            return False

        try:
            await self._kick_peer_from_kernel(public_key)
            await self._remove_peer_from_config(public_key)
            await self._sync_config()
            return True
        except Exception as e:
            logger.error(f"Failed to remove AWG client: {e}")
            return False

    async def update_client(
        self,
        inbound: Inbound,
        connection: InboundConnection,
        new_total_gb: int | None = None,
        new_expiry_date: datetime | None = None,
    ) -> bool:
        return True

    async def enable_client(self, inbound: Inbound, connection: InboundConnection) -> bool:
        public_key = connection.public_key
        psk = connection.psk
        client_ip = connection.client_ip

        if not public_key or not psk or not client_ip:
            logger.error("Missing keys or IP in AWG client connection.")
            return False

        try:
            if not await self._peer_in_config(public_key):
                await self._add_peer_to_config(public_key, psk, client_ip)
            await self._sync_config()
            return True
        except Exception as e:
            logger.error(f"Failed to enable AWG client: {e}")
            return False

    async def disable_client(self, inbound: Inbound, connection: InboundConnection) -> bool:
        public_key = connection.public_key
        if not public_key:
            return False

        try:
            await self._kick_peer_from_kernel(public_key)
            return True
        except Exception as e:
            logger.error(f"Failed to disable AWG client: {e}")
            return False

    async def reset_client_traffic(
        self, inbound: Inbound, connection: InboundConnection
    ) -> bool:
        return True

    async def get_client_traffic(
        self, inbound: Inbound, connection: InboundConnection
    ) -> dict[str, Any] | None:
        return None

    # ── Config generation ─────────────────────────────────────────────

    def _generate_qr_code(self, config_str: str) -> str:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(config_str)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode("utf-8")

    async def get_client_config(
        self, inbound: Inbound, connection: InboundConnection, prefer_json: bool = False
    ) -> dict[str, Any]:
        sp = await self._get_awg_server_params()

        private_key = connection.private_key
        client_ip = connection.client_ip
        psk = connection.psk

        host = self.server.ip_address
        port = sp.get("ListenPort", "51820")
        server_pub_key = await self._get_server_public_key()

        config_lines = [
            "[Interface]",
            f"PrivateKey = {private_key}",
            f"Address = {client_ip}/32",
            "DNS = 1.1.1.1, 8.8.8.8",
        ]

        obfs_keys = ["Jc", "Jmin", "Jmax", "S1", "S2", "S3", "S4", "H1", "H2", "H3", "H4"]
        for key in obfs_keys:
            if key in sp:
                config_lines.append(f"{key} = {sp[key]}")

        config_lines.extend(
            [
                "",
                "[Peer]",
                f"PublicKey = {server_pub_key.strip()}",
                f"PresharedKey = {psk}",
                f"Endpoint = {host}:{port}",
                "AllowedIPs = 0.0.0.0/0, ::/0",
                "PersistentKeepalive = 25",
            ]
        )

        config_str = "\n".join(config_lines)
        qr_base64 = self._generate_qr_code(config_str)

        return {
            "config_type": "file",
            "config_data": config_str,
            "filename": f"AWG_{connection.subscription.name}.conf",
            "qr_code_base64": qr_base64,
        }

    async def close(self) -> None:
        pass
