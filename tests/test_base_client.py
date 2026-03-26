"""Tests for the shared HTTP transport."""

from __future__ import annotations

import json
from typing import Any

import pytest
import requests
import responses
from requests.structures import CaseInsensitiveDict

from flex_mls.auth import BearerTokenAuth, OpenIdConnectAuth
from flex_mls.base_client import BaseClient, DEFAULT_BASE_URL, ResponseFormat
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
from flex_mls.models import AuthTokens


class _NoTokenAuth:
    """Auth strategy that never supplies an access token."""

    def get_access_token(self) -> str | None:
        """Return no access token.

        Returns:
            ``None`` to simulate a missing token.
        """

        return None

    def can_refresh(self) -> bool:
        """Report that this strategy cannot refresh tokens.

        Returns:
            ``False`` because no refresh flow is available.
        """

        return False

    def refresh_tokens(
        self,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 30.0,
    ) -> AuthTokens:
        """Reject refresh calls for the no-token strategy.

        Args:
            session: Unused. Present for protocol compatibility.
            timeout_seconds: Unused. Present for protocol compatibility.

        Raises:
            AssertionError: Always, because refresh should not be called here.
        """

        del session, timeout_seconds
        raise AssertionError("refresh_tokens should not be called for _NoTokenAuth")


class _RefreshingAuth:
    """Refresh-capable auth strategy used to exercise refresh branches."""

    def __init__(
        self,
        *,
        access_token: str | None = "access-token",
        refreshable: bool = True,
    ) -> None:
        self.access_token = access_token
        self.refreshable = refreshable
        self.refreshed = False
        self.refresh_session: requests.Session | None = None
        self.refresh_timeout_seconds: float | None = None

    def get_access_token(self) -> str | None:
        """Return the current access token.

        Returns:
            The configured access token, if available.
        """

        return self.access_token

    def can_refresh(self) -> bool:
        """Report whether the strategy can refresh.

        Returns:
            The configured refresh capability flag.
        """

        return self.refreshable

    def refresh_tokens(
        self,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 30.0,
    ) -> AuthTokens:
        """Record refresh parameters and update the access token.

        Args:
            session: Session passed by the transport.
            timeout_seconds: Timeout value passed by the transport.

        Returns:
            A fresh token set.
        """

        self.refreshed = True
        self.refresh_session = session
        self.refresh_timeout_seconds = timeout_seconds
        self.access_token = "fresh-token"
        return AuthTokens(access_token="fresh-token", refresh_token="refresh-token")


def _make_response(
    *,
    status_code: int,
    body: str,
    headers: dict[str, str] | None = None,
) -> requests.Response:
    """Build a real ``requests.Response`` object for unit-style transport tests.

    Args:
        status_code: HTTP status code for the response.
        body: Raw response body.
        headers: Optional response headers.

    Returns:
        A configured ``requests.Response`` instance.
    """

    response = requests.Response()
    response.status_code = status_code
    response._content = body.encode("utf-8")
    response.encoding = "utf-8"
    response.url = f"{DEFAULT_BASE_URL}/test"
    response.headers = CaseInsensitiveDict(headers or {})
    return response


@responses.activate
def test_get_uses_bearer_auth_and_json_accept_header() -> None:
    """GET requests send bearer auth and expect JSON by default."""

    responses.get(
        f"{DEFAULT_BASE_URL}/Property",
        json={"value": [{"ListingKey": "123"}]},
        status=200,
    )

    client = BaseClient(access_token="access-token")
    payload = client.get("Property")

    assert isinstance(payload, dict)
    assert payload["value"][0]["ListingKey"] == "123"
    request = responses.calls[0].request
    assert request.headers["Authorization"] == "Bearer access-token"
    assert request.headers["Accept"] == "application/json"


@responses.activate
def test_get_metadata_requests_xml() -> None:
    """Metadata requests use the XML accept header."""

    responses.get(
        f"{DEFAULT_BASE_URL}/$metadata",
        body="<xml />",
        content_type="application/xml",
        status=200,
    )

    client = BaseClient(access_token="access-token")
    payload = client.get_metadata()

    assert payload == "<xml />"
    request = responses.calls[0].request
    assert request.headers["Accept"] == "application/xml"


@responses.activate
def test_delete_204_returns_empty_mapping() -> None:
    """No-content responses are normalized to empty mappings."""

    responses.delete(f"{DEFAULT_BASE_URL}/Property('123')", status=204)

    client = BaseClient(access_token="access-token")

    assert client.delete("Property('123')") == {}


@responses.activate
def test_replication_endpoint_error_is_mapped() -> None:
    """Spark's replication-host error is mapped to a dedicated exception."""

    responses.get(
        f"{DEFAULT_BASE_URL}/Property",
        json={"D": {"Code": 1021, "Message": "Use replication.sparkapi.com"}},
        status=403,
    )

    client = BaseClient(access_token="access-token")

    with pytest.raises(ReplicationEndpointRequiredError):
        client.get("Property")


@responses.activate
def test_oidc_auth_refreshes_after_expired_session() -> None:
    """The transport retries once after refreshing an expired OIDC token."""

    oidc_auth = OpenIdConnectAuth(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="https://example.com/callback",
        tokens=AuthTokens(
            access_token="expired-access-token",
            refresh_token="refresh-token",
            expires_in=1,
        ),
    )

    responses.get(
        f"{DEFAULT_BASE_URL}/Property",
        json={"D": {"Code": 1020, "Message": "Session token has expired"}},
        status=401,
        headers={"WWW-Authenticate": "Bearer realm='Flexmls API', error='invalid_token'"},
    )
    responses.post(
        "https://sparkplatform.com/openid/token",
        json={
            "access_token": "fresh-access-token",
            "refresh_token": "fresh-refresh-token",
            "expires_in": 86400,
            "token_type": "Bearer",
        },
        status=200,
    )
    responses.get(
        f"{DEFAULT_BASE_URL}/Property",
        json={"value": [{"ListingKey": "123"}]},
        status=200,
    )

    client = BaseClient(auth=oidc_auth)
    payload = client.get("Property")

    assert isinstance(payload, dict)
    assert payload["value"][0]["ListingKey"] == "123"
    assert oidc_auth.tokens is not None
    assert oidc_auth.tokens.access_token == "fresh-access-token"
    assert responses.calls[2].request.headers["Authorization"] == "Bearer fresh-access-token"


@responses.activate
def test_iter_pages_follows_next_link() -> None:
    """Page iteration follows Spark's absolute ``@odata.nextLink`` URL."""

    next_link = f"{DEFAULT_BASE_URL}/Property?%24skiptoken=abc123&%24top=1000"
    responses.get(
        f"{DEFAULT_BASE_URL}/Property",
        json={
            "value": [{"ListingKey": "1"}],
            "@odata.nextLink": next_link,
            "@odata.count": 2,
        },
        status=200,
    )
    responses.get(
        next_link,
        json={"value": [{"ListingKey": "2"}], "@odata.count": 2},
        status=200,
    )

    client = BaseClient(access_token="access-token")
    pages = list(client.iter_pages("Property", params={"$top": 1000}))

    assert len(pages) == 2
    assert pages[0].next_link == next_link
    assert pages[1].records[0]["ListingKey"] == "2"


@responses.activate
def test_file_upload_does_not_force_json_content_type() -> None:
    """Multipart uploads allow ``requests`` to manage the content type."""

    def callback(request: Any) -> tuple[int, dict[str, str], str]:
        assert request.headers.get("Content-Type") != "application/json"
        return 200, {"Content-Type": "application/json"}, '{"ok": true}'

    responses.add_callback(
        responses.POST,
        f"{DEFAULT_BASE_URL}/upload",
        callback=callback,
        content_type="application/json",
    )

    client = BaseClient(access_token="access-token")
    payload = client.post("upload", files={"file": ("example.txt", b"hello")})

    assert payload == {"ok": True}


def test_network_error_raises_network_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated network failures raise ``NetworkError``."""

    client = BaseClient(access_token="access-token", max_retries=0)

    def raise_connection_error(**kwargs: Any) -> Any:
        raise requests.ConnectionError("boom")

    monkeypatch.setattr(client.session, "request", raise_connection_error)

    with pytest.raises(NetworkError):
        client.get("Property")


def test_constructor_uses_valid_environment_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Environment variables configure the transport when explicit values are absent."""

    monkeypatch.setenv("FLEX_MLS_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("FLEX_MLS_MAX_RETRIES", "7")
    monkeypatch.setenv("FLEX_MLS_RETRY_BACKOFF_SECONDS", "0.25")
    monkeypatch.setenv("FLEX_MLS_USER_AGENT", "env-user-agent")

    client = BaseClient(auth=BearerTokenAuth(access_token="access-token"))

    assert client.timeout_seconds == 12.5
    assert client.max_retries == 7
    assert client.retry_backoff_seconds == 0.25
    assert client.user_agent == "env-user-agent"


def test_constructor_falls_back_for_invalid_environment_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid environment values fall back to the documented defaults."""

    monkeypatch.setenv("FLEX_MLS_TIMEOUT_SECONDS", "not-a-float")
    monkeypatch.setenv("FLEX_MLS_MAX_RETRIES", "not-an-int")
    monkeypatch.setenv("FLEX_MLS_RETRY_BACKOFF_SECONDS", "not-a-float")

    client = BaseClient(auth=BearerTokenAuth(access_token="access-token"))

    assert client.timeout_seconds == 30.0
    assert client.max_retries == 3
    assert client.retry_backoff_seconds == 0.5


def test_base_client_prefers_oidc_auth_discovered_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OIDC environment configuration wins over bearer-token fallback discovery."""

    discovered_auth = OpenIdConnectAuth(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="https://example.com/callback",
    )

    def fake_oidc_from_env(cls: type[OpenIdConnectAuth]) -> OpenIdConnectAuth | None:
        """Return a discovered OIDC auth object.

        Args:
            cls: The ``OpenIdConnectAuth`` class.

        Returns:
            The discovered OIDC auth instance.
        """

        del cls
        return discovered_auth

    def fail_bearer_from_env(cls: type[BearerTokenAuth]) -> BearerTokenAuth | None:
        """Fail if bearer fallback discovery is reached unexpectedly.

        Args:
            cls: The ``BearerTokenAuth`` class.

        Raises:
            AssertionError: Always, because the bearer fallback should be skipped.
        """

        del cls
        raise AssertionError("BearerTokenAuth.from_env should not be called")

    monkeypatch.setattr(OpenIdConnectAuth, "from_env", classmethod(fake_oidc_from_env))
    monkeypatch.setattr(BearerTokenAuth, "from_env", classmethod(fail_bearer_from_env))

    client = BaseClient()

    assert client.auth is discovered_auth


def test_base_client_uses_bearer_fallback_when_oidc_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bearer-token environment discovery is used when OIDC is unavailable."""

    discovered_auth = BearerTokenAuth(access_token="env-access-token")

    def fake_oidc_from_env(cls: type[OpenIdConnectAuth]) -> OpenIdConnectAuth | None:
        """Return no discovered OIDC auth object.

        Args:
            cls: The ``OpenIdConnectAuth`` class.

        Returns:
            ``None`` to force bearer fallback discovery.
        """

        del cls
        return None

    def fake_bearer_from_env(cls: type[BearerTokenAuth]) -> BearerTokenAuth | None:
        """Return a discovered bearer auth object.

        Args:
            cls: The ``BearerTokenAuth`` class.

        Returns:
            The discovered bearer auth instance.
        """

        del cls
        return discovered_auth

    monkeypatch.setattr(OpenIdConnectAuth, "from_env", classmethod(fake_oidc_from_env))
    monkeypatch.setattr(BearerTokenAuth, "from_env", classmethod(fake_bearer_from_env))

    client = BaseClient()

    assert client.auth is discovered_auth


def test_authorization_header_requires_auth_configuration() -> None:
    """Requests fail fast when no auth strategy is configured."""

    client = BaseClient(auth=BearerTokenAuth(access_token="access-token"))
    client.auth = None

    with pytest.raises(AuthenticationError):
        client._authorization_header()


def test_authorization_header_requires_an_access_token() -> None:
    """Requests fail fast when the auth strategy has no access token."""

    client = BaseClient(auth=_NoTokenAuth())

    with pytest.raises(AuthenticationError):
        client._authorization_header()


def test_build_headers_merges_content_type_and_extra_headers() -> None:
    """Header construction preserves base headers and caller overrides."""

    client = BaseClient(
        access_token="access-token",
        extra_headers={"X-Base": "base-value"},
    )

    headers = client._build_headers(
        accept=ResponseFormat.JSON,
        content_type="application/json",
        headers={"X-Trace": "trace-value"},
    )

    assert headers["Accept"] == "application/json"
    assert headers["Authorization"] == "Bearer access-token"
    assert headers["Content-Type"] == "application/json"
    assert headers["X-Base"] == "base-value"
    assert headers["X-Trace"] == "trace-value"


def test_decode_response_handles_plain_text_and_scalar_json() -> None:
    """Response decoding normalizes plain text and scalar JSON payloads."""

    client = BaseClient(access_token="access-token")
    text_response = _make_response(status_code=200, body="not-json")
    scalar_json_response = _make_response(status_code=200, body="7")

    assert client._decode_response(text_response) == "not-json"
    assert client._decode_response(scalar_json_response) == "7"


def test_extract_spark_code_handles_top_level_nested_and_invalid_payloads() -> None:
    """Spark error codes can be extracted from top-level and nested payloads."""

    client = BaseClient(access_token="access-token")

    assert client._extract_spark_code({"Code": 1019}) == 1019
    assert client._extract_spark_code({"D": {"Code": 1021}}) == 1021
    assert client._extract_spark_code({"D": {"Code": "1021"}}) is None
    assert client._extract_spark_code("not-a-dict") is None


def test_extract_error_message_prefers_payload_fields_then_falls_back() -> None:
    """Error-message extraction prefers payload details over generic fallbacks."""

    client = BaseClient(access_token="access-token")
    response = _make_response(status_code=418, body="{}")

    assert client._extract_error_message(response, {"message": "top-level"}) == "top-level"
    assert client._extract_error_message(response, {"D": {"Message": "nested-message"}}) == (
        "nested-message"
    )
    assert client._extract_error_message(response, {"D": {"message": "nested-lowercase"}}) == (
        "nested-lowercase"
    )
    assert client._extract_error_message(response, "plain-text-message") == "plain-text-message"
    assert (
        client._extract_error_message(response, {"unexpected": "value"})
        == "Spark API request failed with HTTP 418."
    )
    assert (
        client._extract_error_message(response, {"D": {"Other": "value"}})
        == "Spark API request failed with HTTP 418."
    )


@pytest.mark.parametrize(
    ("status_code", "payload", "expected_exception"),
    [
        (400, {"message": "bad-request"}, ValidationError),
        (401, {"message": "unauthorized"}, AuthenticationError),
        (403, {"message": "forbidden"}, AuthorizationError),
        (404, {"message": "missing"}, NotFoundError),
        (429, {"message": "slow-down"}, RateLimitError),
        (500, {"message": "server-error"}, ServerError),
        (418, {"message": "teapot"}, ApiError),
    ],
)
def test_raise_for_response_maps_error_statuses(
    status_code: int,
    payload: dict[str, str],
    expected_exception: type[Exception],
) -> None:
    """Transport errors are converted into the expected typed exceptions."""

    client = BaseClient(access_token="access-token")
    response = _make_response(status_code=status_code, body=json.dumps(payload))

    with pytest.raises(expected_exception) as exc_info:
        client._raise_for_response(response)

    error = exc_info.value
    assert isinstance(error, ApiError)
    assert error.status_code == status_code


def test_retry_delay_prefers_retry_after_header_and_falls_back_to_backoff() -> None:
    """Retry delays honor valid server hints and otherwise use exponential backoff."""

    client = BaseClient(access_token="access-token", retry_backoff_seconds=0.25)
    valid_retry_after = _make_response(
        status_code=429,
        body="{}",
        headers={"Retry-After": "1.5"},
    )
    invalid_retry_after = _make_response(
        status_code=429,
        body="{}",
        headers={"Retry-After": "not-a-number"},
    )

    assert client._retry_delay(attempt=2, response=valid_retry_after) == 1.5
    assert client._retry_delay(attempt=2, response=invalid_retry_after) == 1.0
    assert client._retry_delay(attempt=1) == 0.5


def test_should_refresh_detects_refreshable_invalid_token_responses() -> None:
    """Refresh detection requires a refreshable auth strategy and a token signal."""

    refreshable_auth = _RefreshingAuth()
    client = BaseClient(auth=refreshable_auth)
    invalid_token_response = _make_response(
        status_code=401,
        body='{"message": "expired"}',
        headers={"WWW-Authenticate": "Bearer error=invalid_token"},
    )
    non_refresh_response = _make_response(status_code=401, body='{"message": "unauthorized"}')

    assert client._should_refresh(invalid_token_response, has_refreshed=False) is True
    assert client._should_refresh(non_refresh_response, has_refreshed=False) is False
    assert client._should_refresh(_make_response(status_code=503, body="{}"), has_refreshed=False) is False
    assert client._should_refresh(invalid_token_response, has_refreshed=True) is False

    client.auth = None
    assert client._should_refresh(invalid_token_response, has_refreshed=False) is False


def test_refresh_auth_raises_for_non_refreshable_auth() -> None:
    """Refreshing requires a refresh-capable auth strategy."""

    client = BaseClient(access_token="access-token")

    with pytest.raises(AuthenticationError):
        client._refresh_auth()


def test_refresh_auth_passes_session_and_timeout_to_strategy() -> None:
    """Refreshing forwards the shared session and timeout settings."""

    refreshable_auth = _RefreshingAuth()
    client = BaseClient(auth=refreshable_auth, timeout_seconds=12.0)

    client._refresh_auth()

    assert refreshable_auth.refreshed is True
    assert refreshable_auth.refresh_session is client.session
    assert refreshable_auth.refresh_timeout_seconds == 12.0


def test_request_retries_network_failures_before_succeeding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Transient network failures retry before the transport gives up."""

    client = BaseClient(access_token="access-token", max_retries=1)
    sleep_calls: list[float] = []
    attempts = {"count": 0}

    def fake_sleep(delay: float) -> None:
        """Capture retry delays.

        Args:
            delay: Delay passed to ``time.sleep``.
        """

        sleep_calls.append(delay)

    def fake_request(**kwargs: Any) -> requests.Response:
        """Raise once, then return a successful response.

        Args:
            **kwargs: Request arguments forwarded by the transport.

        Returns:
            A successful response on the second call.

        Raises:
            requests.ConnectionError: On the first call.
        """

        attempts["count"] += 1
        if attempts["count"] == 1:
            raise requests.ConnectionError("temporary network failure")

        return _make_response(status_code=200, body='{"ok": true}')

    monkeypatch.setattr("time.sleep", fake_sleep)
    monkeypatch.setattr(client.session, "request", fake_request)

    assert client.get("Property") == {"ok": True}
    assert attempts["count"] == 2
    assert sleep_calls == [0.5]


def test_request_retries_retryable_status_codes_before_succeeding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retryable upstream status codes back off and retry."""

    client = BaseClient(access_token="access-token", max_retries=1)
    sleep_calls: list[float] = []
    attempts = {"count": 0}

    def fake_sleep(delay: float) -> None:
        """Capture retry delays.

        Args:
            delay: Delay passed to ``time.sleep``.
        """

        sleep_calls.append(delay)

    def fake_request(**kwargs: Any) -> requests.Response:
        """Return a retryable error once, then a successful response.

        Args:
            **kwargs: Request arguments forwarded by the transport.

        Returns:
            A retryable response on the first call and a success on the second.
        """

        attempts["count"] += 1
        if attempts["count"] == 1:
            return _make_response(
                status_code=503,
                body='{"message": "temporarily unavailable"}',
                headers={"Retry-After": "1.25"},
            )

        return _make_response(status_code=200, body='{"ok": true}')

    monkeypatch.setattr("time.sleep", fake_sleep)
    monkeypatch.setattr(client.session, "request", fake_request)

    assert client.get("Property") == {"ok": True}
    assert attempts["count"] == 2
    assert sleep_calls == [1.25]


def test_request_supports_json_data_form_data_and_multipart_form_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Request construction uses the correct body argument for each payload style."""

    client = BaseClient(access_token="access-token")
    request_calls: list[dict[str, Any]] = []

    def fake_request(**kwargs: Any) -> requests.Response:
        """Capture outgoing request keyword arguments.

        Args:
            **kwargs: Request arguments forwarded by the transport.

        Returns:
            A successful JSON response.
        """

        request_calls.append(dict(kwargs))
        return _make_response(status_code=200, body='{"ok": true}')

    monkeypatch.setattr(client.session, "request", fake_request)

    assert client.post("Property", json_data={"name": "json"}) == {"ok": True}
    assert client.post("Property", data={"name": "form"}) == {"ok": True}
    assert (
        client.post(
            "upload",
            files={"file": ("example.txt", b"hello")},
            data={"folder": "docs"},
        )
        == {"ok": True}
    )

    assert request_calls[0]["json"] == {"name": "json"}
    assert "data" not in request_calls[0]
    assert request_calls[1]["data"] == {"name": "form"}
    assert "json" not in request_calls[1]
    assert request_calls[2]["files"] == {"file": ("example.txt", b"hello")}
    assert request_calls[2]["data"] == {"folder": "docs"}


def test_put_and_patch_delegate_to_request_with_expected_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Convenience wrappers delegate to the shared request helper."""

    client = BaseClient(access_token="access-token")
    captured_calls: list[dict[str, Any]] = []

    def fake_request(method: str, endpoint: str, **kwargs: Any) -> dict[str, str]:
        """Capture delegated request wrapper calls.

        Args:
            method: HTTP method selected by the wrapper.
            endpoint: Endpoint forwarded to the request helper.
            **kwargs: Additional request helper arguments.

        Returns:
            A simple payload for assertions.
        """

        captured_calls.append(
            {
                "method": method,
                "endpoint": endpoint,
                **kwargs,
            }
        )
        return {"ok": "true"}

    monkeypatch.setattr(client, "_request", fake_request)

    assert client.put("Property('1')", json_data={"ListPrice": 1}) == {"ok": "true"}
    assert client.patch("Property('1')", data={"ListPrice": "2"}) == {"ok": "true"}

    assert captured_calls == [
        {
            "method": "PUT",
            "endpoint": "Property('1')",
            "json_data": {"ListPrice": 1},
            "data": None,
            "timeout_seconds": None,
            "headers": None,
        },
        {
            "method": "PATCH",
            "endpoint": "Property('1')",
            "json_data": None,
            "data": {"ListPrice": "2"},
            "timeout_seconds": None,
            "headers": None,
        },
    ]


def test_get_metadata_requires_an_xml_text_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Metadata helpers reject non-string payloads."""

    client = BaseClient(access_token="access-token")

    def fake_get(endpoint: str, **kwargs: Any) -> dict[str, str]:
        """Return a non-string metadata payload.

        Args:
            endpoint: Requested metadata endpoint.
            **kwargs: GET helper arguments.

        Returns:
            A mapping to trigger the configuration error path.
        """

        del endpoint, kwargs
        return {"not": "xml"}

    monkeypatch.setattr(client, "get", fake_get)

    with pytest.raises(ConfigurationError):
        client.get_metadata()


def test_get_page_requires_a_mapping_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """Page helpers reject non-mapping payloads."""

    client = BaseClient(access_token="access-token")

    def fake_get(endpoint: str, **kwargs: Any) -> list[str]:
        """Return a non-mapping page payload.

        Args:
            endpoint: Requested collection endpoint.
            **kwargs: GET helper arguments.

        Returns:
            A list to trigger the configuration error path.
        """

        del endpoint, kwargs
        return ["not-a-mapping"]

    monkeypatch.setattr(client, "get", fake_get)

    with pytest.raises(ConfigurationError):
        client.get_page("Property")
