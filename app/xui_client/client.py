"""HTTP client for 3x-ui API."""

import contextlib
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
)


class XUIClient:
    """Async HTTP client for 3x-ui panel API."""

    def __init__(
        self,
        base_url: str,
        username: str = "",
        password: str = "",
        timeout: int = 30,
        verify_ssl: bool = True,
        saved_cookies: dict[str, Any] | None = None,
        two_factor_code: str | None = None,
        api_token: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.verify_ssl = verify_ssl
        self.two_factor_code = two_factor_code
        self.api_token = api_token
        self._session: aiohttp.ClientSession | None = None
        self._cookies: dict[str, Any] = saved_cookies or {}
        self._session_created_at: datetime | None = None
        self._csrf_token: str | None = None

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
            except Exception:
                pass

            # Try to set legacy cipher suites for OpenSSL 3.0
            try:
                # More permissive cipher suites
                ssl_context.set_ciphers("DEFAULT:@SECLEVEL=1")
            except Exception:
                # Fallback to even more permissive settings
                with contextlib.suppress(BaseException):
                    ssl_context.set_ciphers("ALL:!aNULL:!eNULL")

            connector_args["ssl"] = ssl_context
            logger.warning("SSL verification disabled for {}", self.base_url)
            logger.info("Connecting to {}/login with SSL verification disabled", self.base_url)
        else:
            # Use default SSL settings
            connector_args["ssl"] = True

        # Additional connection options for problematic servers
        connector_args["force_close"] = True
        connector_args["enable_cleanup_closed"] = True

        connector = aiohttp.TCPConnector(**connector_args)
        jar = aiohttp.CookieJar(unsafe=True)
        self._session = aiohttp.ClientSession(
            timeout=self.timeout,
            connector=connector,
            trust_env=True,
            cookie_jar=jar,
        )

        logger.info("Attempting to connect to {}", self.base_url)

        if self.api_token:
            if await self._test_bearer_token():
                logger.info("Connected via API token to {}", self.base_url)
                return
            logger.warning("API token invalid for {}, falling back to login", self.base_url)

        if self._cookies and await self._test_session():
            logger.info("Successfully reusing saved session for {}", self.base_url)
            return

        try:
            await self.login()
            logger.info("Successfully connected to {}", self.base_url)
        except Exception:
            await self.close()
            raise

    async def close(self) -> None:
        """Close session properly.

        Note: Logout is not necessary for 3x-ui panels. Session cleanup
        happens automatically when closing the HTTP session.
        """
        if self._session and not self._session.closed:
            await self._session.close()
            import asyncio

            await asyncio.sleep(0.05)

    def _get_session(self) -> aiohttp.ClientSession:
        """Get active session or raise error."""
        if not self._session:
            raise XUIConnectionError("Not connected. Call connect() first.")
        return self._session

    async def _get_csrf_token(self) -> str | None:
        """Fetch a fresh CSRF token from the panel.

        Returns:
            CSRF token string, or None if the endpoint is unavailable / returns failure.
        """
        try:
            data = await self._request("GET", "/csrf-token")
            if data.get("success"):
                return data.get("obj")
        except Exception:
            pass
        return None

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
        url = f"{self.base_url.rstrip('/')}{path}"

        logger.debug(
            f"[XUI REQUEST] method={method}, base_url={self.base_url!r}, "
            f"path={path!r}, full_url={url!r}"
        )
        logger.debug(
            f"[XUI COOKIES] jar={list(session.cookie_jar)} "
            f"backup={self._cookies}"
        )

        request_cookies = {c.key: c.value for c in session.cookie_jar}
        if self._cookies and not request_cookies:
            request_cookies = dict(self._cookies)
            session.cookie_jar.update_cookies(self._cookies)

        headers = kwargs.pop("headers", {})
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"

        # CSRF: only for unsafe methods on the cookie path (Bearer skips CSRF entirely)
        _unsafe = method.upper() in {"POST", "PUT", "DELETE"}
        _use_csrf = _unsafe and not self.api_token and path != "/csrf-token"

        if _use_csrf:
            if self._csrf_token is None:
                self._csrf_token = await self._get_csrf_token()
            if self._csrf_token:
                headers["X-CSRF-Token"] = self._csrf_token

        try:
            async with session.request(
                method, url, cookies=request_cookies or None, headers=headers or None, **kwargs
            ) as response:
                if response.status == 401:
                    raise XUIAuthError("Authentication failed")

                if response.status == 403 and _use_csrf:
                    # Refresh token once and retry
                    self._csrf_token = await self._get_csrf_token()
                    if self._csrf_token:
                        headers["X-CSRF-Token"] = self._csrf_token
                    else:
                        headers.pop("X-CSRF-Token", None)
                    async with session.request(
                        method,
                        url,
                        cookies=request_cookies or None,
                        headers=headers or None,
                        **kwargs,
                    ) as retry_response:
                        if retry_response.status == 403:
                            raise XUIAuthError("Authentication failed after CSRF token refresh")
                        if retry_response.status == 404:
                            raise XUINotFoundError(f"Resource not found: {path}")
                        if retry_response.status >= 500:
                            text = await retry_response.text()
                            raise XUIConnectionError(f"Server error: {retry_response.status} - {text}")
                        data = await retry_response.json()
                        return data

                if response.status == 404:
                    location = response.headers.get("Location", "none")
                    logger.warning(
                        f"[XUI 404] full_url={url}, path={path}, "
                        f"location={location}, cookies_sent={response.request_info.headers.get('Cookie', 'none')}"
                    )
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
        except (XUIAuthError, XUINotFoundError, XUIConnectionError, XUIError):
            raise
        except Exception as e:
            # Catch any other exceptions to prevent session leaks
            logger.warning("Unexpected error in XUI request: {}", e)
            raise XUIError(f"Request failed: {e}") from e

    def _build_login_payload(self) -> dict[str, Any]:
        """Build the login payload dict."""
        payload: dict[str, Any] = {
            "username": self.username,
            "password": self.password,
        }
        if self.two_factor_code:
            payload["twoFactorCode"] = self.two_factor_code
        return payload

    async def _do_login_post(self, *, use_form: bool) -> bool:
        """Perform a single login POST (JSON or form-encoded) with CSRF + 403-retry.

        Args:
            use_form: If True, send as form-data; otherwise send as JSON.

        Returns:
            True on success.

        Raises:
            XUIAuthError: Auth failed (non-200 status or success=False in body).
            XUIConnectionError: aiohttp connection error.
        """
        session = self._get_session()
        url = f"{self.base_url.rstrip('/')}/login"
        payload = self._build_login_payload()
        post_kwargs: dict[str, Any] = {"data": payload} if use_form else {"json": payload}

        if self._csrf_token is None:
            self._csrf_token = await self._get_csrf_token()

        async def _attempt() -> Any:
            headers: dict[str, str] = {}
            if self._csrf_token:
                headers["X-CSRF-Token"] = self._csrf_token
            try:
                async with session.post(url, headers=headers or None, **post_kwargs) as resp:
                    return resp.status, await resp.json()
            except aiohttp.ClientError as e:
                raise XUIConnectionError(f"Connection error during login: {e}") from e

        status, data = await _attempt()

        if status == 403:
            self._csrf_token = await self._get_csrf_token()
            status, data = await _attempt()

        if status != 200:
            raise XUIAuthError(f"Login failed: HTTP {status}")

        if not data.get("success", False):
            raise XUIAuthError(f"Login failed: {data.get('msg', 'Unknown error')}")

        self._cookies = {cookie.key: cookie.value for cookie in session.cookie_jar}
        logger.info(
            f"Logged in to {self.base_url}, "
            f"cookies={list(self._cookies.keys())}"
        )
        return True

    async def _login_json(self) -> bool:
        """Login using JSON body."""
        return await self._do_login_post(use_form=False)

    async def _login_form(self) -> bool:
        """Login using form-encoded body (legacy fallback)."""
        return await self._do_login_post(use_form=True)

    async def login(self) -> bool:
        """Login to panel and store session cookie.

        Tries JSON body first; on XUIAuthError or XUIConnectionError falls back
        to form-encoded body. If both fail, re-raises the last error.

        Returns:
            True if login successful

        Raises:
            XUIAuthError: Authentication failed
            XUIConnectionError: Connection failed
        """
        self._get_session()  # validate session is open
        url = f"{self.base_url.rstrip('/')}/login"

        logger.info(f"Login attempt to: {url}")
        logger.info(f"Username: {self.username}, SSL verify: {self.verify_ssl}")

        try:
            return await self._login_json()
        except (XUIAuthError, XUIConnectionError):
            logger.info("JSON login failed, retrying with form-data for {}", self.base_url)

        return await self._login_form()

    async def _test_session(self) -> bool:
        """Test if saved cookies are still valid.

        Returns:
            True if session is valid
        """
        session = self._get_session()

        try:
            for key, value in self._cookies.items():
                session.cookie_jar.update_cookies({key: value})

            async with session.get(f"{self.base_url.rstrip('/')}/panel/api/inbounds/list") as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("success", False):
                        logger.info(f"Saved session is valid for {self.base_url}")
                        return True

            self._cookies = {}
            return False

        except Exception:
            self._cookies = {}
            return False

    async def _test_bearer_token(self) -> bool:
        """Test if API token is valid.

        Returns:
            True if token works
        """
        try:
            data = await self._request("GET", "/panel/api/inbounds/list")
            if data.get("success", False):
                return True
        except Exception:
            pass
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

    async def get_clients(self) -> list[dict[str, Any]]:
        """Get panel-wide list of all clients.

        Returns:
            List of client dicts; each has ``inboundIds``, ``email``, ``uuid``,
            ``traffic``, etc.
        """
        data = await self._request("GET", "/panel/api/clients/list")

        if not data.get("success", False):
            return []

        return data.get("obj", [])

    async def add_client(
        self,
        client: XUIAddClientRequest,
        inbound_ids: list[int],
    ) -> bool:
        """Add client to one or more inbounds.

        Args:
            client: Client configuration (camelCase fields via ``by_alias=True``).
            inbound_ids: List of inbound IDs to attach the client to.

        Returns:
            True if successful

        Raises:
            XUIError: Failed to add client
        """
        data = await self._request(
            "POST",
            "/panel/api/clients/add",
            json={"client": client.model_dump(by_alias=True), "inboundIds": inbound_ids},
        )

        if not data.get("success", False):
            raise XUIError(data.get("msg", "Failed to add client"))

        logger.info(f"Added client {client.email} to inbounds {inbound_ids}")
        return True

    async def update_client(
        self,
        email: str,
        client: XUIAddClientRequest,
    ) -> bool:
        """Update client identified by email.

        The server replaces the entire client row, so *client* must carry the
        full field set (not just the changed fields).

        Args:
            email: Current client email (used as the URL key).
            client: Full client configuration.

        Returns:
            True if successful

        Raises:
            XUIError: Failed to update client
        """
        data = await self._request(
            "POST",
            f"/panel/api/clients/update/{email}",
            json=client.model_dump(by_alias=True),
        )

        if not data.get("success", False):
            raise XUIError(data.get("msg", "Failed to update client"))

        logger.info(f"Updated client {email}")
        return True

    async def delete_client(
        self,
        email: str,
        keep_traffic: bool = False,
    ) -> bool:
        """Delete client by email.

        Args:
            email: Client email.
            keep_traffic: When True, preserves traffic counters on the panel.

        Returns:
            True if successful

        Raises:
            XUIError: Failed to delete client
        """
        kwargs: dict[str, Any] = {}
        if keep_traffic:
            kwargs["params"] = {"keepTraffic": 1}

        data = await self._request(
            "POST",
            f"/panel/api/clients/del/{email}",
            **kwargs,
        )

        if not data.get("success", False):
            raise XUIError(data.get("msg", "Failed to delete client"))

        logger.info(f"Deleted client {email}")
        return True

    async def enable_client(
        self,
        email: str,
        client: XUIAddClientRequest,
        enable: bool = True,
    ) -> bool:
        """Enable or disable a client.

        Sets ``client.enable`` and delegates to :meth:`update_client`.  The
        caller must supply the full client payload (update replaces the row).

        Args:
            email: Client email (URL key for the update endpoint).
            client: Full client configuration.
            enable: True to enable, False to disable.

        Returns:
            True if successful
        """
        client.enable = enable
        return await self.update_client(email, client)

    async def get_client_traffic(
        self,
        email: str,
    ) -> dict[str, Any] | None:
        """Get traffic statistics for a single client by email.

        Args:
            email: Client email.

        Returns:
            Traffic dict on success, or None if not found / on error.
        """
        try:
            data = await self._request(
                "GET",
                f"/panel/api/clients/traffic/{email}",
            )
        except Exception:
            return None

        if not data.get("success", False):
            return None

        return data.get("obj") or None

    async def get_client(
        self,
        email: str,
    ) -> dict[str, Any] | None:
        """Get a single client by email (alias for :meth:`get_client_traffic`).

        Args:
            email: Client email.

        Returns:
            Client dict on success, or None if not found.
        """
        return await self.get_client_traffic(email)

    async def reset_client_traffic(
        self,
        email: str,
    ) -> bool:
        """Reset traffic counters for a client.

        Args:
            email: Client email.

        Returns:
            True if successful
        """
        data = await self._request(
            "POST",
            f"/panel/api/clients/resetTraffic/{email}",
        )

        if not data.get("success", False):
            raise XUIError(data.get("msg", "Failed to reset traffic"))

        logger.info(f"Reset traffic for client {email}")
        return True

    async def create_api_token(self, name: str = "vpnbot") -> str:
        """Create a Bearer API token on the panel.

        Requires an active session (cookie or existing token).

        Args:
            name: Token name (must be unique, 1-64 chars)

        Returns:
            The created token string

        Raises:
            XUIError: If token creation fails
        """
        data = await self._request(
            "POST",
            "/panel/setting/apiTokens/create",
            json={"name": name},
        )

        if not data.get("success", False):
            raise XUIError(f"Failed to create API token: {data.get('msg', 'Unknown error')}")

        token_obj = data.get("obj", {})
        token = token_obj.get("token", "")
        if not token:
            raise XUIError("API token creation returned empty token")

        logger.info("Created API token '{}' for {}", name, self.base_url)
        return token
