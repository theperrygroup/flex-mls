"""Client for the RESO ``OpenHouse`` resource."""

from __future__ import annotations

from typing import Sequence

from flex_mls._resources import CollectionResourceClient, build_query_options
from flex_mls.models import JsonPayload, ODataQueryOptions


class OpenHousesClient(CollectionResourceClient):
    """Access Spark RESO open house records."""

    resource_name = "OpenHouse"

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
        """List all open houses for a specific property.

        Args:
            property_key: Listing key for the property.
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
            f"Property('{property_key}')/OpenHouse",
            params=options.to_params(),
            timeout_seconds=timeout_seconds,
        )

    def get_for_property(
        self,
        property_key: str,
        open_house_id: str,
        *,
        query: ODataQueryOptions | None = None,
        select: Sequence[str] | None = None,
        timeout_seconds: float | None = None,
    ) -> JsonPayload:
        """Retrieve a specific open house record for a property.

        Args:
            property_key: Listing key for the property.
            open_house_id: Open house identifier.
            query: Optional base query configuration.
            select: Optional field selection.
            timeout_seconds: Optional per-request timeout override.

        Returns:
            The decoded Spark payload.
        """

        options = build_query_options(query=query, select=select)
        return self.get(
            f"Property('{property_key}')/OpenHouse('{open_house_id}')",
            params=options.to_params(),
            timeout_seconds=timeout_seconds,
        )
