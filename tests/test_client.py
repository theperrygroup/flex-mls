"""Tests for the facade client."""

from __future__ import annotations

import builtins
from types import ModuleType
from typing import Any

import pytest
import requests
import responses

from flex_mls import FlexMlsClient
from flex_mls.auth import BearerTokenAuth, OpenIdConnectAuth
from flex_mls.base_client import DEFAULT_BASE_URL
from flex_mls.exceptions import AuthenticationError, ConfigurationError
from flex_mls.models import AuthTokens


def test_resource_clients_are_lazy_loaded_and_cached() -> None:
    """The facade creates resource clients lazily and caches them."""

    client = FlexMlsClient(access_token="access-token")

    first_properties_client = client.properties
    second_properties_client = client.properties

    assert first_properties_client is second_properties_client
    assert first_properties_client.session is client.session


def test_build_authorization_url_requires_oidc_configuration() -> None:
    """OIDC helper methods require OIDC configuration."""

    client = FlexMlsClient(access_token="access-token")

    with pytest.raises(ConfigurationError):
        client.build_authorization_url(state="state", nonce="nonce")


def test_build_authorization_url_uses_oidc_configuration() -> None:
    """The facade can build an authorization URL when configured for OIDC."""

    client = FlexMlsClient(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="https://example.com/callback",
    )

    url = client.build_authorization_url(state="state-value", nonce="nonce-value")

    assert "client_id=client-id" in url
    assert "nonce=nonce-value" in url


@responses.activate
def test_get_metadata_uses_shared_configuration() -> None:
    """Metadata requests use the facade's shared base URL and session settings."""

    responses.get(
        f"{DEFAULT_BASE_URL}/$metadata",
        body="<xml />",
        content_type="application/xml",
        status=200,
    )

    client = FlexMlsClient(
        access_token="access-token",
        user_agent="custom-user-agent",
        extra_headers={"X-Test": "value"},
    )

    payload = client.get_metadata()

    assert payload == "<xml />"
    request = responses.calls[0].request
    assert request.headers["User-Agent"] == "custom-user-agent"
    assert request.headers["X-Test"] == "value"


def test_load_dotenv_requires_the_optional_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Loading dotenv support fails cleanly when the dependency is unavailable."""

    real_import = builtins.__import__

    def fake_import(
        name: str,
        globals_dict: dict[str, Any] | None = None,
        locals_dict: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        """Raise for ``dotenv`` imports and delegate everything else.

        Args:
            name: Requested module name.
            globals_dict: Import globals.
            locals_dict: Import locals.
            fromlist: ``from`` import targets.
            level: Relative import level.

        Returns:
            The imported module for non-``dotenv`` imports.

        Raises:
            ImportError: When the ``dotenv`` module is requested.
        """

        if name == "dotenv":
            raise ImportError("missing dependency")

        return real_import(name, globals_dict, locals_dict, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(ConfigurationError):
        FlexMlsClient(load_dotenv=True)


def test_load_dotenv_calls_loader_when_dependency_is_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dotenv loading runs before auth resolution when the module is available."""

    calls: list[str] = []
    fake_module = ModuleType("dotenv")

    def fake_load_dotenv() -> None:
        """Record that dotenv loading was invoked."""

        calls.append("called")

    fake_module.load_dotenv = fake_load_dotenv  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "dotenv", fake_module)

    client = FlexMlsClient(load_dotenv=True, access_token="access-token")

    assert calls == ["called"]
    assert isinstance(client.auth, BearerTokenAuth)


def test_explicit_auth_takes_precedence_over_other_resolution_paths() -> None:
    """A provided auth object is used without any additional discovery."""

    explicit_auth = BearerTokenAuth(access_token="explicit-token")
    client = FlexMlsClient(
        auth=explicit_auth,
        access_token="ignored-token",
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="https://example.com/callback",
    )

    assert client.auth is explicit_auth


def test_oidc_credentials_build_an_oidc_auth_strategy_with_tokens() -> None:
    """OIDC constructor settings produce an ``OpenIdConnectAuth`` strategy."""

    client = FlexMlsClient(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="https://example.com/callback",
        access_token="access-token",
        refresh_token="refresh-token",
        id_token="id-token",
        expires_in=3600,
    )

    assert isinstance(client.auth, OpenIdConnectAuth)
    assert client.auth.tokens is not None
    assert client.auth.tokens.access_token == "access-token"
    assert client.auth.tokens.refresh_token == "refresh-token"
    assert client.auth.tokens.id_token == "id-token"
    assert client.auth.tokens.expires_in == 3600


def test_direct_access_token_builds_a_bearer_auth_strategy() -> None:
    """Direct access tokens resolve to the bearer-token auth strategy."""

    client = FlexMlsClient(access_token="access-token")

    assert isinstance(client.auth, BearerTokenAuth)
    assert client.auth.access_token == "access-token"


def test_incomplete_oidc_configuration_names_missing_fields() -> None:
    """Partial OIDC constructor settings fail fast with clear missing fields."""

    with pytest.raises(ConfigurationError) as exc_info:
        FlexMlsClient(client_id="client-id")

    assert "client_secret" in exc_info.value.message
    assert "redirect_uri" in exc_info.value.message


def test_missing_auth_configuration_raises_before_any_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing auth raises before any HTTP request is attempted."""

    client = FlexMlsClient()
    request_attempted = {"called": False}

    def fail_request(**kwargs: Any) -> requests.Response:
        """Fail if the transport tries to send an HTTP request.

        Args:
            **kwargs: Request arguments forwarded by the transport.

        Raises:
            AssertionError: Always, because no request should be attempted.
        """

        del kwargs
        request_attempted["called"] = True
        raise AssertionError("session.request should not be called")

    monkeypatch.setattr(client.session, "request", fail_request)

    with pytest.raises(AuthenticationError) as exc_info:
        client.properties.list(top=1)

    assert request_attempted["called"] is False
    assert "access_token" in exc_info.value.message
    assert "client_id" in exc_info.value.message


def test_client_prefers_discovered_oidc_auth_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Environment-discovered OIDC config wins over bearer-token fallback discovery."""

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
            The discovered auth object.
        """

        del cls
        return discovered_auth

    def fail_bearer_from_env(cls: type[BearerTokenAuth]) -> BearerTokenAuth | None:
        """Fail if bearer-token discovery is reached unexpectedly.

        Args:
            cls: The ``BearerTokenAuth`` class.

        Raises:
            AssertionError: Always, because the bearer fallback should not run.
        """

        del cls
        raise AssertionError("BearerTokenAuth.from_env should not be called")

    monkeypatch.setattr(OpenIdConnectAuth, "from_env", classmethod(fake_oidc_from_env))
    monkeypatch.setattr(BearerTokenAuth, "from_env", classmethod(fail_bearer_from_env))

    client = FlexMlsClient()

    assert client.auth is discovered_auth


def test_client_uses_bearer_fallback_when_oidc_discovery_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bearer-token discovery runs when OIDC discovery does not return a config."""

    discovered_auth = BearerTokenAuth(access_token="env-access-token")

    def fake_oidc_from_env(cls: type[OpenIdConnectAuth]) -> OpenIdConnectAuth | None:
        """Return no discovered OIDC auth object.

        Args:
            cls: The ``OpenIdConnectAuth`` class.

        Returns:
            ``None`` to trigger bearer-token fallback discovery.
        """

        del cls
        return None

    def fake_bearer_from_env(cls: type[BearerTokenAuth]) -> BearerTokenAuth | None:
        """Return a discovered bearer auth object.

        Args:
            cls: The ``BearerTokenAuth`` class.

        Returns:
            The discovered bearer auth object.
        """

        del cls
        return discovered_auth

    monkeypatch.setattr(OpenIdConnectAuth, "from_env", classmethod(fake_oidc_from_env))
    monkeypatch.setattr(BearerTokenAuth, "from_env", classmethod(fake_bearer_from_env))

    client = FlexMlsClient()

    assert client.auth is discovered_auth


def test_all_resource_clients_are_lazy_loaded_cached_and_share_configuration() -> None:
    """All facade resource properties are cached and share the client config."""

    client = FlexMlsClient(
        access_token="access-token",
        base_url="https://example.com/api",
        timeout_seconds=12.0,
        max_retries=5,
        retry_backoff_seconds=0.75,
        user_agent="custom-user-agent",
        extra_headers={"X-Test": "value"},
    )
    property_names = (
        "properties",
        "members",
        "offices",
        "openhouses",
        "media",
        "rooms",
        "units",
        "green_verification",
        "power_production",
        "lookup",
    )

    for property_name in property_names:
        first_client = getattr(client, property_name)
        second_client = getattr(client, property_name)

        assert first_client is second_client
        assert first_client.session is client.session
        assert first_client.base_url == "https://example.com/api"
        assert first_client.timeout_seconds == 12.0
        assert first_client.max_retries == 5
        assert first_client.retry_backoff_seconds == 0.75
        assert first_client.user_agent == "custom-user-agent"
        assert first_client.extra_headers == {"X-Test": "value"}
        assert first_client.auth is client.auth


@pytest.mark.parametrize(
    "method_name",
    ("exchange_oidc_code", "refresh_oidc_tokens", "revoke_oidc_token"),
)
def test_oidc_helper_methods_require_oidc_configuration(method_name: str) -> None:
    """OIDC helper methods reject bearer-only client instances."""

    client = FlexMlsClient(access_token="access-token")
    method = getattr(client, method_name)

    with pytest.raises(ConfigurationError):
        if method_name == "exchange_oidc_code":
            method("auth-code")
        else:
            method()


def test_oidc_helper_methods_forward_session_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Facade OIDC helper methods forward the shared session and timeouts."""

    client = FlexMlsClient(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="https://example.com/callback",
        timeout_seconds=45.0,
    )
    assert isinstance(client.auth, OpenIdConnectAuth)

    exchange_calls: list[dict[str, Any]] = []
    refresh_calls: list[dict[str, Any]] = []
    revoke_calls: list[dict[str, Any]] = []
    token_result = AuthTokens(access_token="new-access-token", refresh_token="refresh-token")

    def fake_exchange_code(
        self: OpenIdConnectAuth,
        code: str,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 30.0,
    ) -> AuthTokens:
        """Capture the exchange-code invocation.

        Args:
            code: Authorization code passed by the facade.
            session: Session passed by the facade.
            timeout_seconds: Timeout passed by the facade.

        Returns:
            A fresh token set for assertions.
        """

        del self
        exchange_calls.append(
            {
                "code": code,
                "session": session,
                "timeout_seconds": timeout_seconds,
            }
        )
        return token_result

    def fake_refresh_tokens(
        self: OpenIdConnectAuth,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 30.0,
    ) -> AuthTokens:
        """Capture the refresh invocation.

        Args:
            session: Session passed by the facade.
            timeout_seconds: Timeout passed by the facade.

        Returns:
            A fresh token set for assertions.
        """

        del self
        refresh_calls.append(
            {
                "session": session,
                "timeout_seconds": timeout_seconds,
            }
        )
        return token_result

    def fake_revoke_token(
        self: OpenIdConnectAuth,
        *,
        token: str | None = None,
        session: requests.Session | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        """Capture the revoke invocation.

        Args:
            token: Token passed by the facade.
            session: Session passed by the facade.
            timeout_seconds: Timeout passed by the facade.
        """

        del self
        revoke_calls.append(
            {
                "token": token,
                "session": session,
                "timeout_seconds": timeout_seconds,
            }
        )

    monkeypatch.setattr(OpenIdConnectAuth, "exchange_code", fake_exchange_code)
    monkeypatch.setattr(OpenIdConnectAuth, "refresh_tokens", fake_refresh_tokens)
    monkeypatch.setattr(OpenIdConnectAuth, "revoke_token", fake_revoke_token)

    assert client.exchange_oidc_code("auth-code") is token_result
    assert client.refresh_oidc_tokens() is token_result
    client.revoke_oidc_token(token="token-to-revoke")

    assert exchange_calls == [
        {
            "code": "auth-code",
            "session": client.session,
            "timeout_seconds": 45.0,
        }
    ]
    assert refresh_calls == [
        {
            "session": client.session,
            "timeout_seconds": 45.0,
        }
    ]
    assert revoke_calls == [
        {
            "token": "token-to-revoke",
            "session": client.session,
            "timeout_seconds": 45.0,
        }
    ]


def test_oidc_helper_methods_allow_explicit_timeout_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit timeout overrides are passed through to OIDC helper methods."""

    client = FlexMlsClient(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="https://example.com/callback",
        timeout_seconds=45.0,
    )
    assert isinstance(client.auth, OpenIdConnectAuth)

    exchange_timeouts: list[float] = []
    refresh_timeouts: list[float] = []
    revoke_timeouts: list[float] = []
    token_result = AuthTokens(access_token="new-access-token")

    def fake_exchange_code(
        self: OpenIdConnectAuth,
        code: str,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 30.0,
    ) -> AuthTokens:
        """Capture the exchange timeout override.

        Args:
            code: Authorization code passed by the facade.
            session: Session passed by the facade.
            timeout_seconds: Timeout passed by the facade.

        Returns:
            A fresh token set for assertions.
        """

        del self, code, session
        exchange_timeouts.append(timeout_seconds)
        return token_result

    def fake_refresh_tokens(
        self: OpenIdConnectAuth,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 30.0,
    ) -> AuthTokens:
        """Capture the refresh timeout override.

        Args:
            session: Session passed by the facade.
            timeout_seconds: Timeout passed by the facade.

        Returns:
            A fresh token set for assertions.
        """

        del self, session
        refresh_timeouts.append(timeout_seconds)
        return token_result

    def fake_revoke_token(
        self: OpenIdConnectAuth,
        *,
        token: str | None = None,
        session: requests.Session | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        """Capture the revoke timeout override.

        Args:
            token: Token passed by the facade.
            session: Session passed by the facade.
            timeout_seconds: Timeout passed by the facade.
        """

        del self, token, session
        revoke_timeouts.append(timeout_seconds)

    monkeypatch.setattr(OpenIdConnectAuth, "exchange_code", fake_exchange_code)
    monkeypatch.setattr(OpenIdConnectAuth, "refresh_tokens", fake_refresh_tokens)
    monkeypatch.setattr(OpenIdConnectAuth, "revoke_token", fake_revoke_token)

    assert client.exchange_oidc_code("auth-code", timeout_seconds=5.0) is token_result
    assert client.refresh_oidc_tokens(timeout_seconds=6.0) is token_result
    client.revoke_oidc_token(timeout_seconds=7.0)

    assert exchange_timeouts == [5.0]
    assert refresh_timeouts == [6.0]
    assert revoke_timeouts == [7.0]
