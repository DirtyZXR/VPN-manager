"""AmneziaWG installer following original AmneziaVPN logic.

Reference: amnezia-client/client/server_scripts/awg/

Flow:
1. prepare_host() — Docker, utils, UFW (via BaseInstaller)
2. generate_obfuscation_params() — random or admin-defined Jc/Jmin/Jmax/S1-S4/H1-H4
3. install(port, subnet_cidr, obfuscation_params) — full installation
4. Saves config to /opt/vpnbot/awg/ on the server

Container name: vpnbot-awg
Config dir on server: /opt/vpnbot/awg/
"""

import logging
import random

from app.services.installers.base import BASE_DIR, BaseInstaller

logger = logging.getLogger(__name__)

AWG_SERVICE_DIR = f"{BASE_DIR}/awg"
AWG_CONTAINER_NAME = "awg"
AWG_INTERFACE = "awg0"

AWG_SUBNET_DEFAULT = "10.8.0.0"
AWG_SUBNET_CIDR_DEFAULT = 24
AWG_SUBNET_IP_DEFAULT = "10.8.0.1"


def generate_obfuscation_params() -> dict[str, int]:
    """Generate random AWG obfuscation parameters within safe ranges.

    Based on original AmneziaVPN defaults and community recommendations.
    """
    return {
        "Jc": random.randint(3, 10),
        "Jmin": random.randint(50, 300),
        "Jmax": random.randint(500, 1500),
        "S1": random.randint(20, 100),
        "S2": random.randint(20, 100),
        "S3": random.randint(20, 100),
        "S4": random.randint(20, 100),
        "H1": random.randint(1, 2**32 - 1),
        "H2": random.randint(1, 2**32 - 1),
        "H3": random.randint(1, 2**32 - 1),
        "H4": random.randint(1, 2**32 - 1),
    }


class AWGInstaller(BaseInstaller):
    """Installer for AmneziaWG service."""

    SERVICE_NAME = AWG_CONTAINER_NAME

    async def install(
        self,
        port: int,
        subnet_ip: str = AWG_SUBNET_IP_DEFAULT,
        subnet_cidr: int = AWG_SUBNET_CIDR_DEFAULT,
        obfuscation: dict[str, int] | None = None,
    ) -> dict:
        """Install AmneziaWG on the server.

        Args:
            port: UDP port for AWG to listen on.
            subnet_ip: Server IP within the VPN subnet (e.g. '10.8.0.1').
            subnet_cidr: Subnet CIDR mask (e.g. 24).
            obfuscation: AWG obfuscation params. Auto-generated if None.

        Returns:
            Dict with installation details (port, subnet, obfuscation params).

        Raises:
            RuntimeError: If service already installed or port is occupied.
        """
        if await self.check_already_installed():
            raise RuntimeError(f"AWG already installed on {self.ssh.host}")

        if not await self.check_port_free(port):
            raise RuntimeError(f"Port {port}/udp is occupied on {self.ssh.host}")

        if obfuscation is None:
            obfuscation = generate_obfuscation_params()

        service_dir = f"{AWG_SERVICE_DIR}"
        dirs_to_clean = [service_dir]
        ports_to_clean = [(port, "udp")]

        try:
            await self.prepare_host()

            logger.info(
                f"Installing AWG on {self.ssh.host}:{port} "
                f"subnet={subnet_ip}/{subnet_cidr}"
            )

            await self._open_firewall_port(port)
            await self._create_service_dir(service_dir)
            await self._write_dockerfile(service_dir)
            await self._write_start_script(service_dir, subnet_ip, subnet_cidr)
            await self._write_compose_file(service_dir, port)
            await self._build_image()
            await self._start_container(port)
            await self._generate_keys_and_config(
                port, subnet_ip, subnet_cidr, obfuscation
            )
            await self._restart_container()

            logger.info(f"AWG installed successfully on {self.ssh.host}:{port}")

            return {
                "container_name": f"vpnbot-{AWG_CONTAINER_NAME}",
                "port": port,
                "subnet_ip": subnet_ip,
                "subnet_cidr": subnet_cidr,
                "obfuscation": obfuscation,
                "service_dir": service_dir,
            }
        except Exception:
            logger.exception("AWG installation failed, running cleanup")
            await self.cleanup(
                dirs=dirs_to_clean,
                ports=ports_to_clean,
            )
            raise

    async def _open_firewall_port(self, port: int) -> None:
        await self.port_manager.open_port(port, "udp")

    async def _create_service_dir(self, service_dir: str) -> None:
        await self.ensure_dirs(service_dir)

    async def _write_dockerfile(self, service_dir: str) -> None:
        dockerfile = (
            "FROM amneziavpn/amneziawg-go:latest\n"
            "LABEL maintainer=\"vpnbot\"\n"
            "RUN apk add --no-cache bash curl dumb-init\n"
            "RUN apk --update upgrade --no-cache\n"
            "RUN mkdir -p /opt/amnezia\n"
            "COPY start.sh /opt/amnezia/start.sh\n"
            "RUN chmod a+x /opt/amnezia/start.sh\n"
        )
        await self._write_file(f"{service_dir}/Dockerfile", dockerfile)

    async def _write_start_script(
        self, service_dir: str, subnet_ip: str, subnet_cidr: int
    ) -> None:
        script = f"""#!/bin/bash
echo "Container startup"
awg-quick down /opt/amnezia/awg/awg0.conf 2>/dev/null || true

if [ -f /opt/amnezia/awg/awg0.conf ]; then awg-quick up /opt/amnezia/awg/awg0.conf; fi

iptables -A INPUT -i awg0 -j ACCEPT
iptables -A FORWARD -i awg0 -j ACCEPT
iptables -A OUTPUT -o awg0 -j ACCEPT

iptables -A FORWARD -i awg0 -o eth0 -s {subnet_ip}/{subnet_cidr} -j ACCEPT
iptables -A FORWARD -i awg0 -o eth1 -s {subnet_ip}/{subnet_cidr} -j ACCEPT
iptables -A FORWARD -m state --state ESTABLISHED,RELATED -j ACCEPT

iptables -t nat -A POSTROUTING -s {subnet_ip}/{subnet_cidr} -o eth0 -j MASQUERADE
iptables -t nat -A POSTROUTING -s {subnet_ip}/{subnet_cidr} -o eth1 -j MASQUERADE

tail -f /dev/null
"""
        await self._write_file(f"{service_dir}/start.sh", script)

    async def _write_compose_file(self, service_dir: str, port: int) -> None:
        compose = f"""services:
  awg:
    build: {service_dir}
    container_name: vpnbot-awg
    restart: unless-stopped
    privileged: true
    cap_add:
      - NET_ADMIN
      - SYS_MODULE
    ports:
      - "{port}:{port}/udp"
    volumes:
      - {service_dir}/data:/opt/amnezia/awg
      - /lib/modules:/lib/modules:ro
    sysctls:
      - net.ipv4.conf.all.src_valid_mark=1
    labels:
      - "vpnbot.service=awg"
"""
        await self._write_file(f"{service_dir}/docker-compose.yml", compose)

    async def _build_image(self) -> None:
        await self._cmd(f"cd {AWG_SERVICE_DIR} && docker compose build --no-cache")

    async def _start_container(self, port: int) -> None:
        await self._cmd(f"cd {AWG_SERVICE_DIR} && docker compose up -d")
        await self._cmd("sleep 5")

    async def _generate_keys_and_config(
        self,
        port: int,
        subnet_ip: str,
        subnet_cidr: int,
        obfuscation: dict[str, int],
    ) -> None:
        name = f"vpnbot-{AWG_CONTAINER_NAME}"

        private_key = await self._cmd(
            f"docker exec -i {name} awg genkey"
        )
        public_key = await self._cmd(
            f"docker exec -i {name} bash -c 'echo \"{private_key}\" | awg pubkey'"
        )
        psk = await self._cmd(
            f"docker exec -i {name} awg genpsk"
        )

        key_files = {
            "wireguard_server_private_key.key": private_key,
            "wireguard_server_public_key.key": public_key,
            "wireguard_psk.key": psk,
        }
        for filename, content in key_files.items():
            await self._cmd(
                f"docker exec -i {name} bash -c 'cat > /opt/amnezia/awg/{filename}'",
                input_data=content,
            )

        obf_lines = "\n".join(
            f"{k} = {v}" for k, v in obfuscation.items()
        )

        config = (
            f"[Interface]\n"
            f"PrivateKey = {private_key}\n"
            f"Address = {subnet_ip}/{subnet_cidr}\n"
            f"ListenPort = {port}\n"
            f"{obf_lines}\n"
        )

        await self._cmd(
            f"docker exec -i {name} bash -c 'cat > /opt/amnezia/awg/awg0.conf'",
            input_data=config,
        )

    async def _restart_container(self) -> None:
        name = f"vpnbot-{AWG_CONTAINER_NAME}"
        await self._cmd(f"docker restart {name}")
        await self._cmd("sleep 3")
