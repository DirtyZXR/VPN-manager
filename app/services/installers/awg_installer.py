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

import contextlib
import logging
import random

from app.services.installers.base import BASE_DIR, AlreadyInstalledError, BaseInstaller

logger = logging.getLogger(__name__)

AWG_SERVICE_DIR = f"{BASE_DIR}/awg"
AWG_CONTAINER_NAME = "awg"
AWG_INTERFACE = "awg0"

AWG_SUBNET_DEFAULT = "10.8.0.0"
AWG_SUBNET_CIDR_DEFAULT = 24
AWG_SUBNET_IP_DEFAULT = "10.8.0.1"


I1_DEFAULT = "<r 2><b 0x858000010001000000000669636c6f756403636f6d0000010001c00c000100010000105a00044d583737>"


def generate_obfuscation_params() -> dict[str, str]:
    """Generate AWG v2 obfuscation parameters matching original AmneziaVPN.

    H1-H4: non-overlapping ascending ranges in [5, 2^31-1].
    I1: DNS A response for icloud.com (default anti-DPI junk).
    I2-I5: empty (reserved for future use).
    """
    max_val = (2**31) - 1
    headers = []
    lo = 5
    for _ in range(4):
        first = random.randint(lo, max_val)
        second = random.randint(first, max_val)
        headers.append(f"{first}-{second}")
        lo = second + 1

    return {
        "Jc": str(random.randint(3, 10)),
        "Jmin": str(random.randint(10, 50)),
        "Jmax": str(random.randint(50, 100)),
        "S1": str(random.randint(15, 100)),
        "S2": str(random.randint(15, 100)),
        "S3": str(random.randint(15, 100)),
        "S4": str(random.randint(15, 100)),
        "H1": headers[0],
        "H2": headers[1],
        "H3": headers[2],
        "H4": headers[3],
        "I1": I1_DEFAULT,
        "I2": "",
        "I3": "",
        "I4": "",
        "I5": "",
    }


class AWGInstaller(BaseInstaller):
    """Installer for AmneziaWG service."""

    SERVICE_NAME = AWG_CONTAINER_NAME

    async def discover_existing(self) -> dict:
        """Read configs from an existing AWG installation.

        Returns dict with: port, subnet_ip, subnet_cidr, obfuscation,
        server_public_key, server_private_key.
        """
        import re

        config = await self._cmd(f"cat {AWG_SERVICE_DIR}/data/awg0.conf")

        port_match = re.search(r"ListenPort\s*=\s*(\d+)", config)
        addr_match = re.search(r"Address\s*=\s*([\d.]+)/(\d+)", config)
        pk_match = re.search(r"PrivateKey\s*=\s*(\S+)", config)

        obfuscation = {}
        for key in ("Jc", "Jmin", "Jmax", "S1", "S2", "S3", "S4", "H1", "H2", "H3", "H4"):
            m = re.search(rf"{key}\s*=\s*(.+)", config)
            if m:
                obfuscation[key] = m.group(1).strip()
        for key in ("I1", "I2", "I3", "I4", "I5"):
            m = re.search(rf"{key}\s*=\s*(.*)", config)
            obfuscation[key] = m.group(1).strip() if m else ""

        public_key = ""
        with contextlib.suppress(Exception):
            public_key = (await self._cmd(
                f"cat {AWG_SERVICE_DIR}/data/wireguard_server_public_key.key"
            )).strip()

        return {
            "port": int(port_match.group(1)) if port_match else 51820,
            "subnet_ip": addr_match.group(1) if addr_match else "10.8.0.1",
            "subnet_cidr": int(addr_match.group(2)) if addr_match else 24,
            "obfuscation": obfuscation if obfuscation else generate_obfuscation_params(),
            "server_public_key": public_key,
            "server_private_key": pk_match.group(1).strip() if pk_match else "",
        }

    async def install(
        self,
        port: int,
        subnet_ip: str = AWG_SUBNET_IP_DEFAULT,
        subnet_cidr: int = AWG_SUBNET_CIDR_DEFAULT,
        obfuscation: dict[str, str] | None = None,
        force: bool = False,
    ) -> dict:
        """Install AmneziaWG on the server.

        Args:
            port: UDP port for AWG to listen on.
            subnet_ip: Server IP within the VPN subnet (e.g. '10.8.0.1').
            subnet_cidr: Subnet CIDR mask (e.g. 24).
            obfuscation: AWG obfuscation params. Auto-generated if None.
            force: Remove existing container before installing.

        Returns:
            Dict with installation details (port, subnet, obfuscation params).

        Raises:
            AlreadyInstalledError: If service already installed and force=False.
            RuntimeError: If port is occupied.
        """
        service_dir = f"{AWG_SERVICE_DIR}"
        dirs_to_clean: list[str] = []
        ports_to_clean: list[tuple[int, str]] = []

        try:
            logger.info(
                f"Installing AWG on {self.ssh.host}:{port} "
                f"subnet={subnet_ip}/{subnet_cidr}"
            )

            await self._progress(1, 11, "Подготовка сервера (Docker, утилиты)...")
            await self.prepare_host()

            if await self.check_already_installed():
                if force:
                    logger.warning(f"Force reinstall: removing existing vpnbot-awg on {self.ssh.host}")
                    await self._cmd("docker rm -f vpnbot-awg 2>/dev/null || true")
                    await self._cmd("sleep 2")
                else:
                    raise AlreadyInstalledError(
                        f"AmneziaWG уже установлен на {self.ssh.host}. "
                        "Для переустановки нажмите кнопку ниже."
                    )

            if not await self.check_port_free(port):
                raise RuntimeError(f"Port {port}/udp is occupied on {self.ssh.host}")

            if obfuscation is None:
                obfuscation = generate_obfuscation_params()

            dirs_to_clean = [service_dir]
            ports_to_clean = [(port, "udp")]

            await self._progress(2, 11, "Открытие портов в файрволе...")
            await self._open_firewall_port(port)

            await self._progress(3, 11, "Создание директорий...")
            await self._create_service_dir(service_dir)

            await self._progress(4, 11, "Запись Dockerfile...")
            await self._write_dockerfile(service_dir)

            await self._progress(5, 11, "Запись стартового скрипта...")
            await self._write_start_script(service_dir, subnet_ip, subnet_cidr)

            await self._progress(6, 11, "Запись docker-compose.yml...")
            await self._write_compose_file(service_dir, port)

            await self._progress(7, 11, "Сборка Docker-образа (может занять 1-2 мин)...")
            await self._build_image()

            await self._progress(8, 11, "Запуск контейнера...")
            await self._start_container(port)

            await self._progress(9, 11, "Генерация ключей и конфигурации...")
            await self._generate_keys_and_config(
                port, subnet_ip, subnet_cidr, obfuscation
            )

            await self._progress(10, 11, "Перезапуск с конфигурацией...")
            await self._restart_container()

            await self._progress(11, 11, "Установка завершена")

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
    entrypoint: ["/opt/amnezia/start.sh"]
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
        obfuscation: dict[str, str],
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

        obf_keys = ["Jc", "Jmin", "Jmax", "S1", "S2", "S3", "S4", "H1", "H2", "H3", "H4"]
        obf_lines = "\n".join(f"{k} = {obfuscation[k]}" for k in obf_keys if obfuscation.get(k))

        i_keys = ["I1", "I2", "I3", "I4", "I5"]
        i_lines = "\n".join(f"# {k} = {obfuscation.get(k, '')}" for k in i_keys)

        config = (
            f"[Interface]\n"
            f"PrivateKey = {private_key}\n"
            f"Address = {subnet_ip}/{subnet_cidr}\n"
            f"ListenPort = {port}\n"
            f"{obf_lines}\n"
            f"{i_lines}\n"
        )

        await self._cmd(
            f"docker exec -i {name} bash -c 'cat > /opt/amnezia/awg/awg0.conf'",
            input_data=config,
        )

    async def _restart_container(self) -> None:
        name = f"vpnbot-{AWG_CONTAINER_NAME}"
        await self._cmd(f"docker restart {name}")
        await self._cmd("sleep 3")
