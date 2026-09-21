"""The trackingStateKey vocabulary."""

import pytest

from custom_components.post_at.const import ParcelStatus
from custom_components.post_at.status import map_status, normalize_state_key


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("deliveryHandOver", "DELIVERY_HAND_OVER"),
        ("readyForPickUpStation", "READY_FOR_PICK_UP_STATION"),
        ("DELIVERED", "DELIVERED"),
        ("inDelivery", "IN_DELIVERY"),
    ],
)
def test_normalize_state_key(raw, expected):
    assert normalize_state_key(raw) == expected


def test_normalize_state_key_none():
    assert normalize_state_key(None) is None
    assert normalize_state_key("") is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("pendingInformation", ParcelStatus.REGISTERED),
        ("parcelStamp", ParcelStatus.REGISTERED),
        ("aviso", ParcelStatus.REGISTERED),
        ("allesPost", ParcelStatus.REGISTERED),
        ("deliveryHandOver", ParcelStatus.IN_TRANSIT),
        ("inDistribution", ParcelStatus.IN_TRANSIT),
        ("customsClearance", ParcelStatus.IN_TRANSIT),
        ("deliveryInCustoms", ParcelStatus.IN_TRANSIT),
        ("inDelivery", ParcelStatus.OUT_FOR_DELIVERY),
        ("notified", ParcelStatus.AT_PICKUP_POINT),
        ("readyForPickUp", ParcelStatus.AT_PICKUP_POINT),
        ("readyForPickUpStation", ParcelStatus.AT_PICKUP_POINT),
        ("readyForPickUpPoint", ParcelStatus.AT_PICKUP_POINT),
        ("readyForPickUpBox", ParcelStatus.AT_PICKUP_POINT),
        ("delivered", ParcelStatus.DELIVERED),
        ("deliveryParked", ParcelStatus.DELIVERED),
        ("deliveryInReturn", ParcelStatus.RETURNING),
        ("deliveryDelayed", ParcelStatus.PROBLEM),
        ("deliveryInterupted", ParcelStatus.PROBLEM),
        ("notReachable", ParcelStatus.PROBLEM),
    ],
)
def test_map_status_known(raw, expected):
    assert map_status(raw) == expected


def test_map_status_unknown_key_reports_unknown():
    assert map_status("somethingPostInvented") is ParcelStatus.UNKNOWN


def test_map_status_none_reports_unknown():
    assert map_status(None) is ParcelStatus.UNKNOWN


def test_posts_own_unknown_is_not_mapped():
    """Post's app uses UNKNOWN as its own fallback; seeing it means drift."""
    assert map_status("unknown") is ParcelStatus.UNKNOWN


def test_unmapped_key_warns_once(caplog):
    caplog.clear()
    map_status("brandNewKey")
    map_status("brandNewKey")
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "BRAND_NEW_KEY" in warnings[0].getMessage()
