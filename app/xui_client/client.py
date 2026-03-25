"""HTTP client for 3x-ui API."""

import json
import ssl
from datetime import datetime
from typing import Any

import aiohttp
from loguru import logger

from app.xui_client.exceptions import (
    XUIAuthError,
    XUIConnectionError,
    XUIError,
    XUINotFoundError,
)
from app.xui_client.models import (
    XUIAddClientRequest,
    XUIInbound,
    XUIResponse,
)


class XUIClient:
    """Async HTTP client for 3x-ui panel API."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        timeout: int = 30,
        verify_ssl: bool = True,
        saved_cookies: dict[str, Any] | None = None,
    ) -> None:
        """Initialize XUI client.

        Args:
            base_url: Base URL of 3x-ui panel (e.g., https://panel.example.com)
            username: Panel username
            password: Panel password
            timeout: Request timeout in seconds
            verify_ssl: Whether to verify SSL certificates (default: True)
            saved_cookies: Saved session cookies to reuse (optional)
        """
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.verify_ssl = verify_ssl
        self._session: aiohttp.ClientSession | None = None
        self._cookies: dict[str, Any] = saved_cookies or {}
        self._session_created_at: datetime | None = None

    async def __aenter__(self) -> "XUIClient":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()

    async def connect(self) -> None:
        """Create session and login to panel."""
        # Configure SSL context
        connector_args = {}
        if not self.verify_ssl:
            # Disable SSL verification (not recommended for production)
            # Create a custom SSL context that ignores all verification
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            # For OpenSSL 3.0 compatibility
            try:
                ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
                ssl_context.maximum_version = ssl.TLSVersion.TLSv1_3
            except:
                pass

            # Try to set legacy cipher suites for OpenSSL 3.0
            try:
                # More permissive cipher suites
                ssl_context.set_ciphers('DEFAULT:@SECLEVEL=1')
            except:
                # Fallback to even more permissive settings
                try:
                    ssl_context.set_ciphers('ALL:!aNULL:!eNULL')
                except:
                    pass

            connector_args['ssl'] = ssl_context
            logger.warning(f"SSL verification disabled for {self.base_url}")
            logger.info(f"Connecting to {self.base_url}/login with SSL verification disabled")
        else:
            # Use default SSL settings
            connector_args['ssl'] = True

        # Additional connection options for problematic servers
        connector_args['force_close'] = True
        connector_args['enable_cleanup_closed'] = True

        connector = aiohttp.TCPConnector(**connector_args)
        self._session = aiohttp.ClientSession(
            timeout=self.timeout,
            connector=connector,
            trust_env=True,  # Allow environment variables
        )

        logger.info(f"Attempting to connect to {self.base_url}")

        # Try to use saved cookies first
        if self._cookies and await self._test_session():
            logger.info(f"Successfully reusing saved session for {self.base_url}")
            return

        # Fall back to login
        await self.login()
        logger.info(f"Successfully connected to {self.base_url}")

    async def close(self) -> None:
        """Close session properly.

        Note: Logout is not necessary for 3x-ui panels. Session cleanup
        happens automatically when closing the HTTP session.
        """
        if self._session:
            try:
                await self._session.close()
            except Exception as e:
                logger.warning(f"Error closing session: {e}")
            finally:
                self._session = None

    def _get_session(self) -> aiohttp.ClientSession:
        """Get active session or raise error."""
        if not self._session:
            raise XUIConnectionError("Not connected. Call connect() first.")
        return self._session

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Make HTTP request to panel.

        Args:
            method: HTTP method
            path: API path
            **kwargs: Additional request parameters

        Returns:
            Response JSON data

        Raises:
            XUIConnectionError: Connection failed
            XUIAuthError: Authentication failed
            XUIError: API error
        """
        session = self._get_session()
        url = f"{self.base_url}{path}"

        try:
            async with session.request(method, url, **kwargs) as response:
                if response.status == 401:
                    raise XUIAuthError("Authentication failed")

                if response.status == 404:
                    raise XUINotFoundError(f"Resource not found: {path}")

                if response.status >= 500:
                    text = await response.text()
                    raise XUIConnectionError(f"Server error: {response.status} - {text}")

                data = await response.json()
                return data

        except aiohttp.ClientError as e:
            raise XUIConnectionError(f"Connection error: {e}") from e
        except json.JSONDecodeError as e:
            raise XUIError(f"Invalid JSON response: {e}") from e
        except Exception as e:
            # Catch any other exceptions to prevent session leaks
            logger.warning(f"Unexpected error in XUI request: {e}")
            raise XUIError(f"Request failed: {e}") from e

    async def login(self) -> bool:
        """Login to panel and store session cookie.

        Returns:
            True if login successful

        Raises:
            XUIAuthError: Authentication failed
            XUIConnectionError: Connection failed
        """
        session = self._get_session()
        url = f"{self.base_url}/login"

        logger.info(f"Login attempt to: {url}")
        logger.info(f"Username: {self.username}, SSL verify: {self.verify_ssl}")

        try:
            async with session.post(
                url,
                data={"username": self.username, "password": self.password},
            ) as response:
                if response.status != 200:
                    raise XUIAuthError(f"Login failed: HTTP {response.status}")

                data = await response.json()
                if not data.get("success", False):
                    raise XUIAuthError(f"Login failed: {data.get('msg', 'Unknown error')}")

                # Store session cookies
                self._cookies = {cookie.key: cookie.value for cookie in session.cookie_jar}
                logger.info(f"Logged in to {self.base_url}")
                return True

        except aiohttp.ClientError as e:
            raise XUIConnectionError(f"Connection error during login: {e}") from e

    async def _test_session(self) -> bool:
        """Test if saved cookies are still valid.

        Returns:
            True if session is valid
        """
        session = self._get_session()

        try:
            # Load saved cookies into session
            for key, value in self._cookies.items():
                session.cookie_jar.update_cookies({key: value})

            # Test with a simple API call
            async with session.get(f"{self.base_url}/panel/api/inbounds/list") as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("success", False):
                        logger.info(f"Saved session is valid for {self.base_url}")
                        return True

            # Session is invalid, clear cookies
            self._cookies = {}
            return False

        except Exception:
            # Any error means session is invalid
            self._cookies = {}
            return False

    def get_session_cookies(self) -> dict[str, Any]:
        """Get current session cookies.

        Returns:
            Dictionary of cookies
        """
        if self._session:
            return {cookie.key: cookie.value for cookie in self._session.cookie_jar}
        return self._cookies

    async def get_inbounds(self) -> list[XUIInbound]:
        """Get list of all inbounds.

        Returns:
            List of inbound configurations
        """
        data = await self._request("GET", "/panel/api/inbounds/list")

        if not data.get("success", False):
            raise XUIError(f"Failed to get inbounds: {data.get('msg', 'Unknown error')}")

        inbounds = []
        for item in data.get("obj", []):
            inbound = XUIInbound(**item)
            inbounds.append(inbound)

        return inbounds

    async def get_inbound(self, inbound_id: int) -> XUIInbound:
        """Get specific inbound by ID.

        Args:
            inbound_id: Inbound ID

        Returns:
            Inbound configuration
        """
        data = await self._request("GET", f"/panel/api/inbounds/get/{inbound_id}")

        if not data.get("success", False):
            raise XUIError(f"Failed to get inbound: {data.get('msg', 'Unknown error')}")

        return XUIInbound(**data["obj"])

    async def get_clients(self, inbound_id: int) -> list[dict[str, Any]]:
        """Get list of clients for inbound.

        Args:
            inbound_id: Inbound ID

        Returns:
            List of client configurations
        """
        data = await self._request("GET", f"/panel/api/inbounds/getClientTraffics/{inbound_id}")

        if not data.get("success", False):
            # May return empty if no clients
            return []

        return data.get("obj", [])

    async def add_client(
        self,
        inbound_id: int,
        client: XUIAddClientRequest,
    ) -> bool:
        """Add client to inbound.

        Args:
            inbound_id: Inbound ID
            client: Client configuration

        Returns:
            True if successful

        Raises:
            XUIError: Failed to add client
        """
        # Build settings JSON string
        settings = {
            "clients": [client.model_dump()],
            "decryption": "none",
            "fallbacks": [],
        }

        data = await self._request(
            "POST",
            "/panel/api/inbounds/addClient",
            data={"id": str(inbound_id), "settings": json.dumps(settings)},
        )

        if not data.get("success", False):
            raise XUIError(f"Failed to add client: {data.get('msg', 'Unknown error')}")

        logger.info(f"Added client {client.email} to inbound {inbound_id}")
        return True

    async def update_client(
        self,
        inbound_id: int,
        client: XUIAddClientRequest,
    ) -> bool:
        """Update client in inbound.

        Args:
            inbound_id: Inbound ID
            client: Client configuration (must include UUID)

        Returns:
            True if successful

        Raises:
            XUIError: Failed to update client
        """
        settings = {
            "clients": [client.model_dump()],
            "decryption": "none",
            "fallbacks": [],
        }

        data = await self._request(
            "POST",
            f"/panel/api/inbounds/updateClient/{client.id}",
            data={"id": inbound_id, "settings": json.dumps(settings)},
        )

        if not data.get("success", False):
            raise XUIError(f"Failed to update client: {data.get('msg', 'Unknown error')}")

        logger.info(f"Updated client {client.email} in inbound {inbound_id}")
        return True

    async def delete_client(
        self,
        inbound_id: int,
        client_uuid: str,
    ) -> bool:
        """Delete client from inbound.

        Args:
            inbound_id: Inbound ID
            client_uuid: Client UUID

        Returns:
            True if successful

        Raises:
            XUIError: Failed to delete client
        """
        data = await self._request(
            "POST",
            f"/panel/api/inbounds/{inbound_id}/delClient/{client_uuid}",
        )

        if not data.get("success", False):
            raise XUIError(f"Failed to delete client: {data.get('msg', 'Unknown error')}")

        logger.info(f"Deleted client {client_uuid} from inbound {inbound_id}")
        return True

    async def enable_client(
        self,
        inbound_id: int,
        client_uuid: str,
        enable: bool = True,
    ) -> bool:
        """Enable or disable client.

        Args:
            inbound_id: Inbound ID
            client_uuid: Client UUID
            enable: True to enable, False to disable

        Returns:
            True if successful
        """
        # First get current client data from inbound
        inbound = await self.get_inbound(inbound_id)
        import json
        settings_data = json.loads(inbound.settings)
        clients_list = settings_data.get("clients", [])

        client_data = None
        for c in clients_list:
            if c.get("id") == client_uuid:
                client_data = c
                break

        if not client_data:
            raise XUINotFoundError(f"Client {client_uuid} not found in inbound {inbound_id}")

        # Update enable flag
        client_data["enable"] = enable

        # Build update request
        client = XUIAddClientRequest(**client_data)
        return await self.update_client(inbound_id, client)

    async def get_client_traffic(
        self,
        inbound_id: int,
        email: str,
    ) -> dict[str, Any] | None:
        """Get client traffic statistics.

        Args:
            inbound_id: Inbound ID
            email: Client email

        Returns:
            Traffic statistics or None if not found
        """
        data = await self._request(
            "GET",
            f"/panel/api/inbounds/getClientTraffics/{inbound_id}",
        )

        if not data.get("success", False):
            return None

        for client in data.get("obj", []):
            if client.get("email") == email:
                return client

        return None

    async def reset_client_traffic(
        self,
        inbound_id: int,
        client_email: str,
    ) -> bool:
        """Reset client traffic statistics.

        Args:
            inbound_id: Inbound ID
            client_email: Client email

        Returns:
            True if successful
        """
        data = await self._request(
            "POST",
            f"/panel/api/inbounds/{inbound_id}/resetClientTraffic/{client_email}",
        )

        if not data.get("success", False):
            raise XUIError(f"Failed to reset traffic: {data.get('msg', 'Unknown error')}")

        logger.info(f"Reset traffic for client {client_email}")
        return True
