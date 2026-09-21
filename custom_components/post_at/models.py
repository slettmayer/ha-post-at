"""The normalised parcel this integration publishes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .const import ParcelStatus

# Statuses that mean the parcel has stopped moving. `unknown` is deliberately
# not here: a parcel Post has not scanned yet is still on its way.
_TERMINAL = frozenset({ParcelStatus.DELIVERED, ParcelStatus.RETURNING})


@dataclass(frozen=True, slots=True)
class Parcel:
    """One parcel, merged from the account list and the public detail.

    Deliberately carries no address: ``recipientAddress`` is the user's own
    name and street on every parcel, it adds nothing to a dashboard, and it
    would otherwise land in the recorder database and in diagnostics.
    """

    tracking_code: str
    label: str | None
    status: ParcelStatus
    # Post's own key, both ways round: `tracking_state_key` is verbatim off
    # the wire (`deliveryHandOver`), `raw_status` is the upper-snaked spelling
    # the status table is keyed on (`DELIVERY_HAND_OVER`). Both are published
    # -- the verbatim one is what a bug report or an issue should quote.
    tracking_state_key: str | None
    raw_status: str | None
    status_text: str | None
    eta_start: datetime | None
    eta_end: datetime | None
    eta_time: str | None
    eta_text: str | None
    sender: str | None
    weight: float | None
    dimensions: dict[str, float] | None
    last_event: dict[str, Any] | None
    url: str

    @property
    def is_active(self) -> bool:
        """Whether the parcel is still on its way."""
        return self.status not in _TERMINAL

    def as_attribute(self) -> dict[str, Any]:
        """The projection published on the summary sensor's attribute.

        Everything here must be JSON-serialisable: it crosses the websocket
        API and is written to the recorder.
        """
        return {
            "sendungsnummer": self.tracking_code,
            "bezeichnung": self.label,
            "status": self.status.value,
            "trackingStateKey": self.tracking_state_key,
            "raw_status": self.raw_status,
            "status_text": self.status_text,
            "eta_start": self.eta_start.isoformat() if self.eta_start else None,
            "eta_end": self.eta_end.isoformat() if self.eta_end else None,
            "eta_time": self.eta_time,
            "eta_text": self.eta_text,
            "sender": self.sender,
            "weight": self.weight,
            "dimensions": self.dimensions,
            "last_event": self.last_event,
            "url": self.url,
        }
