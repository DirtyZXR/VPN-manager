class AmneziaError(Exception):
    """Base exception for Amnezia API client."""

    pass


class AmneziaAuthError(AmneziaError):
    """Raised when authentication fails."""

    pass


class AmneziaConnectionError(AmneziaError):
    """Raised when connection to Amnezia API fails."""

    pass
