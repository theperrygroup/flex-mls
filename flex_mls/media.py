"""Client for the RESO ``Media`` property subresource."""

from __future__ import annotations

from flex_mls._resources import PropertyCollectionSubresourceClient


class MediaClient(PropertyCollectionSubresourceClient):
    """Access photos, videos, documents, and virtual tours for a property."""

    subresource_name = "Media"
