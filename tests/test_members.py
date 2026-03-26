"""Tests for the member resource client."""

from __future__ import annotations

import responses

from flex_mls import FlexMlsClient
from flex_mls.base_client import DEFAULT_BASE_URL


@responses.activate
def test_members_list_uses_collection_endpoint() -> None:
    """Member listing uses the RESO collection endpoint."""

    responses.get(f"{DEFAULT_BASE_URL}/Member", json={"value": []}, status=200)

    client = FlexMlsClient(access_token="access-token")
    payload = client.members.list(top=5)

    assert payload == {"value": []}
