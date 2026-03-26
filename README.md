# flex_mls

`flex_mls` is a typed Python client library for the Spark RESO Web API used by
Flexmls.

## Features

- Direct bearer-token authentication for personal access token workflows
- OpenID Connect helpers for authorization-code, refresh, and revoke flows
- Typed resource clients for the RESO Web API surface
- Replication-aware pagination and incremental sync helpers
- Google-style docstrings and shipped type information

## Installation

```bash
pip install flex-mls
```

## Quickstart

```python
from flex_mls import FlexMlsClient

client = FlexMlsClient(access_token="your-access-token")
response = client.properties.list(top=5, count=True)

for record in response.get("value", []):
    print(record.get("ListingKey"))
```

## Documentation

The package mirrors Spark's RESO documentation and adds Python-focused guides
for authentication, querying, and replication workflows.

## Releases

GitHub Actions runs the test suite for pull requests, pushes to `main`, and
version tags. Publishing to PyPI happens automatically when a tag in `vX.Y.Z`
format is pushed, and the workflow verifies that the tag matches the package
version metadata before publishing.
