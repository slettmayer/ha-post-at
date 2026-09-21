"""Constants for the Österreichische Post account integration."""

from __future__ import annotations

from enum import StrEnum

DOMAIN = "post_at"
MANUFACTURER = "Österreichische Post AG"
ATTRIBUTION = "Data provided by Österreichische Post AG"


class ParcelStatus(StrEnum):
    """Carrier-agnostic parcel status.

    Deliberately identical to the vocabulary published by the
    ha-parcel-integrations family, so community parcel cards and cross-carrier
    automations work against this integration unchanged.
    """

    REGISTERED = "registered"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    AT_PICKUP_POINT = "at_pickup_point"
    DELIVERED = "delivered"
    RETURNING = "returning"
    PROBLEM = "problem"
    UNKNOWN = "unknown"
