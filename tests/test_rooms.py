"""Tests for the room subresource client."""

from __future__ import annotations

import responses

from flex_mls import FlexMlsClient
from flex_mls.base_client import DEFAULT_BASE_URL


@responses.activate
def test_rooms_list_for_property_uses_nested_collection_endpoint() -> None:
    """Room listing uses the nested property room endpoint."""

    responses.get(
        f"{DEFAULT_BASE_URL}/Property('listing-1')/Room",
        json={"value": []},
        status=200,
    )

    client = FlexMlsClient(access_token="access-token")
    payload = client.rooms.list_for_property("listing-1")

    assert payload == {"value": []}
