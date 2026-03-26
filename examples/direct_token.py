"""Example using a direct Spark bearer token."""

from flex_mls import FlexMlsClient


def main() -> None:
    """Run the direct-token example."""

    client = FlexMlsClient(access_token="your-access-token")
    response = client.properties.list(top=5, count=True)
    print(response)


if __name__ == "__main__":
    main()
