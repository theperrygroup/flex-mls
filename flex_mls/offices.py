"""Client for the RESO ``Office`` resource."""

from __future__ import annotations

from flex_mls._resources import CollectionResourceClient


class OfficesClient(CollectionResourceClient):
    """Access Spark RESO office records."""

    resource_name = "Office"
