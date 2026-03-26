"""Internal helpers shared by resource client modules."""

from __future__ import annotations

from enum import Enum
from typing import Any, Iterator, Mapping, Sequence

from flex_mls.base_client import BaseClient
from flex_mls.exceptions import ValidationError
from flex_mls.models import JsonPayload, ODataPage, ODataQueryOptions, ReplicationWindow


def normalize_values(values: Sequence[str | Enum] | None) -> tuple[str, ...]:
    """Normalize string and enum values into a tuple of strings."""

    if values is None:
        return ()

    normalized: list[str] = []
    for value in values:
        normalized.append(value.value if isinstance(value, Enum) else value)

    return tuple(normalized)


def validate_top(top: int | None) -> None:
    """Validate Spark-compatible ``$top`` values.

    Args:
        top: Requested page size.

    Raises:
        ValidationError: If the page size falls outside Spark's documented
            maximum range.
    """

    if top is None:
        return

    if top <= 0 or top > 1000:
        raise ValidationError("The $top parameter must be between 1 and 1000.")


def build_query_options(
    *,
    query: ODataQueryOptions | None = None,
    select: Sequence[str] | None = None,
    top: int | None = None,
    skip: int | None = None,
    count: bool | None = None,
    order_by: Sequence[str] | None = None,
    filter_expression: str | None = None,
    expand: Sequence[str | Enum] | None = None,
    extra_params: Mapping[str, Any] | None = None,
) -> ODataQueryOptions:
    """Merge query overrides into a single ``ODataQueryOptions`` instance."""

    resolved = query or ODataQueryOptions()
    final_top = top if top is not None else resolved.top
    validate_top(final_top)

    merged_extra_params = dict(resolved.extra_params)
    if extra_params:
        merged_extra_params.update(
            {key: value for key, value in extra_params.items() if value is not None}
        )

    return ODataQueryOptions(
        select=tuple(select) if select is not None else resolved.select,
        top=final_top,
        skip=skip if skip is not None else resolved.skip,
        count=count if count is not None else resolved.count,
        order_by=tuple(order_by) if order_by is not None else resolved.order_by,
        filter_expression=(
            filter_expression
            if filter_expression is not None
            else resolved.filter_expression
        ),
        expand=normalize_values(expand) if expand is not None else resolved.expand,
        extra_params=merged_extra_params,
    )


class CollectionResourceClient(BaseClient):
    """Base class for top-level RESO collection resources."""

    resource_name: str = ""

    def _endpoint(self, record_id: str | None = None) -> str:
        """Build a collection or item endpoint for the configured resource."""

        if not self.resource_name:
            raise ValidationError("Resource name has not been configured.")

        if record_id is None:
            return self.resource_name

        return f"{self.resource_name}('{record_id}')"

    def list(
        self,
        *,
        query: ODataQueryOptions | None = None,
        select: Sequence[str] | None = None,
        top: int | None = None,
        skip: int | None = None,
        count: bool | None = None,
        order_by: Sequence[str] | None = None,
        filter_expression: str | None = None,
        expand: Sequence[str | Enum] | None = None,
        timeout_seconds: float | None = None,
    ) -> JsonPayload:
        """List resource records from Spark.

        Args:
            query: Optional query options object to use as a base.
            select: Optional field selection.
            top: Optional page size.
            skip: Optional offset.
            count: Optional flag for ``@odata.count``.
            order_by: Optional sort expressions.
            filter_expression: Optional raw OData filter expression.
            expand: Optional expansions to include.
            timeout_seconds: Optional per-request timeout override.

        Returns:
            The decoded OData collection payload.
        """

        options = build_query_options(
            query=query,
            select=select,
            top=top,
            skip=skip,
            count=count,
            order_by=order_by,
            filter_expression=filter_expression,
            expand=expand,
        )
        return self.get(
            self._endpoint(),
            params=options.to_params(),
            timeout_seconds=timeout_seconds,
        )

    def get_by_id(
        self,
        record_id: str,
        *,
        query: ODataQueryOptions | None = None,
        select: Sequence[str] | None = None,
        expand: Sequence[str | Enum] | None = None,
        timeout_seconds: float | None = None,
    ) -> JsonPayload:
        """Retrieve a single record by its RESO identifier.

        Args:
            record_id: Resource identifier or key.
            query: Optional query options object to use as a base.
            select: Optional field selection.
            expand: Optional expansions to include.
            timeout_seconds: Optional per-request timeout override.

        Returns:
            The decoded Spark payload for the specific record.
        """

        options = build_query_options(
            query=query,
            select=select,
            expand=expand,
        )
        return self.get(
            self._endpoint(record_id),
            params=options.to_params(),
            timeout_seconds=timeout_seconds,
        )

    def iter_all(
        self,
        *,
        query: ODataQueryOptions | None = None,
        select: Sequence[str] | None = None,
        top: int = 1000,
        order_by: Sequence[str] | None = None,
        filter_expression: str | None = None,
        expand: Sequence[str | Enum] | None = None,
        timeout_seconds: float | None = None,
    ) -> Iterator[ODataPage[dict[str, Any]]]:
        """Iterate over all pages for the collection resource."""

        options = build_query_options(
            query=query,
            select=select,
            top=top,
            order_by=order_by,
            filter_expression=filter_expression,
            expand=expand,
        )
        yield from self.iter_pages(
            self._endpoint(),
            params=options.to_params(),
            timeout_seconds=timeout_seconds,
        )

    def iter_recently_modified(
        self,
        window: ReplicationWindow,
        *,
        top: int = 1000,
        select: Sequence[str] | None = None,
        order_by: Sequence[str] | None = None,
        expand: Sequence[str | Enum] | None = None,
        additional_filter: str | None = None,
        timeout_seconds: float | None = None,
    ) -> Iterator[ODataPage[dict[str, Any]]]:
        """Iterate over pages modified within a replication window."""

        yield from self.iter_all(
            select=select,
            top=top,
            order_by=order_by,
            filter_expression=window.to_filter(additional_filter),
            expand=expand,
            timeout_seconds=timeout_seconds,
        )


class PropertyCollectionSubresourceClient(BaseClient):
    """Base class for property-scoped collection subresources."""

    subresource_name: str = ""

    def _endpoint(self, property_key: str, record_id: str | None = None) -> str:
        """Build a property-scoped endpoint."""

        if not self.subresource_name:
            raise ValidationError("Subresource name has not been configured.")

        base = f"Property('{property_key}')/{self.subresource_name}"
        if record_id is None:
            return base

        return f"{base}('{record_id}')"

    def list_for_property(
        self,
        property_key: str,
        *,
        query: ODataQueryOptions | None = None,
        select: Sequence[str] | None = None,
        top: int | None = None,
        skip: int | None = None,
        count: bool | None = None,
        order_by: Sequence[str] | None = None,
        filter_expression: str | None = None,
        timeout_seconds: float | None = None,
    ) -> JsonPayload:
        """List subresource records for a single property."""

        options = build_query_options(
            query=query,
            select=select,
            top=top,
            skip=skip,
            count=count,
            order_by=order_by,
            filter_expression=filter_expression,
        )
        return self.get(
            self._endpoint(property_key),
            params=options.to_params(),
            timeout_seconds=timeout_seconds,
        )

    def get_for_property(
        self,
        property_key: str,
        record_id: str,
        *,
        query: ODataQueryOptions | None = None,
        select: Sequence[str] | None = None,
        timeout_seconds: float | None = None,
    ) -> JsonPayload:
        """Retrieve a property-scoped subresource record by identifier."""

        options = build_query_options(query=query, select=select)
        return self.get(
            self._endpoint(property_key, record_id),
            params=options.to_params(),
            timeout_seconds=timeout_seconds,
        )


class PropertySingletonSubresourceClient(BaseClient):
    """Base class for property-scoped singleton subresources."""

    subresource_name: str = ""

    def _endpoint(self, property_key: str) -> str:
        """Build a property-scoped singleton endpoint."""

        if not self.subresource_name:
            raise ValidationError("Subresource name has not been configured.")

        return f"Property('{property_key}')/{self.subresource_name}"

    def get_for_property(
        self,
        property_key: str,
        *,
        query: ODataQueryOptions | None = None,
        select: Sequence[str] | None = None,
        timeout_seconds: float | None = None,
    ) -> JsonPayload:
        """Retrieve the singleton subresource for a property."""

        options = build_query_options(query=query, select=select)
        return self.get(
            self._endpoint(property_key),
            params=options.to_params(),
            timeout_seconds=timeout_seconds,
        )
