"""Example querying properties with related expansions."""

from flex_mls import FlexMlsClient, PropertyExpansion


def main() -> None:
    """Run the property expansion example."""

    client = FlexMlsClient(access_token="your-access-token")
    response = client.properties.list_with_expansions(
        expansions=(
            PropertyExpansion.MEDIA,
            PropertyExpansion.ROOM,
            PropertyExpansion.OPEN_HOUSE,
        ),
        top=5,
    )
    print(response)


if __name__ == "__main__":
    main()
