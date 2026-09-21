"""The three sensors, exercised through a real config entry setup."""

from unittest.mock import AsyncMock, patch

from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.post_at.const import (
    CONF_EMAIL,
    CONF_SSO_COOKIE_NAME,
    CONF_SSO_COOKIE_VALUE,
    DOMAIN,
)

SUMMARIES = [
    {"sendungsnummer": "0001", "bezeichnung": "One", "isRecipient": True},
    {"sendungsnummer": "0002", "bezeichnung": "Two", "isRecipient": True},
]
DETAILS = {
    "0001": {
        "estimatedDelivery": {
            "startDate": "2026-09-22T00:00:00.000Z",
            "endDate": "2026-09-23T00:00:00.000Z",
            "startTime": None,
        },
        "estimatedDeliveryDateText": "Voraussichtlich morgen",
        "weight": 1.25,
        "shipper": {"name": "Example Sender"},
        "sendungsEvents": [
            {
                "trackingStateKey": "deliveryHandOver",
                "textEn": "Item accepted",
                "timestamp": "2026-09-21T08:00:00.000+00:00",
                "eventPlaceName": "PLZ 9010",
            }
        ],
    },
    "0002": {
        "estimatedDelivery": {"startDate": None, "endDate": None, "startTime": None},
        "sendungsEvents": [
            {
                "trackingStateKey": "delivered",
                "textEn": "Delivered",
                "timestamp": "2026-09-20T10:00:00.000+00:00",
                "eventPlaceName": "PLZ 9020",
            }
        ],
    },
}


async def setup_integration(hass, summaries=None, details=None):
    """Set the integration up with a mocked API client."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="user@example.invalid",
        title="user@example.invalid",
        data={
            CONF_EMAIL: "user@example.invalid",
            CONF_SSO_COOKIE_NAME: "x-ms-cpim-sso:t_0",
            CONF_SSO_COOKIE_VALUE: "V",
        },
    )
    entry.add_to_hass(hass)
    resolved = DETAILS if details is None else details
    with (
        patch(
            "custom_components.post_at.PostAtApiClient.async_list_shipments",
            AsyncMock(return_value=SUMMARIES if summaries is None else summaries),
        ),
        patch(
            "custom_components.post_at.PostAtApiClient.async_get_public_detail",
            AsyncMock(side_effect=lambda code: resolved.get(code)),
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_count_sensor_counts_only_active_parcels(hass):
    await setup_integration(hass)
    state = hass.states.get("sensor.osterreichische_post_parcels_in_delivery")
    assert state is not None
    assert state.state == "1"


async def test_count_sensor_lists_every_parcel_in_its_attribute(hass):
    await setup_integration(hass)
    state = hass.states.get("sensor.osterreichische_post_parcels_in_delivery")
    parcels = state.attributes["parcels"]

    assert [p["sendungsnummer"] for p in parcels] == ["0001", "0002"]
    assert parcels[0]["status_text"] == "Item accepted"
    assert parcels[0]["status"] == "in_transit"
    assert parcels[1]["status"] == "delivered"


async def test_attributes_carry_no_address(hass):
    await setup_integration(hass)
    state = hass.states.get("sensor.osterreichische_post_parcels_in_delivery")
    blob = str(state.attributes).lower()

    for forbidden in ("consignee", "street", "recipientaddress"):
        assert forbidden not in blob


async def test_next_delivery_is_the_earliest_active_eta(hass):
    await setup_integration(hass)
    state = hass.states.get("sensor.osterreichische_post_next_delivery")
    assert state.state.startswith("2026-09-22")


async def test_next_delivery_is_unknown_with_nothing_in_flight(hass):
    await setup_integration(hass, summaries=[], details={})
    state = hass.states.get("sensor.osterreichische_post_next_delivery")
    assert state.state == "unknown"


async def test_count_is_zero_for_an_empty_account(hass):
    await setup_integration(hass, summaries=[], details={})
    state = hass.states.get("sensor.osterreichische_post_parcels_in_delivery")
    assert state.state == "0"
    assert state.attributes["parcels"] == []


async def test_last_update_is_a_diagnostic_timestamp(hass):
    await setup_integration(hass)
    state = hass.states.get("sensor.osterreichische_post_last_update")
    assert state.state not in ("unknown", "unavailable")


async def test_all_three_sensors_share_one_device(hass):
    entry = await setup_integration(hass)
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    devices = {e.device_id for e in entities}

    assert len(entities) == 3
    assert len(devices) == 1
    device = dr.async_get(hass).async_get(devices.pop())
    assert device.manufacturer == "Österreichische Post AG"


async def test_unload_removes_the_entities(hass):
    entry = await setup_integration(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.osterreichische_post_parcels_in_delivery")
    assert state is None or state.state == "unavailable"
