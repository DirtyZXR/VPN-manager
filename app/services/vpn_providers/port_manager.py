"""Port Manager for allocating free ports on a server via SSH."""

from loguru import logger

from app.services.ssh_service import SSHManager

# Range of ports to use for new VPN containers/protocols
PORT_RANGE_START = 30000
PORT_RANGE_END = 50000


class PortManager:
    """Allocates and manages free ports on remote servers."""

    def __init__(self, ssh_manager: SSHManager) -> None:
        """Initialize with SSHManager.

        Args:
            ssh_manager: Configured SSHManager instance
        """
        self.ssh = ssh_manager

    async def get_used_ports(self) -> set[int]:
        """Fetch a set of currently used TCP and UDP ports on the server.

        Returns:
            Set of used port numbers.
        """
        try:
            # -t: tcp, -u: udp, -l: listening, -n: numeric
            # We parse the local address column (e.g. 0.0.0.0:443 or :::80)
            try:
                output = await self.ssh.run_command(
                    "sudo -n ss -tuln 2>/dev/null | awk '{print $5}' | grep -o '[0-9]*$' || ss -tuln | awk '{print $5}' | grep -o '[0-9]*$'"
                )
            except Exception:
                # Fallback to netstat if ss is not available
                output = await self.ssh.run_command(
                    "sudo -n netstat -tuln 2>/dev/null | awk '{print $4}' | grep -o '[0-9]*$' || netstat -tuln | awk '{print $4}' | grep -o '[0-9]*$'"
                )

            used_ports = set()
            for line in output.strip().split("\n"):
                if line.strip().isdigit():
                    used_ports.add(int(line.strip()))
            return used_ports
        except Exception as e:
            logger.error(f"Failed to get used ports from server {self.ssh.server.id}: {e}")
            raise

    async def allocate_free_port(
        self, start: int = PORT_RANGE_START, end: int = PORT_RANGE_END
    ) -> int:
        """Find the first available port in the specified range.

        Args:
            start: Start of the port range
            end: End of the port range

        Returns:
            An available port number.

        Raises:
            Exception: If no free ports are found in the range.
        """
        used_ports = await self.get_used_ports()

        # Iterate through the range and find the first unused port
        for port in range(start, end + 1):
            if port not in used_ports:
                logger.info(f"Allocated free port {port} on server {self.ssh.server.id}")
                return port

        raise Exception(
            f"No free ports available in range {start}-{end} on server {self.ssh.server.id}"
        )

    async def is_port_free(self, port: int) -> bool:
        """Check if a specific port is free (both TCP and UDP).

        A port is considered occupied if it is used by EITHER TCP or UDP.

        Args:
            port: Port number to check.

        Returns:
            True if the port is free on both TCP and UDP.
        """
        used = await self.get_used_ports()
        return port not in used

    async def open_port(self, port: int, protocol: str = "tcp") -> None:
        """Open a port in the server's firewall using UFW.

        Args:
            port: Port number to open
            protocol: Protocol ('tcp', 'udp', or 'any' for both)
        """
        try:
            if protocol.lower() == "any":
                await self.ssh.run_command(f"sudo -n ufw allow {port} 2>/dev/null || ufw allow {port}")
            else:
                await self.ssh.run_command(f"sudo -n ufw allow {port}/{protocol.lower()} 2>/dev/null || ufw allow {port}/{protocol.lower()}")
            logger.info(f"Opened port {port}/{protocol} via UFW on server {self.ssh.server.id}")
        except Exception as e:
            logger.error(f"Failed to open port {port} via UFW on server {self.ssh.server.id}: {e}")
            raise

    async def close_port(self, port: int, protocol: str = "tcp") -> None:
        """Close a port in the server's firewall using UFW.

        Args:
            port: Port number to close
            protocol: Protocol ('tcp', 'udp', or 'any' for both)
        """
        try:
            if protocol.lower() == "any":
                await self.ssh.run_command(f"sudo -n ufw delete allow {port} 2>/dev/null || ufw delete allow {port} 2>/dev/null || true")
            else:
                await self.ssh.run_command(
                    f"sudo -n ufw delete allow {port}/{protocol.lower()} 2>/dev/null || ufw delete allow {port}/{protocol.lower()} 2>/dev/null || true"
                )
            logger.info(f"Closed port {port}/{protocol} via UFW on server {self.ssh.server.id}")
        except Exception as e:
            logger.error(f"Failed to close port {port} via UFW on server {self.ssh.server.id}: {e}")
            raise
