"""Client for the RESO ``Property`` resource."""

from __future__ import annotations

from typing import Any, Iterator, Sequence

from flex_mls._resources import CollectionResourceClient, normalize_values
from flex_mls.enums import PropertyExpansion
from flex_mls.exceptions import ValidationError
from flex_mls.models import JsonPayload, ODataPage, ODataQueryOptions, ReplicationWindow


def _escape_odata_string(value: str) -> str:
    """Escape a string literal for safe use in an OData filter expression.

    Args:
        value: Raw string value supplied by the caller.

    Returns:
        The OData-safe string literal value.
    """

    return value.replace("'", "''")


def _require_filter_value(value: str, *, field_name: str) -> str:
    """Normalize a required string value used in a filter clause.

    Args:
        value: Raw string value supplied by the caller.
        field_name: User-facing parameter name for validation errors.

    Returns:
        The stripped string value.

    Raises:
        ValidationError: If the value is empty after trimming whitespace.
    """

    normalized = value.strip()
    if not normalized:
        raise ValidationError(f"{field_name} must be a non-empty string.")

    return normalized


def _normalize_optional_filter_value(value: str | None) -> str | None:
    """Normalize an optional string value used in a filter clause.

    Args:
        value: Raw optional string value supplied by the caller.

    Returns:
        The stripped string value, or ``None`` when the value is absent or blank.
    """

    if value is None:
        return None

    normalized = value.strip()
    if not normalized:
        return None

    return normalized


def _combine_filter_expressions(*expressions: str | None) -> str | None:
    """Combine one or more optional OData filter expressions with ``and``.

    Args:
        *expressions: Optional filter expressions to combine.

    Returns:
        The combined filter expression, or ``None`` when no expressions were
        provided.
    """

    parts = [expression.strip() for expression in expressions if expression and expression.strip()]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]

    return " and ".join(f"({part})" for part in parts)


def _build_string_equality_filter(field_name: str, value: str) -> str:
    """Build an exact string-equality OData filter clause.

    Args:
        field_name: RESO field name to compare.
        value: String value that must match exactly.

    Returns:
        The OData filter clause.
    """

    return f"{field_name} eq '{_escape_odata_string(value)}'"


def _build_postal_code_prefix_filter(postal_code: str) -> str:
    """Build a postal-code prefix filter using Spark's ``startswith`` syntax.

    Args:
        postal_code: Raw postal code or ZIP+4 value supplied by the caller.

    Returns:
        The OData prefix filter clause using the first five characters.
    """

    postal_prefix = postal_code[:5]
    return f"startswith(PostalCode,'{_escape_odata_string(postal_prefix)}')"


class PropertiesClient(CollectionResourceClient):
    """Access Spark RESO property data and replication helpers."""

    resource_name = "Property"

    def get_by_listing_key(
        self,
        listing_key: str,
        *,
        query: ODataQueryOptions | None = None,
        select: Sequence[str] | None = None,
        expand: Sequence[str | PropertyExpansion] | None = None,
        timeout_seconds: float | None = None,
    ) -> JsonPayload:
        """Retrieve a single property by ``ListingKey``.

        Args:
            listing_key: Property listing key.
            query: Optional base query configuration.
            select: Optional field selection.
            expand: Optional property expansions.
            timeout_seconds: Optional per-request timeout override.

        Returns:
            The decoded property payload.
        """

        return self.get_by_id(
            listing_key,
            query=query,
            select=select,
            expand=expand,
            timeout_seconds=timeout_seconds,
        )

    def list_with_expansions(
        self,
        *,
        expansions: Sequence[str | PropertyExpansion],
        query: ODataQueryOptions | None = None,
        select: Sequence[str] | None = None,
        top: int | None = None,
        skip: int | None = None,
        count: bool | None = None,
        order_by: Sequence[str] | None = None,
        filter_expression: str | None = None,
        timeout_seconds: float | None = None,
    ) -> JsonPayload:
        """List properties and include related entities via ``$expand``.

        Args:
            expansions: Expansions to include.
            query: Optional base query configuration.
            select: Optional field selection.
            top: Optional page size.
            skip: Optional offset.
            count: Optional flag for ``@odata.count``.
            order_by: Optional sort expressions.
            filter_expression: Optional OData filter expression.
            timeout_seconds: Optional per-request timeout override.

        Returns:
            The decoded collection payload.
        """

        return self.list(
            query=query,
            select=select,
            top=top,
            skip=skip,
            count=count,
            order_by=order_by,
            filter_expression=filter_expression,
            expand=normalize_values(expansions),
            timeout_seconds=timeout_seconds,
        )

    def list_by_address(
        self,
        *,
        unparsed_address: str,
        city: str,
        state_or_province: str | None = None,
        postal_code: str | None = None,
        query: ODataQueryOptions | None = None,
        select: Sequence[str] | None = None,
        top: int | None = None,
        skip: int | None = None,
        count: bool | None = None,
        order_by: Sequence[str] | None = None,
        filter_expression: str | None = None,
        expand: Sequence[str | PropertyExpansion] | None = None,
        timeout_seconds: float | None = None,
    ) -> JsonPayload:
        """List properties by a strict address match.

        Args:
            unparsed_address: Exact ``UnparsedAddress`` value to match.
            city: Exact ``City`` value to match.
            state_or_province: Optional exact ``StateOrProvince`` value.
            postal_code: Optional postal code or ZIP value. When provided, the
                first five characters are used in a ``startswith(PostalCode, ...)``
                filter.
            query: Optional base query configuration.
            select: Optional field selection.
            top: Optional page size.
            skip: Optional offset.
            count: Optional flag for ``@odata.count``.
            order_by: Optional sort expressions.
            filter_expression: Optional extra OData filter expression that will be
                combined with the strict address filter using ``and``.
            expand: Optional property expansions.
            timeout_seconds: Optional per-request timeout override.

        Returns:
            The decoded collection payload.

        Raises:
            ValidationError: If a required address field is blank.
        """

        normalized_address = _require_filter_value(
            unparsed_address,
            field_name="unparsed_address",
        )
        normalized_city = _require_filter_value(city, field_name="city")
        normalized_state = _normalize_optional_filter_value(state_or_province)
        normalized_postal_code = _normalize_optional_filter_value(postal_code)

        strict_address_filter = _combine_filter_expressions(
            _build_string_equality_filter("UnparsedAddress", normalized_address),
            _build_string_equality_filter("City", normalized_city),
            (
                _build_string_equality_filter("StateOrProvince", normalized_state)
                if normalized_state is not None
                else None
            ),
            (
                _build_postal_code_prefix_filter(normalized_postal_code)
                if normalized_postal_code is not None
                else None
            ),
        )
        combined_filter = _combine_filter_expressions(
            query.filter_expression if query is not None else None,
            filter_expression,
            strict_address_filter,
        )

        return self.list(
            query=query,
            select=select,
            top=top,
            skip=skip,
            count=count,
            order_by=order_by,
            filter_expression=combined_filter,
            expand=expand,
            timeout_seconds=timeout_seconds,
        )

    def list_by_parcel(
        self,
        *,
        parcel_number: str,
        query: ODataQueryOptions | None = None,
        select: Sequence[str] | None = None,
        top: int | None = None,
        skip: int | None = None,
        count: bool | None = None,
        order_by: Sequence[str] | None = None,
        filter_expression: str | None = None,
        expand: Sequence[str | PropertyExpansion] | None = None,
        timeout_seconds: float | None = None,
    ) -> JsonPayload:
        """List properties by exact ``ParcelNumber`` equality.

        Args:
            parcel_number: Exact ``ParcelNumber`` value to match.
            query: Optional base query configuration.
            select: Optional field selection.
            top: Optional page size.
            skip: Optional offset.
            count: Optional flag for ``@odata.count``.
            order_by: Optional sort expressions.
            filter_expression: Optional extra OData filter expression that will be
                combined with the exact parcel filter using ``and``.
            expand: Optional property expansions.
            timeout_seconds: Optional per-request timeout override.

        Returns:
            The decoded collection payload.

        Raises:
            ValidationError: If ``parcel_number`` is blank.
        """

        normalized_parcel_number = _require_filter_value(
            parcel_number,
            field_name="parcel_number",
        )
        parcel_filter = _build_string_equality_filter(
            "ParcelNumber",
            normalized_parcel_number,
        )
        combined_filter = _combine_filter_expressions(
            query.filter_expression if query is not None else None,
            filter_expression,
            parcel_filter,
        )

        return self.list(
            query=query,
            select=select,
            top=top,
            skip=skip,
            count=count,
            order_by=order_by,
            filter_expression=combined_filter,
            expand=expand,
            timeout_seconds=timeout_seconds,
        )

    def iter_listing_keys(
        self,
        *,
        top: int = 1000,
        timeout_seconds: float | None = None,
    ) -> Iterator[str]:
        """Iterate over all currently accessible property listing keys.

        Args:
            top: Number of records to request per page.
            timeout_seconds: Optional per-request timeout override.

        Yields:
            Listing keys returned by Spark.
        """

        for page in self.iter_all(
            select=("ListingKey",),
            top=top,
            timeout_seconds=timeout_seconds,
        ):
            for record in page.records:
                listing_key = record.get("ListingKey")
                if isinstance(listing_key, str):
                    yield listing_key

    def iter_replication_pages(
        self,
        *,
        query: ODataQueryOptions | None = None,
        select: Sequence[str] | None = None,
        top: int = 1000,
        order_by: Sequence[str] | None = None,
        filter_expression: str | None = None,
        expand: Sequence[str | PropertyExpansion] | None = None,
        timeout_seconds: float | None = None,
    ) -> Iterator[ODataPage[dict[str, Any]]]:
        """Iterate over property pages for an initial replication sync.

        Args:
            query: Optional base query configuration.
            select: Optional field selection.
            top: Number of records to request per page.
            order_by: Optional sort expressions.
            filter_expression: Optional extra filter expression.
            expand: Optional property expansions.
            timeout_seconds: Optional per-request timeout override.

        Yields:
            Parsed OData pages.
        """

        yield from self.iter_all(
            query=query,
            select=select,
            top=top,
            order_by=order_by,
            filter_expression=filter_expression,
            expand=expand,
            timeout_seconds=timeout_seconds,
        )

    def iter_recently_modified_properties(
        self,
        window: ReplicationWindow,
        *,
        top: int = 1000,
        select: Sequence[str] | None = None,
        order_by: Sequence[str] | None = None,
        expand: Sequence[str | PropertyExpansion] | None = None,
        additional_filter: str | None = None,
        timeout_seconds: float | None = None,
    ) -> Iterator[ODataPage[dict[str, Any]]]:
        """Iterate over properties modified inside a replication window.

        Args:
            window: Replication window used to build the timestamp filter.
            top: Number of records to request per page.
            select: Optional field selection.
            order_by: Optional sort expressions.
            expand: Optional property expansions.
            additional_filter: Optional extra filter expression.
            timeout_seconds: Optional per-request timeout override.

        Yields:
            Parsed OData pages.
        """

        yield from self.iter_recently_modified(
            window,
            top=top,
            select=select,
            order_by=order_by,
            expand=expand,
            additional_filter=additional_filter,
            timeout_seconds=timeout_seconds,
        )
