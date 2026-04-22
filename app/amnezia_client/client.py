from typing import Any

import aiohttp

from .exceptions import AmneziaAuthError, AmneziaConnectionError, AmneziaError
from .models import (
    AmneziaClientCreateResponse,
    AmneziaClientDetails,
    AmneziaProtocol,
    AmneziaServer,
)


class AmneziaClient:
    def __init__(
        self,
        base_url: str,
        email: str,
        password: str,
        verify_ssl: bool = False,
    ):
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.password = password
        self.verify_ssl = verify_ssl
        self._session: aiohttp.ClientSession | None = None
        self._token: str | None = None

    async def __aenter__(self):
        await self._init_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def _init_session(self):
        if self._session is None:
            self._session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(verify_ssl=self.verify_ssl)
            )

    async def close(self):
        if self._session:
            await self._session.close()
            self._session = None

    async def _ensure_auth(self):
        await self._init_session()
        if not self._token:
            await self.login()

    async def login(self) -> str:
        await self._init_session()
        url = f"{self.base_url}/auth/token"
        data = {"email": self.email, "password": self.password}

        try:
            assert self._session is not None
            async with self._session.post(url, data=data) as response:
                if response.status != 200:
                    text = await response.text()
                    raise AmneziaAuthError(f"Login failed: {response.status} {text}")

                result = await response.json()
                self._token = result.get("token")
                if not self._token:
                    raise AmneziaAuthError("Token not found in response")
                return self._token
        except aiohttp.ClientError as e:
            raise AmneziaConnectionError(f"Connection error during login: {e}") from e

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        await self._ensure_auth()

        url = f"{self.base_url}{path}"
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self._token}"

        try:
            assert self._session is not None
            async with self._session.request(method, url, headers=headers, **kwargs) as response:
                if response.status in (401, 403):
                    # Try to refresh token once
                    await self.login()
                    headers["Authorization"] = f"Bearer {self._token}"
                    async with self._session.request(
                        method, url, headers=headers, **kwargs
                    ) as retry_resp:
                        retry_resp.raise_for_status()
                        content_type = retry_resp.content_type
                        if retry_resp.status == 204 or not content_type.startswith(
                            "application/json"
                        ):
                            text = await retry_resp.text()
                            try:
                                import json

                                return json.loads(text)
                            except Exception:
                                return text
                        return await retry_resp.json()

                response.raise_for_status()

                content_type = response.content_type
                if response.status == 204 or not content_type.startswith("application/json"):
                    text = await response.text()
                    try:
                        import json

                        return json.loads(text)
                    except Exception:
                        return text
                return await response.json()
        except aiohttp.ClientResponseError as e:
            raise AmneziaError(f"API request failed with status {e.status}: {e.message}") from e
        except aiohttp.ClientError as e:
            raise AmneziaConnectionError(f"Connection error: {e}") from e
        except Exception as e:
            if isinstance(e, AmneziaError):
                raise
            raise AmneziaError(f"API request failed: {e}") from e

    async def get_active_protocols(self) -> list[AmneziaProtocol]:
        data = await self._request("GET", "/protocols/active")
        protocols = data.get("protocols", [])
        return [AmneziaProtocol(**p) for p in protocols]

    async def get_servers(self) -> list[AmneziaServer]:
        data = await self._request("GET", "/servers")
        servers = data.get("servers", [])
        return [AmneziaServer(**s) for s in servers]

    async def create_client(
        self, server_id: int, name: str, expires_in_days: int
    ) -> AmneziaClientCreateResponse:
        data = await self._request(
            "POST",
            "/clients/create",
            json={"server_id": server_id, "name": name, "expires_in_days": expires_in_days},
        )
        return AmneziaClientCreateResponse(**data)

    async def set_traffic_limit(self, client_id: int, limit_bytes: int) -> bool:
        data = await self._request(
            "POST", f"/clients/{client_id}/set-traffic-limit", json={"limit_bytes": limit_bytes}
        )
        return data.get("success", True) if isinstance(data, dict) else True

    async def set_expiration(self, client_id: int, expires_at_str: str) -> bool:
        data = await self._request(
            "POST", f"/clients/{client_id}/set-expiration", json={"expires_at_str": expires_at_str}
        )
        return data.get("success", True) if isinstance(data, dict) else True

    async def get_client_details(self, client_id: int) -> AmneziaClientDetails:
        data = await self._request("GET", f"/clients/{client_id}/details")
        client_data = data.get("client", {})
        return AmneziaClientDetails(**client_data)

    async def delete_client(self, client_id: int) -> bool:
        data = await self._request("DELETE", f"/clients/{client_id}/delete")
        if isinstance(data, dict):
            return data.get("success", True)
        return True
