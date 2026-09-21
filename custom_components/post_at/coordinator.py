"""Polling coordinator for the post.at account."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    TimestampDataUpdateCoordinator,
    UpdateFailed,
)

from .api import PostAtApiClient, PostAtApiError
from .auth import PostAtAuthExpired
from .const import (
    ACTIVE_INTERVAL_MINUTES,
    DOMAIN,
    EVENT_PARCEL_DELIVERED,
    EVENT_PARCEL_DELIVERY_TIME_CHANGED,
    EVENT_PARCEL_REGISTERED,
    EVENT_PARCEL_STATUS_CHANGED,
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
        here means it was rejected early. One retry forces a fresh renewal; a
        second failure is a genuinely dead session and becomes a reauth.
        """
        try:
            return await self._client.async_list_shipments()
        except PostAtAuthExpired:
            _LOGGER.debug("post.at rejected the token; renewing once and retrying")
            return await self._client.async_list_shipments()

    async def _build(self, summary: dict[str, Any]) -> Parcel:
        """Normalise one shipment, reusing a settled parcel when we have one."""
        code = str(summary.get("sendungsnummer") or "")
        if (settled := self._settled.get(code)) is not None:
            return settled
        detail = await self._client.async_get_public_detail(code)
        parcel = normalize_parcel(summary, detail)
        if not parcel.is_active:
            self._settled[code] = parcel
        return parcel

    def _fire_events(self, parcels: list[Parcel]) -> None:
        """Emit bus events for whatever changed since the previous refresh.

        Suppressed on the first refresh after a restart: otherwise every
        reboot would replay the whole account as fresh arrivals.
        """
        previous = {parcel.tracking_code: parcel for parcel in (self.data or [])}
        if not self._seen_first_refresh:
            self._seen_first_refresh = True
            return

        for parcel in parcels:
            before = previous.get(parcel.tracking_code)
            payload = parcel.as_attribute()
            if before is None:
                self.hass.bus.async_fire(EVENT_PARCEL_REGISTERED, payload)
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
