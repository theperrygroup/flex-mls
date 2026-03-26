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
