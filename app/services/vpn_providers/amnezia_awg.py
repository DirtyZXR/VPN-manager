"""AmneziaWG (AWG/AWG2) Provider implementation."""

import base64
import io
import ipaddress
import logging
import re
import uuid
from typing import Any

import qrcode

from app.database.models import Inbound, InboundConnection, Server, Subscription
from app.services.ssh_service import SSHManager
from app.services.vpn_providers.base import BaseVPNProvider

logger = logging.getLogger(__name__)


class AmneziaAWGProvider(BaseVPNProvider):
    """Provider for AmneziaWG via direct SSH and Docker execution."""

    def __init__(self, server: Server) -> None:
        """Initialize provider with server and setup SSH."""
        super().__init__(server)
        self.ssh = SSHManager(server)

        # Typically the container name is 'amnezia-awg' or 'amnezia-awg2'
        payload = self.server.provider_payload or {}
        self.container_name = payload.get("container_name", "amnezia-awg")
        self.interface_name = payload.get("interface_name", "awg0")
        self.config_path = f"/opt/amnezia/awg/{self.interface_name}.conf"

    async def _get_server_psk(self) -> str:
        """Read the pre-shared key from the server."""
        cmd = f"docker exec -i {self.container_name} cat /opt/amnezia/awg/wireguard_psk.key"
        try:
            return await self.ssh.run_command(cmd)
        except Exception:
            # Fallback or empty if not strictly required, though original Amnezia sets it
            logger.warning(
                "Failed to read PSK from server, generating a new one temporarily or proceeding without."
            )
            return await self.ssh.run_command(f"docker exec -i {self.container_name} awg genpsk")

    async def _get_server_public_key(self) -> str:
        """Read the server's public key."""
        cmd = f"docker exec -i {self.container_name} cat /opt/amnezia/awg/wireguard_server_public_key.key"
        return await self.ssh.run_command(cmd)

    async def _find_next_free_ip(self, inbound: Inbound) -> str:
        """Parse server config and DB to find the next available IP for a peer."""
        cmd = f"docker exec -i {self.container_name} cat {self.config_path}"
        config_text = await self.ssh.run_command(cmd)

        # 1. Find all AllowedIPs = 10.8.X.Y/32 in the file
        file_ips = re.findall(r"AllowedIPs\s*=\s*([0-9\.]+)/32", config_text)

        # 2. Find all IPs currently assigned in the database for this inbound
        db_ips = []

        from sqlalchemy import select
        from app.database import async_session_factory

        async with async_session_factory() as session:
            result = await session.execute(
                select(InboundConnection).where(InboundConnection.inbound_id == inbound.id)
            )
            connections = result.scalars().all()
            for conn in connections:
                payload = conn.provider_payload or {}
                if ip := payload.get("client_ip"):
                    db_ips.append(ip)

        # Combine all used IPs
        all_used_ips = set(file_ips + db_ips)

        if not all_used_ips:
            # Try to find the interface Address to know the subnet
            iface_match = re.search(r"Address\s*=\s*([0-9\.]+)/[0-9]+", config_text)
            base_ip = iface_match.group(1) if iface_match else "10.8.1.1"  # default assumption
            next_ip_obj = ipaddress.IPv4Address(base_ip) + 1
        else:
            # Sort IPs and take the last + 1
            ip_objs = sorted([ipaddress.IPv4Address(ip) for ip in all_used_ips])
            next_ip_obj = ip_objs[-1] + 1

        return str(next_ip_obj)

    async def _get_awg_server_params(self) -> dict[str, str]:
        """Extract obfuscation parameters from the server config."""
        cmd = f"docker exec -i {self.container_name} cat {self.config_path}"
        config_text = await self.ssh.run_command(cmd)

        params = {}
        for line in config_text.splitlines():
            if "=" in line:
                key, val = [x.strip() for x in line.split("=", 1)]
                params[key] = val
        return params

    async def add_client(
        self,
        inbound: Inbound,
        subscription: Subscription,
        client_uuid: str | None = None,
        email: str | None = None,
    ) -> dict[str, Any]:
        """Add a peer to AmneziaWG using original CLI sequence."""
        # 1. Generate keys
        priv_key_cmd = f"docker exec -i {self.container_name} awg genkey"
        private_key = await self.ssh.run_command(priv_key_cmd)

        pub_key_cmd = (
            f"docker exec -i {self.container_name} bash -c 'echo \"{private_key}\" | awg pubkey'"
        )
        public_key = await self.ssh.run_command(pub_key_cmd)

        # We need a PresharedKey as per original Amnezia
        psk = await self._get_server_psk()

        # 2. Get next free IP
        next_ip = await self._find_next_free_ip(inbound)

        # 3. Add to configuration file
        peer_block = f"\\n[Peer]\\nPublicKey = {public_key}\\nPresharedKey = {psk}\\nAllowedIPs = {next_ip}/32\\n"
        append_cmd = f"docker exec -i {self.container_name} bash -c 'echo -e \"{peer_block}\" >> {self.config_path}'"
        await self.ssh.run_command(append_cmd)

        # 4. Sync configuration on the fly
        sync_cmd = f"docker exec -i {self.container_name} bash -c 'awg syncconf {self.interface_name} <(awg-quick strip {self.config_path})'"
        await self.ssh.run_command(sync_cmd)

        # 5. Extract Server Params for config generation
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
        """Remove a peer from AmneziaWG."""
        payload = connection.provider_payload or {}
        public_key = payload.get("public_key")

        if not public_key:
            return False

        try:
            # 1. Immediate kick from kernel
            kick_cmd = f"docker exec -i {self.container_name} awg set {self.interface_name} peer {public_key} remove"
            await self.ssh.run_command(kick_cmd)

            # 2. Remove from config file using Python directly to avoid bash quoting issues
            config_text = await self.ssh.run_command(
                f"docker exec -i {self.container_name} cat {self.config_path}"
            )

            blocks = config_text.split("[Peer]")
            new_blocks = [blocks[0]]  # Add the [Interface] block back

            for block in blocks[1:]:
                if public_key not in block:
                    new_blocks.append(block)

            new_config_text = "[Peer]".join(new_blocks)

            # Write it back via stdin
            write_cmd = f"docker exec -i {self.container_name} bash -c 'cat > {self.config_path}'"
            await self.ssh.run_command(write_cmd, input_data=new_config_text)

            # 3. Sync again for consistency (optional but safe)
            sync_cmd = f"docker exec -i {self.container_name} bash -c 'awg syncconf {self.interface_name} <(awg-quick strip {self.config_path})'"
            await self.ssh.run_command(sync_cmd)
            return True
        except Exception as e:
            logger.error(f"Failed to remove AWG client: {e}")
            return False

    async def disable_client(self, inbound: Inbound, connection: InboundConnection) -> bool:
        """Temporarily disable a peer by removing it from the kernel and config."""
        return await self.remove_client(inbound, connection)

    async def enable_client(self, inbound: Inbound, connection: InboundConnection) -> bool:
        """Re-enable a disabled peer by adding it back to the config."""
        payload = connection.provider_payload or {}
        public_key = payload.get("public_key")
        psk = payload.get("psk")
        client_ip = payload.get("client_ip")

        if not public_key or not psk or not client_ip:
            logger.error("Missing keys or IP in provider_payload for AWG client.")
            return False

        try:
            # 1. Check if it's already in the config
            check_cmd = f"docker exec -i {self.container_name} grep -q {public_key} {self.config_path} && echo 'EXISTS' || echo 'MISSING'"
            status = await self.ssh.run_command(check_cmd)

            if "MISSING" in status:
                # 2. Add to configuration file
                peer_block = f"\\n[Peer]\\nPublicKey = {public_key}\\nPresharedKey = {psk}\\nAllowedIPs = {client_ip}/32\\n"
                append_cmd = f"docker exec -i {self.container_name} bash -c 'echo -e \"{peer_block}\" >> {self.config_path}'"
                await self.ssh.run_command(append_cmd)

                # 3. Sync configuration
                sync_cmd = f"docker exec -i {self.container_name} bash -c 'awg syncconf {self.interface_name} <(awg-quick strip {self.config_path})'"
                await self.ssh.run_command(sync_cmd)

            return True
        except Exception as e:
            logger.error(f"Failed to enable AWG client: {e}")
            return False

    def _generate_qr_code(self, config_str: str) -> str:
        """Generate a base64 encoded QR code PNG from the config string."""
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
        """Generate the WireGuard/AmneziaWG .conf file and QR code."""
        payload = connection.provider_payload or {}
        sp = payload.get("server_params", {})

        private_key = payload.get("private_key")
        client_ip = payload.get("client_ip")
        psk = payload.get("psk")

        # Derive server host from Server.url
        host = self.ssh.host
        port = sp.get("ListenPort", "51820")
        server_pub_key = await self._get_server_public_key()

        # Build the config
        config_lines = [
            "[Interface]",
            f"PrivateKey = {private_key}",
            f"Address = {client_ip}/32",
            "DNS = 1.1.1.1, 8.8.8.8",
        ]

        # Add AWG obfuscation parameters if they exist
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
        """No persistent HTTP session to close."""
        pass
