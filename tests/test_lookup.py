"""Tests for the lookup resource client."""

from __future__ import annotations

import responses

from flex_mls import FlexMlsClient
from flex_mls.base_client import DEFAULT_BASE_URL


@responses.activate
def test_lookup_list_uses_collection_endpoint() -> None:
    """Lookup requests use the top-level lookup collection endpoint."""

    responses.get(f"{DEFAULT_BASE_URL}/Lookup", json={"value": []}, status=200)

    client = FlexMlsClient(access_token="access-token")
    payload = client.lookup.list(top=25)

    assert payload == {"value": []}
