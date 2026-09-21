"""Polling, interval selection, the 401 retry and event emission."""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.post_at.api import PostAtApiError
from custom_components.post_at.auth import PostAtAuthExpired
from custom_components.post_at.const import (
    ACTIVE_INTERVAL_MINUTES,
    DOMAIN,
    EVENT_PARCEL_DELIVERED,
    EVENT_PARCEL_DELIVERY_TIME_CHANGED,
    EVENT_PARCEL_REGISTERED,
    EVENT_PARCEL_STATUS_CHANGED,
    IDLE_INTERVAL_MINUTES,
    ParcelStatus,
)
from custom_components.post_at.coordinator import PostAtCoordinator

SUMMARY_ONE = {"sendungsnummer": "0001", "bezeichnung": "One", "isRecipient": True}
SUMMARY_TWO = {"sendungsnummer": "0002", "bezeichnung": "Two", "isRecipient": True}


def _detail(state_key, timestamp="2026-09-21T08:00:00.000+00:00", eta=None):
    return {
        "estimatedDelivery": eta
        or {"startDate": None, "endDate": None, "startTime": None},
        "sendungsEvents": [
            {
                "trackingStateKey": state_key,
                "textEn": "x",
                "timestamp": timestamp,
                "eventPlaceName": "p",
            }
        ],
    }


def _client(shipments, details):
    client = AsyncMock()
    client.async_list_shipments = AsyncMock(return_value=shipments)
    client.async_get_public_detail = AsyncMock(
        side_effect=lambda code: details.get(code)
    )
    return client


@pytest.fixture
def entry(hass):
    item = MockConfigEntry(domain=DOMAIN, data={"email": "u@example.invalid"})
    item.add_to_hass(hass)
    return item


async def test_refresh_returns_normalised_parcels(hass, entry):
    client = _client([SUMMARY_ONE], {"0001": _detail("deliveryHandOver")})
    coordinator = PostAtCoordinator(hass, entry, client)
    await coordinator.async_refresh()

    assert coordinator.last_update_success
    assert coordinator.data[0].status is ParcelStatus.IN_TRANSIT


async def test_parcel_without_public_detail_still_appears(hass, entry):
    client = _client([SUMMARY_ONE], {})
    coordinator = PostAtCoordinator(hass, entry, client)
    await coordinator.async_refresh()

    assert coordinator.data[0].tracking_code == "0001"
    assert coordinator.data[0].status is ParcelStatus.UNKNOWN


async def test_interval_is_short_while_a_parcel_is_active(hass, entry):
    client = _client([SUMMARY_ONE], {"0001": _detail("deliveryHandOver")})
    coordinator = PostAtCoordinator(hass, entry, client)
    await coordinator.async_refresh()

    assert coordinator.update_interval == timedelta(minutes=ACTIVE_INTERVAL_MINUTES)


async def test_interval_is_long_when_everything_is_delivered(hass, entry):
    client = _client([SUMMARY_ONE], {"0001": _detail("delivered")})
    coordinator = PostAtCoordinator(hass, entry, client)
    await coordinator.async_refresh()

    assert coordinator.update_interval == timedelta(minutes=IDLE_INTERVAL_MINUTES)


async def test_interval_is_long_for_an_empty_account(hass, entry):
    coordinator = PostAtCoordinator(hass, entry, _client([], {}))
    await coordinator.async_refresh()

    assert coordinator.update_interval == timedelta(minutes=IDLE_INTERVAL_MINUTES)


async def test_delivered_parcels_are_not_enriched_twice(hass, entry):
    client = _client([SUMMARY_ONE], {"0001": _detail("delivered")})
    coordinator = PostAtCoordinator(hass, entry, client)
    await coordinator.async_refresh()
    await coordinator.async_refresh()

    assert client.async_get_public_detail.await_count == 1


async def test_active_parcels_are_re_enriched_every_poll(hass, entry):
    client = _client([SUMMARY_ONE], {"0001": _detail("deliveryHandOver")})
    coordinator = PostAtCoordinator(hass, entry, client)
    await coordinator.async_refresh()
    await coordinator.async_refresh()

    assert client.async_get_public_detail.await_count == 2


async def test_401_triggers_one_retry_then_succeeds(hass, entry):
    client = _client([SUMMARY_ONE], {"0001": _detail("deliveryHandOver")})
    client.async_list_shipments = AsyncMock(
        side_effect=[PostAtAuthExpired("stale"), [SUMMARY_ONE]]
    )
    coordinator = PostAtCoordinator(hass, entry, client)
    await coordinator.async_refresh()

    assert coordinator.last_update_success
    assert client.async_list_shipments.await_count == 2


async def test_second_401_starts_reauth(hass, entry):
    client = _client([], {})
    client.async_list_shipments = AsyncMock(side_effect=PostAtAuthExpired("gone"))
    coordinator = PostAtCoordinator(hass, entry, client)

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_api_error_fails_the_refresh(hass, entry):
    client = _client([], {})
    client.async_list_shipments = AsyncMock(side_effect=PostAtApiError("boom"))
    coordinator = PostAtCoordinator(hass, entry, client)

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_no_events_on_the_first_refresh(hass, entry):
    events = []
    hass.bus.async_listen(EVENT_PARCEL_REGISTERED, events.append)
    client = _client([SUMMARY_ONE], {"0001": _detail("deliveryHandOver")})
    coordinator = PostAtCoordinator(hass, entry, client)
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert events == []


async def test_new_parcel_fires_registered(hass, entry):
    events = []
    hass.bus.async_listen(EVENT_PARCEL_REGISTERED, events.append)
    details = {
        "0001": _detail("deliveryHandOver"),
        "0002": _detail("deliveryHandOver"),
    }
    client = _client([SUMMARY_ONE], details)
    coordinator = PostAtCoordinator(hass, entry, client)
    await coordinator.async_refresh()

    client.async_list_shipments = AsyncMock(return_value=[SUMMARY_ONE, SUMMARY_TWO])
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["sendungsnummer"] == "0002"


async def test_status_change_fires_status_changed(hass, entry):
    events = []
    hass.bus.async_listen(EVENT_PARCEL_STATUS_CHANGED, events.append)
    details = {"0001": _detail("deliveryHandOver")}
    client = _client([SUMMARY_ONE], details)
    coordinator = PostAtCoordinator(hass, entry, client)
    await coordinator.async_refresh()

    details["0001"] = _detail("inDelivery", "2026-09-22T06:00:00.000+00:00")
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["old_status"] == ParcelStatus.IN_TRANSIT.value
    assert events[0].data["new_status"] == ParcelStatus.OUT_FOR_DELIVERY.value


async def test_delivery_fires_delivered_not_status_changed(hass, entry):
    delivered, changed = [], []
    hass.bus.async_listen(EVENT_PARCEL_DELIVERED, delivered.append)
    hass.bus.async_listen(EVENT_PARCEL_STATUS_CHANGED, changed.append)
    details = {"0001": _detail("deliveryHandOver")}
    client = _client([SUMMARY_ONE], details)
    coordinator = PostAtCoordinator(hass, entry, client)
    await coordinator.async_refresh()

    details["0001"] = _detail("delivered", "2026-09-22T09:00:00.000+00:00")
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert len(delivered) == 1
    assert changed == []


async def test_eta_change_fires_delivery_time_changed(hass, entry):
    events = []
    hass.bus.async_listen(EVENT_PARCEL_DELIVERY_TIME_CHANGED, events.append)
    details = {
        "0001": _detail(
            "deliveryHandOver",
            eta={
                "startDate": "2026-09-22T00:00:00.000Z",
                "endDate": None,
                "startTime": None,
            },
        )
    }
    client = _client([SUMMARY_ONE], details)
    coordinator = PostAtCoordinator(hass, entry, client)
    await coordinator.async_refresh()

    details["0001"] = _detail(
        "deliveryHandOver",
        eta={
            "startDate": "2026-09-23T00:00:00.000Z",
            "endDate": None,
            "startTime": None,
        },
    )
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert len(events) == 1


async def test_unchanged_parcel_fires_nothing(hass, entry):
    events = []
    for name in (
        EVENT_PARCEL_REGISTERED,
        EVENT_PARCEL_STATUS_CHANGED,
        EVENT_PARCEL_DELIVERED,
        EVENT_PARCEL_DELIVERY_TIME_CHANGED,
    ):
        hass.bus.async_listen(name, events.append)
    client = _client([SUMMARY_ONE], {"0001": _detail("deliveryHandOver")})
    coordinator = PostAtCoordinator(hass, entry, client)
    await coordinator.async_refresh()
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert events == []
