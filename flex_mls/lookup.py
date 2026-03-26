"""Client for the RESO ``Lookup`` resource."""

from __future__ import annotations

from flex_mls._resources import CollectionResourceClient


class LookupClient(CollectionResourceClient):
    """Access discrete lookup values advertised by Spark metadata."""

    resource_name = "Lookup"
