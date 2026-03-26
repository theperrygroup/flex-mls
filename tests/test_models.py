"""Tests for shared model helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest  # type: ignore[import-not-found]

import flex_mls.models as models_module
from flex_mls.models import AuthTokens, ODataPage, ODataQueryOptions, ReplicationWindow


def test_auth_tokens_builds_authorization_header() -> None:
    """Token models format the ``Authorization`` header value."""

    tokens = AuthTokens(access_token="access-token", token_type="Bearer")

    assert tokens.authorization_header() == "Bearer access-token"


def test_auth_tokens_expires_at_returns_none_without_lifetime() -> None:
    """Tokens without ``expires_in`` do not report an expiration timestamp."""

    tokens = AuthTokens(access_token="access-token")

    assert tokens.expires_at() is None


def test_auth_tokens_expires_at_returns_absolute_timestamp() -> None:
    """Token lifetimes resolve to an absolute expiration time."""

    obtained_at = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    tokens = AuthTokens(
        access_token="access-token",
        expires_in=120,
        obtained_at=obtained_at,
    )

    assert tokens.expires_at() == obtained_at + timedelta(seconds=120)


def test_auth_tokens_is_expired_returns_false_without_lifetime() -> None:
    """Tokens without lifetimes are treated as non-expiring."""

    tokens = AuthTokens(access_token="access-token")

    assert tokens.is_expired() is False


def test_auth_tokens_is_expired_respects_buffer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Expiry checks honor optional refresh buffers."""

    obtained_at = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    current_time = datetime(2024, 1, 1, 0, 0, 50, tzinfo=timezone.utc)
    tokens = AuthTokens(
        access_token="access-token",
        expires_in=60,
        obtained_at=obtained_at,
    )

    monkeypatch.setattr(models_module, "_utc_now", lambda: current_time)

    assert tokens.is_expired() is False
    assert tokens.is_expired(buffer_seconds=15) is True


def test_odata_query_options_to_params_serializes_all_supported_fields() -> None:
    """OData options serialize into Spark-compatible request parameters."""

    options = ODataQueryOptions(
        select=("ListingKey", "ListPrice"),
        top=25,
        skip=5,
        count=True,
        order_by=("ListPrice desc",),
        filter_expression="StandardStatus eq 'Active'",
        expand=("Media", "Room"),
        extra_params={"custom": "value"},
    )

    assert options.to_params() == {
        "custom": "value",
        "$select": "ListingKey,ListPrice",
        "$top": 25,
        "$skip": 5,
        "$count": "true",
        "$orderby": "ListPrice desc",
        "$filter": "StandardStatus eq 'Active'",
        "$expand": "Media,Room",
    }


def test_odata_query_options_to_params_returns_extra_params_when_unset() -> None:
    """Unset OData fields do not add empty request parameters."""

    options = ODataQueryOptions(extra_params={"custom": "value"})

    assert options.to_params() == {"custom": "value"}


def test_odata_page_from_response_parses_payload_and_filters_non_mappings() -> None:
    """OData page parsing keeps only mapping records from the payload list."""

    page = ODataPage.from_response(
        {
            "value": [{"ListingKey": "123"}, "ignore-me", 42],
            "@odata.nextLink": "https://example.com/next",
            "@odata.count": 3,
        }
    )

    assert page.records == [{"ListingKey": "123"}]
    assert page.next_link == "https://example.com/next"
    assert page.count == 3
    assert page.raw["value"] == [{"ListingKey": "123"}, "ignore-me", 42]


def test_odata_page_from_response_uses_empty_records_for_non_list_values() -> None:
    """Non-list ``value`` payloads are normalized to empty record lists."""

    page = ODataPage.from_response({"value": {"ListingKey": "123"}})

    assert page.records == []
    assert page.raw == {"value": {"ListingKey": "123"}}


def test_odata_page_from_response_rejects_non_mapping_payloads() -> None:
    """Non-mapping OData payloads raise a ``TypeError``."""

    invalid_payload = cast(Any, ["not-a-mapping"])

    with pytest.raises(TypeError):
        ODataPage.from_response(invalid_payload)


def test_replication_window_to_filter_without_additional_expression() -> None:
    """Replication filters are bounded when no extra clause is supplied."""

    window = ReplicationWindow(
        start=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
        end=datetime(2024, 1, 1, 1, 0, tzinfo=timezone.utc),
    )

    assert window.to_filter() == (
        "(ModificationTimestamp gt 2024-01-01T00:00:00Z and "
        "ModificationTimestamp lt 2024-01-01T01:00:00Z)"
    )


def test_replication_window_to_filter_with_additional_expression() -> None:
    """Replication filters append any extra caller-supplied constraint."""

    window = ReplicationWindow(
        start=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
        end=datetime(2024, 1, 1, 1, 0, tzinfo=timezone.utc),
    )

    assert window.to_filter("ListPrice gt 100000") == (
        "((ModificationTimestamp gt 2024-01-01T00:00:00Z and "
        "ModificationTimestamp lt 2024-01-01T01:00:00Z) and "
        "(ListPrice gt 100000))"
    )
