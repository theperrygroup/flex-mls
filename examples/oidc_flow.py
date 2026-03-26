"""Example building a Spark OIDC authorization URL."""

from flex_mls import FlexMlsClient


def main() -> None:
    """Run the OIDC example."""

    client = FlexMlsClient(
        client_id="your-client-id",
        client_secret="your-client-secret",
        redirect_uri="https://example.com/callback",
    )
    print(client.build_authorization_url(state="state-token", nonce="nonce-token"))


if __name__ == "__main__":
    main()
