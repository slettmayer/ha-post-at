"""Post's TrackingState vocabulary, mapped onto :class:`ParcelStatus`.

The table below is Post's own ``TrackingState`` enum. It was lifted from Post's
app by the MIT-licensed ha-oesterreichische-post project
(https://github.com/ha-parcel-integrations/ha-oesterreichische-post) and is
reproduced here with thanks.

Status is taken from ``trackingStateKey``, never from the coarse ``status``
field (``AN``/``ZU``, which cannot express "out for delivery") and never from
``reasontypecode`` (undocumented; no consumer has managed to map it).
"""

from __future__ import annotations

import logging
import re

from .const import ParcelStatus

_LOGGER = logging.getLogger(__name__)

# Post sends camelCase (``readyForPickUp``); its own app upper-snakes the key
# before resolving it against the enum. Same transform here, so the table can
# be written in the enum's own spelling.
_CAMEL_BOUNDARY_RE = re.compile(r"([a-z0-9])([A-Z])")

# ``UNKNOWN`` is deliberately absent: it is the app's own fallback for a key it
# does not recognise, so seeing it on the wire means the vocabulary moved. It
# lands on ``unknown`` plus the one-shot warning like any other unmapped value.
_STATUS_MAP: dict[str, ParcelStatus] = {
    # Announced, label printed, or handed over but not yet in the network
    "PENDING_INFORMATION": ParcelStatus.REGISTERED,
    "PARCEL_STAMP": ParcelStatus.REGISTERED,
    "AVISO": ParcelStatus.REGISTERED,
    "ALLES_POST": ParcelStatus.REGISTERED,
    # Moving through the network, customs included
    "DELIVERY_HAND_OVER": ParcelStatus.IN_TRANSIT,
    "IN_DISTRIBUTION": ParcelStatus.IN_TRANSIT,
    "CUSTOMS_CLEARANCE": ParcelStatus.IN_TRANSIT,
    "DELIVERY_IN_CUSTOMS": ParcelStatus.IN_TRANSIT,
    # On the van today
    "IN_DELIVERY": ParcelStatus.OUT_FOR_DELIVERY,
    # Waiting to be collected -- branch, post partner, station or locker
    "NOTIFIED": ParcelStatus.AT_PICKUP_POINT,
    "READY_FOR_PICK_UP": ParcelStatus.AT_PICKUP_POINT,
    "READY_FOR_PICK_UP_STATION": ParcelStatus.AT_PICKUP_POINT,
    "READY_FOR_PICK_UP_POINT": ParcelStatus.AT_PICKUP_POINT,
    "READY_FOR_PICK_UP_BOX": ParcelStatus.AT_PICKUP_POINT,
    # Arrived. DELIVERY_PARKED is a parcel left at the agreed Wunschplatz, and
    # Post's own isDelivered() counts it as delivered -- so do we.
    "DELIVERED": ParcelStatus.DELIVERED,
    "DELIVERY_PARKED": ParcelStatus.DELIVERED,
    # Going back to the sender
    "DELIVERY_IN_RETURN": ParcelStatus.RETURNING,
    # Something went wrong; the parcel is still in the network
    "DELIVERY_DELAYED": ParcelStatus.PROBLEM,
    "DELIVERY_INTERUPTED": ParcelStatus.PROBLEM,  # sic -- Post's own spelling
    "NOT_REACHABLE": ParcelStatus.PROBLEM,
}

_warned: set[str] = set()


def normalize_state_key(key: str | None) -> str | None:
    """Return a ``trackingStateKey`` in the vocabulary's own spelling."""
    if not key:
        return None
    return _CAMEL_BOUNDARY_RE.sub(r"\1_\2", str(key)).upper()


def map_status(key: str | None) -> ParcelStatus:
    """Map a ``trackingStateKey`` onto the canonical status.

    An unrecognised key reports ``unknown`` and warns once. Reporting a guess
    would be worse: a wrong ``delivered`` is far more damaging than an honest
    ``unknown``.
    """
    normalized = normalize_state_key(key)
    if normalized is None:
        return ParcelStatus.UNKNOWN
    mapped = _STATUS_MAP.get(normalized)
    if mapped is not None:
        return mapped
    if normalized not in _warned:
        _warned.add(normalized)
        _LOGGER.warning(
            "Österreichische Post reported the unmapped tracking state %s. "
            "The parcel shows as 'unknown'. Please report it at "
            "https://github.com/slettmayer/ha-post-at/issues so it can be mapped",
            normalized,
        )
    return ParcelStatus.UNKNOWN
