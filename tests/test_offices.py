"""Tests for the office resource client."""

from __future__ import annotations

import responses

from flex_mls import FlexMlsClient
from flex_mls.base_client import DEFAULT_BASE_URL


@responses.activate
def test_offices_get_by_id_uses_item_endpoint() -> None:
    """Office item lookup uses the RESO office item endpoint."""

    responses.get(
        f"{DEFAULT_BASE_URL}/Office('office-1')",
        json={"OfficeKey": "office-1"},
        status=200,
    )

    client = FlexMlsClient(access_token="access-token")
    payload = client.offices.get_by_id("office-1")

    assert payload == {"OfficeKey": "office-1"}
