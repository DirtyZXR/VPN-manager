"""XUI client package."""

from app.xui_client.client import XUIClient
from app.xui_client.exceptions import (
    XUIAuthError,
    XUIConnectionError,
    XUIError,
    XUINotFoundError,
    XUIValidationError,
)
from app.xui_client.models import (
    XUIAddClientRequest,
    XUIInbound,
)
from app.xui_client.models import (
    XUIClient as XUIClientModel,
)

__all__ = [
    "XUIClient",
    "XUIError",
    "XUIAuthError",
    "XUIConnectionError",
    "XUINotFoundError",
    "XUIValidationError",
    "XUIInbound",
    "XUIClientModel",
    "XUIAddClientRequest",
]
