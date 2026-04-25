"""Base installer providing shared host preparation and cleanup for all VPN service installers.

All installers (AWG, XUI, MTProxy) inherit from BaseInstaller which handles:
- Docker installation and verification
- OS detection (multi-distro: Debian, Fedora, CentOS, openSUSE, Arch)
- Essential utilities (curl, jq)
- UFW firewall setup
- Container naming convention: vpnbot-<service>
- Rollback/cleanup on failure

Architecture note (TODO): Currently each SSH command opens/closes a separate connection
via SSHManager.run_command(). For installers that run many sequential commands, consider
adding a persistent session context manager to SSHManager:

    async with ssh.session() as conn:
        await conn.run("cmd1")
        result = await conn.run("cmd2")
        ...

This would reduce connection overhead for installer workflows. Current workaround: batch
commands into single bash scripts sent via one run_command() call.
"""

import logging
import random
import string

from app.services.ssh_service import SSHManager
from app.services.vpn_providers.port_manager import PortManager

logger = logging.getLogger(__name__)

CONTAINER_PREFIX = "vpnbot"
BASE_DIR = "/opt/vpnbot"
PREPARED_MARKER = f"{BASE_DIR}/.prepared"


def _container_name(service: str) -> str:
    return f"{CONTAINER_PREFIX}-{service}"


class BaseInstaller:
    """Base class for all VPN service installers."""

    SERVICE_NAME: str = ""

    def __init__(self, ssh: SSHManager) -> None:
        self.ssh = ssh
        self.port_manager = PortManager(ssh)

    # ── Container identification ──────────────────────────────────────

    async def preflight_check(self) -> tuple[bool, str]:
        """Run pre-installation checks: ping + SSH connectivity.

        Returns:
            Tuple of (success: bool, message: str).
        """
        from app.services.server_monitor import ServerMonitor

        host = self.ssh.host

        ping_ok = await ServerMonitor.ping(host)
        if not ping_ok:
            return False, f"Сервер {host} не отвечает на ping"

        ssh_ok = await self.ssh.test_connection()
        if not ssh_ok:
            return False, f"Не удалось подключиться по SSH к {host}:{self.ssh.port}. Проверьте логин/пароль/ключ."

        return True, "OK"

    async def check_already_installed(self) -> bool:
        """Check if a container with our naming convention already exists."""
        name = _container_name(self.SERVICE_NAME)
        result = await self.ssh.run_command(
            f"docker ps -a --filter name=^{name}$ --format '{{{{.Names}}}}'"
        )
        return bool(result.strip())

    async def list_installed_services(self) -> list[str]:
        """List all vpnbot-managed containers on the server."""
        result = await self.ssh.run_command(
            f"docker ps -a --filter name={CONTAINER_PREFIX}- --format '{{{{.Names}}}}'"
        )
        names = [n.strip() for n in result.strip().split("\n") if n.strip()]
        return [n.removeprefix(f"{CONTAINER_PREFIX}-") for n in names]

    # ── Host preparation ──────────────────────────────────────────────

    async def is_prepared(self) -> bool:
        """Check if host has already been prepared."""
        try:
            result = await self.ssh.run_command(f"test -f {PREPARED_MARKER} && echo yes")
            return result.strip() == "yes"
        except Exception:
            return False

    async def prepare_host(self) -> None:
        """Prepare server: install Docker, utils, configure UFW. Skips if already done."""
        if await self.is_prepared():
            logger.info(f"Host already prepared ({PREPARED_MARKER} exists), skipping")
            return

        logger.info(f"Preparing host {self.ssh.host}...")
        await self._ensure_docker()
        await self._ensure_utils()
        await self._ensure_ufw()
        await self._mark_prepared()
        logger.info(f"Host {self.ssh.host} prepared successfully")

    async def _detect_os(self) -> str:
        """Detect the OS package manager. Returns: debian, fedora, centos, opensuse, archlinux."""
        script = (
            "if which apt-get > /dev/null 2>&1; then echo debian;"
            "elif which dnf > /dev/null 2>&1; then echo fedora;"
            "elif which yum > /dev/null 2>&1; then echo centos;"
            "elif which zypper > /dev/null 2>&1; then echo opensuse;"
            "elif which pacman > /dev/null 2>&1; then echo archlinux;"
            "else echo unknown; fi"
        )
        dist = await self.ssh.run_command(script)
        dist = dist.strip()
        logger.info(f"Detected OS family: {dist}")
        return dist

    async def _ensure_docker(self) -> None:
        """Install Docker if not present, start and enable it."""
        dist = await self._detect_os()
        script = ""

        if dist == "debian":
            script = (
                "if ! command -v docker > /dev/null 2>&1; then "
                "export DEBIAN_FRONTEND=noninteractive; "
                "apt-get update -yq && apt-get install -yq docker.io; "
                "systemctl enable --now docker; "
                "sleep 3; "
                "fi; "
                "if [ \"$(systemctl is-active docker)\" != \"active\" ]; then "
                "systemctl start docker; sleep 3; "
                "fi"
            )
        elif dist == "fedora":
            script = (
                "if ! command -v docker > /dev/null 2>&1; then "
                "dnf install -yq docker; systemctl enable --now docker; sleep 3; "
                "fi; "
                "if [ \"$(systemctl is-active docker)\" != \"active\" ]; then "
                "systemctl start docker; sleep 3; "
                "fi"
            )
        elif dist == "centos":
            script = (
                "if ! command -v docker > /dev/null 2>&1; then "
                "yum install -yq docker; systemctl enable --now docker; sleep 3; "
                "fi; "
                "if [ \"$(systemctl is-active docker)\" != \"active\" ]; then "
                "systemctl start docker; sleep 3; "
                "fi"
            )
        elif dist == "opensuse":
            script = (
                "if ! command -v docker > /dev/null 2>&1; then "
                "zypper -nq install docker; systemctl enable --now docker; sleep 3; "
                "fi; "
                "if [ \"$(systemctl is-active docker)\" != \"active\" ]; then "
                "systemctl start docker; sleep 3; "
                "fi"
            )
        elif dist == "archlinux":
            script = (
                "if ! command -v docker > /dev/null 2>&1; then "
                "pacman -S --noconfirm --noprogressbar docker; systemctl enable --now docker; sleep 3; "
                "fi; "
                "if [ \"$(systemctl is-active docker)\" != \"active\" ]; then "
                "systemctl start docker; sleep 3; "
                "fi"
            )
        else:
            script = (
                "if ! command -v docker > /dev/null 2>&1; then "
                "curl -fsSL https://get.docker.com | sh; "
                "systemctl enable --now docker; sleep 3; "
                "fi"
            )

        await self.ssh.run_command(script)
        version = await self.ssh.run_command("docker --version")
        logger.info(f"Docker: {version}")

    async def _ensure_utils(self) -> None:
        """Install essential utilities (curl, jq)."""
        dist = await self._detect_os()
        if dist == "debian":
            await self.ssh.run_command(
                "apt-get update -yq && apt-get install -yq curl jq"
            )
        elif dist == "fedora":
            await self.ssh.run_command("dnf install -yq curl jq")
        elif dist == "centos":
            await self.ssh.run_command("yum install -yq curl jq")
        elif dist == "opensuse":
            await self.ssh.run_command("zypper -nq install curl jq")
        elif dist == "archlinux":
            await self.ssh.run_command("pacman -S --noconfirm --noprogressbar curl jq")
        else:
            logger.warning(f"Unknown dist '{dist}', skipping utils installation")

    async def _ensure_ufw(self) -> None:
        """Install and enable UFW with SSH allowed."""
        dist = await self._detect_os()
        if dist == "debian":
            await self.ssh.run_command("apt-get install -yq ufw")
        elif dist in ("fedora", "centos"):
            await self.ssh.run_command("yum install -yq ufw || dnf install -yq ufw")
        elif dist == "opensuse":
            await self.ssh.run_command("zypper -nq install ufw")
        elif dist == "archlinux":
            await self.ssh.run_command("pacman -S --noconfirm ufw")

        ssh_port = self.ssh.port
        await self.ssh.run_command(
            f"ufw allow {ssh_port}/tcp && ufw --force enable"
        )
        logger.info(f"UFW enabled, SSH port {ssh_port} allowed")

    async def _mark_prepared(self) -> None:
        """Mark host as prepared."""
        await self.ssh.run_command(f"mkdir -p {BASE_DIR} && touch {PREPARED_MARKER}")

    # ── Cleanup / Rollback ────────────────────────────────────────────

    async def cleanup(
        self,
        dirs: list[str] | None = None,
        ports: list[tuple[int, str]] | None = None,
    ) -> None:
        """Remove container, directories, and close UFW ports for rollback.

        Args:
            dirs: List of remote directories to remove.
            ports: List of (port, protocol) tuples to close in UFW.
        """
        name = _container_name(self.SERVICE_NAME)
        logger.warning(f"Rollback: cleaning up {name}")

        try:
            await self.ssh.run_command(f"docker rm -f {name} 2>/dev/null || true")
        except Exception as e:
            logger.error(f"Failed to remove container {name}: {e}")

        for d in dirs or []:
            try:
                await self.ssh.run_command(f"rm -rf {d}")
            except Exception as e:
                logger.error(f"Failed to remove dir {d}: {e}")

        for port, proto in ports or []:
            try:
                await self.port_manager.close_port(port, proto)
            except Exception as e:
                logger.error(f"Failed to close port {port}/{proto}: {e}")

    # ── Helpers ───────────────────────────────────────────────────────

    async def ensure_dirs(self, *paths: str) -> None:
        """Create directories on the remote server."""
        for p in paths:
            await self.ssh.run_command(f"mkdir -p {p}")

    @staticmethod
    def generate_random_string(length: int = 16) -> str:
        chars = string.ascii_letters + string.digits
        return "".join(random.choices(chars, k=length))

    async def check_port_free(self, port: int) -> bool:
        """Check if a specific port is free on the server (TCP + UDP)."""
        return await self.port_manager.is_port_free(port)
