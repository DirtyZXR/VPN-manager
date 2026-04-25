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

import logging

from app.services.installers.base import BASE_DIR, BaseInstaller

logger = logging.getLogger(__name__)

MTPROXY_SERVICE_DIR = f"{BASE_DIR}/mtproxy"
MTPROXY_CONTAINER = "mtproxy"

MTG_IMAGE = "nineseconds/mtg:2"
MTG_MULTI_IMAGE = "ghcr.io/dolonet/mtg-multi:latest"


class MTProxyInstaller(BaseInstaller):
    """Installer for MTProxy (mtg / mtg-multi)."""

    SERVICE_NAME = MTPROXY_CONTAINER

    async def install(
        self,
        port: int = 443,
        domain: str = "google.com",
        implementation: str = "mtg-multi",
        max_connections: int = 5000,
    ) -> dict:
        """Install MTProxy on the server.

        Args:
            port: TCP port for MTProxy to listen on.
            domain: Fake-TLS domain for domain fronting.
            implementation: 'mtg' or 'mtg-multi'.
            max_connections: Max concurrent connections (mtg-multi only).

        Returns:
            Dict with installation details.

        Raises:
            RuntimeError: If already installed or port occupied.
        """
        if await self.check_already_installed():
            raise RuntimeError(f"MTProxy already installed on {self.ssh.host}")

        if not await self.check_port_free(port):
            raise RuntimeError(f"Port {port}/tcp is occupied on {self.ssh.host}")

        if implementation not in ("mtg", "mtg-multi"):
            raise ValueError(f"Unknown implementation: {implementation}")

        image = MTG_MULTI_IMAGE if implementation == "mtg-multi" else MTG_IMAGE
        service_dir = MTPROXY_SERVICE_DIR
        dirs_to_clean = [service_dir]
        ports_to_clean = [(port, "tcp")]

        try:
            await self.prepare_host()

            logger.info(
                f"Installing MTProxy ({implementation}) on {self.ssh.host}:{port}"
            )

            await self._open_firewall_port(port)
            await self._create_dirs(service_dir)
            await self._generate_secret(service_dir, domain)
            await self._write_config(service_dir, port, domain, implementation, max_connections)
            await self._write_compose_file(service_dir, port, image, implementation)
            await self._start_container(service_dir)
            await self._verify(port)

            logger.info(f"MTProxy ({implementation}) installed on {self.ssh.host}:{port}")

            return {
                "container_name": f"vpnbot-{MTPROXY_CONTAINER}",
                "image": image,
                "implementation": implementation,
                "port": port,
                "domain": domain,
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
            f"docker run --rm {MTG_MULTI_IMAGE} generate-secret --hex {domain} "
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
                f"public-ipv4 = \"auto\"\n"
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
            f"docker run --rm {MTG_MULTI_IMAGE} generate-secret --hex {domain}"
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
