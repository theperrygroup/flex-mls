"""Shared models for the ``flex_mls`` package."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Generic, Mapping, TypeVar

JsonMapping = dict[str, Any]
JsonRecord = dict[str, Any]
JsonList = list[JsonRecord]
JsonPayload = JsonMapping | JsonList | str
ScalarQueryValue = str | int | float | bool

_T = TypeVar("_T")


def _utc_now() -> datetime:
    """Return the current UTC timestamp."""

    return datetime.now(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    """Format a datetime as the UTC timestamp string Spark expects."""

    normalized = value.astimezone(timezone.utc).replace(microsecond=0)
    return normalized.isoformat().replace("+00:00", "Z")


@dataclass(slots=True)
class AuthTokens:
    """Container for OAuth token responses.

    Attributes:
        access_token: Access token used for authenticated API requests.
        token_type: Token type returned by Spark. Usually ``Bearer``.
        expires_in: Token lifetime in seconds, when the server supplies one.
        refresh_token: Refresh token used to renew an expired access token.
        id_token: OpenID Connect ID token returned by Spark.
        obtained_at: Timestamp at which the token set was obtained.
    """

    access_token: str
    token_type: str = "Bearer"
    expires_in: int | None = None
    refresh_token: str | None = None
    id_token: str | None = None
    obtained_at: datetime = field(default_factory=_utc_now)

    def authorization_header(self) -> str:
        """Build the Authorization header value for this token set.

        Returns:
            The ``Authorization`` header value.
        """

        return f"{self.token_type} {self.access_token}"

    def expires_at(self) -> datetime | None:
        """Return the absolute expiration time for the access token.

        Returns:
            The UTC expiration timestamp when ``expires_in`` is available,
            otherwise ``None``.
        """

        if self.expires_in is None:
            return None

        return self.obtained_at + timedelta(seconds=self.expires_in)

    def is_expired(self, buffer_seconds: int = 0) -> bool:
        """Report whether the access token should be treated as expired.

        Args:
            buffer_seconds: Optional time buffer applied before expiration to
                proactively refresh the token.

        Returns:
            ``True`` when the token is expired or about to expire.
        """

        expires_at = self.expires_at()
        if expires_at is None:
            return False

        return _utc_now() >= expires_at - timedelta(seconds=buffer_seconds)


@dataclass(slots=True)
class ODataQueryOptions:
    """Typed representation of common OData query parameters.

    Attributes:
        select: Top-level fields to include in the response.
        top: Maximum number of records to return.
        skip: Number of records to skip.
        count: Whether the server should include ``@odata.count``.
        order_by: Sort expressions sent via ``$orderby``.
        filter_expression: Raw OData filter expression.
        expand: Expansion expressions for related entities.
        extra_params: Any additional raw query parameters to include.
    """

    select: tuple[str, ...] = ()
    top: int | None = None
    skip: int | None = None
    count: bool | None = None
    order_by: tuple[str, ...] = ()
    filter_expression: str | None = None
    expand: tuple[str, ...] = ()
    extra_params: dict[str, ScalarQueryValue] = field(default_factory=dict)

    def to_params(self) -> dict[str, ScalarQueryValue]:
        """Convert the query options into Spark-compatible request parameters.

        Returns:
            A dictionary that can be passed directly to ``requests``.
        """

        params: dict[str, ScalarQueryValue] = dict(self.extra_params)

        if self.select:
            params["$select"] = ",".join(self.select)
        if self.top is not None:
            params["$top"] = self.top
        if self.skip is not None:
            params["$skip"] = self.skip
        if self.count is not None:
            params["$count"] = str(self.count).lower()
        if self.order_by:
            params["$orderby"] = ",".join(self.order_by)
        if self.filter_expression:
            params["$filter"] = self.filter_expression
        if self.expand:
            params["$expand"] = ",".join(self.expand)

        return params


@dataclass(slots=True)
class ODataPage(Generic[_T]):
    """One page of OData response data.

    Attributes:
        records: Records from the ``value`` array.
        next_link: Absolute URL for the next page, when present.
        count: Total number of matching records, when requested.
        raw: The raw JSON payload returned by Spark.
    """

    records: list[_T]
    next_link: str | None = None
    count: int | None = None
    raw: JsonMapping = field(default_factory=dict)

    @classmethod
    def from_response(cls, payload: Mapping[str, Any]) -> "ODataPage[JsonRecord]":
        """Create an ``ODataPage`` from a RESO response payload.

        Args:
            payload: Raw JSON mapping returned by Spark.

        Returns:
            A typed page object built from the payload's ``value`` array.

        Raises:
            TypeError: If the response payload is not a mapping.
        """

        if not isinstance(payload, Mapping):
            raise TypeError("Expected an OData payload mapping.")

        raw_records = payload.get("value", [])
        records: list[JsonRecord] = []
        if isinstance(raw_records, list):
            records = [item for item in raw_records if isinstance(item, dict)]

        return ODataPage[JsonRecord](
            records=records,
            next_link=payload.get("@odata.nextLink"),
            count=payload.get("@odata.count"),
            raw=dict(payload),
        )


@dataclass(slots=True)
class ReplicationWindow:
    """Time window used for incremental RESO replication polling.

    Attributes:
        start: Exclusive lower bound for ``ModificationTimestamp``.
        end: Exclusive upper bound for ``ModificationTimestamp``.
    """

    start: datetime
    end: datetime

    def to_filter(self, additional_filter: str | None = None) -> str:
        """Build a bounded ``ModificationTimestamp`` filter expression.

        Args:
            additional_filter: Optional extra filter expression to append.

        Returns:
            A Spark-compatible OData filter expression.
        """

        base = (
            f"(ModificationTimestamp gt {_format_timestamp(self.start)} and "
            f"ModificationTimestamp lt {_format_timestamp(self.end)})"
        )
        if not additional_filter:
            return base

        return f"({base} and ({additional_filter}))"


@dataclass(slots=True)
class ClientConfig:
    """Resolved shared configuration for a ``FlexMlsClient`` instance.

    Attributes:
        base_url: Base URL for standard RESO API requests.
        timeout_seconds: Default timeout applied to all requests.
        max_retries: Number of retries for transient errors.
        retry_backoff_seconds: Initial delay applied before retrying a request.
        user_agent: User-Agent header applied to outgoing requests.
        extra_headers: Additional headers added to every request.
    """

    base_url: str
    timeout_seconds: float
    max_retries: int
    retry_backoff_seconds: float
    user_agent: str
    extra_headers: dict[str, str] = field(default_factory=dict)
