"""Client for the RESO ``Unit`` property subresource."""

from __future__ import annotations

from flex_mls._resources import PropertyCollectionSubresourceClient


class UnitsClient(PropertyCollectionSubresourceClient):
    """Access unit records for a property."""

    subresource_name = "Unit"
