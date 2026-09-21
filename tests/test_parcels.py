"""Merging a list summary and a public detail into a Parcel."""

import json
from copy import deepcopy
from pathlib import Path

from custom_components.post_at.const import ParcelStatus
from custom_components.post_at.parcels import normalize_parcel

FIXTURES = Path(__file__).parent / "fixtures"
DETAIL = json.loads((FIXTURES / "detail_response.json").read_text())["data"][
    "einzelsendung"
]
SUMMARY = {
    "sendungsnummer": "0000000000000000000001",
    "bezeichnung": "Test Parcel One",
    "status": "AN",
    "isRecipient": True,
}


def test_status_comes_from_tracking_state_key():
    parcel = normalize_parcel(SUMMARY, DETAIL)
    assert parcel.status is ParcelStatus.IN_TRANSIT
    assert parcel.raw_status == "DELIVERY_HAND_OVER"


def test_tracking_state_key_is_kept_verbatim():
    """raw_status is upper-snaked; this one is exactly what Post sent."""
    parcel = normalize_parcel(SUMMARY, DETAIL)
    assert parcel.tracking_state_key == "deliveryHandOver"
    assert parcel.as_attribute()["trackingStateKey"] == "deliveryHandOver"


def test_tracking_state_key_is_none_without_detail():
    parcel = normalize_parcel(SUMMARY, None)
    assert parcel.tracking_state_key is None
    assert parcel.as_attribute()["trackingStateKey"] is None


def test_an_unmapped_key_is_still_reported_verbatim():
    """An unknown status is only actionable if the raw key survives."""
    detail = deepcopy(DETAIL)
    detail["sendungsEvents"][0]["trackingStateKey"] = "somethingPostInvented"
    parcel = normalize_parcel(SUMMARY, detail)
    assert parcel.status is ParcelStatus.UNKNOWN
    assert parcel.tracking_state_key == "somethingPostInvented"


def test_coarse_an_status_is_ignored():
    """The summary says AN; deliveryHandOver is in_transit, not registered."""
    assert normalize_parcel(SUMMARY, DETAIL).status is not ParcelStatus.REGISTERED


def test_label_and_tracking_code_come_from_the_summary():
    parcel = normalize_parcel(SUMMARY, DETAIL)
    assert parcel.tracking_code == "0000000000000000000001"
    assert parcel.label == "Test Parcel One"


def test_human_readable_fields_are_passed_through():
    parcel = normalize_parcel(SUMMARY, DETAIL)
    assert parcel.status_text == "Item accepted"
    assert parcel.eta_text == "Voraussichtlich morgen"


def test_detail_fields_are_carried():
    parcel = normalize_parcel(SUMMARY, DETAIL)
    assert parcel.sender == "Example Sender"
    assert parcel.weight == 1.25
    assert parcel.dimensions == {"height": 10.0, "length": 30.0, "width": 20.0}
    assert parcel.eta_start is not None
    assert parcel.eta_start.tzinfo is not None


def test_missing_detail_degrades_without_losing_identity():
    parcel = normalize_parcel(SUMMARY, None)
    assert parcel.status is ParcelStatus.UNKNOWN
    assert parcel.tracking_code == "0000000000000000000001"
    assert parcel.label == "Test Parcel One"
    assert parcel.sender is None
    assert parcel.url.endswith("0000000000000000000001")


def test_missing_detail_is_still_active():
    """An unscanned parcel is on its way, not finished."""
    assert normalize_parcel(SUMMARY, None).is_active is True


def test_delivered_parcel_is_not_active():
    detail = deepcopy(DETAIL)
    detail["sendungsEvents"][0]["trackingStateKey"] = "delivered"
    parcel = normalize_parcel(SUMMARY, detail)
    assert parcel.status is ParcelStatus.DELIVERED
    assert parcel.is_active is False


def test_returning_parcel_is_not_active():
    detail = deepcopy(DETAIL)
    detail["sendungsEvents"][0]["trackingStateKey"] = "deliveryInReturn"
    assert normalize_parcel(SUMMARY, detail).is_active is False


def test_in_transit_parcel_is_active():
    assert normalize_parcel(SUMMARY, DETAIL).is_active is True


def test_newest_event_wins():
    detail = deepcopy(DETAIL)
    detail["sendungsEvents"] = [
        {
            "trackingStateKey": "deliveryHandOver",
            "textEn": "Item accepted",
            "timestamp": "2026-09-21T08:35:23.000+00:00",
            "eventPlaceName": "PLZ 9010",
        },
        {
            "trackingStateKey": "inDelivery",
            "textEn": "Out for delivery",
            "timestamp": "2026-09-22T06:00:00.000+00:00",
            "eventPlaceName": "PLZ 9020",
        },
    ]
    parcel = normalize_parcel(SUMMARY, detail)
    assert parcel.status is ParcelStatus.OUT_FOR_DELIVERY
    assert parcel.last_event["place"] == "PLZ 9020"


def test_no_events_reports_unknown():
    detail = deepcopy(DETAIL)
    detail["sendungsEvents"] = []
    parcel = normalize_parcel(SUMMARY, detail)
    assert parcel.status is ParcelStatus.UNKNOWN
    assert parcel.last_event is None


def test_german_text_is_used_when_english_is_absent():
    detail = deepcopy(DETAIL)
    detail["sendungsEvents"][0]["textEn"] = None
    assert normalize_parcel(SUMMARY, detail).status_text == (
        "Sendungsannahme durchgeführt"
    )


def test_unparseable_numbers_do_not_raise():
    detail = deepcopy(DETAIL)
    detail["weight"] = "not a number"
    detail["dimensions"] = {"height": None, "length": None, "width": None}
    parcel = normalize_parcel(SUMMARY, detail)
    assert parcel.weight is None
    assert parcel.dimensions is None


def test_unparseable_timestamps_do_not_raise():
    detail = deepcopy(DETAIL)
    detail["estimatedDelivery"]["startDate"] = "tomorrow-ish"
    assert normalize_parcel(SUMMARY, detail).eta_start is None


def test_attributes_never_expose_an_address():
    attribute = normalize_parcel(SUMMARY, DETAIL).as_attribute()
    serialised = json.dumps(attribute, default=str).lower()
    for forbidden in ("consignee", "recipientaddress", "street"):
        assert forbidden not in serialised


def test_attributes_are_json_serialisable():
    """State attributes must survive the recorder and the websocket API."""
    json.dumps(normalize_parcel(SUMMARY, DETAIL).as_attribute())


def test_url_points_at_the_tracking_page():
    parcel = normalize_parcel(SUMMARY, DETAIL)
    assert parcel.tracking_code in parcel.url
