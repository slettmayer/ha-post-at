"""Merge the account list summary with the public detail."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .const import TRACKING_URL, ParcelStatus
from .models import Parcel
from .status import map_status, normalize_state_key


def normalize_parcel(summary: dict[str, Any], detail: dict[str, Any] | None) -> Parcel:
    """Build a :class:`Parcel` from one list entry and its public detail.

    ``detail`` is ``None`` for a parcel the account knows about but Post has
    not scanned yet. That is a normal state, not an error: identity is kept and
    the status reports ``unknown`` until the first scan.
    """
    tracking_code = str(summary.get("sendungsnummer") or "")
    label = summary.get("bezeichnung") or None
    url = TRACKING_URL.format(tracking_code=tracking_code)

    if detail is None:
        return Parcel(
            tracking_code=tracking_code,
            label=label,
            status=ParcelStatus.UNKNOWN,
            raw_status=None,
            status_text=None,
            eta_start=None,
            eta_end=None,
            eta_time=None,
            eta_text=None,
            sender=None,
            weight=None,
            dimensions=None,
            last_event=None,
            url=url,
        )

    event = _newest_event(detail.get("sendungsEvents"))
    state_key = event.get("trackingStateKey") if event else None
    eta = detail.get("estimatedDelivery") or {}
    shipper = detail.get("shipper") or {}

    return Parcel(
        tracking_code=tracking_code,
        label=label,
        status=map_status(state_key),
        raw_status=normalize_state_key(state_key),
        status_text=_event_text(event),
        eta_start=_parse_dt(eta.get("startDate")),
        eta_end=_parse_dt(eta.get("endDate")),
        eta_time=eta.get("startTime"),
        eta_text=detail.get("estimatedDeliveryDateText"),
        sender=shipper.get("name"),
        weight=_as_float(detail.get("weight")),
        dimensions=_dimensions(detail.get("dimensions")),
        last_event=_event_projection(event),
        url=url,
    )


def _newest_event(events: Any) -> dict[str, Any] | None:
    """Return the most recent event, by timestamp.

    Post lists events newest-first, but sorting explicitly costs nothing and
    means a reordered response cannot silently roll a parcel's status back.
    """
    if not isinstance(events, list):
        return None
    dated = [e for e in events if isinstance(e, dict)]
    if not dated:
        return None
    return max(dated, key=lambda e: str(e.get("timestamp") or ""))


def _event_text(event: dict[str, Any] | None) -> str | None:
    """Post's own wording for an event, English first."""
    if not event:
        return None
    return event.get("textEn") or event.get("text") or None


def _event_projection(event: dict[str, Any] | None) -> dict[str, Any] | None:
    """Reduce an event to the few fields worth publishing."""
    if not event:
        return None
    return {
        "timestamp": event.get("timestamp"),
        "place": event.get("eventPlaceName"),
        "state_key": normalize_state_key(event.get("trackingStateKey")),
        "text": _event_text(event),
    }


def _parse_dt(value: Any) -> datetime | None:
    """Parse one of Post's ISO timestamps, keeping it timezone-aware."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _as_float(value: Any) -> float | None:
    """Coerce a numeric field, tolerating strings and nulls."""
    if value is None:
        return None
    try:
        return float(value)
    except TypeError, ValueError:
        return None


def _dimensions(value: Any) -> dict[str, float] | None:
    """Keep only the dimension fields that carry a usable number."""
    if not isinstance(value, dict):
        return None
    out: dict[str, float] = {}
    for key in ("height", "length", "width"):
        number = _as_float(value.get(key))
        if number is not None:
            out[key] = number
    return out or None
