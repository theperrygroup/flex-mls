# Quickstart

```python
from flex_mls import FlexMlsClient, PropertyExpansion

client = FlexMlsClient(access_token="your-access-token")

page = client.properties.list_with_expansions(
    expansions=(PropertyExpansion.MEDIA, PropertyExpansion.OPEN_HOUSE),
    top=5,
    count=True,
)

for property_record in page.get("value", []):
    print(property_record.get("ListingKey"))
```

For strict property lookups, use the public helpers on `client.properties`:

```python
address_matches = client.properties.list_by_address(
    unparsed_address="123 Main St",
    city="Salt Lake City",
    state_or_province="UT",
    postal_code="84101-1234",
)

parcel_matches = client.properties.list_by_parcel(parcel_number="06-079-0012")
```

`list_by_parcel()` performs exact `ParcelNumber` equality and does not apply
normalization variants by default.
