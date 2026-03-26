"""Client for the RESO ``Member`` resource."""

from __future__ import annotations

from flex_mls._resources import CollectionResourceClient


class MembersClient(CollectionResourceClient):
    """Access Spark RESO member records."""

    resource_name = "Member"
