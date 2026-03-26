"""Tests for the media subresource client."""

from __future__ import annotations

import responses

from flex_mls import FlexMlsClient
from flex_mls.base_client import DEFAULT_BASE_URL


@responses.activate
def test_media_get_for_property_uses_nested_item_endpoint() -> None:
    """Media item lookup uses the nested property media path."""

    responses.get(
        f"{DEFAULT_BASE_URL}/Property('listing-1')/Media('media-1')",
        json={"MediaKey": "media-1"},
        status=200,
    )

    client = FlexMlsClient(access_token="access-token")
    payload = client.media.get_for_property("listing-1", "media-1")

    assert payload == {"MediaKey": "media-1"}
