"""MTProxy installer with support for two implementations:

1. mtg (upstream) — nineseconds/mtg:2
   Single secret, no stats API. Mature, 3.4k stars.

2. mtg-multi (fork) — ghcr.io/dolonet/mtg-multi:latest
   Multi-secret, Stats API, throttling. Fork of mtg, 32 stars.

Both use TOML config, Fake-TLS, domain fronting, doppelganger.
mtg-multi config is a superset of mtg config.

Container name: vpnbot-mtproxy
Config dir on server: /opt/vpnbot/mtproxy/
"""

from loguru import logger

from app.services.installers.base import BASE_DIR, AlreadyInstalledError, BaseInstaller

MTPROXY_SERVICE_DIR = f"{BASE_DIR}/mtproxy"
MTPROXY_CONTAINER = "mtproxy"

MTG_IMAGE = "nineseconds/mtg:2"
MTG_MULTI_IMAGE = "ghcr.io/dolonet/mtg-multi:latest"


class MTProxyInstaller(BaseInstaller):
    """Installer for MTProxy (mtg / mtg-multi)."""

    SERVICE_NAME = MTPROXY_CONTAINER

    async def discover_existing(self) -> dict:
        """Read config.toml from an existing MTProxy installation.

        Returns dict with: port, domain, implementation, max_connections, secret.
        """
        import re

        from app.utils import extract_mtproxy_domain

        async with self.ssh:
            config = await self._cmd(f"cat {MTPROXY_SERVICE_DIR}/config.toml")

        bind_match = re.search(r'bind-to\s*=\s*"0\.0\.0\.0:(\d+)"', config)
        secret_match = re.search(r'(?:secret|default)\s*=\s*"([^"]+)"', config)
        conns_match = re.search(r"max-connections\s*=\s*(\d+)", config)

        implementation = "mtg-multi" if "max-connections" in config or "secrets" in config else "mtg"

        secret = secret_match.group(1) if secret_match else None
        domain = extract_mtproxy_domain(secret) if secret else "google.com"

        return {
            "port": int(bind_match.group(1)) if bind_match else 443,
            "domain": domain or "google.com",
            "implementation": implementation,
            "max_connections": int(conns_match.group(1)) if conns_match else 5000,
            "secret": secret,
        }

    async def install(
        self,
        port: int = 443,
        domain: str = "google.com",
        implementation: str = "mtg-multi",
        max_connections: int = 5000,
        force: bool = False,
    ) -> dict:
        """Install MTProxy on the server.

        Args:
            port: TCP port for MTProxy to listen on.
            domain: Fake-TLS domain for domain fronting.
            implementation: 'mtg' or 'mtg-multi'.
            max_connections: Max concurrent connections (mtg-multi only).
            force: Remove existing container before installing.

        Returns:
            Dict with installation details.

        Raises:
            AlreadyInstalledError: If already installed and force=False.
            RuntimeError: If port is occupied.
        """
        service_dir = MTPROXY_SERVICE_DIR
        dirs_to_clean: list[str] = []
        ports_to_clean: list[tuple[int, str]] = []

        try:
            async with self.ssh:
                logger.info(
                    f"Installing MTProxy ({implementation}) on {self.ssh.host}:{port}"
                )

                await self._progress(1, 9, "Подготовка сервера (Docker, утилиты)...")
                await self.prepare_host()

                if await self.check_already_installed():
                    if force:
                        logger.warning(f"Force reinstall: removing existing vpnbot-mtproxy on {self.ssh.host}")
                        await self._cmd("docker rm -f vpnbot-mtproxy 2>/dev/null || true")
                        await self._cmd("sleep 2")
                    else:
                        raise AlreadyInstalledError(
                            f"MTProxy уже установлен на {self.ssh.host}. "
                            "Для переустановки нажмите кнопку ниже."
                        )

                if not await self.check_port_free(port):
                    raise RuntimeError(f"Port {port}/tcp is occupied on {self.ssh.host}")

                if implementation not in ("mtg", "mtg-multi"):
                    raise ValueError(f"Unknown implementation: {implementation}")

                image = MTG_MULTI_IMAGE if implementation == "mtg-multi" else MTG_IMAGE
                dirs_to_clean = [service_dir]
                ports_to_clean = [(port, "tcp")]

                await self._progress(2, 9, "Открытие портов в файрволе...")
                await self._open_firewall_port(port)

                await self._progress(3, 9, "Создание директорий...")
                await self._create_dirs(service_dir)

                await self._progress(4, 9, "Генерация секрета...")
                await self._generate_secret(service_dir, domain)
                secret = (await self._cmd(f"cat {service_dir}/secret.txt")).strip()

                await self._progress(5, 9, "Запись конфигурации...")
                await self._write_config(service_dir, port, domain, implementation, max_connections)

                await self._progress(6, 9, "Запись docker-compose.yml...")
                await self._write_compose_file(service_dir, port, image, implementation)

                await self._progress(7, 9, "Запуск контейнера...")
                await self._start_container(service_dir)

                await self._progress(8, 9, "Проверка доступности...")
                await self._verify(port)

                await self._progress(9, 9, "Установка завершена")

                logger.info(f"MTProxy ({implementation}) installed on {self.ssh.host}:{port}")

                return {
                    "container_name": f"vpnbot-{MTPROXY_CONTAINER}",
                    "image": image,
                    "implementation": implementation,
                    "port": port,
                    "domain": domain,
                    "secret": secret,
                    "max_connections": max_connections if implementation == "mtg-multi" else None,
                    "service_dir": service_dir,
                }
        except Exception:
            logger.exception("MTProxy installation failed, running cleanup")
            await self.cleanup(
                dirs=dirs_to_clean,
                ports=ports_to_clean,
            )
            raise

    async def _open_firewall_port(self, port: int) -> None:
        await self.port_manager.open_port(port, "tcp")

    async def _create_dirs(self, service_dir: str) -> None:
        await self.ensure_dirs(service_dir)

    async def _generate_secret(self, service_dir: str, domain: str) -> None:
        await self._cmd(
            f"docker run --rm {MTG_MULTI_IMAGE} generate-secret {domain} "
            f"> {service_dir}/secret.txt"
        )

    async def _write_config(
        self,
        service_dir: str,
        port: int,
        domain: str,
        implementation: str,
        max_connections: int,
    ) -> None:
        secret = (await self._cmd(f"cat {service_dir}/secret.txt")).strip()

        if implementation == "mtg-multi":
            config = (
                f'bind-to = "0.0.0.0:{port}"\n'
                f"api-bind-to = \"127.0.0.1:9090\"\n"
                f"\n"
                f"[throttle]\n"
                f"max-connections = {max_connections}\n"
                f"check-interval = \"5s\"\n"
                f"\n"
                f"[secrets]\n"
                f"default = \"{secret}\"\n"
            )
        else:
            config = (
                f'secret = "{secret}"\n'
                f'bind-to = "0.0.0.0:{port}"\n'
            )

        await self._write_file(f"{service_dir}/config.toml", config)

    async def _write_compose_file(
        self,
        service_dir: str,
        port: int,
        image: str,
        implementation: str,
    ) -> None:
        stats_port = ""
        if implementation == "mtg-multi":
            stats_port = "\n      - \"9090:9090\""

        compose = (
            f"services:\n"
            f"  mtproxy:\n"
            f"    image: {image}\n"
            f"    container_name: vpnbot-mtproxy\n"
            f"    restart: unless-stopped\n"
            f"    ports:\n"
            f"      - \"{port}:{port}/tcp\""
            f"{stats_port}\n"
            f"    volumes:\n"
            f"      - ./config.toml:/config.toml:ro\n"
            f"    command: [\"run\", \"/config.toml\"]\n"
            f"    labels:\n"
            f"      - \"vpnbot.service=mtproxy\"\n"
        )
        await self._write_file(f"{service_dir}/docker-compose.yml", compose)

    async def _start_container(self, service_dir: str) -> None:
        await self._cmd(f"cd {service_dir} && docker compose up -d")
        await self._cmd("sleep 5")

    async def _verify(self, port: int) -> None:
        result = await self._cmd(
            f"ss -tln | grep ':{port} '"
        )
        if not result.strip():
            raise RuntimeError(
                f"MTProxy verification failed: port {port} not listening"
            )
        logger.info(f"MTProxy verified: port {port} listening")

    async def add_secret(self, name: str, domain: str = "google.com") -> str:
        """Add a new named secret to mtg-multi config.

        Args:
            name: Secret name (user identifier).
            domain: Fake-TLS domain for this secret.

        Returns:
            Generated secret string.
        """
        secret = (await self._cmd(
            f"docker run --rm {MTG_MULTI_IMAGE} generate-secret {domain}"
        )).strip()

        config_path = f"{MTPROXY_SERVICE_DIR}/config.toml"
        await self._cmd(
            f"sed -i '/\\[secrets\\]/a {name} = \"{secret}\"' {config_path}"
        )
        await self._cmd(f"docker restart vpnbot-{MTPROXY_CONTAINER}")
        return secret

    async def remove_secret(self, name: str) -> None:
        """Remove a named secret from mtg-multi config."""
        config_path = f"{MTPROXY_SERVICE_DIR}/config.toml"
        await self._cmd(f"sed -i '/^{name} = /d' {config_path}")
        await self._cmd(f"docker restart vpnbot-{MTPROXY_CONTAINER}")

    async def get_stats(self) -> dict | None:
        """Get per-user stats from mtg-multi Stats API."""
        try:
            result = await self._cmd(
                "curl -s http://127.0.0.1:9090/stats"
            )
            import json
            return json.loads(result)
        except Exception:
            return None
