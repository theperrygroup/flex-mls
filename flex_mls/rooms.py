"""Client for the RESO ``Room`` property subresource."""

from __future__ import annotations

from flex_mls._resources import PropertyCollectionSubresourceClient


class RoomsClient(PropertyCollectionSubresourceClient):
    """Access room records for a property."""

    subresource_name = "Room"
