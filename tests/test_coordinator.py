"""Polling, interval selection, the 401 retry and event emission."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
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
    LANGUAGE_DE,
    LANGUAGE_EN,
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


def _client(shipments, details, language=LANGUAGE_EN):
    client = AsyncMock()
    client.language = language
    client.async_list_shipments = AsyncMock(return_value=shipments)
    client.async_get_public_detail = AsyncMock(
        side_effect=lambda code: details.get(code)
    )
    # Sync on the real client, so an AsyncMock here would hand the coordinator
    # a coroutine it never awaits.
    client.invalidate_token = MagicMock()
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


def _delivered_detail(days_ago: int):
    when = dt_util.utcnow() - timedelta(days=days_ago)
    return _detail("delivered", when.isoformat())


async def test_recently_delivered_parcels_are_kept(hass, entry):
    client = _client([SUMMARY_ONE], {"0001": _delivered_detail(2)})
    coordinator = PostAtCoordinator(hass, entry, client)
    await coordinator.async_refresh()

    assert [p.tracking_code for p in coordinator.data] == ["0001"]


async def test_long_delivered_parcels_are_dropped(hass, entry):
    client = _client([SUMMARY_ONE], {"0001": _delivered_detail(30)})
    coordinator = PostAtCoordinator(hass, entry, client)
    await coordinator.async_refresh()

    assert coordinator.data == []


async def test_active_parcels_are_never_dropped_however_old(hass, entry):
    client = _client(
        [SUMMARY_ONE],
        {"0001": _detail("deliveryHandOver", "2020-01-01T00:00:00+00:00")},
    )
    coordinator = PostAtCoordinator(hass, entry, client)
    await coordinator.async_refresh()

    assert [p.tracking_code for p in coordinator.data] == ["0001"]


async def test_a_delivered_parcel_without_a_timestamp_is_kept(hass, entry):
    detail = {
        "estimatedDelivery": {"startDate": None, "endDate": None, "startTime": None},
        "sendungsEvents": [{"trackingStateKey": "delivered", "textEn": "x"}],
    }
    client = _client([SUMMARY_ONE], {"0001": detail})
    coordinator = PostAtCoordinator(hass, entry, client)
    await coordinator.async_refresh()

    assert [p.tracking_code for p in coordinator.data] == ["0001"]


async def test_an_aged_out_parcel_does_not_re_register_every_poll(hass, entry):
    """The trap the retention filter introduces if events diff on self.data."""
    events = []
    hass.bus.async_listen(EVENT_PARCEL_REGISTERED, events.append)
    client = _client(
        [SUMMARY_ONE, SUMMARY_TWO],
        {"0001": _detail("deliveryHandOver"), "0002": _delivered_detail(30)},
    )
    coordinator = PostAtCoordinator(hass, entry, client)
    await coordinator.async_refresh()  # first refresh: events suppressed
    await coordinator.async_refresh()
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.data and all(p.tracking_code == "0001" for p in coordinator.data)
    assert events == [], "an aged-out parcel was re-announced"


async def test_parcels_are_normalised_in_the_language_the_client_asked_for(hass, entry):
    """The client owns the language; the coordinator must not re-derive it."""
    detail = _detail("deliveryHandOver")
    detail["sendungsEvents"][0] |= {"text": "auf Deutsch", "textEn": "in English"}
    coordinator = PostAtCoordinator(
        hass, entry, _client([SUMMARY_ONE], {"0001": detail}, LANGUAGE_DE)
    )
    await coordinator.async_refresh()

    assert coordinator.data[0].status_text == "auf Deutsch"


async def test_the_401_retry_drops_the_rejected_token(hass, entry):
    """Without this the retry replays the token post.at just rejected."""
    client = _client([SUMMARY_ONE], {"0001": _detail("deliveryHandOver")})
    client.async_list_shipments = AsyncMock(
        side_effect=[PostAtAuthExpired("stale"), [SUMMARY_ONE]]
    )
    coordinator = PostAtCoordinator(hass, entry, client)
    await coordinator.async_refresh()

    assert client.invalidate_token.call_count == 1


async def test_returning_parcels_are_re_enriched_every_poll(hass, entry):
    """A returning parcel is inactive but still moving, so it is not settled.

    Caching it would freeze its status and `last_event` for as long as it
    stayed on the account list, and a reroute or a counter collection could
    never take it to delivered.
    """
    client = _client([SUMMARY_ONE], {"0001": _detail("deliveryInReturn")})
    coordinator = PostAtCoordinator(hass, entry, client)
    await coordinator.async_refresh()
    await coordinator.async_refresh()

    assert coordinator.data[0].status is ParcelStatus.RETURNING
    assert client.async_get_public_detail.await_count == 2


async def _first_sight(hass, entry, timestamp):
    """Introduce an already-delivered parcel *after* the first refresh.

    The first refresh is deliberately silent, so the parcel has to arrive on
    a later poll for the first-sight path to be the one under test.
    """
    client = _client([], {})
    coordinator = PostAtCoordinator(hass, entry, client)
    await coordinator.async_refresh()

    delivered = []
    hass.bus.async_listen(EVENT_PARCEL_DELIVERED, delivered.append)
    client.async_list_shipments = AsyncMock(return_value=[SUMMARY_ONE])
    client.async_get_public_detail = AsyncMock(
        return_value=_detail("delivered", timestamp=timestamp)
    )
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    return delivered


async def test_a_parcel_first_seen_already_delivered_fires_delivered(hass, entry):
    """There is no transition to observe, but it did just arrive."""
    just_now = (dt_util.utcnow() - timedelta(minutes=30)).isoformat()
    assert len(await _first_sight(hass, entry, just_now)) == 1


async def test_an_old_delivery_surfacing_late_stays_quiet(hass, entry):
    """Post's list reaches months back; nobody wants last month's parcel."""
    long_ago = (dt_util.utcnow() - timedelta(days=40)).isoformat()
    assert await _first_sight(hass, entry, long_ago) == []


async def test_a_first_sight_delivery_without_a_timestamp_stays_quiet(hass, entry):
    """A missed notification beats a wrong one."""
    assert await _first_sight(hass, entry, None) == []
