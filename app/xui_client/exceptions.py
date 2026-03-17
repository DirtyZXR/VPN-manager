"""Exceptions for XUI client."""


class XUIError(Exception):
    """Base exception for XUI client errors."""

    pass


class XUIAuthError(XUIError):
    """Authentication failed."""

    pass


class XUIConnectionError(XUIError):
    """Connection to XUI panel failed."""

    pass


class XUINotFoundError(XUIError):
    """Resource not found in XUI."""

    pass


class XUIValidationError(XUIError):
    """Validation error in XUI request."""

    pass


class XUIClientError(XUIError):
    """Client-related error in XUI."""

    pass
