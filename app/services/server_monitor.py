"""Server monitor service for pinging and checking host availability."""

import asyncio
import platform

from loguru import logger

from app.database import async_session_factory
from app.database.models import Server


class ServerMonitor:
    """Service to periodically check server availability via ICMP ping."""

    @staticmethod
    async def ping(host: str, timeout: int = 2) -> bool:
        """Check if a host is reachable via ping.

        Args:
            host: IP address or domain name
            timeout: Timeout in seconds

        Returns:
            True if reachable, False otherwise
        """
        # Determine the correct ping command parameters based on OS
        param_count = "-n" if platform.system().lower() == "windows" else "-c"
        param_timeout = "-w" if platform.system().lower() == "windows" else "-W"

        # Windows ping -w is in milliseconds, Linux -W is in seconds or depends on implementation.
        # Usually -W 2 on Linux, and -w 2000 on Windows
        timeout_val = (
            str(timeout * 1000) if platform.system().lower() == "windows" else str(timeout)
        )

        command = ["ping", param_count, "1", param_timeout, timeout_val, host]

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            await process.communicate()
            return process.returncode == 0
        except Exception as e:
            logger.error(f"Ping failed for host {host}: {e}")
            return False

    @classmethod
    async def check_server_status(cls, server_id: int) -> bool:
        """Ping a specific server and update its status in DB.

        Args:
            server_id: Server model ID

        Returns:
            True if online, False otherwise
        """
        async with async_session_factory() as session:
            server = await session.get(Server, server_id)
            if not server:
                return False

            # If ip_address is provided use it
            if server.ip_address:
                host = server.ip_address
                # Strip http:// or https:// if present
                if host.startswith("http://"):
                    host = host[7:]
                elif host.startswith("https://"):
                    host = host[8:]
                # Strip port if present
                if ":" in host:
                    host = host.split(":")[0]
            else:
                return False

            if not host:
                return False

            is_online = await cls.ping(host)

            # Update DB if status changed
            if server.is_online != is_online:
                server.is_online = is_online
                await session.commit()

            return is_online
