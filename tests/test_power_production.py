"""Tests for the power production subresource client."""

from __future__ import annotations

import responses

from flex_mls import FlexMlsClient
from flex_mls.base_client import DEFAULT_BASE_URL


@responses.activate
def test_power_production_get_for_property_uses_singleton_endpoint() -> None:
    """Power production uses the singleton property endpoint."""

    responses.get(
        f"{DEFAULT_BASE_URL}/Property('listing-1')/PowerProduction",
        json={"PowerProductionAnnual": 12000},
        status=200,
    )

    client = FlexMlsClient(access_token="access-token")
    payload = client.power_production.get_for_property("listing-1")

    assert payload == {"PowerProductionAnnual": 12000}
