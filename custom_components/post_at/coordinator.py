"""Polling coordinator for the post.at account."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    TimestampDataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from .api import PostAtApiClient, PostAtApiError
from .auth import PostAtAuthExpired
from .const import (
    ACTIVE_INTERVAL_MINUTES,
    DELIVERED_RETENTION_DAYS,
    DOMAIN,
    EVENT_PARCEL_DELIVERED,
    EVENT_PARCEL_DELIVERY_TIME_CHANGED,
    EVENT_PARCEL_REGISTERED,
    EVENT_PARCEL_STATUS_CHANGED,
    FIRST_SIGHT_DELIVERED_MAX_AGE_HOURS,
    IDLE_INTERVAL_MINUTES,
    ParcelStatus,
)
from .models import Parcel
from .parcels import normalize_parcel

_LOGGER = logging.getLogger(__name__)

type PostAtConfigEntry = ConfigEntry[PostAtCoordinator]


class PostAtCoordinator(TimestampDataUpdateCoordinator[list[Parcel]]):
    """Polls the account and publishes a list of normalised parcels."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: PostAtConfigEntry,
        client: PostAtApiClient,
    ) -> None:
        """Start on the idle cadence; the first refresh picks the real one."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=IDLE_INTERVAL_MINUTES),
        )
        self._client = client
        # A delivered parcel never changes again, so its detail is fetched
        # once and reused for as long as it stays on the account list.
        self._settled: dict[str, Parcel] = {}
        # Events diff against this rather than against `self.data`, because
        # `self.data` holds the *filtered* list: an old delivered parcel that
        # has aged out of the attribute would otherwise look new on every
        # single poll and re-fire `parcel_registered` forever.
        self._previous: dict[str, Parcel] = {}
        self._seen_first_refresh = False

    async def _async_update_data(self) -> list[Parcel]:
        """Fetch the account list and enrich every parcel still in flight."""
        try:
            summaries = await self._list_with_one_retry()
            parcels = [await self._build(summary) for summary in summaries]
        except PostAtAuthExpired as err:
            raise ConfigEntryAuthFailed(
                "post.at sign-in has expired; sign in again"
            ) from err
        except PostAtApiError as err:
            raise UpdateFailed(str(err)) from err

        self._fire_events(parcels)
        parcels = _drop_stale_deliveries(parcels)
        self.update_interval = timedelta(
            minutes=(
                ACTIVE_INTERVAL_MINUTES
                if any(parcel.is_active for parcel in parcels)
                else IDLE_INTERVAL_MINUTES
            )
        )
        return parcels

    async def _list_with_one_retry(self) -> list[dict[str, Any]]:
        """List shipments, renewing the token once if the first call is 401.

        The access token lives an hour and is renewed pre-emptively, so a 401
        here means it was rejected early. Dropping the cached token forces the
        retry to mint a new one -- without that the retry would replay the
        token post.at just rejected and fail identically. A second failure is
        a genuinely dead session and becomes a reauth.
        """
        try:
            return await self._client.async_list_shipments()
        except PostAtAuthExpired:
            _LOGGER.debug("post.at rejected the token; renewing once and retrying")
            self._client.invalidate_token()
            return await self._client.async_list_shipments()

    async def _build(self, summary: dict[str, Any]) -> Parcel:
        """Normalise one shipment, reusing a settled parcel when we have one."""
        code = str(summary.get("sendungsnummer") or "")
        if (settled := self._settled.get(code)) is not None:
            return settled
        detail = await self._client.async_get_public_detail(code)
        parcel = normalize_parcel(summary, detail, self._client.language)
        # Only `delivered` is final. A returning parcel is also `is_active ==
        # False` -- it no longer counts towards the active poll cadence -- but
        # it is still being scanned, and a reroute or a counter collection can
        # still take it to delivered. Caching it here would freeze it forever.
        if parcel.status is ParcelStatus.DELIVERED:
            self._settled[code] = parcel
        return parcel

    def _fire_events(self, parcels: list[Parcel]) -> None:
        """Emit bus events for whatever changed since the previous refresh.

        Suppressed on the first refresh after a restart: otherwise every
        reboot would replay the whole account as fresh arrivals.
        """
        previous = self._previous
        self._previous = {parcel.tracking_code: parcel for parcel in parcels}
        if not self._seen_first_refresh:
            self._seen_first_refresh = True
            return

        now = dt_util.utcnow()
        for parcel in parcels:
            before = previous.get(parcel.tracking_code)
            payload = parcel.as_attribute()
            if before is None:
                self.hass.bus.async_fire(EVENT_PARCEL_REGISTERED, payload)
                # A parcel can appear already delivered -- there is no
                # transition to observe, but it did just arrive, so the
                # arrival event still has to fire.
                if parcel.status is ParcelStatus.DELIVERED and _arrived_recently(
                    parcel, now
                ):
                    self.hass.bus.async_fire(EVENT_PARCEL_DELIVERED, payload)
                continue
            if before.status is not parcel.status:
                # The final hop to delivered gets its own event rather than a
                # status_changed, so an automation can key on arrival alone.
                if parcel.status is ParcelStatus.DELIVERED:
                    self.hass.bus.async_fire(EVENT_PARCEL_DELIVERED, payload)
                else:
                    self.hass.bus.async_fire(
                        EVENT_PARCEL_STATUS_CHANGED,
                        payload
                        | {
                            "old_status": before.status.value,
                            "new_status": parcel.status.value,
                        },
                    )
            if (before.eta_start, before.eta_end) != (parcel.eta_start, parcel.eta_end):
                self.hass.bus.async_fire(EVENT_PARCEL_DELIVERY_TIME_CHANGED, payload)


def _arrived_recently(parcel: Parcel, now: datetime) -> bool:
    """Whether a parcel seen for the first time has only just been delivered.

    Post's account list reaches months back and can surface an old delivery
    late, so an unbounded first-sight `delivered` would announce a parcel that
    arrived weeks ago. A parcel whose delivery carries no usable timestamp
    stays silent: a missed notification is better than a wrong one, and the
    parcel is still published on the summary sensor either way.
    """
    when = _delivered_at(parcel)
    if when is None:
        return False
    return when >= now - timedelta(hours=FIRST_SIGHT_DELIVERED_MAX_AGE_HOURS)


def _drop_stale_deliveries(parcels: list[Parcel]) -> list[Parcel]:
    """Keep every active parcel, and only recently delivered ones.

    Post's account list reaches months back. Publishing all of it would grow
    the summary sensor's attribute past what Home Assistant will carry, and
    rewrite the whole blob into the recorder on every poll. Events fire before
    this runs, so a delivery is never missed just because it is being dropped
    from the attribute in the same refresh.
    """
    cutoff = dt_util.utcnow() - timedelta(days=DELIVERED_RETENTION_DAYS)
    kept: list[Parcel] = []
    for parcel in parcels:
        if parcel.is_active:
            kept.append(parcel)
            continue
        when = _delivered_at(parcel)
        # A delivered parcel with no usable timestamp is kept: dropping it
        # would hide it forever, and there are only ever a handful.
        if when is None or when >= cutoff:
            kept.append(parcel)
    return kept


def _delivered_at(parcel: Parcel) -> datetime | None:
    """When the parcel last moved, from its newest event."""
    stamp = (parcel.last_event or {}).get("timestamp")
    if not stamp:
        return None
    parsed = dt_util.parse_datetime(str(stamp))
    return dt_util.as_utc(parsed) if parsed else None
