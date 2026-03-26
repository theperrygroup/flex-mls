# Replication

Spark's RESO replication guidance breaks the sync cycle into three parts:

1. Initial download with pagination, preferably via `@odata.nextLink`
2. Incremental polling using a bounded `ModificationTimestamp` window
3. Stale-key purging by comparing current `ListingKey` values with local state

`flex_mls` exposes the core helpers directly on `PropertiesClient`:

```python
from datetime import datetime, timedelta, timezone

from flex_mls import FlexMlsClient, ReplicationWindow

client = FlexMlsClient(access_token="your-access-token")
now = datetime.now(timezone.utc)
window = ReplicationWindow(start=now - timedelta(hours=1), end=now)

for page in client.properties.iter_replication_pages(top=1000):
    print(len(page.records))

for page in client.properties.iter_recently_modified_properties(window, top=1000):
    print(len(page.records))

for listing_key in client.properties.iter_listing_keys(top=1000):
    print(listing_key)
```

Spark also recommends replicating `Member` and `Office` records alongside
`Property` so listing display data stays current even when those related records
change independently of the property modification timestamp.
