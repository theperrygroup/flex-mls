"""Shared enums for the ``flex_mls`` package."""

from __future__ import annotations

from enum import Enum


class ResponseFormat(str, Enum):
    """Supported response formats for Spark RESO requests."""

    JSON = "application/json"
    XML = "application/xml"


class OpenIdScope(str, Enum):
    """Spark OpenID Connect scopes exposed by the discovery document."""

    OPENID = "openid"
    PROFILE = "profile"
    EMAIL = "email"
    ADDRESS = "address"
    PHONE = "phone"
    RESO = "RESO"
    FBS = "FBS"


class PropertyExpansion(str, Enum):
    """Supported property expansions documented by Spark."""

    GREEN_VERIFICATION = "GreenVerification"
    MEDIA = "Media"
    ROOM = "Room"
    UNIT = "Unit"
    OPEN_HOUSE = "OpenHouse"
    POWER_PRODUCTION = "PowerProduction"
    HISTORY_TRANSACTIONAL = "HistoryTransactional"
    RENTAL_CALENDAR = "RentalCalendar"
