"""Authentication helpers for the Spark RESO Web API."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from typing import Any, Iterable, Mapping, Protocol, cast
from urllib.parse import urlencode

import requests

from flex_mls.enums import OpenIdScope
from flex_mls.exceptions import AuthenticationError
from flex_mls.models import AuthTokens

DEFAULT_DISCOVERY_URL = "https://sparkplatform.com/.well-known/openid-configuration"
DEFAULT_AUTHORIZATION_ENDPOINT = "https://sparkplatform.com/openid/authorize"
DEFAULT_TOKEN_ENDPOINT = "https://sparkplatform.com/openid/token"
DEFAULT_REVOCATION_ENDPOINT = "https://sparkplatform.com/openid/revoke"


class TokenAuthStrategy(Protocol):
    """Protocol implemented by auth strategies that provide bearer tokens."""

    def get_access_token(self) -> str | None:
        """Return the current access token, if one is available."""

        ...

    def can_refresh(self) -> bool:
        """Report whether the strategy can refresh its access token."""

        ...

    def refresh_tokens(
        self,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 30.0,
    ) -> AuthTokens:
        """Refresh and return the current token set."""

        ...


def fetch_openid_configuration(
    *,
    discovery_url: str = DEFAULT_DISCOVERY_URL,
    session: requests.Session | None = None,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Fetch Spark's OpenID Connect discovery document.

    Args:
        discovery_url: OpenID discovery URL.
        session: Optional HTTP session to reuse.
        timeout_seconds: Request timeout in seconds.

    Returns:
        The decoded discovery document.

    Raises:
        AuthenticationError: If the discovery request fails.
    """

    active_session = session or requests.Session()
    try:
        response = active_session.get(discovery_url, timeout=timeout_seconds)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise AuthenticationError(
            "Failed to fetch the Spark OpenID configuration."
        ) from exc

    payload = response.json()
    if not isinstance(payload, dict):
        raise AuthenticationError("Spark OpenID configuration returned invalid JSON.")

    return cast(dict[str, Any], payload)


def _normalize_scopes(scopes: Iterable[OpenIdScope | str] | None) -> str:
    """Convert a sequence of scopes into a Spark-compatible string."""

    resolved = [scope.value if isinstance(scope, OpenIdScope) else scope for scope in scopes or ()]
    if not resolved:
        resolved = [OpenIdScope.OPENID.value]

    return " ".join(resolved)


def _request_tokens(
    *,
    payload: Mapping[str, str],
    token_endpoint: str,
    session: requests.Session | None,
    timeout_seconds: float,
) -> AuthTokens:
    """Send a token request to Spark and parse the response.

    Args:
        payload: Form body sent to the token endpoint.
        token_endpoint: Spark token endpoint.
        session: Optional HTTP session to reuse.
        timeout_seconds: Request timeout in seconds.

    Returns:
        Parsed token data.

    Raises:
        AuthenticationError: If the token exchange fails.
    """

    active_session = session or requests.Session()
    try:
        response = active_session.post(
            token_endpoint,
            json=dict(payload),
            timeout=timeout_seconds,
        )
    except requests.RequestException as exc:
        raise AuthenticationError("Spark token request failed.") from exc

    if response.status_code >= 400:
        try:
            error_payload = response.json()
        except ValueError:
            error_payload = response.text

        message = "Spark token request failed."
        if isinstance(error_payload, dict):
            error_description = error_payload.get("error_description")
            error_code = error_payload.get("error")
            if error_description:
                message = str(error_description)
            elif error_code:
                message = str(error_code)
        elif isinstance(error_payload, str) and error_payload:
            message = error_payload

        raise AuthenticationError(
            message,
            status_code=response.status_code,
            response_data=error_payload,
        )

    payload_data = response.json()
    if not isinstance(payload_data, dict) or "access_token" not in payload_data:
        raise AuthenticationError("Spark token response did not include an access token.")

    expires_in = payload_data.get("expires_in")
    parsed_expires_in: int | None = int(expires_in) if expires_in is not None else None

    return AuthTokens(
        access_token=str(payload_data["access_token"]),
        token_type=str(payload_data.get("token_type", "Bearer")),
        expires_in=parsed_expires_in,
        refresh_token=(
            str(payload_data["refresh_token"])
            if payload_data.get("refresh_token") is not None
            else None
        ),
        id_token=(
            str(payload_data["id_token"])
            if payload_data.get("id_token") is not None
            else None
        ),
    )


@dataclass(slots=True)
class BearerTokenAuth:
    """Direct bearer-token authentication strategy.

    Attributes:
        access_token: Non-expiring personal access token issued by Spark.
    """

    access_token: str

    @classmethod
    def from_env(cls, env_var: str = "FLEX_MLS_ACCESS_TOKEN") -> "BearerTokenAuth | None":
        """Build a bearer strategy from an environment variable.

        Args:
            env_var: Environment variable containing the bearer token.

        Returns:
            A configured auth strategy when the variable is present, otherwise
            ``None``.
        """

        token = os.getenv(env_var)
        if not token:
            return None

        return cls(access_token=token)

    def get_access_token(self) -> str | None:
        """Return the configured access token.

        Returns:
            The direct bearer token.
        """

        return self.access_token

    def can_refresh(self) -> bool:
        """Report whether this strategy can refresh access tokens.

        Returns:
            ``False`` because personal access tokens do not expire.
        """

        return False

    def refresh_tokens(
        self,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 30.0,
    ) -> AuthTokens:
        """Reject refresh attempts for direct bearer tokens.

        Args:
            session: Unused. Present for protocol compatibility.
            timeout_seconds: Unused. Present for protocol compatibility.

        Raises:
            AuthenticationError: Always, because the strategy cannot refresh.
        """

        del session, timeout_seconds
        raise AuthenticationError(
            "Direct bearer tokens do not support token refresh."
        )


@dataclass(slots=True)
class OpenIdConnectAuth:
    """Spark OpenID Connect authorization-code authentication state.

    Attributes:
        client_id: OAuth client ID supplied by Spark.
        client_secret: OAuth client secret supplied by Spark.
        redirect_uri: Redirect URI registered with Spark.
        authorization_endpoint: Endpoint used to obtain user authorization.
        token_endpoint: Endpoint used for code exchange and refresh.
        revocation_endpoint: Endpoint used to revoke tokens.
        discovery_url: OpenID discovery URL.
        tokens: Current token set, when one has already been obtained.
    """

    client_id: str
    client_secret: str
    redirect_uri: str
    authorization_endpoint: str = DEFAULT_AUTHORIZATION_ENDPOINT
    token_endpoint: str = DEFAULT_TOKEN_ENDPOINT
    revocation_endpoint: str = DEFAULT_REVOCATION_ENDPOINT
    discovery_url: str = DEFAULT_DISCOVERY_URL
    tokens: AuthTokens | None = field(default=None)

    @classmethod
    def from_env(cls) -> "OpenIdConnectAuth | None":
        """Build an OIDC auth object from environment variables.

        Returns:
            An OIDC auth object when the required client settings exist,
            otherwise ``None``.
        """

        client_id = os.getenv("FLEX_MLS_CLIENT_ID")
        client_secret = os.getenv("FLEX_MLS_CLIENT_SECRET")
        redirect_uri = os.getenv("FLEX_MLS_REDIRECT_URI")

        if not client_id or not client_secret or not redirect_uri:
            return None

        access_token = os.getenv("FLEX_MLS_ACCESS_TOKEN")
        refresh_token = os.getenv("FLEX_MLS_REFRESH_TOKEN")
        expires_in = os.getenv("FLEX_MLS_EXPIRES_IN")
        id_token = os.getenv("FLEX_MLS_ID_TOKEN")

        tokens: AuthTokens | None = None
        if access_token:
            tokens = AuthTokens(
                access_token=access_token,
                refresh_token=refresh_token,
                expires_in=int(expires_in) if expires_in else None,
                id_token=id_token,
            )

        return cls(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            tokens=tokens,
        )

    def get_access_token(self) -> str | None:
        """Return the current access token.

        Returns:
            The access token if present, otherwise ``None``.
        """

        if self.tokens is None:
            return None

        return self.tokens.access_token

    def can_refresh(self) -> bool:
        """Report whether the current auth state supports token refresh.

        Returns:
            ``True`` when a refresh token is available.
        """

        return self.tokens is not None and self.tokens.refresh_token is not None

    def build_authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        scopes: Iterable[OpenIdScope | str] | None = None,
        response_type: str = "code",
        extra_params: Mapping[str, str] | None = None,
    ) -> str:
        """Build the Spark authorization URL for an OIDC login flow.

        Args:
            state: Opaque CSRF protection value.
            nonce: OIDC nonce.
            scopes: Optional scopes to request. Defaults to ``openid``.
            response_type: OIDC response type. Spark uses ``code``.
            extra_params: Optional additional query parameters.

        Returns:
            A redirect URL for Spark's authorization endpoint.
        """

        query: dict[str, str] = {
            "client_id": self.client_id,
            "scope": _normalize_scopes(scopes),
            "response_type": response_type,
            "redirect_uri": self.redirect_uri,
            "state": state,
            "nonce": nonce,
        }
        if extra_params:
            query.update(dict(extra_params))

        return f"{self.authorization_endpoint}?{urlencode(query)}"

    def exchange_code(
        self,
        code: str,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 30.0,
    ) -> AuthTokens:
        """Exchange an authorization code for a Spark token set.

        Args:
            code: Authorization code returned by Spark.
            session: Optional HTTP session to reuse.
            timeout_seconds: Request timeout in seconds.

        Returns:
            The token set returned by Spark.
        """

        tokens = _request_tokens(
            payload={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
            },
            token_endpoint=self.token_endpoint,
            session=session,
            timeout_seconds=timeout_seconds,
        )
        self.tokens = tokens
        return tokens

    def refresh_tokens(
        self,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 30.0,
    ) -> AuthTokens:
        """Refresh an expired Spark token set.

        Args:
            session: Optional HTTP session to reuse.
            timeout_seconds: Request timeout in seconds.

        Returns:
            The refreshed token set.

        Raises:
            AuthenticationError: If no refresh token is available.
        """

        if self.tokens is None or self.tokens.refresh_token is None:
            raise AuthenticationError(
                "A refresh token is required to renew an OIDC session."
            )

        tokens = _request_tokens(
            payload={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": self.tokens.refresh_token,
            },
            token_endpoint=self.token_endpoint,
            session=session,
            timeout_seconds=timeout_seconds,
        )
        self.tokens = tokens
        return tokens

    def revoke_token(
        self,
        *,
        token: str | None = None,
        session: requests.Session | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        """Revoke a Spark access or refresh token.

        Args:
            token: Token value to revoke. Defaults to the current access token.
            session: Optional HTTP session to reuse.
            timeout_seconds: Request timeout in seconds.

        Raises:
            AuthenticationError: If no token is available or the request fails.
        """

        target_token = token or self.get_access_token()
        if not target_token:
            raise AuthenticationError("No token is available to revoke.")

        active_session = session or requests.Session()
        try:
            response = active_session.post(
                self.revocation_endpoint,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "token": target_token,
                },
                timeout=timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise AuthenticationError("Spark token revocation failed.") from exc

        if self.tokens is not None and target_token == self.tokens.access_token:
            self.tokens = None
