"""Tests for authentication helpers."""

from __future__ import annotations

from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import pytest
import requests
import responses

from flex_mls.auth import (
    DEFAULT_DISCOVERY_URL,
    DEFAULT_REVOCATION_ENDPOINT,
    DEFAULT_TOKEN_ENDPOINT,
    BearerTokenAuth,
    OpenIdConnectAuth,
    OpenIdScope,
    TokenAuthStrategy,
    _normalize_scopes,
    _request_tokens,
    fetch_openid_configuration,
)
from flex_mls.exceptions import AuthenticationError
from flex_mls.models import AuthTokens


@responses.activate
def test_fetch_openid_configuration_returns_payload() -> None:
    """Discovery fetches and returns Spark's OIDC configuration."""

    responses.get(
        DEFAULT_DISCOVERY_URL,
        json={"issuer": "https://sparkplatform.com"},
        status=200,
    )

    payload = fetch_openid_configuration()

    assert payload["issuer"] == "https://sparkplatform.com"


def test_bearer_token_auth_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bearer auth can be constructed from environment variables."""

    monkeypatch.setenv("FLEX_MLS_ACCESS_TOKEN", "token-from-env")

    auth = BearerTokenAuth.from_env()

    assert auth is not None
    assert auth.get_access_token() == "token-from-env"
    assert auth.can_refresh() is False


def test_bearer_token_refresh_raises() -> None:
    """Direct bearer auth rejects refresh attempts."""

    auth = BearerTokenAuth(access_token="token")

    with pytest.raises(AuthenticationError):
        auth.refresh_tokens()


def test_oidc_build_authorization_url() -> None:
    """OIDC auth builds the Spark authorization redirect URL."""

    auth = OpenIdConnectAuth(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="https://example.com/callback",
    )

    url = auth.build_authorization_url(state="state-value", nonce="nonce-value")
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "sparkplatform.com"
    assert query["client_id"] == ["client-id"]
    assert query["redirect_uri"] == ["https://example.com/callback"]
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["openid"]


@responses.activate
def test_oidc_exchange_code_updates_tokens() -> None:
    """OIDC code exchange stores the returned token set."""

    responses.post(
        DEFAULT_TOKEN_ENDPOINT,
        json={
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "expires_in": 86400,
            "token_type": "Bearer",
            "id_token": "id-token",
        },
        status=200,
    )

    auth = OpenIdConnectAuth(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="https://example.com/callback",
    )

    tokens = auth.exchange_code("auth-code")

    assert tokens.access_token == "access-token"
    assert tokens.refresh_token == "refresh-token"
    assert auth.tokens is not None
    assert auth.tokens.access_token == "access-token"


@responses.activate
def test_oidc_refresh_tokens_updates_current_state() -> None:
    """OIDC refresh replaces the current token set."""

    responses.post(
        DEFAULT_TOKEN_ENDPOINT,
        json={
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": 86400,
            "token_type": "Bearer",
        },
        status=200,
    )

    auth = OpenIdConnectAuth(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="https://example.com/callback",
    )
    auth.tokens = AuthTokens(
        access_token="stale-access-token",
        refresh_token="refresh-token",
        expires_in=3600,
    )

    tokens = auth.refresh_tokens()

    assert tokens.access_token == "new-access-token"
    assert auth.tokens is not None
    assert auth.tokens.refresh_token == "new-refresh-token"


def test_oidc_refresh_without_refresh_token_raises() -> None:
    """OIDC refresh requires a refresh token."""

    auth = OpenIdConnectAuth(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="https://example.com/callback",
        tokens=AuthTokens(access_token="access-token"),
    )

    with pytest.raises(AuthenticationError):
        auth.refresh_tokens()


@responses.activate
def test_oidc_revoke_token_clears_current_tokens() -> None:
    """OIDC revoke can clear the active access token."""

    responses.post(DEFAULT_REVOCATION_ENDPOINT, status=200)

    auth = OpenIdConnectAuth(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="https://example.com/callback",
        tokens=AuthTokens(
            access_token="access-token",
            refresh_token="refresh-token",
            expires_in=3600,
        ),
    )

    auth.revoke_token()

    assert auth.tokens is None


def test_token_auth_strategy_protocol_methods_are_noop_placeholders() -> None:
    """Protocol placeholder methods return ``None`` when invoked directly."""

    strategy = cast(Any, object())

    assert TokenAuthStrategy.get_access_token(strategy) is None
    assert TokenAuthStrategy.can_refresh(strategy) is None
    assert TokenAuthStrategy.refresh_tokens(strategy) is None


@responses.activate
def test_fetch_openid_configuration_raises_for_request_failures() -> None:
    """Discovery failures are surfaced as authentication errors."""

    responses.get(DEFAULT_DISCOVERY_URL, status=500)

    with pytest.raises(AuthenticationError):
        fetch_openid_configuration()


@responses.activate
def test_fetch_openid_configuration_rejects_non_mapping_json() -> None:
    """Discovery responses must decode to a JSON object."""

    responses.get(DEFAULT_DISCOVERY_URL, json=["not", "a", "mapping"], status=200)

    with pytest.raises(AuthenticationError):
        fetch_openid_configuration()


def test_normalize_scopes_defaults_and_serializes_explicit_values() -> None:
    """Scopes default to ``openid`` and preserve explicit mixed inputs."""

    assert _normalize_scopes(None) == "openid"
    assert _normalize_scopes((OpenIdScope.OPENID, OpenIdScope.EMAIL, "RESO")) == (
        "openid email RESO"
    )


def test_request_tokens_raises_for_network_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Token request transport failures raise ``AuthenticationError``."""

    session = requests.Session()

    def raise_connection_error(url: str, **kwargs: Any) -> requests.Response:
        """Raise a request exception for the token request.

        Args:
            url: Request URL forwarded by ``requests``.
            **kwargs: Token request keyword arguments.

        Raises:
            requests.ConnectionError: Always, to simulate a network failure.
        """

        del url, kwargs
        raise requests.ConnectionError("network failure")

    monkeypatch.setattr(session, "post", raise_connection_error)

    with pytest.raises(AuthenticationError):
        _request_tokens(
            payload={"grant_type": "client_credentials"},
            token_endpoint=DEFAULT_TOKEN_ENDPOINT,
            session=session,
            timeout_seconds=30.0,
        )


@pytest.mark.parametrize(
    ("response_body", "status_code", "expected_message"),
    [
        ({"error_description": "bad credentials"}, 400, "bad credentials"),
        ({"error": "invalid_grant"}, 401, "invalid_grant"),
        ("plain-text-error", 400, "plain-text-error"),
        ("", 500, "Spark token request failed."),
        ({}, 500, "Spark token request failed."),
    ],
)
@responses.activate
def test_request_tokens_maps_error_payloads_into_messages(
    response_body: dict[str, str] | str,
    status_code: int,
    expected_message: str,
) -> None:
    """Token request errors preserve the most useful available message."""

    if isinstance(response_body, dict):
        responses.post(DEFAULT_TOKEN_ENDPOINT, json=response_body, status=status_code)
    else:
        responses.post(DEFAULT_TOKEN_ENDPOINT, body=response_body, status=status_code)

    with pytest.raises(AuthenticationError) as exc_info:
        _request_tokens(
            payload={"grant_type": "authorization_code"},
            token_endpoint=DEFAULT_TOKEN_ENDPOINT,
            session=None,
            timeout_seconds=30.0,
        )

    assert exc_info.value.message == expected_message
    assert exc_info.value.status_code == status_code


@responses.activate
def test_request_tokens_requires_an_access_token_in_successful_payloads() -> None:
    """Token responses without an access token are rejected."""

    responses.post(DEFAULT_TOKEN_ENDPOINT, json={"token_type": "Bearer"}, status=200)

    with pytest.raises(AuthenticationError):
        _request_tokens(
            payload={"grant_type": "authorization_code"},
            token_endpoint=DEFAULT_TOKEN_ENDPOINT,
            session=None,
            timeout_seconds=30.0,
        )


def test_bearer_token_auth_from_env_returns_none_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing bearer-token environment variables produce no auth object."""

    monkeypatch.delenv("FLEX_MLS_ACCESS_TOKEN", raising=False)

    assert BearerTokenAuth.from_env() is None


def test_oidc_from_env_returns_none_without_required_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OIDC discovery from environment requires all client settings."""

    monkeypatch.delenv("FLEX_MLS_CLIENT_ID", raising=False)
    monkeypatch.delenv("FLEX_MLS_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("FLEX_MLS_REDIRECT_URI", raising=False)

    assert OpenIdConnectAuth.from_env() is None


def test_oidc_from_env_builds_tokens_when_env_tokens_are_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OIDC environment loading captures any stored token state."""

    monkeypatch.setenv("FLEX_MLS_CLIENT_ID", "client-id")
    monkeypatch.setenv("FLEX_MLS_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("FLEX_MLS_REDIRECT_URI", "https://example.com/callback")
    monkeypatch.setenv("FLEX_MLS_ACCESS_TOKEN", "access-token")
    monkeypatch.setenv("FLEX_MLS_REFRESH_TOKEN", "refresh-token")
    monkeypatch.setenv("FLEX_MLS_EXPIRES_IN", "3600")
    monkeypatch.setenv("FLEX_MLS_ID_TOKEN", "id-token")

    auth = OpenIdConnectAuth.from_env()

    assert auth is not None
    assert auth.client_id == "client-id"
    assert auth.tokens is not None
    assert auth.tokens.access_token == "access-token"
    assert auth.tokens.refresh_token == "refresh-token"
    assert auth.tokens.expires_in == 3600
    assert auth.tokens.id_token == "id-token"


def test_oidc_from_env_without_tokens_keeps_token_state_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OIDC env loading works even when no access token has been stored yet."""

    monkeypatch.setenv("FLEX_MLS_CLIENT_ID", "client-id")
    monkeypatch.setenv("FLEX_MLS_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("FLEX_MLS_REDIRECT_URI", "https://example.com/callback")
    monkeypatch.delenv("FLEX_MLS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("FLEX_MLS_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("FLEX_MLS_EXPIRES_IN", raising=False)
    monkeypatch.delenv("FLEX_MLS_ID_TOKEN", raising=False)

    auth = OpenIdConnectAuth.from_env()

    assert auth is not None
    assert auth.tokens is None


def test_oidc_access_token_and_refresh_capability_handle_missing_tokens() -> None:
    """OIDC helpers report missing token state cleanly."""

    auth = OpenIdConnectAuth(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="https://example.com/callback",
    )

    assert auth.get_access_token() is None
    assert auth.can_refresh() is False


def test_oidc_build_authorization_url_supports_extra_params_and_explicit_scopes() -> None:
    """Explicit scopes and extra query parameters are forwarded to Spark."""

    auth = OpenIdConnectAuth(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="https://example.com/callback",
    )

    url = auth.build_authorization_url(
        state="state-value",
        nonce="nonce-value",
        scopes=(OpenIdScope.OPENID, OpenIdScope.EMAIL),
        extra_params={"prompt": "login"},
    )
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert query["scope"] == ["openid email"]
    assert query["prompt"] == ["login"]


def test_oidc_refresh_without_any_tokens_raises() -> None:
    """Refreshing requires an existing token set with a refresh token."""

    auth = OpenIdConnectAuth(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="https://example.com/callback",
    )

    with pytest.raises(AuthenticationError):
        auth.refresh_tokens()


def test_oidc_revoke_requires_a_token_when_none_is_available() -> None:
    """Revocation fails when there is no explicit or stored token."""

    auth = OpenIdConnectAuth(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="https://example.com/callback",
    )

    with pytest.raises(AuthenticationError):
        auth.revoke_token()


def test_oidc_revoke_surfaces_transport_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Revocation transport failures are mapped to ``AuthenticationError``."""

    auth = OpenIdConnectAuth(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="https://example.com/callback",
        tokens=AuthTokens(access_token="access-token"),
    )
    session = requests.Session()

    def raise_connection_error(url: str, **kwargs: Any) -> requests.Response:
        """Raise a request exception for the revoke request.

        Args:
            url: Request URL forwarded by ``requests``.
            **kwargs: Revocation request keyword arguments.

        Raises:
            requests.ConnectionError: Always, to simulate a network failure.
        """

        del url, kwargs
        raise requests.ConnectionError("network failure")

    monkeypatch.setattr(session, "post", raise_connection_error)

    with pytest.raises(AuthenticationError):
        auth.revoke_token(session=session)


@responses.activate
def test_oidc_revoke_explicit_non_access_token_preserves_current_tokens() -> None:
    """Revoking a token other than the current access token keeps the session."""

    responses.post(DEFAULT_REVOCATION_ENDPOINT, status=200)

    auth = OpenIdConnectAuth(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="https://example.com/callback",
        tokens=AuthTokens(
            access_token="access-token",
            refresh_token="refresh-token",
            expires_in=3600,
        ),
    )

    auth.revoke_token(token="refresh-token")

    assert auth.tokens is not None
    assert auth.tokens.access_token == "access-token"
