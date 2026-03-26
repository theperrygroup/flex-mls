"""Client for the RESO ``GreenVerification`` property subresource."""

from __future__ import annotations

from flex_mls._resources import PropertySingletonSubresourceClient


class GreenVerificationClient(PropertySingletonSubresourceClient):
    """Access green verification fields for a property."""

    subresource_name = "GreenVerification"
