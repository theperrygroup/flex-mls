"""Tests for the property resource client."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import pytest
import responses

from flex_mls import FlexMlsClient, ODataQueryOptions, PropertyExpansion, ReplicationWindow
from flex_mls.base_client import DEFAULT_BASE_URL
from flex_mls.exceptions import ValidationError
from flex_mls.properties import _combine_filter_expressions, _normalize_optional_filter_value


@responses.activate
def test_list_with_expansions_builds_query_string() -> None:
    """Property expansion helpers build the expected OData parameters."""

    responses.get(
        f"{DEFAULT_BASE_URL}/Property",
        json={"value": []},
        status=200,
    )

    client = FlexMlsClient(access_token="access-token")
    client.properties.list_with_expansions(
        expansions=(PropertyExpansion.MEDIA, PropertyExpansion.OPEN_HOUSE),
        top=5,
        count=True,
        select=("ListingKey",),
    )

    parsed = urlparse(responses.calls[0].request.url)
    query = parse_qs(parsed.query)
    assert query["$expand"] == ["Media,OpenHouse"]
    assert query["$top"] == ["5"]
    assert query["$count"] == ["true"]
    assert query["$select"] == ["ListingKey"]


@responses.activate
def test_list_by_address_builds_strict_query_string() -> None:
    """Strict address searches use exact address fields and a ZIP prefix filter."""

    responses.get(
        f"{DEFAULT_BASE_URL}/Property",
        json={"value": []},
        status=200,
    )

    client = FlexMlsClient(access_token="access-token")
    client.properties.list_by_address(
        unparsed_address="12 O'Brien St",
        city="Salt Lake City",
        state_or_province="UT",
        postal_code="84101-1234",
        top=5,
        count=True,
        select=("ListingKey",),
    )

    parsed = urlparse(responses.calls[0].request.url)
    query = parse_qs(parsed.query)
    assert query["$filter"] == [
        "(UnparsedAddress eq '12 O''Brien St') and (City eq 'Salt Lake City') and "
        "(StateOrProvince eq 'UT') and (startswith(PostalCode,'84101'))"
    ]
    assert query["$top"] == ["5"]
    assert query["$count"] == ["true"]
    assert query["$select"] == ["ListingKey"]


@responses.activate
def test_list_by_address_combines_existing_filters() -> None:
    """Strict address searches preserve caller-provided filters."""

    responses.get(
        f"{DEFAULT_BASE_URL}/Property",
        json={"value": []},
        status=200,
    )

    client = FlexMlsClient(access_token="access-token")
    client.properties.list_by_address(
        unparsed_address="123 Main St",
        city="Salt Lake City",
        state_or_province="   ",
        postal_code="   ",
        query=ODataQueryOptions(filter_expression="StandardStatus eq 'Active'"),
        filter_expression="ListPrice gt 100000",
    )

    parsed = urlparse(responses.calls[0].request.url)
    query = parse_qs(parsed.query)
    assert query["$filter"] == [
        "(StandardStatus eq 'Active') and (ListPrice gt 100000) and "
        "((UnparsedAddress eq '123 Main St') and (City eq 'Salt Lake City'))"
    ]


@responses.activate
def test_list_by_parcel_builds_exact_query_string() -> None:
    """Parcel searches perform exact ``ParcelNumber`` equality."""

    responses.get(
        f"{DEFAULT_BASE_URL}/Property",
        json={"value": []},
        status=200,
    )

    client = FlexMlsClient(access_token="access-token")
    client.properties.list_by_parcel(parcel_number="06-079-0012")

    parsed = urlparse(responses.calls[0].request.url)
    query = parse_qs(parsed.query)
    assert query["$filter"] == ["ParcelNumber eq '06-079-0012'"]


def test_property_search_helpers_reject_blank_required_values() -> None:
    """Property search helpers reject blank required inputs."""

    client = FlexMlsClient(access_token="access-token")

    with pytest.raises(ValidationError, match="unparsed_address"):
        client.properties.list_by_address(
            unparsed_address="   ",
            city="Salt Lake City",
        )
    with pytest.raises(ValidationError, match="city"):
        client.properties.list_by_address(
            unparsed_address="123 Main St",
            city="   ",
        )
    with pytest.raises(ValidationError, match="parcel_number"):
        client.properties.list_by_parcel(parcel_number="   ")


def test_property_filter_helpers_handle_missing_optional_values() -> None:
    """Property filter helpers skip missing optional values cleanly."""

    assert _normalize_optional_filter_value(None) is None
    assert _combine_filter_expressions(None, "   ", "") is None


@responses.activate
def test_address_search_can_recover_when_exact_parcel_search_returns_no_rows() -> None:
    """Address search remains available when exact parcel equality misses records."""

    property_record = {
        "ListingKey": "listing-1",
        "ParcelNumber": "06-079-0012",
        "UnparsedAddress": "123 Main St",
        "City": "Salt Lake City",
        "StateOrProvince": "UT",
        "PostalCode": "84101-1234",
    }
    responses.get(
        f"{DEFAULT_BASE_URL}/Property",
        json={"value": []},
        status=200,
    )
    responses.get(
        f"{DEFAULT_BASE_URL}/Property",
        json={"value": [property_record]},
        status=200,
    )

    client = FlexMlsClient(access_token="access-token")
    parcel_response = client.properties.list_by_parcel(parcel_number="06-079-0012")
    address_response = client.properties.list_by_address(
        unparsed_address="123 Main St",
        city="Salt Lake City",
        state_or_province="UT",
        postal_code="84101",
    )

    assert parcel_response == {"value": []}
    assert address_response == {"value": [property_record]}

    parcel_query = parse_qs(urlparse(responses.calls[0].request.url).query)
    address_query = parse_qs(urlparse(responses.calls[1].request.url).query)
    assert parcel_query["$filter"] == ["ParcelNumber eq '06-079-0012'"]
    assert address_query["$filter"] == [
        "(UnparsedAddress eq '123 Main St') and (City eq 'Salt Lake City') and "
        "(StateOrProvince eq 'UT') and (startswith(PostalCode,'84101'))"
    ]


@responses.activate
def test_get_by_listing_key_uses_item_endpoint() -> None:
    """Property item lookups use the documented item endpoint."""

    responses.get(
        f"{DEFAULT_BASE_URL}/Property('123')",
        json={"ListingKey": "123"},
        status=200,
    )

    client = FlexMlsClient(access_token="access-token")
    payload = client.properties.get_by_listing_key("123")

    assert payload == {"ListingKey": "123"}


@responses.activate
def test_iter_listing_keys_returns_current_keys() -> None:
    """Listing-key iteration yields values from each page."""

    next_link = f"{DEFAULT_BASE_URL}/Property?%24skiptoken=abc123&%24top=1000"
    responses.get(
        f"{DEFAULT_BASE_URL}/Property",
        json={"value": [{"ListingKey": "123"}], "@odata.nextLink": next_link},
        status=200,
    )
    responses.get(
        next_link,
        json={"value": [{"ListingKey": "456"}]},
        status=200,
    )

    client = FlexMlsClient(access_token="access-token")
    keys = list(client.properties.iter_listing_keys())

    assert keys == ["123", "456"]


@responses.activate
def test_iter_listing_keys_skips_non_string_values() -> None:
    """Listing-key iteration ignores records without string listing keys."""

    responses.get(
        f"{DEFAULT_BASE_URL}/Property",
        json={
            "value": [
                {"ListingKey": "123"},
                {"ListingKey": 456},
                {"ListingKey": None},
                {},
            ]
        },
        status=200,
    )

    client = FlexMlsClient(access_token="access-token")
    keys = list(client.properties.iter_listing_keys())

    assert keys == ["123"]


@responses.activate
def test_iter_replication_pages_forwards_query_parameters() -> None:
    """Replication page iteration forwards the expected OData query options."""

    responses.get(
        f"{DEFAULT_BASE_URL}/Property",
        json={"value": []},
        status=200,
    )

    client = FlexMlsClient(access_token="access-token")
    list(
        client.properties.iter_replication_pages(
            select=("ListingKey",),
            top=250,
            order_by=("ModificationTimestamp asc",),
            filter_expression="StandardStatus eq 'Active'",
            expand=(PropertyExpansion.MEDIA,),
            timeout_seconds=5.0,
        )
    )

    parsed = urlparse(responses.calls[0].request.url)
    query = parse_qs(parsed.query)
    assert query["$select"] == ["ListingKey"]
    assert query["$top"] == ["250"]
    assert query["$orderby"] == ["ModificationTimestamp asc"]
    assert query["$filter"] == ["StandardStatus eq 'Active'"]
    assert query["$expand"] == ["Media"]


@responses.activate
def test_recently_modified_properties_uses_bounded_window_filter() -> None:
    """Incremental replication requests use a bounded timestamp window."""

    responses.get(
        f"{DEFAULT_BASE_URL}/Property",
        json={"value": []},
        status=200,
    )

    client = FlexMlsClient(access_token="access-token")
    window = ReplicationWindow(
        start=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
        end=datetime(2024, 1, 1, 1, 0, tzinfo=timezone.utc),
    )
    list(client.properties.iter_recently_modified_properties(window, top=1000))

    parsed = urlparse(responses.calls[0].request.url)
    query = parse_qs(parsed.query)
    assert (
        query["$filter"][0]
        == "(ModificationTimestamp gt 2024-01-01T00:00:00Z and "
        "ModificationTimestamp lt 2024-01-01T01:00:00Z)"
    )
