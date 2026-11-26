"""The parcel contract's checks, run over every normalised sample."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from custom_components.nationex.const import ParcelStatus
from custom_components.nationex.parcels import (
    is_pickup,
    normalize_parcel,
    parse_iso,
    planned_window,
)

from .payloads import active_sample, delivered_sample

CANONICAL_KEYS = [
    "carrier",
    "barcode",
    "sender",
    "receiver",
    "contents",
    "status",
    "raw_status",
    "delivered",
    "delivered_at",
    "planned_from",
    "planned_to",
    "pickup",
    "pickup_point",
    "url",
    "weight",
    "dimensions",
    "history",
    "raw",
]
TORONTO = ZoneInfo("America/Toronto")


def _with_state(state: str) -> dict:
    sample = active_sample()
    sample["ShipmentStatus"] = sample["Parcels"][0]["Status"] = state
    return sample


def _moment_only() -> dict:
    sample = active_sample()
    sample["Parcels"][0]["EstimatedDeliveryDateTimeStart"] = "2099-04-29T13:00:00"
    return sample


def _date_only() -> dict:
    sample = active_sample()
    sample["Parcels"][0]["EstimatedDeliveryDate"] = "2099-04-29"
    return sample


SAMPLES = {
    "delivered": delivered_sample,
    "active": active_sample,
    "returning": lambda: _with_state("ReturnToSender"),
    "returned": lambda: _with_state("ReturnCompleted"),
    "problem": lambda: _with_state("OnHold"),
    "moment_only": _moment_only,
    "date_only": _date_only,
    "bare": dict,
}


def _normalise(raw: dict) -> dict:
    number = str(raw["ShipmentId"]) if "ShipmentId" in raw else "900000099"
    return normalize_parcel({**raw, "trackingNumber": number})


@pytest.fixture(params=SAMPLES)
def parcel(request) -> dict:
    return _normalise(SAMPLES[request.param]())


def test_keys_and_order(parcel):
    assert list(parcel) == CANONICAL_KEYS


def test_delivered_follows_status(parcel):
    assert parcel["delivered"] is (parcel["status"] is ParcelStatus.DELIVERED)


def test_a_completed_return_is_not_delivered():
    parcel = _normalise(_with_state("ReturnCompleted"))
    assert parcel["status"] is ParcelStatus.RETURNING
    assert parcel["delivered"] is False


def test_delivered_at_only_when_delivered(parcel):
    if parcel["delivered"]:
        assert parcel["delivered_at"] is not None
    else:
        assert parcel["delivered_at"] is None


def test_planned_window_is_ordered_and_anchored(parcel):
    if parcel["planned_to"] is not None:
        assert parcel["planned_from"] is not None
        assert parse_iso(parcel["planned_to"]) > parse_iso(parcel["planned_from"])


def test_planned_is_empty_when_the_parcel_is_done_or_waiting(parcel):
    if parcel["status"] in (
        ParcelStatus.DELIVERED,
        ParcelStatus.AT_PICKUP_POINT,
        ParcelStatus.RETURNING,
    ):
        assert parcel["planned_from"] is None
        assert parcel["planned_to"] is None


def test_a_problem_parcel_keeps_the_window_the_carrier_reports():
    parcel = _normalise(_with_state("OnHold"))
    assert parcel["status"] is ParcelStatus.PROBLEM
    assert parcel["planned_from"] is not None


def test_pickup_is_a_bool_and_the_point_needs_it(parcel):
    assert isinstance(parcel["pickup"], bool)
    assert parcel["pickup"] is False
    assert parcel["pickup_point"] is None


def test_pickup_stays_true_after_collection():
    events = [ParcelStatus.AT_PICKUP_POINT, ParcelStatus.DELIVERED]
    assert is_pickup(None, ParcelStatus.DELIVERED, events) is True
    assert is_pickup(None, ParcelStatus.DELIVERED, [ParcelStatus.IN_TRANSIT]) is False


def test_a_moment_ends_at_the_end_of_that_day():
    parcel = _normalise(_moment_only())
    start = datetime.fromisoformat(parcel["planned_from"])
    end = datetime.fromisoformat(parcel["planned_to"])
    assert (start.hour, start.minute) == (13, 0)
    assert (end.hour, end.minute, end.second, end.microsecond) == (23, 59, 59, 0)
    assert end.date() == start.date()
    assert end.utcoffset() == start.utcoffset()


def test_a_date_covers_the_whole_day():
    parcel = _normalise(_date_only())
    start = datetime.fromisoformat(parcel["planned_from"])
    end = datetime.fromisoformat(parcel["planned_to"])
    assert (start.hour, start.minute, start.second) == (0, 0, 0)
    assert (end.hour, end.minute, end.second, end.microsecond) == (23, 59, 59, 0)
    assert start.date() == end.date()


def test_a_past_window_is_published_as_sent():
    sample = active_sample()
    sample["Parcels"][0]["EstimatedDeliveryDate"] = "2000-01-01"
    assert _normalise(sample)["planned_from"] == "2000-01-01T00:00:00-05:00"


def test_a_utc_moment_ends_on_the_toronto_day():
    start, end = planned_window("2099-07-01T02:00:00Z", None, zone=TORONTO)
    assert start == "2099-07-01T02:00:00Z"
    assert end == "2099-06-30T23:59:59-04:00"
