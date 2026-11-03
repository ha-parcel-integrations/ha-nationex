"""Canonical parcel shape, status mapping and list helpers.

Everything in this module is a **pure function** — no I/O, no Home Assistant
objects beyond the config entry's options. That is deliberate: it keeps the
carrier-specific mapping (which you rewrite per carrier) apart from the
coordinator (which is nearly identical everywhere), and it makes the mapping
trivially unit-testable without spinning up HA.

The carrier-specific parts are the two vocabularies (shipment/parcel state and
scan code) and :func:`normalize_parcel`; the sort contract and the delivered
filter are suite-wide machinery.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
import logging
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry

from .const import (
    CARRIER_TIMEZONE,
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    DEFAULT_DELIVERED_FILTER_AMOUNT,
    DEFAULT_DELIVERED_FILTER_TYPE,
    HISTORY_MAX_EVENTS,
    TRACKING_URL,
    ParcelStatus,
)

_LOGGER = logging.getLogger(__name__)

# Where users report a status we do not map yet. Rewritten by the bootstrap
# script; it must point at the carrier's own repo so the log line is
# copy-pasteable straight into a new issue.
#
# The ``?template=`` parameter matters: without it the link opens a blank form,
# and the report comes back missing the version and the log line we need.
NEW_ISSUE_URL = (
    "https://github.com/ha-parcel-integrations/ha-nationex/issues/new"
    "?template=unrecognised_status.yml"
)

_STATE_MAP: dict[str, ParcelStatus] = {
    "Creation": ParcelStatus.REGISTERED,
    "OutForPickup": ParcelStatus.REGISTERED,
    "Pickup": ParcelStatus.IN_TRANSIT,
    "PartiallyPickedUp": ParcelStatus.IN_TRANSIT,
    "Transit": ParcelStatus.IN_TRANSIT,
    "PartiallyInTransit": ParcelStatus.IN_TRANSIT,
    # Other parcels of the shipment are still on their way.
    "PartiallyDelivered": ParcelStatus.IN_TRANSIT,
    "OutForDelivery": ParcelStatus.OUT_FOR_DELIVERY,
    "PartiallyOutForDelivery": ParcelStatus.OUT_FOR_DELIVERY,
    "Delivered": ParcelStatus.DELIVERED,
    "ReturnToSender": ParcelStatus.RETURNING,
    # Back with the sender, never a delivery to the recipient.
    "ReturnCompleted": ParcelStatus.RETURNING,
    "Attention": ParcelStatus.PROBLEM,
    "RefusedDelivery": ParcelStatus.PROBLEM,
    "PickupAttemptFailed": ParcelStatus.PROBLEM,
    "OnHold": ParcelStatus.PROBLEM,
    "Cancelled": ParcelStatus.PROBLEM,
    "500": ParcelStatus.PROBLEM,
    "501": ParcelStatus.PROBLEM,
}

# In the tracker's own list but never seen on a real parcel.
_UNSEEN_STATES = frozenset(
    {
        "ReturnToSender", "ReturnCompleted", "Attention", "RefusedDelivery",
        "PickupAttemptFailed", "OnHold", "Cancelled", "500", "501",
    }
)  # fmt: skip

_FAILED_DELIVERY = 40
_DELIVERY_COMPLETED = 119
_SCAN_MAP: dict[int, ParcelStatus] = {
    538: ParcelStatus.REGISTERED,
    910: ParcelStatus.REGISTERED,
    52: ParcelStatus.IN_TRANSIT,
    252: ParcelStatus.IN_TRANSIT,
    901: ParcelStatus.IN_TRANSIT,
    903: ParcelStatus.IN_TRANSIT,
    904: ParcelStatus.IN_TRANSIT,
    90: ParcelStatus.IN_TRANSIT,
    900: ParcelStatus.OUT_FOR_DELIVERY,
    _FAILED_DELIVERY: ParcelStatus.PROBLEM,
    _DELIVERY_COMPLETED: ParcelStatus.DELIVERED,
}
# Notification and photo scans say nothing about where the parcel is.
_QUIET_SCANS = frozenset({720, 730})

_TOP_KEYS = frozenset(
    {
        "CustomerId", "ShipmentId", "ExpeditionDate", "TotalParcels",
        "TotalWeight", "ShipmentStatus", "ShipmentStatusEn", "StatusHistories",
        "ShipmentType", "ReferenceNumber", "Note", "Sender", "Destination",
        "Accessory", "Parcels", "ConsolId", "Photos", "LastStop",
        "IsInvoiced", "IsScanned", "IsConsolidated", "IsPickup",
        "IsDelivered", "HasCode390", "IsGreen", "InsertedDate",
        "BillingAccount", "trackingNumber",
    }
)  # fmt: skip
_PARCEL_KEYS = frozenset(
    {
        "ParcelId", "ParcelNumber", "ReferenceNumber", "Weight", "Status",
        "StatusDescriptionEn", "Contact", "EstimatedDeliveryDate",
        "EstimatedDeliveryTime", "EstimatedDeliveryDateRangeStart",
        "EstimatedDeliveryDateRangeEnd", "EstimatedDeliveryDateRangeEn",
        "EstimatedDeliveryTimeEn",
        "EstimatedDeliveryDateTimeStart", "EstimatedDeliveryDateTimeEnd",
        "EstimatedDeliveryDateTimeExact", "EstimatedPercentageBeforeDelivery",
        "EstimatedDeliveryWithinFewHours", "Dimensions", "History",
        "ParcelStatusHistories", "NCV",
    }
)  # fmt: skip
_SCAN_KEYS = frozenset(
    {
        "ParcelHistoryId", "ProcessedDate", "ExceptionId", "CityDepot",
        "DescriptionEn", "DescriptionShortEn", "PhotoId", "SignatureId",
        "Geocoding", "Contact",
    }
)  # fmt: skip
# Known keys only ever seen empty; a first real value needs a look.
_UNSEEN_TOP_KEYS = frozenset(
    {"CustomerId", "BillingAccount", "InsertedDate", "Note", "Accessory", "Photos"}
)
_UNSEEN_PARCEL_KEYS = frozenset(
    {
        "EstimatedDeliveryDateTimeStart", "EstimatedDeliveryDateTimeEnd",
        "EstimatedDeliveryDateTimeExact", "EstimatedPercentageBeforeDelivery",
        "EstimatedDeliveryWithinFewHours",
    }
)  # fmt: skip
_SHIPMENT_TYPES = frozenset({"Delivery", "PickupDelivery"})
_ETA_STATUSES = frozenset(
    {ParcelStatus.REGISTERED, ParcelStatus.IN_TRANSIT, ParcelStatus.OUT_FOR_DELIVERY}
)
_POUND_KG = 0.45359237
_INCH_CM = 2.54
_CUBING_TOLERANCE = 0.05
_CARRIER_TZ = ZoneInfo(CARRIER_TIMEZONE)

# Keys already warned about, so each unmapped value is logged only once per HA
# session instead of on every poll.
_unmapped_statuses_logged: set[str] = set()


def warn_once(key: str, message: str, *args: Any) -> None:
    """Log a warning about something unseen once per HA session."""
    if key in _unmapped_statuses_logged:
        return
    _unmapped_statuses_logged.add(key)
    _LOGGER.warning(message, *args)


def _warn_unmapped_state(state: str) -> None:
    warn_once(
        f"state:{state}",
        "Unrecognised Nationex status — help us map it. Open an issue "
        "and paste this line: %s\n  status=%s → treated as unmapped",
        NEW_ISSUE_URL,
        state,
    )


def _warn_unmapped_scan(code: Any) -> None:
    warn_once(
        f"scan:{code}",
        "Unrecognised Nationex scan code — help us map it. Open an issue "
        "and paste this line: %s\n  code=%s → reported as 'unknown'",
        NEW_ISSUE_URL,
        code,
    )


def _warn_unkeyed(level: str, raw: dict, known: frozenset[str]) -> None:
    for key in raw:
        if key in known or key.endswith("Fr") or "Tooltip" in key:
            continue
        warn_once(
            f"key:{level}:{key}",
            "Unrecognised Nationex %s field %s — help us map it. Open an issue: %s",
            level,
            key,
            NEW_ISSUE_URL,
        )


def _warn_unseen(level: str, raw: dict, keys: frozenset[str]) -> None:
    for key in keys:
        if raw.get(key):
            warn_once(
                f"unseen:{level}:{key}",
                "Nationex filled the %s field %s, which we have only seen empty "
                "— help us map it. Open an issue: %s",
                level,
                key,
                NEW_ISSUE_URL,
            )


def parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO 8601 string to an aware datetime, or ``None`` on failure.

    Naive values are treated as UTC so a list always sorts without crashing on
    a mixed set.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _clock(value: Any) -> datetime | None:
    """Parse a wall clock; one without an offset is Nationex local time."""
    parsed = None
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            parsed = None
    if parsed is None:
        if value:
            warn_once(
                "clock",
                "Unparseable Nationex timestamp — help us map it. Open an issue: %s",
                NEW_ISSUE_URL,
            )
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_CARRIER_TZ)
    return parsed


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _scan_code(value: Any) -> int | str | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None if value is None else str(value)


def _collect_scans(parcels: list[dict]) -> list[dict]:
    """Return the selected parcels' scans, deduplicated, oldest first."""
    seen: set[tuple] = set()
    scans: list[dict] = []
    for parcel in parcels:
        history = parcel.get("History")
        if not isinstance(history, list):
            continue
        # History is newest first; reversing keeps same-second scans in order
        # through the stable sort below.
        for row in reversed(history):
            if not isinstance(row, dict):
                continue
            _warn_unkeyed("scan", row, _SCAN_KEYS)
            text = str(row.get("DescriptionEn") or "").strip()
            code = _scan_code(row.get("ExceptionId"))
            identity = (row.get("ProcessedDate"), code, text)
            if identity in seen:
                continue
            seen.add(identity)
            at = _clock(row.get("ProcessedDate"))
            if at is None:
                continue
            scans.append({"at": at, "code": code, "text": text})
    scans.sort(key=lambda scan: scan["at"])
    return scans


def _walk_scans(scans: list[dict]) -> None:
    """Give every scan its status; quiet codes keep the previous one."""
    previous = ParcelStatus.UNKNOWN
    for scan in scans:
        code = scan["code"]
        if code in _QUIET_SCANS:
            scan["status"] = previous
            scan["quiet"] = True
            continue
        scan["quiet"] = False
        status = _SCAN_MAP.get(code) if isinstance(code, int) else None
        if status is None:
            _warn_unmapped_scan(code)
            status = ParcelStatus.UNKNOWN
        scan["status"] = status
        previous = status


def map_state(state: Any) -> ParcelStatus | None:
    """Map a shipment or parcel state, or ``None`` when absent or unmapped."""
    if not state:
        return None
    mapped = _STATE_MAP.get(str(state))
    if mapped is None:
        _warn_unmapped_state(str(state))
    elif str(state) in _UNSEEN_STATES:
        warn_once(
            f"unseen-state:{state}",
            "Nationex reported status %s, which we have not seen on a real "
            "parcel yet. Please open an issue if the result looks wrong: %s",
            state,
            NEW_ISSUE_URL,
        )
    return mapped


def _eta(
    parcels: list[dict], last_scan: datetime | None
) -> tuple[str | None, str | None]:
    """Return the expected delivery window, latest across the parcels."""
    best: tuple[datetime, datetime | None] | None = None
    for parcel in parcels:
        # A delivered parcel's forecast fields hold its delivery moment.
        if parcel.get("Status") == "Delivered":
            continue
        start = _clock(parcel.get("EstimatedDeliveryDateTimeStart"))
        end = _clock(parcel.get("EstimatedDeliveryDateTimeEnd"))
        if start is None:
            day = _day(parcel.get("EstimatedDeliveryDate"))
            if day is None:
                continue
            warn_once(
                "forecast-day",
                "Nationex gave a forecast delivery day for a parcel on its way, "
                "which we have not confirmed yet. Please open an issue if the "
                "day looks right or wrong: %s",
                NEW_ISSUE_URL,
            )
            start = datetime.combine(day, time.min, tzinfo=_CARRIER_TZ)
            end = datetime.combine(day, time(23, 59, 59), tzinfo=_CARRIER_TZ)
        if best is None or (end or start) > (best[1] or best[0]):
            best = (start, end)
    if best is None:
        return None, None
    start, end = best
    if (
        last_scan is not None
        and last_scan.astimezone(_CARRIER_TZ).date()
        > (end or start).astimezone(_CARRIER_TZ).date()
    ):
        return None, None
    return start.isoformat(), end.isoformat() if end else None


def _day(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        warn_once(
            "clock",
            "Unparseable Nationex timestamp — help us map it. Open an issue: %s",
            NEW_ISSUE_URL,
        )
        return None


def _weight(value: Any) -> float | None:
    pounds = _number(value)
    if not pounds:
        return None
    return round(pounds * _POUND_KG, 2) or None


def _dimensions(parcel: dict) -> dict[str, Any] | None:
    dims = parcel.get("Dimensions")
    if not isinstance(dims, dict):
        return None
    length, width, height = (
        _number(dims.get(key)) for key in ("Length", "Width", "Height")
    )
    # Parcels nobody measured come back as all zeros.
    if not (length and width and height):
        return None
    cubing = _number(dims.get("Cubing"))
    if (
        cubing is not None
        and abs(length * width * height / 1728 - cubing) > _CUBING_TOLERANCE
    ):
        warn_once(
            "cubing",
            "Nationex dimensions do not match the reported volume, so they "
            "are not shown. Open an issue: %s",
            NEW_ISSUE_URL,
        )
        return None
    return format_dimensions(
        round(length * _INCH_CM, 1),
        round(width * _INCH_CM, 1),
        round(height * _INCH_CM, 1),
    )


def _all_completed(parcels: list[dict]) -> bool:
    """Whether every parcel has its own delivery-completed scan."""
    return all(
        any(
            isinstance(row, dict)
            and _scan_code(row.get("ExceptionId")) == _DELIVERY_COMPLETED
            for row in parcel.get("History") or []
        )
        for parcel in parcels
    )


def _state_delivered_at(rows: Any, key: str) -> datetime | None:
    if not isinstance(rows, list):
        return None
    clocks = [
        at
        for row in rows
        if isinstance(row, dict)
        and row.get(key) == "Delivered"
        and (at := _clock(row.get("StatusDate"))) is not None
    ]
    return max(clocks) if clocks else None


def format_dimensions(
    length: float | None, width: float | None, height: float | None
) -> dict[str, Any] | None:
    """Return the canonical ``dimensions`` dict, or ``None`` when incomplete.

    Units contract: **centimetres**, with ``text`` pre-formatted as
    ``"L x W x H cm"`` (integer values, lowercase ``x``) so dashboards can show
    a dimension without doing their own formatting. Convert before calling if
    the carrier reports millimetres or inches.
    """
    if length is None or width is None or height is None:
        return None
    return {
        "length": length,
        "width": width,
        "height": height,
        "text": f"{round(length)} x {round(width)} x {round(height)} cm",
    }


def tracking_url(tracking_code: str | None) -> str | None:
    """Construct the consumer tracking deep-link for a parcel."""
    if not tracking_code:
        return None
    return TRACKING_URL.format(tracking_code=tracking_code)


def normalize_parcel(raw: dict, *, include_history: bool = False) -> dict:
    """Return a carrier-agnostic parcel dict with the payload under ``raw``.

    ``raw["trackingNumber"]`` is the number the user entered. A nine-digit
    number selects the whole shipment, an eleven-digit one a single parcel of
    it. A raw without a shipment (not found yet) yields an ``unknown`` parcel.
    """
    number = raw.get("trackingNumber")
    result: dict[str, Any] = {
        "carrier": "Nationex",
        "barcode": number,
        "sender": None,
        "receiver": None,
        "status": ParcelStatus.UNKNOWN,
        "raw_status": None,
        "delivered": False,
        "delivered_at": None,
        "planned_from": None,
        "planned_to": None,
        "pickup": False,
        "pickup_point": None,
        "url": tracking_url(number),
        "weight": None,
        "dimensions": None,
        "history": [] if include_history else None,
        "raw": raw,
    }
    if raw.get("ShipmentId") is None:
        return result

    _warn_unkeyed("shipment", raw, _TOP_KEYS)
    _warn_unseen("shipment", raw, _UNSEEN_TOP_KEYS)
    shipment_type = raw.get("ShipmentType")
    if shipment_type not in _SHIPMENT_TYPES:
        warn_once(
            f"type:{shipment_type}",
            "Unrecognised Nationex shipment type %s — help us map it. Open "
            "an issue: %s",
            shipment_type,
            NEW_ISSUE_URL,
        )

    all_parcels = [p for p in raw.get("Parcels") or [] if isinstance(p, dict)]
    for parcel in all_parcels:
        _warn_unkeyed("parcel", parcel, _PARCEL_KEYS)
        _warn_unseen("parcel", parcel, _UNSEEN_PARCEL_KEYS)
    selected = [p for p in all_parcels if str(p.get("ParcelId")) == number]
    single = bool(selected)
    if not single:
        selected = all_parcels

    scans = _collect_scans(selected)
    _walk_scans(scans)
    loud = [scan for scan in scans if not scan["quiet"]]

    if single:
        state = selected[0].get("Status")
        raw_status = selected[0].get("StatusDescriptionEn")
        rows, row_key = selected[0].get("ParcelStatusHistories"), "ParcelStatus"
    else:
        state = raw.get("ShipmentStatus")
        raw_status = raw.get("ShipmentStatusEn")
        rows, row_key = raw.get("StatusHistories"), "ShipmentStatus"
    status = map_state(state)

    if status is None:
        # One parcel's delivery scan must not close a shipment still under way.
        may_be_delivered = _all_completed(selected)
        fallback = next(
            (
                scan
                for scan in reversed(loud)
                if scan["status"] is not ParcelStatus.UNKNOWN
                and (may_be_delivered or scan["status"] is not ParcelStatus.DELIVERED)
            ),
            None,
        )
        if fallback is not None:
            status, raw_status = fallback["status"], fallback["text"]
        else:
            status = ParcelStatus.UNKNOWN
            if not state:
                warn_once(
                    "no-state",
                    "Nationex reported no status and no usable scan. Open an issue: %s",
                    NEW_ISSUE_URL,
                )

    # The state goes back to "Transit" right after a failed delivery attempt;
    # without this the attempt would be invisible until the next scan.
    if (
        loud
        and loud[-1]["code"] == _FAILED_DELIVERY
        and status in (ParcelStatus.IN_TRANSIT, ParcelStatus.OUT_FOR_DELIVERY)
    ):
        status = ParcelStatus.PROBLEM
        raw_status = loud[-1]["text"] or raw_status

    delivered = status is ParcelStatus.DELIVERED
    delivered_at = None
    if delivered:
        completed = [s["at"] for s in scans if s["code"] == _DELIVERY_COMPLETED]
        found = max(completed) if completed else _state_delivered_at(rows, row_key)
        delivered_at = found.isoformat() if found else None

    planned_from = planned_to = None
    if status in _ETA_STATUSES:
        planned_from, planned_to = _eta(selected, scans[-1]["at"] if scans else None)

    # Statuses on the history rows are the scan statuses, oldest to newest.
    history = None
    if include_history:
        history = [
            {
                "timestamp": scan["at"].isoformat(),
                "status": scan["status"],
                "raw_status": scan["text"],
            }
            for scan in scans[-HISTORY_MAX_EVENTS:]
        ]

    result.update(
        {
            "status": status,
            "raw_status": str(raw_status or state).strip()
            if raw_status or state
            else None,
            "delivered": delivered,
            "delivered_at": delivered_at,
            "planned_from": planned_from,
            "planned_to": planned_to,
            "weight": _weight(
                selected[0].get("Weight") if single else raw.get("TotalWeight")
            ),
            "dimensions": _dimensions(selected[0]) if len(selected) == 1 else None,
            "history": history,
        }
    )
    return result


def sort_parcels_by_ts(
    parcels: list[dict], key_field: str, *, descending: bool = False
) -> list[dict]:
    """Return normalised parcels sorted by the ISO timestamp at ``key_field``.

    The suite's sort contract: incoming/outgoing ascending on ``planned_from``,
    delivered descending on ``delivered_at``. Parcels whose value is missing or
    unparseable always sort to the end, regardless of ``descending``.
    """
    with_ts: list[tuple[datetime, dict]] = []
    without_ts: list[dict] = []
    for parcel in parcels:
        parsed = parse_iso(parcel.get(key_field))
        if parsed is None:
            without_ts.append(parcel)
        else:
            with_ts.append((parsed, parcel))
    with_ts.sort(key=lambda item: item[0], reverse=descending)
    return [parcel for _, parcel in with_ts] + without_ts


def apply_delivered_filter(parcels: list[dict], entry: ConfigEntry) -> list[dict]:
    """Trim the delivered list per the entry's retention option.

    ``parcels`` must already be sorted newest-first. ``days`` keeps deliveries
    from the last N days (an unparseable ``delivered_at`` is kept rather than
    silently dropped); the ``parcels`` type keeps the N most recent. Parcels
    stay *tracked* either way — this only controls what the delivered sensor
    shows.
    """
    options = entry.options
    filter_type = options.get(CONF_DELIVERED_FILTER_TYPE, DEFAULT_DELIVERED_FILTER_TYPE)
    amount = int(
        options.get(CONF_DELIVERED_FILTER_AMOUNT, DEFAULT_DELIVERED_FILTER_AMOUNT)
    )
    if filter_type == "days":
        cutoff = datetime.now(UTC) - timedelta(days=amount)
        return [
            parcel
            for parcel in parcels
            if (parsed := parse_iso(parcel.get("delivered_at"))) is None
            or parsed >= cutoff
        ]
    return parcels[:amount]
