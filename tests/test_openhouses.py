"""Tests for the open house resource client."""

from __future__ import annotations

import responses

from flex_mls import FlexMlsClient
from flex_mls.base_client import DEFAULT_BASE_URL


@responses.activate
def test_openhouses_list_for_property_uses_property_endpoint() -> None:
    """Property-scoped open house requests use the documented nested path."""

    responses.get(
        f"{DEFAULT_BASE_URL}/Property('listing-1')/OpenHouse",
        json={"value": []},
        status=200,
    )

    client = FlexMlsClient(access_token="access-token")
    payload = client.openhouses.list_for_property("listing-1")

    assert payload == {"value": []}


@responses.activate
def test_openhouses_get_for_property_uses_item_endpoint() -> None:
    """Open house item lookups use the documented nested item path."""

    responses.get(
        f"{DEFAULT_BASE_URL}/Property('listing-1')/OpenHouse('open-house-1')",
        json={"OpenHouseKey": "open-house-1"},
        status=200,
    )

    client = FlexMlsClient(access_token="access-token")
    payload = client.openhouses.get_for_property("listing-1", "open-house-1")

    assert payload == {"OpenHouseKey": "open-house-1"}
