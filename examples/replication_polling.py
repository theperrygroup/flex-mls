"""Example iterating through replication pages."""

from datetime import datetime, timedelta, timezone

from flex_mls import FlexMlsClient, ReplicationWindow


def main() -> None:
    """Run the replication polling example."""

    client = FlexMlsClient(access_token="your-access-token")
    now = datetime.now(timezone.utc)
    window = ReplicationWindow(start=now - timedelta(hours=1), end=now)

    for page in client.properties.iter_recently_modified_properties(window, top=1000):
        print(len(page.records))


if __name__ == "__main__":
    main()
