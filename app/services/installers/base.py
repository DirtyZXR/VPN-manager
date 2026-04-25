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
FIREWALL_POLICY_FILE = f"{BASE_DIR}/.firewall-policy"


def _container_name(service: str) -> str:
    return f"{CONTAINER_PREFIX}-{service}"


class BaseInstaller:
    """Base class for all VPN service installers."""

    SERVICE_NAME: str = ""

    # ── Container identification ──────────────────────────────────────

    def __init__(self, ssh: SSHManager) -> None:
        self.ssh = ssh
        self.port_manager = PortManager(ssh)
        self._use_sudo = False

    async def _cmd(self, command: str, input_data: str | None = None) -> str:
        """Execute command with optional sudo prefix."""
        if self._use_sudo:
            command = f"sudo {command}"
        return await self.ssh.run_command(command, input_data=input_data)

    async def _write_file(self, filepath: str, content: str) -> None:
        """Write file with optional sudo."""
        if self._use_sudo:
            await self.ssh.run_command(
                f"sudo tee {filepath} > /dev/null", input_data=content
            )
        else:
            await self.ssh.write_file(filepath, content)

    async def preflight_check(self) -> tuple[bool, str]:
        """Run pre-installation checks: ping + SSH + root/sudo access.

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

        root_ok, root_msg = await self._check_root_access()
        if not root_ok:
            return False, root_msg

        return True, "OK"

    async def _check_root_access(self) -> tuple[bool, str]:
        """Check if SSH user is root or has passwordless sudo.

        Returns:
            Tuple of (has_root: bool, message: str).
        """
        try:
            result = await self.ssh.run_command("whoami")
            if result.strip() == "root":
                self._use_sudo = False
                return True, "root"
        except Exception:
            pass

        try:
            result = await self.ssh.run_command("sudo -n whoami 2>/dev/null")
            if result.strip() == "root":
                self._use_sudo = True
                return True, "sudo"
        except Exception:
            pass

        return False, (
            f"Пользователь {self.ssh.username}@{self.ssh.host} "
            "не имеет root-прав и не настроен passwordless sudo. "
            "Подключитесь под root или настройте sudo."
        )

    async def check_already_installed(self) -> bool:
        """Check if a container with our naming convention already exists."""
        name = _container_name(self.SERVICE_NAME)
        result = await self._cmd(
            f"docker ps -a --filter name=^{name}$ --format '{{{{.Names}}}}'"
        )
        return bool(result.strip())

    async def list_installed_services(self) -> list[str]:
        """List all vpnbot-managed containers on the server."""
        result = await self._cmd(
            f"docker ps -a --filter name={CONTAINER_PREFIX}- --format '{{{{.Names}}}}'"
        )
        names = [n.strip() for n in result.strip().split("\n") if n.strip()]
        return [n.removeprefix(f"{CONTAINER_PREFIX}-") for n in names]

    # ── Host preparation ──────────────────────────────────────────────

    async def is_prepared(self) -> bool:
        """Check if host has already been prepared."""
        try:
            result = await self._cmd(f"test -f {PREPARED_MARKER} && echo yes")
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
        dist = await self._cmd(script)
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

        await self._cmd(script)
        version = await self._cmd("docker --version")
        logger.info(f"Docker: {version}")

    async def _ensure_utils(self) -> None:
        """Install essential utilities (curl, jq)."""
        dist = await self._detect_os()
        if dist == "debian":
            await self._cmd(
                "apt-get update -yq && apt-get install -yq curl jq"
            )
        elif dist == "fedora":
            await self._cmd("dnf install -yq curl jq")
        elif dist == "centos":
            await self._cmd("yum install -yq curl jq")
        elif dist == "opensuse":
            await self._cmd("zypper -nq install curl jq")
        elif dist == "archlinux":
            await self._cmd("pacman -S --noconfirm --noprogressbar curl jq")
        else:
            logger.warning(f"Unknown dist '{dist}', skipping utils installation")

    async def _ensure_ufw(self) -> None:
        """Install and enable UFW with SSH allowed."""
        dist = await self._detect_os()
        if dist == "debian":
            await self._cmd("apt-get install -yq ufw")
        elif dist in ("fedora", "centos"):
            await self._cmd("yum install -yq ufw || dnf install -yq ufw")
        elif dist == "opensuse":
            await self._cmd("zypper -nq install ufw")
        elif dist == "archlinux":
            await self._cmd("pacman -S --noconfirm ufw")

        ssh_port = self.ssh.port
        await self._cmd(
            f"ufw allow {ssh_port}/tcp && ufw --force enable"
        )
        logger.info(f"UFW enabled, SSH port {ssh_port} allowed")

    async def _mark_prepared(self) -> None:
        """Mark host as prepared."""
        await self._cmd(f"mkdir -p {BASE_DIR} && touch {PREPARED_MARKER}")

    async def get_firewall_policy(self) -> str | None:
        """Read firewall policy from server. Returns 'strict', 'permissive', or None."""
        try:
            result = await self._cmd(f"cat {FIREWALL_POLICY_FILE} 2>/dev/null")
            policy = result.strip()
            return policy if policy in ("strict", "permissive") else None
        except Exception:
            return None

    async def apply_firewall_policy(self, strict: bool) -> None:
        """Apply firewall policy. Only called on first server setup.

        Args:
            strict: If True, deny all incoming except SSH. If False, leave as-is.
        """
        ssh_port = self.ssh.port

        if strict:
            await self._cmd(
                f"ufw default deny incoming && "
                f"ufw default allow outgoing && "
                f"ufw allow {ssh_port}/tcp && "
                f"ufw --force reload"
            )
            logger.info(f"Strict firewall applied on {self.ssh.host}: only SSH/{ssh_port} allowed")
        else:
            logger.info(f"Permissive firewall on {self.ssh.host}: UFW policy unchanged")

        policy = "strict" if strict else "permissive"
        await self._cmd(
            f"mkdir -p {BASE_DIR} && echo '{policy}' > {FIREWALL_POLICY_FILE}"
        )

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
            await self._cmd(f"docker rm -f {name} 2>/dev/null || true")
        except Exception as e:
            logger.error(f"Failed to remove container {name}: {e}")

        for d in dirs or []:
            try:
                await self._cmd(f"rm -rf {d}")
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
            await self._cmd(f"mkdir -p {p}")

    @staticmethod
    def generate_random_string(length: int = 16) -> str:
        chars = string.ascii_letters + string.digits
        return "".join(random.choices(chars, k=length))

    async def check_port_free(self, port: int) -> bool:
        """Check if a specific port is free on the server (TCP + UDP)."""
        return await self.port_manager.is_port_free(port)

    # ── SSH port change ────────────────────────────────────────────────

    async def change_ssh_port(self, new_port: int) -> tuple[bool, str]:
        """Change SSH daemon port with automatic rollback on failure.

        Strategy:
        1. Add new port alongside old port in sshd_config
        2. Open new port in UFW
        3. Restart sshd
        4. Verify connectivity on new port
        5. If OK: remove old port, close old port in UFW
        6. If FAIL: revert config, keep old port

        Args:
            new_port: New SSH port number.

        Returns:
            Tuple of (success, message).
        """
        old_port = self.ssh.port
        if new_port == old_port:
            return True, f"SSH port already {old_port}"

        host = self.ssh.host

        if not await self.check_port_free(new_port):
            return False, f"Порт {new_port} занят на сервере"

        config_backup = await self._cmd("cat /etc/ssh/sshd_config")

        try:
            await self._cmd(
                f"sed -i 's/^#*Port {old_port}/Port {old_port}\\nPort {new_port}/' /etc/ssh/sshd_config"
            )

            if f"Port {new_port}" not in await self._cmd("grep '^Port' /etc/ssh/sshd_config"):
                await self._cmd(
                    f"echo 'Port {old_port}' >> /etc/ssh/sshd_config && "
                    f"echo 'Port {new_port}' >> /etc/ssh/sshd_config"
                )

            await self._cmd(f"ufw allow {new_port}/tcp")
            await self._cmd("systemctl restart sshd || systemctl restart ssh")
            import asyncio
            await asyncio.sleep(3)

            test_ssh = SSHManager.__new__(SSHManager)
            test_ssh.server = self.ssh.server
            test_ssh.host = host
            test_ssh.port = new_port
            test_ssh.username = self.ssh.username
            test_ssh._decrypt = self.ssh._decrypt

            if await test_ssh.test_connection():
                await self._cmd(
                    f"sed -i '/^Port {old_port}$/d' /etc/ssh/sshd_config"
                )
                await self._cmd(f"ufw delete allow {old_port}/tcp || true")
                await self._cmd("systemctl restart sshd || systemctl restart ssh")

                logger.info(f"SSH port changed: {old_port} -> {new_port} on {host}")
                return True, f"SSH порт изменён: {old_port} → {new_port}"
            else:
                raise RuntimeError("Не удалось подключиться на новый порт")

        except Exception as e:
            logger.error(f"SSH port change failed, reverting: {e}")
            try:
                await self.ssh.write_file("/etc/ssh/sshd_config", config_backup)
                await self._cmd("systemctl restart sshd || systemctl restart ssh")
                await self._cmd(f"ufw delete allow {new_port}/tcp || true")
            except Exception as rollback_err:
                logger.error(f"Rollback also failed: {rollback_err}")
                return False, f"Ошибка смены порта и отката: {rollback_err}"

            return False, f"Не удалось сменить SSH порт: {e}. Откачено к порту {old_port}."

    # ── Healthcheck ────────────────────────────────────────────────────

    async def healthcheck(self, service_name: str) -> tuple[bool, str]:
        """Check if a vpnbot container is running and healthy.

        Args:
            service_name: Service name (e.g. 'awg', 'xui').

        Returns:
            Tuple of (healthy, status_text).
        """
        container = _container_name(service_name)
        try:
            status = await self._cmd(
                f"docker inspect --format '{{{{.State.Status}}}}' {container} 2>/dev/null"
            )
            status = status.strip().strip("'")

            if status == "running":
                uptime = await self._cmd(
                    f"docker inspect --format '{{{{.State.StartedAt}}}}' {container} 2>/dev/null"
                )
                return True, f"running (started {uptime.strip().strip(chr(39))})"

            return False, f"container status: {status}"
        except Exception as e:
            return False, f"error: {e}"
