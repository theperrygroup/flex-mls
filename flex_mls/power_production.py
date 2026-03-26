"""Client for the RESO ``PowerProduction`` property subresource."""

from __future__ import annotations

from flex_mls._resources import PropertySingletonSubresourceClient


class PowerProductionClient(PropertySingletonSubresourceClient):
    """Access power production fields for a property."""

    subresource_name = "PowerProduction"
