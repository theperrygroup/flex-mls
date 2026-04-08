"""Facade client for the ``flex_mls`` package."""

from __future__ import annotations

from typing import Mapping, TypeVar

import requests

from flex_mls.auth import BearerTokenAuth, OpenIdConnectAuth, TokenAuthStrategy
from flex_mls.base_client import (
    DEFAULT_BASE_URL,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_BACKOFF_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_USER_AGENT,
    BaseClient,
)
from flex_mls.exceptions import ConfigurationError
from flex_mls.green_verification import GreenVerificationClient
from flex_mls.lookup import LookupClient
from flex_mls.media import MediaClient
from flex_mls.members import MembersClient
from flex_mls.models import AuthTokens, ClientConfig
from flex_mls.offices import OfficesClient
from flex_mls.openhouses import OpenHousesClient
from flex_mls.power_production import PowerProductionClient
from flex_mls.properties import PropertiesClient
from flex_mls.rooms import RoomsClient
from flex_mls.units import UnitsClient

_ClientT = TypeVar("_ClientT", bound=BaseClient)


class FlexMlsClient:
    """Main entrypoint for Spark RESO Web API access.

    Args:
        access_token: Direct bearer token or already-issued OIDC access token.
        auth: Optional pre-built auth strategy.
        client_id: Spark OAuth client ID for OIDC workflows.
        client_secret: Spark OAuth client secret for OIDC workflows.
        redirect_uri: Redirect URI registered with Spark for OIDC.
        refresh_token: Optional OIDC refresh token.
        id_token: Optional OIDC ID token.
        expires_in: Optional access-token lifetime in seconds.
        base_url: Base URL for RESO requests.
        timeout_seconds: Default request timeout in seconds.
        max_retries: Number of retries for transient failures.
        retry_backoff_seconds: Initial backoff delay for retries.
        load_dotenv: Whether to load environment variables from a ``.env`` file.
        user_agent: User-Agent header to apply to requests.
        extra_headers: Additional headers to include with every request.
    """

    def __init__(
        self,
        *,
        access_token: str | None = None,
        auth: TokenAuthStrategy | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        redirect_uri: str | None = None,
        refresh_token: str | None = None,
        id_token: str | None = None,
        expires_in: int | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
        load_dotenv: bool = False,
        user_agent: str = DEFAULT_USER_AGENT,
        extra_headers: Mapping[str, str] | None = None,
    ) -> None:
        if load_dotenv:
            try:
                from dotenv import load_dotenv as load_dotenv_fn
            except ImportError as exc:
                raise ConfigurationError(
                    "load_dotenv=True requires the optional python-dotenv dependency."
                ) from exc

            load_dotenv_fn()

        self.auth = self._resolve_auth(
            auth=auth,
            access_token=access_token,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            refresh_token=refresh_token,
            id_token=id_token,
            expires_in=expires_in,
        )
        self.session = requests.Session()
        self.config = ClientConfig(
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            user_agent=user_agent,
            extra_headers=dict(extra_headers or {}),
        )

        self._properties: PropertiesClient | None = None
        self._members: MembersClient | None = None
        self._offices: OfficesClient | None = None
        self._openhouses: OpenHousesClient | None = None
        self._media: MediaClient | None = None
        self._rooms: RoomsClient | None = None
        self._units: UnitsClient | None = None
        self._green_verification: GreenVerificationClient | None = None
        self._power_production: PowerProductionClient | None = None
        self._lookup: LookupClient | None = None

    def _resolve_auth(
        self,
        *,
        auth: TokenAuthStrategy | None,
        access_token: str | None,
        client_id: str | None,
        client_secret: str | None,
        redirect_uri: str | None,
        refresh_token: str | None,
        id_token: str | None,
        expires_in: int | None,
    ) -> TokenAuthStrategy | None:
        """Resolve the auth strategy used by the facade client."""

        if auth is not None:
            return auth

        oidc_settings = {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
        }
        provided_oidc_fields = [
            field_name for field_name, value in oidc_settings.items() if value is not None
        ]
        if provided_oidc_fields and len(provided_oidc_fields) != len(oidc_settings):
            missing_fields = [
                field_name for field_name, value in oidc_settings.items() if value is None
            ]
            missing_fields_display = ", ".join(missing_fields)
            raise ConfigurationError(
                "Incomplete OpenID Connect configuration. Missing required field(s): "
                f"{missing_fields_display}."
            )

        if client_id and client_secret and redirect_uri:
            tokens: AuthTokens | None = None
            if access_token:
                tokens = AuthTokens(
                    access_token=access_token,
                    refresh_token=refresh_token,
                    id_token=id_token,
                    expires_in=expires_in,
                )

            return OpenIdConnectAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                tokens=tokens,
            )

        if access_token:
            return BearerTokenAuth(access_token=access_token)

        discovered_oidc = OpenIdConnectAuth.from_env()
        if discovered_oidc is not None:
            return discovered_oidc

        return BearerTokenAuth.from_env()

    def _instantiate_client(self, client_cls: type[_ClientT]) -> _ClientT:
        """Create a sub-client with the shared facade configuration."""

        return client_cls(
            auth=self.auth,
            base_url=self.config.base_url,
            session=self.session,
            timeout_seconds=self.config.timeout_seconds,
            max_retries=self.config.max_retries,
            retry_backoff_seconds=self.config.retry_backoff_seconds,
            user_agent=self.config.user_agent,
            extra_headers=self.config.extra_headers,
        )

    @property
    def properties(self) -> PropertiesClient:
        """Access the ``Property`` resource client."""

        if self._properties is None:
            self._properties = self._instantiate_client(PropertiesClient)

        return self._properties

    @property
    def members(self) -> MembersClient:
        """Access the ``Member`` resource client."""

        if self._members is None:
            self._members = self._instantiate_client(MembersClient)

        return self._members

    @property
    def offices(self) -> OfficesClient:
        """Access the ``Office`` resource client."""

        if self._offices is None:
            self._offices = self._instantiate_client(OfficesClient)

        return self._offices

    @property
    def openhouses(self) -> OpenHousesClient:
        """Access the ``OpenHouse`` resource client."""

        if self._openhouses is None:
            self._openhouses = self._instantiate_client(OpenHousesClient)

        return self._openhouses

    @property
    def media(self) -> MediaClient:
        """Access the ``Media`` property subresource client."""

        if self._media is None:
            self._media = self._instantiate_client(MediaClient)

        return self._media

    @property
    def rooms(self) -> RoomsClient:
        """Access the ``Room`` property subresource client."""

        if self._rooms is None:
            self._rooms = self._instantiate_client(RoomsClient)

        return self._rooms

    @property
    def units(self) -> UnitsClient:
        """Access the ``Unit`` property subresource client."""

        if self._units is None:
            self._units = self._instantiate_client(UnitsClient)

        return self._units

    @property
    def green_verification(self) -> GreenVerificationClient:
        """Access the ``GreenVerification`` property subresource client."""

        if self._green_verification is None:
            self._green_verification = self._instantiate_client(
                GreenVerificationClient
            )

        return self._green_verification

    @property
    def power_production(self) -> PowerProductionClient:
        """Access the ``PowerProduction`` property subresource client."""

        if self._power_production is None:
            self._power_production = self._instantiate_client(
                PowerProductionClient
            )

        return self._power_production

    @property
    def lookup(self) -> LookupClient:
        """Access the ``Lookup`` resource client."""

        if self._lookup is None:
            self._lookup = self._instantiate_client(LookupClient)

        return self._lookup

    def get_metadata(self, *, timeout_seconds: float | None = None) -> str:
        """Fetch the RESO metadata document as XML.

        Args:
            timeout_seconds: Optional per-request timeout override.

        Returns:
            The raw metadata XML document.
        """

        base_client = self._instantiate_client(BaseClient)
        return base_client.get_metadata(timeout_seconds=timeout_seconds)

    def build_authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        scopes: tuple[str, ...] | None = None,
        response_type: str = "code",
    ) -> str:
        """Build the Spark OIDC authorization URL for user sign-in.

        Args:
            state: Opaque CSRF protection value.
            nonce: OIDC nonce.
            scopes: Optional explicit scopes. Defaults to ``openid``.
            response_type: OIDC response type. Spark uses ``code``.

        Returns:
            A redirect URL for Spark's authorization endpoint.

        Raises:
            ConfigurationError: If the client is not configured for OIDC.
        """

        if not isinstance(self.auth, OpenIdConnectAuth):
            raise ConfigurationError(
                "OpenID Connect is not configured for this client instance."
            )

        return self.auth.build_authorization_url(
            state=state,
            nonce=nonce,
            scopes=scopes,
            response_type=response_type,
        )

    def exchange_oidc_code(
        self,
        code: str,
        *,
        timeout_seconds: float | None = None,
    ) -> AuthTokens:
        """Exchange a Spark OIDC authorization code for tokens.

        Args:
            code: Authorization code returned by Spark.
            timeout_seconds: Optional per-request timeout override.

        Returns:
            The token set returned by Spark.

        Raises:
            ConfigurationError: If OIDC is not configured for this client.
        """

        if not isinstance(self.auth, OpenIdConnectAuth):
            raise ConfigurationError(
                "OpenID Connect is not configured for this client instance."
            )

        return self.auth.exchange_code(
            code,
            session=self.session,
            timeout_seconds=timeout_seconds or self.config.timeout_seconds,
        )

    def refresh_oidc_tokens(self, *, timeout_seconds: float | None = None) -> AuthTokens:
        """Refresh the current Spark OIDC access token.

        Args:
            timeout_seconds: Optional per-request timeout override.

        Returns:
            The refreshed token set.

        Raises:
            ConfigurationError: If OIDC is not configured for this client.
        """

        if not isinstance(self.auth, OpenIdConnectAuth):
            raise ConfigurationError(
                "OpenID Connect is not configured for this client instance."
            )

        return self.auth.refresh_tokens(
            session=self.session,
            timeout_seconds=timeout_seconds or self.config.timeout_seconds,
        )

    def revoke_oidc_token(
        self,
        *,
        token: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        """Revoke a Spark OIDC token.

        Args:
            token: Specific token to revoke. Defaults to the current access token.
            timeout_seconds: Optional per-request timeout override.

        Raises:
            ConfigurationError: If OIDC is not configured for this client.
        """

        if not isinstance(self.auth, OpenIdConnectAuth):
            raise ConfigurationError(
                "OpenID Connect is not configured for this client instance."
            )

        self.auth.revoke_token(
            token=token,
            session=self.session,
            timeout_seconds=timeout_seconds or self.config.timeout_seconds,
        )
