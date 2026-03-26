"""Shared HTTP transport for the ``flex_mls`` package."""

from __future__ import annotations

import os
import time
from typing import Any, Iterator, Mapping, Sequence
from urllib.parse import urljoin

import requests

from flex_mls.auth import (
    BearerTokenAuth,
    OpenIdConnectAuth,
    TokenAuthStrategy,
)
from flex_mls.enums import ResponseFormat
from flex_mls.exceptions import (
    ApiError,
    AuthenticationError,
    AuthorizationError,
    ConfigurationError,
    NetworkError,
    NotFoundError,
    RateLimitError,
    ReplicationEndpointRequiredError,
    ServerError,
    ValidationError,
)
from flex_mls.models import JsonPayload, ODataPage

DEFAULT_BASE_URL = "https://replication.sparkapi.com/Version/3/Reso/OData"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 0.5
DEFAULT_USER_AGENT = "flex-mls-python-client/0.1.0"
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _parse_float_env(env_var: str, default: float) -> float:
    """Safely parse a float environment variable."""

    raw_value = os.getenv(env_var)
    if raw_value is None:
        return default

    try:
        return float(raw_value)
    except ValueError:
        return default


def _parse_int_env(env_var: str, default: int) -> int:
    """Safely parse an integer environment variable."""

    raw_value = os.getenv(env_var)
    if raw_value is None:
        return default

    try:
        return int(raw_value)
    except ValueError:
        return default


class BaseClient:
    """HTTP transport shared by all Flex MLS resource clients.

    Args:
        access_token: Direct bearer token to use for requests.
        auth: Optional auth strategy that supplies bearer tokens.
        base_url: Base URL for RESO API requests.
        session: Optional ``requests.Session`` to reuse across clients.
        timeout_seconds: Default request timeout in seconds.
        max_retries: Number of retries for transient failures.
        retry_backoff_seconds: Initial backoff delay between retries.
        user_agent: User-Agent header value for outgoing requests.
        extra_headers: Additional headers included with every request.
    """

    def __init__(
        self,
        *,
        access_token: str | None = None,
        auth: TokenAuthStrategy | None = None,
        base_url: str = DEFAULT_BASE_URL,
        session: requests.Session | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
        retry_backoff_seconds: float | None = None,
        user_agent: str | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds or _parse_float_env(
            "FLEX_MLS_TIMEOUT_SECONDS",
            DEFAULT_TIMEOUT_SECONDS,
        )
        self.max_retries = max_retries if max_retries is not None else _parse_int_env(
            "FLEX_MLS_MAX_RETRIES",
            DEFAULT_MAX_RETRIES,
        )
        self.retry_backoff_seconds: float = (
            retry_backoff_seconds
            if retry_backoff_seconds is not None
            else _parse_float_env(
                "FLEX_MLS_RETRY_BACKOFF_SECONDS",
                DEFAULT_RETRY_BACKOFF_SECONDS,
            )
        )
        self.user_agent: str = (
            user_agent or os.getenv("FLEX_MLS_USER_AGENT") or DEFAULT_USER_AGENT
        )
        self.extra_headers = dict(extra_headers or {})

        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})

        self.auth = auth or self._resolve_auth(access_token=access_token)

    def _resolve_auth(self, *, access_token: str | None) -> TokenAuthStrategy | None:
        """Resolve the effective auth strategy for the client."""

        if access_token:
            return BearerTokenAuth(access_token=access_token)

        oidc_auth = OpenIdConnectAuth.from_env()
        if oidc_auth is not None:
            return oidc_auth

        return BearerTokenAuth.from_env()

    def _build_url(self, endpoint: str) -> str:
        """Convert a relative endpoint into an absolute request URL."""

        if endpoint.startswith(("https://", "http://")):
            return endpoint

        return urljoin(f"{self.base_url}/", endpoint.lstrip("/"))

    def _authorization_header(self) -> str:
        """Return the Authorization header value for the current auth state.

        Raises:
            AuthenticationError: If an access token is not available.
        """

        if self.auth is None:
            raise AuthenticationError(
                "No authentication configuration is available for this client."
            )

        access_token = self.auth.get_access_token()
        if not access_token:
            raise AuthenticationError(
                "No access token is available. Complete the OIDC flow or provide "
                "a bearer token before making API requests."
            )

        return f"Bearer {access_token}"

    def _build_headers(
        self,
        *,
        accept: ResponseFormat,
        content_type: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        """Build request headers for an API call."""

        request_headers = {
            "Accept": accept.value,
            "Authorization": self._authorization_header(),
            **self.extra_headers,
        }
        if content_type is not None:
            request_headers["Content-Type"] = content_type
        if headers:
            request_headers.update(dict(headers))

        return request_headers

    def _decode_response(self, response: requests.Response) -> JsonPayload:
        """Decode a Spark response into JSON or plain text."""

        if response.status_code == 204:
            return {}

        try:
            payload = response.json()
        except ValueError:
            return response.text

        if isinstance(payload, (dict, list, str)):
            return payload

        return str(payload)

    def _extract_spark_code(self, response_data: Any) -> int | None:
        """Pull a Spark-specific error code from a decoded response payload."""

        if not isinstance(response_data, dict):
            return None

        if isinstance(response_data.get("Code"), int):
            return int(response_data["Code"])

        nested = response_data.get("D")
        if isinstance(nested, dict) and isinstance(nested.get("Code"), int):
            return int(nested["Code"])

        return None

    def _extract_error_message(self, response: requests.Response, response_data: Any) -> str:
        """Extract a readable error message from a Spark response."""

        if isinstance(response_data, dict):
            for key in ("error_description", "message", "Message"):
                if response_data.get(key):
                    return str(response_data[key])

            nested = response_data.get("D")
            if isinstance(nested, dict):
                for key in ("Message", "message", "error_description"):
                    if nested.get(key):
                        return str(nested[key])

        if isinstance(response_data, str) and response_data:
            return response_data

        return f"Spark API request failed with HTTP {response.status_code}."

    def _raise_for_response(self, response: requests.Response) -> None:
        """Raise a typed exception for an error response.

        Args:
            response: Raw HTTP response object.

        Raises:
            ApiError: A typed exception matching the response status and payload.
        """

        response_data = self._decode_response(response)
        spark_code = self._extract_spark_code(response_data)
        message = self._extract_error_message(response, response_data)

        if response.status_code in {400, 422}:
            raise ValidationError(
                message,
                status_code=response.status_code,
                response_data=response_data,
                spark_code=spark_code,
            )
        if response.status_code == 401:
            raise AuthenticationError(
                message,
                status_code=response.status_code,
                response_data=response_data,
                spark_code=spark_code,
            )
        if response.status_code == 403 and spark_code == 1021:
            raise ReplicationEndpointRequiredError(
                message,
                status_code=response.status_code,
                response_data=response_data,
                spark_code=spark_code,
            )
        if response.status_code == 403:
            raise AuthorizationError(
                message,
                status_code=response.status_code,
                response_data=response_data,
                spark_code=spark_code,
            )
        if response.status_code == 404:
            raise NotFoundError(
                message,
                status_code=response.status_code,
                response_data=response_data,
                spark_code=spark_code,
            )
        if response.status_code == 429:
            raise RateLimitError(
                message,
                status_code=response.status_code,
                response_data=response_data,
                spark_code=spark_code,
            )
        if response.status_code >= 500:
            raise ServerError(
                message,
                status_code=response.status_code,
                response_data=response_data,
                spark_code=spark_code,
            )

        raise ApiError(
            message,
            status_code=response.status_code,
            response_data=response_data,
            spark_code=spark_code,
        )

    def _retry_delay(self, *, attempt: int, response: requests.Response | None = None) -> float:
        """Determine the retry delay for the current attempt."""

        if response is not None:
            raw_retry_after = response.headers.get("Retry-After")
        else:
            raw_retry_after = None

        if raw_retry_after is not None:
            try:
                return float(raw_retry_after)
            except ValueError:
                pass

        return float(self.retry_backoff_seconds * (2**attempt))

    def _should_refresh(self, response: requests.Response, *, has_refreshed: bool) -> bool:
        """Report whether the current response should trigger an auth refresh."""

        if has_refreshed or self.auth is None or not self.auth.can_refresh():
            return False

        if response.status_code != 401:
            return False

        response_data = self._decode_response(response)
        spark_code = self._extract_spark_code(response_data)
        www_authenticate = response.headers.get("WWW-Authenticate", "").lower()

        return spark_code == 1020 or "invalid_token" in www_authenticate

    def _refresh_auth(self) -> None:
        """Refresh the current auth state.

        Raises:
            AuthenticationError: If the current auth strategy cannot refresh.
        """

        if self.auth is None or not self.auth.can_refresh():
            raise AuthenticationError("The current auth strategy cannot refresh tokens.")

        self.auth.refresh_tokens(
            session=self.session,
            timeout_seconds=self.timeout_seconds,
        )

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_data: Any = None,
        data: Mapping[str, Any] | None = None,
        files: Mapping[str, Any] | Sequence[tuple[str, Any]] | None = None,
        timeout_seconds: float | None = None,
        accept: ResponseFormat = ResponseFormat.JSON,
        headers: Mapping[str, str] | None = None,
    ) -> JsonPayload:
        """Send an HTTP request to the Spark RESO API.

        Args:
            method: HTTP method to use.
            endpoint: Relative path or absolute URL.
            params: Optional query parameters.
            json_data: Optional JSON request body.
            data: Optional non-JSON body payload.
            files: Optional multipart upload payload.
            timeout_seconds: Optional per-request timeout override.
            accept: Expected response format.
            headers: Optional additional request headers.

        Returns:
            A decoded JSON payload or plain-text response body.

        Raises:
            ApiError: If the request fails permanently.
        """

        url = self._build_url(endpoint)
        effective_timeout = timeout_seconds or self.timeout_seconds
        attempt = 0
        has_refreshed = False

        while True:
            content_type = None if files is not None else "application/json"
            request_headers = self._build_headers(
                accept=accept,
                content_type=content_type if json_data is not None else None,
                headers=headers,
            )
            if files is not None:
                request_headers.pop("Content-Type", None)

            request_kwargs: dict[str, Any] = {
                "method": method.upper(),
                "url": url,
                "headers": request_headers,
                "params": params,
                "timeout": effective_timeout,
            }
            if files is not None:
                request_kwargs["files"] = files
                if data is not None:
                    request_kwargs["data"] = data
            elif json_data is not None:
                request_kwargs["json"] = json_data
            elif data is not None:
                request_kwargs["data"] = data

            try:
                response = self.session.request(**request_kwargs)
            except requests.RequestException as exc:
                if attempt < self.max_retries:
                    time.sleep(self._retry_delay(attempt=attempt))
                    attempt += 1
                    continue

                raise NetworkError("Spark API request failed due to a network error.") from exc

            if self._should_refresh(response, has_refreshed=has_refreshed):
                self._refresh_auth()
                has_refreshed = True
                continue

            if response.status_code in RETRYABLE_STATUS_CODES and attempt < self.max_retries:
                time.sleep(self._retry_delay(attempt=attempt, response=response))
                attempt += 1
                continue

            if response.status_code >= 400:
                self._raise_for_response(response)

            return self._decode_response(response)

    def get(
        self,
        endpoint: str,
        *,
        params: Mapping[str, Any] | None = None,
        timeout_seconds: float | None = None,
        accept: ResponseFormat = ResponseFormat.JSON,
        headers: Mapping[str, str] | None = None,
    ) -> JsonPayload:
        """Send a ``GET`` request.

        Args:
            endpoint: Relative path or absolute URL.
            params: Optional query parameters.
            timeout_seconds: Optional per-request timeout override.
            accept: Expected response format.
            headers: Optional extra headers.

        Returns:
            A decoded response body.
        """

        return self._request(
            "GET",
            endpoint,
            params=params,
            timeout_seconds=timeout_seconds,
            accept=accept,
            headers=headers,
        )

    def post(
        self,
        endpoint: str,
        *,
        json_data: Any = None,
        data: Mapping[str, Any] | None = None,
        files: Mapping[str, Any] | Sequence[tuple[str, Any]] | None = None,
        timeout_seconds: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> JsonPayload:
        """Send a ``POST`` request."""

        return self._request(
            "POST",
            endpoint,
            json_data=json_data,
            data=data,
            files=files,
            timeout_seconds=timeout_seconds,
            headers=headers,
        )

    def put(
        self,
        endpoint: str,
        *,
        json_data: Any = None,
        data: Mapping[str, Any] | None = None,
        timeout_seconds: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> JsonPayload:
        """Send a ``PUT`` request."""

        return self._request(
            "PUT",
            endpoint,
            json_data=json_data,
            data=data,
            timeout_seconds=timeout_seconds,
            headers=headers,
        )

    def patch(
        self,
        endpoint: str,
        *,
        json_data: Any = None,
        data: Mapping[str, Any] | None = None,
        timeout_seconds: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> JsonPayload:
        """Send a ``PATCH`` request."""

        return self._request(
            "PATCH",
            endpoint,
            json_data=json_data,
            data=data,
            timeout_seconds=timeout_seconds,
            headers=headers,
        )

    def delete(
        self,
        endpoint: str,
        *,
        timeout_seconds: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> JsonPayload:
        """Send a ``DELETE`` request."""

        return self._request(
            "DELETE",
            endpoint,
            timeout_seconds=timeout_seconds,
            headers=headers,
        )

    def get_metadata(self, *, timeout_seconds: float | None = None) -> str:
        """Fetch the RESO metadata document as XML.

        Args:
            timeout_seconds: Optional per-request timeout override.

        Returns:
            The raw XML metadata document.

        Raises:
            ConfigurationError: If the metadata response is not XML text.
        """

        payload = self.get(
            "$metadata",
            timeout_seconds=timeout_seconds,
            accept=ResponseFormat.XML,
        )
        if not isinstance(payload, str):
            raise ConfigurationError("Spark metadata response was not XML text.")

        return payload

    def get_page(
        self,
        endpoint: str,
        *,
        params: Mapping[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> ODataPage[dict[str, Any]]:
        """Fetch and parse one OData result page.

        Args:
            endpoint: Relative path or absolute URL for the collection request.
            params: Optional query parameters.
            timeout_seconds: Optional per-request timeout override.

        Returns:
            A parsed OData page.

        Raises:
            ConfigurationError: If Spark returns a non-mapping payload.
        """

        payload = self.get(endpoint, params=params, timeout_seconds=timeout_seconds)
        if not isinstance(payload, dict):
            raise ConfigurationError("Expected an OData response object.")

        return ODataPage.from_response(payload)

    def iter_pages(
        self,
        endpoint: str,
        *,
        params: Mapping[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> Iterator[ODataPage[dict[str, Any]]]:
        """Iterate over all OData pages starting at the given endpoint.

        Args:
            endpoint: Relative path or absolute URL for the collection request.
            params: Optional query parameters for the first request.
            timeout_seconds: Optional per-request timeout override.

        Yields:
            Parsed OData pages following ``@odata.nextLink`` until exhaustion.
        """

        next_endpoint: str | None = endpoint
        next_params: Mapping[str, Any] | None = params

        while next_endpoint is not None:
            page = self.get_page(
                next_endpoint,
                params=next_params,
                timeout_seconds=timeout_seconds,
            )
            yield page
            next_endpoint = page.next_link
            next_params = None
