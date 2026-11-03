"""Tests for the pure parcel-mapping helpers."""

from datetime import UTC, datetime, timedelta
import logging

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nationex.const import (
    CAPABILITIES,
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    DOMAIN,
    KNOWN_CAPABILITIES,
    PENDING_CAPABILITIES,
    ParcelStatus,
)
from custom_components.nationex.parcels import (
    apply_delivered_filter,
    format_dimensions,
    map_state,
    normalize_parcel,
    parse_iso,
    sort_parcels_by_ts,
    tracking_url,
)

from .payloads import (
    active_sample,
    delivered_sample,
    parcel,
    scan,
    shipment,
    status_row,
)

TORONTO_EDT = "-04:00"


def _n(raw: dict, code: str | None = None, **kwargs) -> dict:
    """Normalise, as the coordinator does: the entered number rides along."""
    return normalize_parcel(
        {**raw, "trackingNumber": code or str(raw["ShipmentId"])}, **kwargs
    )


def _shipment_with(history, *, status="Transit", parcel_status=None, **parcel_kwargs):
    return shipment(
        900000010,
        [
            parcel(
                90000001001,
                status=parcel_status or status,
                history=history,
                **parcel_kwargs,
            )
        ],
        status=status,
    )


# ---------------------------------------------------------------------------
# state map
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("Creation", ParcelStatus.REGISTERED),
        ("OutForPickup", ParcelStatus.REGISTERED),
        ("Pickup", ParcelStatus.IN_TRANSIT),
        ("PartiallyPickedUp", ParcelStatus.IN_TRANSIT),
        ("Transit", ParcelStatus.IN_TRANSIT),
        ("PartiallyInTransit", ParcelStatus.IN_TRANSIT),
        ("PartiallyDelivered", ParcelStatus.IN_TRANSIT),
        ("OutForDelivery", ParcelStatus.OUT_FOR_DELIVERY),
        ("PartiallyOutForDelivery", ParcelStatus.OUT_FOR_DELIVERY),
        ("Delivered", ParcelStatus.DELIVERED),
        ("ReturnToSender", ParcelStatus.RETURNING),
        ("ReturnCompleted", ParcelStatus.RETURNING),
        ("Attention", ParcelStatus.PROBLEM),
        ("RefusedDelivery", ParcelStatus.PROBLEM),
        ("PickupAttemptFailed", ParcelStatus.PROBLEM),
        ("OnHold", ParcelStatus.PROBLEM),
        ("Cancelled", ParcelStatus.PROBLEM),
        ("500", ParcelStatus.PROBLEM),
        ("501", ParcelStatus.PROBLEM),
        (500, ParcelStatus.PROBLEM),
        (501, ParcelStatus.PROBLEM),
    ],
)
def test_state_map(state, expected):
    assert map_state(state) is expected


def test_missing_state_is_none_without_warning(caplog):
    with caplog.at_level(logging.WARNING):
        assert map_state(None) is None
    assert caplog.records == []


def test_return_completed_is_returning_not_delivered():
    raw = _shipment_with(
        [scan(900, "2026-10-15T09:00:00", "Parcel out for delivery")],
        status="ReturnCompleted",
    )
    result = _n(raw)
    assert result["status"] is ParcelStatus.RETURNING
    assert result["delivered"] is False
    assert result["delivered_at"] is None


# ---------------------------------------------------------------------------
# scan map and history
# ---------------------------------------------------------------------------

SCAN_CASES = [
    (538, ParcelStatus.REGISTERED),
    (910, ParcelStatus.REGISTERED),
    (52, ParcelStatus.IN_TRANSIT),
    (252, ParcelStatus.IN_TRANSIT),
    (901, ParcelStatus.IN_TRANSIT),
    (903, ParcelStatus.IN_TRANSIT),
    (904, ParcelStatus.IN_TRANSIT),
    (90, ParcelStatus.IN_TRANSIT),
    (900, ParcelStatus.OUT_FOR_DELIVERY),
    (40, ParcelStatus.PROBLEM),
    (119, ParcelStatus.DELIVERED),
]


@pytest.mark.parametrize(("code", "expected"), SCAN_CASES)
def test_scan_map(code, expected):
    raw = _shipment_with([scan(code, "2026-10-15T09:00:00", "x")], status="Pickup")
    history = _n(raw, include_history=True)["history"]
    assert [row["status"] for row in history] == [expected]


def test_history_is_oldest_first_deduplicated_and_stripped():
    result = _n(delivered_sample(), include_history=True)
    history = result["history"]
    stamps = [row["timestamp"] for row in history]
    assert stamps == sorted(stamps)
    assert history[0] == {
        "timestamp": f"2026-10-10T12:57:06{TORONTO_EDT}",
        "status": ParcelStatus.REGISTERED,
        "raw_status": "Shipment created",
    }
    failed = next(row for row in history if row["raw_status"].startswith("Unable"))
    assert failed["raw_status"] == "Unable to complete the delivery"
    assert failed["status"] is ParcelStatus.PROBLEM


def test_duplicate_scans_collapse():
    rows = [
        scan(730, "2026-10-15T16:34:52", "Picture taken"),
        scan(730, "2026-10-15T16:34:52", " Picture taken "),
        scan(900, "2026-10-15T15:00:00", "Parcel out for delivery"),
    ]
    history = _n(_shipment_with(rows), include_history=True)["history"]
    assert len(history) == 2


def test_quiet_scans_keep_previous_status():
    rows = [
        scan(730, "2026-10-15T10:02:00", "Picture taken"),
        scan(720, "2026-10-15T10:01:00", "Delivery notifications sent"),
        scan(900, "2026-10-15T10:00:00", "Parcel out for delivery"),
    ]
    history = _n(_shipment_with(rows), include_history=True)["history"]
    assert [row["status"] for row in history] == [ParcelStatus.OUT_FOR_DELIVERY] * 3


def test_leading_quiet_scan_is_unknown():
    rows = [scan(730, "2026-10-15T10:00:00", "Picture taken")]
    history = _n(_shipment_with(rows), include_history=True)["history"]
    assert history[0]["status"] is ParcelStatus.UNKNOWN


def test_same_second_scans_keep_their_order():
    rows = [
        scan(900, "2026-10-15T10:00:00", "Parcel out for delivery"),
        scan(40, "2026-10-15T10:00:00", "Unable to complete the delivery"),
    ]
    assert _n(_shipment_with(rows))["status"] is ParcelStatus.IN_TRANSIT


@pytest.mark.parametrize("state", [500, "500"])
def test_numeric_state_without_label_keeps_it_as_raw_status(state):
    raw = _shipment_with([])
    raw["ShipmentStatus"] = state
    raw["ShipmentStatusEn"] = None
    result = _n(raw)
    assert result["status"] is ParcelStatus.PROBLEM
    assert result["raw_status"] == "500"


def test_numeric_parcel_state_maps_on_a_parcel_number():
    raw = delivered_sample()
    raw["Parcels"][0]["Status"] = 501
    raw["Parcels"][0]["StatusDescriptionEn"] = None
    result = _n(raw, code=str(raw["Parcels"][0]["ParcelId"]))
    assert result["status"] is ParcelStatus.PROBLEM
    assert result["raw_status"] == "501"


def _partly_done(state):
    raw = _two_parcels()
    raw["ShipmentStatus"] = state
    return raw


@pytest.mark.parametrize("state", ["PartlyDone", None])
def test_one_delivery_scan_does_not_close_an_unmapped_shipment(state):
    result = _n(_partly_done(state))
    assert result["status"] is not ParcelStatus.DELIVERED
    assert result["delivered"] is False


def test_unmapped_shipment_is_delivered_once_every_parcel_is():
    raw = _partly_done("PartlyDone")
    raw["Parcels"][1]["History"].append(
        scan(119, "2026-10-16T10:00:00", "Delivery completed")
    )
    assert _n(raw)["status"] is ParcelStatus.DELIVERED


def test_delivered_parcel_is_no_forecast_for_the_rest():
    raw = _two_parcels()
    raw["Parcels"][1]["EstimatedDeliveryDate"] = None
    raw["Parcels"][0]["EstimatedDeliveryDate"] = "2026-10-15"
    result = _n(raw)
    assert result["planned_from"] is None
    assert result["planned_to"] is None


@pytest.mark.parametrize(
    "key",
    [
        "EstimatedDeliveryDateTimeStart",
        "EstimatedDeliveryDateTimeExact",
        "EstimatedPercentageBeforeDelivery",
        "EstimatedDeliveryWithinFewHours",
    ],
)
def test_parcel_field_only_seen_empty_warns_once_without_value(caplog, key):
    raw = _shipment_with([])
    raw["Parcels"][0][key] = "2026-10-15T10:00:00"
    with caplog.at_level(logging.WARNING):
        _n(raw)
        _n(raw)
    assert caplog.text.count(f"field {key}") == 1
    assert "2026-10-15T10:00:00" not in caplog.text


@pytest.mark.parametrize(
    "key",
    ["CustomerId", "BillingAccount", "InsertedDate", "Note", "Accessory", "Photos"],
)
def test_shipment_field_only_seen_empty_warns_once_without_value(caplog, key):
    raw = _shipment_with([])
    raw[key] = "secret-value"
    with caplog.at_level(logging.WARNING):
        _n(raw)
        _n(raw)
    assert caplog.text.count(f"field {key}") == 1
    assert "secret-value" not in caplog.text


def test_state_never_seen_live_warns_once(caplog):
    with caplog.at_level(logging.WARNING):
        assert map_state("OnHold") is ParcelStatus.PROBLEM
        assert map_state("OnHold") is ParcelStatus.PROBLEM
        map_state(500)
        map_state("Transit")
    assert caplog.text.count("status OnHold") == 1
    assert caplog.text.count("status 500") == 1
    assert "Transit" not in caplog.text


def test_forecast_day_in_flight_warns_once_without_value(caplog):
    raw = _shipment_with([], eta_date="2026-10-16")
    with caplog.at_level(logging.WARNING):
        assert _n(raw)["planned_from"] is not None
        _n(raw)
    assert caplog.text.count("forecast delivery day") == 1
    assert "2026-10-16" not in caplog.text


def test_history_caps_to_last_twenty():
    rows = [
        scan(903, f"2026-10-{day:02d}T08:00:00", "Parcel scanned")
        for day in range(1, 29)
    ]
    history = _n(_shipment_with(rows), include_history=True)["history"]
    assert len(history) == 20
    assert history[-1]["timestamp"].startswith("2026-10-28")


def test_history_is_opt_in():
    assert _n(delivered_sample())["history"] is None
    assert _n(delivered_sample(), include_history=True)["history"]


def test_unparseable_scan_clock_is_dropped_with_one_warning(caplog):
    rows = [
        scan(900, "not a time", "Parcel out for delivery"),
        scan(903, "2026-10-15T08:00:00", "Parcel scanned"),
    ]
    with caplog.at_level(logging.WARNING):
        history = _n(_shipment_with(rows), include_history=True)["history"]
        _n(_shipment_with(rows))
    assert len(history) == 1
    assert caplog.text.count("Unparseable Nationex timestamp") == 1


def test_clock_is_localised_to_toronto_across_dst():
    rows = [
        scan(903, "2026-01-15T08:00:00", "Parcel scanned"),
        scan(903, "2026-07-15T08:00:00", "Parcel scanned"),
    ]
    history = _n(_shipment_with(rows), include_history=True)["history"]
    assert history[0]["timestamp"] == "2026-01-15T08:00:00-05:00"
    assert history[1]["timestamp"] == "2026-07-15T08:00:00-04:00"


def test_offset_bearing_clock_is_kept():
    rows = [scan(903, "2026-07-15T08:00:00+00:00", "Parcel scanned")]
    history = _n(_shipment_with(rows), include_history=True)["history"]
    assert history[0]["timestamp"] == "2026-07-15T08:00:00+00:00"


# ---------------------------------------------------------------------------
# unmapped values: fallback, unknown, one warning
# ---------------------------------------------------------------------------


def test_unmapped_state_falls_back_to_newest_mappable_scan(caplog):
    rows = [
        scan(730, "2026-10-15T10:05:00", "Picture taken"),
        scan(9999, "2026-10-15T10:04:00", "Brand new thing"),
        scan(900, "2026-10-15T10:00:00", "Parcel out for delivery"),
    ]
    with caplog.at_level(logging.WARNING):
        result = _n(_shipment_with(rows, status="Teleported"))
        _n(_shipment_with(rows, status="Teleported"))
    assert result["status"] is ParcelStatus.OUT_FOR_DELIVERY
    assert result["raw_status"] == "Parcel out for delivery"
    assert caplog.text.count("status=Teleported") == 1
    assert caplog.text.count("code=9999") == 1
    assert "Brand new thing" not in caplog.text
    assert "unrecognised_status.yml" in caplog.text


def test_unmapped_state_without_usable_scan_is_unknown(caplog):
    rows = [scan(9999, "2026-10-15T10:04:00", "Brand new thing")]
    with caplog.at_level(logging.WARNING):
        result = _n(_shipment_with(rows, status="Teleported"), include_history=True)
    assert result["status"] is ParcelStatus.UNKNOWN
    assert result["history"][0]["status"] is ParcelStatus.UNKNOWN


def test_missing_state_without_scans_warns_once(caplog):
    raw = _shipment_with([])
    raw["ShipmentStatus"] = None
    with caplog.at_level(logging.WARNING):
        assert _n(raw)["status"] is ParcelStatus.UNKNOWN
        _n(raw)
    assert caplog.text.count("reported no status") == 1


def test_non_numeric_scan_code_is_unknown(caplog):
    rows = [{**scan(1, "2026-10-15T10:00:00", "Odd"), "ExceptionId": "X-1"}]
    with caplog.at_level(logging.WARNING):
        history = _n(_shipment_with(rows), include_history=True)["history"]
    assert history[0]["status"] is ParcelStatus.UNKNOWN
    assert "code=X-1" in caplog.text


def test_missing_scan_code_is_unknown():
    rows = [{**scan(1, "2026-10-15T10:00:00", "Odd"), "ExceptionId": None}]
    assert (
        _n(_shipment_with(rows), include_history=True)["history"][0]["status"]
        is ParcelStatus.UNKNOWN
    )


def test_unknown_keys_and_shipment_type_warn_once_without_values(caplog):
    raw = _shipment_with([scan(900, "2026-10-15T10:00:00", "x")])
    raw["NewTop"] = "secret-value"
    raw["Parcels"][0]["NewParcel"] = "secret-value"
    raw["Parcels"][0]["History"][0]["NewScan"] = "secret-value"
    raw["Parcels"][0]["SomeTooltipEn"] = "ignored"
    raw["ExtraFr"] = "ignored"
    raw["ShipmentType"] = "Freight"
    with caplog.at_level(logging.WARNING):
        _n(raw)
        _n(raw)
    for key in ("NewTop", "NewParcel", "NewScan"):
        assert caplog.text.count(f"field {key}") == 1
    assert "Tooltip" not in caplog.text
    assert "ExtraFr" not in caplog.text
    assert caplog.text.count("shipment type Freight") == 1
    assert "secret-value" not in caplog.text


def test_live_keys_and_delivery_type_raise_no_warnings(caplog):
    raw = delivered_sample()
    raw.update(InsertedDate=None, BillingAccount=None, ShipmentType="Delivery")
    raw["Parcels"][0].update(NCV=False, EstimatedDeliveryDateRangeEn="2026-10-15")
    with caplog.at_level(logging.WARNING):
        _n(raw)
    assert caplog.records == []


def test_known_payload_raises_no_warnings(caplog):
    with caplog.at_level(logging.WARNING):
        _n(delivered_sample(), include_history=True)
        _n(active_sample())
    assert [
        record.getMessage()
        for record in caplog.records
        if "forecast" not in record.getMessage()
    ] == []


# ---------------------------------------------------------------------------
# sequence rules
# ---------------------------------------------------------------------------


def test_rule_a_failed_delivery_stands_over_transit_state():
    rows = [
        scan(40, "2026-10-14T18:21:51", " Unable to complete the delivery"),
        scan(900, "2026-10-14T13:12:33", "Parcel out for delivery"),
    ]
    result = _n(_shipment_with(rows, status="Transit"))
    assert result["status"] is ParcelStatus.PROBLEM
    assert result["raw_status"] == "Unable to complete the delivery"


def test_rule_a_applies_to_out_for_delivery_state_and_skips_quiet_scans():
    rows = [
        scan(730, "2026-10-14T18:30:00", "Picture taken"),
        scan(40, "2026-10-14T18:21:51", " Unable to complete the delivery"),
    ]
    assert (
        _n(_shipment_with(rows, status="OutForDelivery"))["status"]
        is ParcelStatus.PROBLEM
    )


def test_rule_a_cleared_by_a_later_out_for_delivery_scan():
    rows = [
        scan(900, "2026-10-15T11:36:22", "Parcel out for delivery"),
        scan(40, "2026-10-14T18:21:51", " Unable to complete the delivery"),
    ]
    result = _n(_shipment_with(rows, status="Transit"))
    assert result["status"] is ParcelStatus.IN_TRANSIT
    rows[0] = scan(900, "2026-10-15T11:36:22", "Parcel out for delivery")
    assert (
        _n(_shipment_with(rows, status="OutForDelivery"))["status"]
        is ParcelStatus.OUT_FOR_DELIVERY
    )


def test_rule_a_does_not_touch_other_states():
    rows = [scan(40, "2026-10-14T18:21:51", " Unable to complete the delivery")]
    assert _n(_shipment_with(rows, status="OnHold"))["status"] is ParcelStatus.PROBLEM
    assert (
        _n(_shipment_with(rows, status="ReturnToSender"))["status"]
        is ParcelStatus.RETURNING
    )


def _two_parcels():
    delivered = parcel(
        90000002001,
        status="Delivered",
        history=[
            scan(119, "2026-10-15T16:00:00", "Delivery completed"),
            scan(900, "2026-10-15T09:00:00", "Parcel out for delivery"),
        ],
        weight=3,
    )
    waiting = parcel(
        90000002002,
        status="Transit",
        history=[scan(903, "2026-10-14T01:00:00", "Parcel scanned")],
        weight=5,
        eta_date="2026-10-16",
    )
    return shipment(900000020, [delivered, waiting], status="PartiallyDelivered")


def test_rule_b_partial_delivery_is_not_a_delivery():
    result = _n(_two_parcels())
    assert result["status"] is ParcelStatus.IN_TRANSIT
    assert result["delivered"] is False
    assert result["delivered_at"] is None


def test_parcel_number_uses_that_parcels_own_status():
    done = _n(_two_parcels(), code="90000002001")
    assert done["status"] is ParcelStatus.DELIVERED
    assert done["delivered_at"] == f"2026-10-15T16:00:00{TORONTO_EDT}"
    assert done["weight"] == pytest.approx(1.36)
    assert done["dimensions"]["text"] == "30 x 13 x 53 cm"
    waiting = _n(_two_parcels(), code="90000002002")
    assert waiting["status"] is ParcelStatus.IN_TRANSIT
    assert waiting["barcode"] == "90000002002"
    assert waiting["raw_status"] == "Transit"


def test_shipment_scope_merges_parcels_and_hides_dimensions():
    result = _n(_two_parcels(), include_history=True)
    assert result["dimensions"] is None
    assert result["weight"] == pytest.approx(3.63)
    assert len(result["history"]) == 3
    assert result["planned_from"] == f"2026-10-16T00:00:00{TORONTO_EDT}"


def test_unknown_parcel_number_in_reply_falls_back_to_shipment_scope():
    result = _n(_two_parcels(), code="90000002099")
    assert result["status"] is ParcelStatus.IN_TRANSIT


# ---------------------------------------------------------------------------
# normalize_parcel — the canonical contract
# ---------------------------------------------------------------------------

CANONICAL_KEYS = [
    "carrier",
    "barcode",
    "sender",
    "receiver",
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


def test_normalize_publishes_exactly_the_canonical_keys():
    """The aggregator and cross-carrier dashboards depend on this key set."""
    assert list(_n(delivered_sample())) == CANONICAL_KEYS
    assert list(normalize_parcel({"trackingNumber": "900000001"})) == CANONICAL_KEYS


def test_capabilities_are_known_values():
    assert CAPABILITIES <= KNOWN_CAPABILITIES
    assert PENDING_CAPABILITIES <= KNOWN_CAPABILITIES


def test_a_capability_is_never_both_populated_and_pending():
    assert not CAPABILITIES & PENDING_CAPABILITIES


def test_capabilities_match_what_normalize_parcel_actually_returns():
    delivered = _n(delivered_sample())
    active = _n(active_sample())
    with_history = _n(delivered_sample(), include_history=True)

    if "weight" in CAPABILITIES:
        assert delivered["weight"] is not None
    if "dimensions" in CAPABILITIES:
        assert delivered["dimensions"] is not None
    if "url" in CAPABILITIES:
        assert delivered["url"] is not None
    if "history" in CAPABILITIES:
        assert with_history["history"] is not None
    # Pending: the window is built from the forecast day, never yet seen live.
    assert "delivery_window" in PENDING_CAPABILITIES
    assert active["planned_from"] is not None
    assert delivered["pickup_point"] is None


def test_normalize_delivered_parcel_with_failed_first_attempt():
    result = _n(delivered_sample())
    assert result["carrier"] == "Nationex"
    assert result["barcode"] == "900000001"
    assert result["sender"] is None
    assert result["receiver"] is None
    assert result["status"] is ParcelStatus.DELIVERED
    assert result["raw_status"] == "Delivered"
    assert result["delivered"] is True
    assert result["delivered_at"] == f"2026-10-15T16:34:54{TORONTO_EDT}"
    assert result["planned_from"] is None
    assert result["planned_to"] is None
    assert result["pickup"] is False
    assert result["pickup_point"] is None
    assert result["url"] == "https://nationex.com/en/tracking/900000001"
    assert result["weight"] == 1.81
    assert result["dimensions"] == {
        "length": 30.5,
        "width": 12.7,
        "height": 53.3,
        "text": "30 x 13 x 53 cm",
    }


def test_delivered_at_falls_back_to_state_history_row():
    raw = delivered_sample()
    raw["Parcels"][0]["History"] = []
    assert _n(raw)["delivered_at"] == f"2026-10-15T16:34:54{TORONTO_EDT}"
    raw["StatusHistories"] = None
    assert _n(raw)["delivered_at"] is None


def test_delivered_state_history_ignores_other_rows_and_bad_clocks():
    raw = delivered_sample()
    raw["Parcels"][0]["History"] = []
    raw["StatusHistories"] = [
        "junk",
        status_row("Transit", "2026-10-14T01:00:00"),
        status_row("Delivered", "garbage"),
    ]
    assert _n(raw)["delivered_at"] is None


def test_eta_is_a_whole_day_while_in_flight():
    result = _n(active_sample())
    assert result["status"] is ParcelStatus.OUT_FOR_DELIVERY
    assert result["planned_from"] == f"2026-04-29T00:00:00{TORONTO_EDT}"
    assert result["planned_to"] == f"2026-04-29T23:59:59{TORONTO_EDT}"


def test_eta_dropped_once_delivered():
    raw = delivered_sample()
    assert raw["Parcels"][0]["EstimatedDeliveryDate"] == "2026-10-15"
    result = _n(raw)
    assert (result["planned_from"], result["planned_to"]) == (None, None)


def test_eta_dropped_when_a_later_day_scan_exists():
    raw = active_sample()
    raw["Parcels"][0]["History"].insert(
        0, scan(903, "2026-04-30T01:00:00", "Parcel scanned")
    )
    result = _n(raw)
    assert result["planned_from"] is None


def test_eta_kept_when_scan_is_same_day():
    assert _n(active_sample())["planned_from"] is not None


def test_eta_prefers_explicit_window():
    raw = active_sample()
    raw["Parcels"][0]["EstimatedDeliveryDateTimeStart"] = "2026-04-29T13:00:00"
    raw["Parcels"][0]["EstimatedDeliveryDateTimeEnd"] = "2026-04-29T15:00:00"
    result = _n(raw)
    assert result["planned_from"] == f"2026-04-29T13:00:00{TORONTO_EDT}"
    assert result["planned_to"] == f"2026-04-29T15:00:00{TORONTO_EDT}"


def test_eta_with_start_only_has_no_end():
    raw = active_sample()
    raw["Parcels"][0]["EstimatedDeliveryDateTimeStart"] = "2026-04-29T13:00:00"
    result = _n(raw)
    assert result["planned_from"] == f"2026-04-29T13:00:00{TORONTO_EDT}"
    assert result["planned_to"] is None


def test_eta_absent_or_unparseable_is_none(caplog):
    raw = active_sample()
    raw["Parcels"][0]["EstimatedDeliveryDate"] = None
    assert _n(raw)["planned_from"] is None
    raw["Parcels"][0]["EstimatedDeliveryDate"] = "soon"
    with caplog.at_level(logging.WARNING):
        assert _n(raw)["planned_from"] is None
    assert "Unparseable Nationex timestamp" in caplog.text


def test_eta_takes_the_latest_across_parcels():
    raw = _two_parcels()
    raw["Parcels"][0]["Status"] = "Transit"
    raw["ShipmentStatus"] = "Transit"
    raw["Parcels"][0]["EstimatedDeliveryDate"] = "2026-10-12"
    assert _n(raw)["planned_from"] == f"2026-10-16T00:00:00{TORONTO_EDT}"
    raw["Parcels"][0]["EstimatedDeliveryDate"] = "2026-10-20"
    assert _n(raw)["planned_from"] == f"2026-10-20T00:00:00{TORONTO_EDT}"


def test_eta_only_while_registered_in_transit_or_out_for_delivery():
    for state in ("Creation", "Transit", "OutForDelivery"):
        raw = active_sample()
        raw["ShipmentStatus"] = raw["Parcels"][0]["Status"] = state
        assert _n(raw)["planned_from"] is not None, state
    for state in ("OnHold", "ReturnToSender"):
        raw = active_sample()
        raw["ShipmentStatus"] = raw["Parcels"][0]["Status"] = state
        assert _n(raw)["planned_from"] is None, state


@pytest.mark.parametrize(
    ("pounds", "kilograms"),
    [(10, 4.54), (0, None), (None, None), (True, None), (0.0001, None)],
)
def test_weight_conversion_and_missing(pounds, kilograms):
    raw = delivered_sample()
    raw["TotalWeight"] = raw["Parcels"][0]["Weight"] = pounds
    assert _n(raw)["weight"] == kilograms
    assert _n(raw, code="90000000101")["weight"] == kilograms


def test_cubing_mismatch_drops_dimensions_with_one_warning(caplog):
    raw = delivered_sample()
    raw["Parcels"][0]["Dimensions"]["Cubing"] = 5.0
    with caplog.at_level(logging.WARNING):
        assert _n(raw)["dimensions"] is None
        assert _n(raw)["dimensions"] is None
    assert caplog.text.count("do not match the reported volume") == 1


def test_dimensions_without_cubing_are_kept():
    raw = delivered_sample()
    del raw["Parcels"][0]["Dimensions"]["Cubing"]
    assert _n(raw)["dimensions"]["text"] == "30 x 13 x 53 cm"


@pytest.mark.parametrize("value", [None, "big", {"Length": 1, "Width": 2}])
def test_incomplete_dimensions_are_none(value):
    raw = delivered_sample()
    raw["Parcels"][0]["Dimensions"] = value
    assert _n(raw)["dimensions"] is None


def test_placeholder_for_unknown_number():
    result = normalize_parcel({"trackingNumber": "900000007"})
    assert result["status"] is ParcelStatus.UNKNOWN
    assert result["delivered"] is False
    assert result["raw_status"] is None
    assert result["history"] is None
    assert result["url"].endswith("/900000007")
    assert (
        normalize_parcel({"trackingNumber": "900000007"}, include_history=True)[
            "history"
        ]
        == []
    )


def test_normalize_keeps_full_raw_payload():
    raw = {**delivered_sample(), "trackingNumber": "900000001"}
    assert normalize_parcel(raw)["raw"] is raw


def test_malformed_parcels_and_scans_are_skipped():
    raw = delivered_sample()
    raw["Parcels"] = ["junk", raw["Parcels"][0]]
    raw["Parcels"][1]["History"] = ["junk", *raw["Parcels"][1]["History"]]
    assert _n(raw)["status"] is ParcelStatus.DELIVERED
    raw["Parcels"][1]["History"] = None
    assert _n(raw)["status"] is ParcelStatus.DELIVERED


def test_tracking_url():
    assert tracking_url(None) is None


def test_unmeasured_zero_dimensions_are_none(caplog):
    raw = delivered_sample()
    raw["Parcels"][0]["Dimensions"] = {
        "Length": 0,
        "Width": 0,
        "Height": 0,
        "Cubing": 0,
    }
    with caplog.at_level(logging.WARNING):
        assert _n(raw)["dimensions"] is None
    assert caplog.records == []


def test_format_dimensions_rounds_the_text():
    assert format_dimensions(27.9, 5.1, 27.9)["text"] == "28 x 5 x 28 cm"


def test_format_dimensions_needs_all_three_axes():
    assert format_dimensions(1, None, 3) is None
    assert format_dimensions(30, 20, 10)["text"] == "30 x 20 x 10 cm"


def test_parse_iso_handles_z_naive_and_garbage():
    assert parse_iso("2026-04-29T13:12:42Z") == datetime(
        2026, 4, 29, 13, 12, 42, tzinfo=UTC
    )
    assert parse_iso("2026-04-29T13:12:42").tzinfo is UTC
    assert parse_iso("garbage") is None
    assert parse_iso(None) is None


# ---------------------------------------------------------------------------
# sort_parcels_by_ts
# ---------------------------------------------------------------------------


def test_sort_parcels_ascending_puts_unparseable_last():
    parcels = [
        {"barcode": "a", "planned_from": "2026-05-02T10:00:00Z"},
        {"barcode": "b", "planned_from": None},
        {"barcode": "c", "planned_from": "2026-05-01T10:00:00Z"},
    ]
    ordered = [p["barcode"] for p in sort_parcels_by_ts(parcels, "planned_from")]
    assert ordered == ["c", "a", "b"]


def test_sort_parcels_descending_still_puts_unparseable_last():
    parcels = [
        {"barcode": "a", "delivered_at": "2026-05-02T10:00:00Z"},
        {"barcode": "b", "delivered_at": "nonsense"},
        {"barcode": "c", "delivered_at": "2026-05-01T10:00:00Z"},
    ]
    ordered = [
        p["barcode"]
        for p in sort_parcels_by_ts(parcels, "delivered_at", descending=True)
    ]
    assert ordered == ["a", "c", "b"]


# ---------------------------------------------------------------------------
# apply_delivered_filter
# ---------------------------------------------------------------------------


def _entry(filter_type: str, amount: int) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        options={
            CONF_DELIVERED_FILTER_TYPE: filter_type,
            CONF_DELIVERED_FILTER_AMOUNT: amount,
        },
        unique_id=DOMAIN,
    )


def _delivered_pair() -> list[dict]:
    now = datetime.now(UTC)
    return [
        {"barcode": "RECENT", "delivered_at": (now - timedelta(days=1)).isoformat()},
        {"barcode": "OLD", "delivered_at": (now - timedelta(days=30)).isoformat()},
    ]


def test_delivered_filter_by_days():
    kept = apply_delivered_filter(_delivered_pair(), _entry("days", 7))
    assert [p["barcode"] for p in kept] == ["RECENT"]


def test_delivered_filter_by_count():
    parcels = _delivered_pair()
    assert apply_delivered_filter(parcels, _entry("parcels", 1)) == parcels[:1]


def test_delivered_filter_keeps_unparseable_timestamp():
    """Better to show a parcel with a broken date than to silently drop it."""
    parcels = [{"barcode": "WEIRD", "delivered_at": "nonsense"}]
    assert apply_delivered_filter(parcels, _entry("days", 7)) == parcels
