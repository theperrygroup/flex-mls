"""Tests for shared resource helper utilities."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterator

import pytest

from flex_mls._resources import (
    CollectionResourceClient,
    PropertyCollectionSubresourceClient,
    PropertySingletonSubresourceClient,
    build_query_options,
    normalize_values,
    validate_top,
)
from flex_mls.exceptions import ValidationError
from flex_mls.models import ODataPage, ODataQueryOptions, ReplicationWindow


class SampleExpansion(str, Enum):
    """Example enum used to exercise helper normalization."""

    MEDIA = "Media"
    ROOM = "Room"


class DemoCollectionClient(CollectionResourceClient):
    """Concrete collection client used for helper tests."""

    resource_name = "Demo"


class UnconfiguredCollectionClient(CollectionResourceClient):
    """Collection client without a configured resource name."""


class DemoPropertyCollectionClient(PropertyCollectionSubresourceClient):
    """Concrete property collection subresource client used for tests."""

    subresource_name = "DemoSubresource"


class UnconfiguredPropertyCollectionClient(PropertyCollectionSubresourceClient):
    """Property collection subresource client without a resource name."""


class DemoPropertySingletonClient(PropertySingletonSubresourceClient):
    """Concrete property singleton subresource client used for tests."""

    subresource_name = "DemoSingleton"


class UnconfiguredPropertySingletonClient(PropertySingletonSubresourceClient):
    """Property singleton subresource client without a resource name."""


def _empty_page() -> ODataPage[dict[str, Any]]:
    """Return an empty OData page for iterator tests.

    Returns:
        A page object with no records and no next link.
    """

    return ODataPage(records=[], raw={})


def test_normalize_values_handles_none_strings_and_enums() -> None:
    """Enum and string inputs are normalized into plain string tuples."""

    assert normalize_values(None) == ()
    assert normalize_values(("ListingKey", SampleExpansion.MEDIA, SampleExpansion.ROOM)) == (
        "ListingKey",
        "Media",
        "Room",
    )


@pytest.mark.parametrize("top", [None, 1, 1000])
def test_validate_top_accepts_documented_values(top: int | None) -> None:
    """Supported ``$top`` values pass validation."""

    validate_top(top)


@pytest.mark.parametrize("top", [0, -1, 1001])
def test_validate_top_rejects_out_of_range_values(top: int) -> None:
    """Out-of-range ``$top`` values raise a validation error."""

    with pytest.raises(ValidationError):
        validate_top(top)


def test_build_query_options_merges_query_and_filters_none_extra_params() -> None:
    """Query option overrides merge cleanly with an existing base query."""

    base_query = ODataQueryOptions(
        select=("ListingKey",),
        top=10,
        skip=5,
        count=False,
        order_by=("ListPrice desc",),
        filter_expression="StandardStatus eq 'Active'",
        expand=("Media",),
        extra_params={"keep": "original", "stay": "value"},
    )

    options = build_query_options(
        query=base_query,
        select=("ListPrice",),
        top=25,
        count=True,
        order_by=("ListPrice asc",),
        filter_expression="ListPrice gt 100000",
        expand=(SampleExpansion.MEDIA, "Room"),
        extra_params={"keep": "updated", "drop": None},
    )

    assert options.select == ("ListPrice",)
    assert options.top == 25
    assert options.skip == 5
    assert options.count is True
    assert options.order_by == ("ListPrice asc",)
    assert options.filter_expression == "ListPrice gt 100000"
    assert options.expand == ("Media", "Room")
    assert options.extra_params == {"keep": "updated", "stay": "value"}


def test_build_query_options_uses_defaults_without_a_base_query() -> None:
    """A missing base query produces a fresh options object."""

    options = build_query_options(select=("ListingKey",), top=3, count=True)

    assert options.select == ("ListingKey",)
    assert options.top == 3
    assert options.count is True
    assert options.skip is None
    assert options.order_by == ()


def test_collection_endpoint_requires_resource_name() -> None:
    """Collection endpoints require a configured resource name."""

    client = UnconfiguredCollectionClient()

    with pytest.raises(ValidationError):
        client._endpoint()


def test_collection_methods_build_expected_endpoints_and_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Collection helper methods forward the expected endpoint arguments."""

    client = DemoCollectionClient()
    captured_calls: list[dict[str, Any]] = []

    def fake_get(
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Capture GET call arguments for assertions.

        Args:
            endpoint: Requested resource endpoint.
            params: Serialized query parameters.
            timeout_seconds: Per-request timeout override.

        Returns:
            An empty payload.
        """

        captured_calls.append(
            {
                "endpoint": endpoint,
                "params": params,
                "timeout_seconds": timeout_seconds,
            }
        )
        return {"value": []}

    monkeypatch.setattr(client, "get", fake_get)

    assert client.list(
        select=("ListingKey",),
        top=5,
        skip=2,
        count=True,
        order_by=("ListPrice desc",),
        filter_expression="ListPrice gt 100000",
        expand=(SampleExpansion.MEDIA,),
        timeout_seconds=1.5,
    ) == {"value": []}
    assert client.get_by_id(
        "record-1",
        select=("ListingKey",),
        expand=("Room",),
        timeout_seconds=2.5,
    ) == {"value": []}

    assert captured_calls[0]["endpoint"] == "Demo"
    assert captured_calls[0]["params"] == {
        "$select": "ListingKey",
        "$top": 5,
        "$skip": 2,
        "$count": "true",
        "$orderby": "ListPrice desc",
        "$filter": "ListPrice gt 100000",
        "$expand": "Media",
    }
    assert captured_calls[0]["timeout_seconds"] == 1.5
    assert captured_calls[1]["endpoint"] == "Demo('record-1')"
    assert captured_calls[1]["params"] == {
        "$select": "ListingKey",
        "$expand": "Room",
    }
    assert captured_calls[1]["timeout_seconds"] == 2.5


def test_iter_all_forwards_expected_filters_to_iter_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Collection iteration forwards normalized filters to page fetching."""

    client = DemoCollectionClient()
    iter_pages_calls: list[dict[str, Any]] = []
    page = _empty_page()

    def fake_iter_pages(
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> Iterator[ODataPage[dict[str, Any]]]:
        """Capture iter-page calls for assertions.

        Args:
            endpoint: Requested collection endpoint.
            params: Serialized query parameters.
            timeout_seconds: Per-request timeout override.

        Yields:
            A single empty page.
        """

        iter_pages_calls.append(
            {
                "endpoint": endpoint,
                "params": params,
                "timeout_seconds": timeout_seconds,
            }
        )
        yield page

    monkeypatch.setattr(client, "iter_pages", fake_iter_pages)

    assert list(
        client.iter_all(
            select=("ListingKey",),
            top=50,
            order_by=("ListPrice desc",),
            filter_expression="StandardStatus eq 'Active'",
            expand=(SampleExpansion.MEDIA,),
            timeout_seconds=3.0,
        )
    ) == [page]

    assert iter_pages_calls == [
        {
            "endpoint": "Demo",
            "params": {
                "$select": "ListingKey",
                "$top": 50,
                "$orderby": "ListPrice desc",
                "$filter": "StandardStatus eq 'Active'",
                "$expand": "Media",
            },
            "timeout_seconds": 3.0,
        }
    ]


def test_iter_recently_modified_forwards_window_filter_to_iter_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replication iteration forwards the bounded timestamp filter."""

    client = DemoCollectionClient()
    iter_all_calls: list[dict[str, Any]] = []
    page = _empty_page()
    window = ReplicationWindow(
        start=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
        end=datetime(2024, 1, 1, 1, 0, tzinfo=timezone.utc),
    )

    def fake_iter_all(
        *,
        query: ODataQueryOptions | None = None,
        select: tuple[str, ...] | None = None,
        top: int = 1000,
        order_by: tuple[str, ...] | None = None,
        filter_expression: str | None = None,
        expand: tuple[str | Enum, ...] | None = None,
        timeout_seconds: float | None = None,
    ) -> Iterator[ODataPage[dict[str, Any]]]:
        """Capture iter-all calls for assertions.

        Args:
            query: Optional base query.
            select: Requested fields.
            top: Requested page size.
            order_by: Sort expressions.
            filter_expression: Final filter expression.
            expand: Expansion values.
            timeout_seconds: Per-request timeout override.

        Yields:
            A single empty page.
        """

        iter_all_calls.append(
            {
                "query": query,
                "select": select,
                "top": top,
                "order_by": order_by,
                "filter_expression": filter_expression,
                "expand": expand,
                "timeout_seconds": timeout_seconds,
            }
        )
        yield page

    monkeypatch.setattr(client, "iter_all", fake_iter_all)

    assert list(
        client.iter_recently_modified(
            window,
            top=25,
            select=("ListingKey",),
            order_by=("ModificationTimestamp asc",),
            expand=(SampleExpansion.ROOM,),
            additional_filter="ListPrice gt 100000",
            timeout_seconds=4.0,
        )
    ) == [page]

    assert iter_all_calls == [
        {
            "query": None,
            "select": ("ListingKey",),
            "top": 25,
            "order_by": ("ModificationTimestamp asc",),
            "filter_expression": (
                "((ModificationTimestamp gt 2024-01-01T00:00:00Z and "
                "ModificationTimestamp lt 2024-01-01T01:00:00Z) and "
                "(ListPrice gt 100000))"
            ),
            "expand": (SampleExpansion.ROOM,),
            "timeout_seconds": 4.0,
        }
    ]


def test_property_collection_endpoint_requires_subresource_name() -> None:
    """Property collection endpoints require a configured subresource name."""

    client = UnconfiguredPropertyCollectionClient()

    with pytest.raises(ValidationError):
        client._endpoint("listing-1")


def test_property_collection_methods_build_expected_endpoints_and_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Property collection helpers use the documented nested endpoints."""

    client = DemoPropertyCollectionClient()
    captured_calls: list[dict[str, Any]] = []

    def fake_get(
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Capture property subresource GET arguments.

        Args:
            endpoint: Requested resource endpoint.
            params: Serialized query parameters.
            timeout_seconds: Per-request timeout override.

        Returns:
            An empty payload.
        """

        captured_calls.append(
            {
                "endpoint": endpoint,
                "params": params,
                "timeout_seconds": timeout_seconds,
            }
        )
        return {"value": []}

    monkeypatch.setattr(client, "get", fake_get)

    assert client.list_for_property(
        "listing-1",
        select=("OpenHouseKey",),
        top=3,
        skip=1,
        count=True,
        order_by=("OpenHouseKey desc",),
        filter_expression="OpenHouseKey ne null",
        timeout_seconds=1.0,
    ) == {"value": []}
    assert client.get_for_property(
        "listing-1",
        "record-2",
        select=("OpenHouseKey",),
        timeout_seconds=2.0,
    ) == {"value": []}

    assert captured_calls == [
        {
            "endpoint": "Property('listing-1')/DemoSubresource",
            "params": {
                "$select": "OpenHouseKey",
                "$top": 3,
                "$skip": 1,
                "$count": "true",
                "$orderby": "OpenHouseKey desc",
                "$filter": "OpenHouseKey ne null",
            },
            "timeout_seconds": 1.0,
        },
        {
            "endpoint": "Property('listing-1')/DemoSubresource('record-2')",
            "params": {"$select": "OpenHouseKey"},
            "timeout_seconds": 2.0,
        },
    ]


def test_property_singleton_endpoint_requires_subresource_name() -> None:
    """Property singleton endpoints require a configured subresource name."""

    client = UnconfiguredPropertySingletonClient()

    with pytest.raises(ValidationError):
        client._endpoint("listing-1")


def test_property_singleton_get_builds_expected_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Property singleton helpers use the documented nested endpoint."""

    client = DemoPropertySingletonClient()
    captured_call: dict[str, Any] = {}

    def fake_get(
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Capture property singleton GET arguments.

        Args:
            endpoint: Requested resource endpoint.
            params: Serialized query parameters.
            timeout_seconds: Per-request timeout override.

        Returns:
            An empty payload.
        """

        captured_call.update(
            {
                "endpoint": endpoint,
                "params": params,
                "timeout_seconds": timeout_seconds,
            }
        )
        return {"value": []}

    monkeypatch.setattr(client, "get", fake_get)

    assert client.get_for_property(
        "listing-1",
        select=("ListingKey",),
        timeout_seconds=2.5,
    ) == {"value": []}
    assert captured_call == {
        "endpoint": "Property('listing-1')/DemoSingleton",
        "params": {"$select": "ListingKey"},
        "timeout_seconds": 2.5,
    }
