"""Diagnostics must never leak the session, the account or a tracking number."""

import json

from custom_components.post_at.diagnostics import async_get_config_entry_diagnostics
from tests.test_sensor import setup_integration


async def test_diagnostics_redact_the_cookie_and_the_email(hass):
    entry = await setup_integration(hass)
    result = await async_get_config_entry_diagnostics(hass, entry)
    blob = json.dumps(result)

    assert "user@example.invalid" not in blob
    assert "x-ms-cpim-sso:t_0" not in blob
    assert result["entry"]["sso_cookie_value"] != "V"


async def test_diagnostics_drop_tracking_numbers_and_labels(hass):
    entry = await setup_integration(hass)
    result = await async_get_config_entry_diagnostics(hass, entry)
    blob = json.dumps(result)

    assert "0001" not in blob
    assert "0002" not in blob
    assert "One" not in blob
    assert "Two" not in blob


async def test_diagnostics_keep_what_a_status_report_needs(hass):
    entry = await setup_integration(hass)
    result = await async_get_config_entry_diagnostics(hass, entry)

    assert [p["status"] for p in result["parcels"]] == ["in_transit", "delivered"]
    assert result["parcels"][0]["trackingStateKey"] == "deliveryHandOver"
    assert result["parcels"][0]["raw_status"] == "DELIVERY_HAND_OVER"


async def test_diagnostics_report_coordinator_health(hass):
    entry = await setup_integration(hass)
    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["last_update_success"] is True
    assert result["parcel_count"] == 2
    assert result["update_interval"] == "0:15:00"


async def test_diagnostics_are_json_serialisable(hass):
    entry = await setup_integration(hass)
    json.dumps(await async_get_config_entry_diagnostics(hass, entry))
