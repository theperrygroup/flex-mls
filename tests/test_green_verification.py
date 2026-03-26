"""Tests for the green verification subresource client."""

from __future__ import annotations

import responses

from flex_mls import FlexMlsClient
from flex_mls.base_client import DEFAULT_BASE_URL


@responses.activate
def test_green_verification_get_for_property_uses_singleton_endpoint() -> None:
    """Green verification uses the singleton property endpoint."""

    responses.get(
        f"{DEFAULT_BASE_URL}/Property('listing-1')/GreenVerification",
        json={"GreenBuildingVerificationType": "LEED"},
        status=200,
    )

    client = FlexMlsClient(access_token="access-token")
    payload = client.green_verification.get_for_property("listing-1")

    assert payload == {"GreenBuildingVerificationType": "LEED"}
