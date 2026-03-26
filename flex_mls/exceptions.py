"""Custom exception hierarchy for the ``flex_mls`` package."""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    """Base exception for errors raised by the Flex MLS client.

    Args:
        message: Human-readable error message.
        status_code: Optional HTTP status code returned by the server.
        response_data: Optional decoded response payload returned by Spark.
        spark_code: Optional Spark-specific error code.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_data: Any = None,
        spark_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.response_data = response_data
        self.spark_code = spark_code


class AuthenticationError(ApiError):
    """Raised when authentication credentials are missing or invalid."""


class AuthorizationError(ApiError):
    """Raised when the current key or user lacks permission for a request."""


class ValidationError(ApiError):
    """Raised when request parameters or payloads are invalid."""


class NotFoundError(ApiError):
    """Raised when the requested resource cannot be found."""


class RateLimitError(ApiError):
    """Raised when the API rate limit has been exceeded."""


class ServerError(ApiError):
    """Raised for 5xx upstream server failures."""


class NetworkError(ApiError):
    """Raised for client-side network errors."""


class ConfigurationError(ApiError):
    """Raised when the client is misconfigured."""


class ReplicationEndpointRequiredError(AuthorizationError):
    """Raised when Spark requires the replication endpoint to be used."""
