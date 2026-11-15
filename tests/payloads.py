"""Sample Nationex API payloads shared by the test modules.

Scrubbed: the numbers, ids and person fields are invented. Clocks, scan codes,
depot towns and wordings follow what the service returns.
"""

from __future__ import annotations

import copy

ACTIVE_CODE = "900000002"
DELIVERED_CODE = "900000001"
UNKNOWN_BODY = {"code": 404, "message": "Sorry, no results."}


def scan(code: int, at: str, text: str, depot: str = "OTTAWA") -> dict:
    """One scan of a parcel's history, with the extra keys every scan carries."""
    return {
        "ParcelHistoryId": 1000 + code,
        "ProcessedDate": at,
        "ExceptionId": code,
        "CityDepot": depot,
        "DescriptionFr": "fr",
        "DescriptionEn": text,
        "DescriptionShortFr": "fr",
        "DescriptionShortEn": text,
        "PhotoId": None,
        "SignatureId": None,
        "Geocoding": {"Longitude": 0.0, "Latitude": 0.0},
        "Contact": "Jane Doe" if code == 119 else None,
    }


def status_row(status: str, at: str, key: str = "ShipmentStatus") -> dict:
    """One row of a state history."""
    return {
        key: status,
        "ShipmentStatusEn": status,
        "StatusDate": at,
        "LastLocation": None,
    }


def parcel(
    parcel_id: int,
    *,
    status: str = "Delivered",
    history: list[dict] | None = None,
    state_rows: list[dict] | None = None,
    eta_date: str | None = "2026-10-15",
    weight: int = 4,
) -> dict:
    """One parcel of a shipment (dimensions 12 x 5 x 21 inches)."""
    return {
        "ParcelId": parcel_id,
        "ParcelNumber": parcel_id % 100,
        "ReferenceNumber": "REF-1",
        "Weight": weight,
        "Status": status,
        "StatusDescriptionEn": status,
        "Contact": "Jane Doe",
        "EstimatedDeliveryDate": eta_date,
        "EstimatedDeliveryTime": "16:34",
        "EstimatedDeliveryDateRangeStart": None,
        "EstimatedDeliveryDateRangeEnd": None,
        "EstimatedDeliveryTimeEn": None,
        "EstimatedDeliveryDateTimeStart": None,
        "EstimatedDeliveryDateTimeEnd": None,
        "EstimatedDeliveryDateTimeExact": None,
        "EstimatedPercentageBeforeDelivery": None,
        "EstimatedDeliveryWithinFewHours": False,
        "Dimensions": {"Height": 21, "Length": 12, "Width": 5, "Cubing": 0.7291667},
        "History": history or [],
        "ParcelStatusHistories": state_rows or [],
    }


def shipment(
    shipment_id: int,
    parcels: list[dict],
    *,
    status: str = "Delivered",
    state_rows: list[dict] | None = None,
) -> dict:
    """A shipment object as the service returns it."""
    return {
        "CustomerId": None,
        "ShipmentId": shipment_id,
        "ExpeditionDate": "2026-10-13",
        "TotalParcels": len(parcels),
        "TotalWeight": sum(p["Weight"] for p in parcels),
        "ShipmentStatus": status,
        "ShipmentStatusFr": "fr",
        "ShipmentStatusEn": status,
        "ShipmentStatusTooltipEn": "Your order from Example Shop was delivered today",
        "StatusHistories": state_rows or [],
        "ShipmentType": "PickupDelivery",
        "ReferenceNumber": "REF-1",
        "Note": None,
        "Sender": {
            "AccountName": "Example Shop",
            "City": "Montreal",
            "PostalCode": "H0H0H0",
        },
        "Destination": {"AccountName": None, "City": "Ottawa", "PostalCode": "K0K0K0"},
        "Accessory": None,
        "Parcels": parcels,
        "ConsolId": shipment_id,
        "Photos": None,
        "LastStop": {
            "Location": "Example Street 1",
            "CurrentStop": None,
            "TotalStop": None,
        },
        "IsInvoiced": False,
        "IsScanned": True,
        "IsConsolidated": False,
        "IsPickup": True,
        "IsDelivered": status == "Delivered",
        "HasCode390": False,
        "IsGreen": False,
    }


DELIVERED_HISTORY = [
    scan(
        119, "2026-10-15T16:34:54", "Delivery completed - Parcel left at the front door"
    ),
    scan(730, "2026-10-15T16:34:52", "Picture taken", ""),
    scan(900, "2026-10-15T15:54:45", "Parcel out for delivery"),
    scan(900, "2026-10-15T11:36:22", "Parcel out for delivery"),
    scan(40, "2026-10-14T18:21:51", " Unable to complete the delivery"),
    scan(900, "2026-10-14T13:12:33", "Parcel out for delivery"),
    scan(904, "2026-10-14T07:00:58", "Parcel scanned"),
    scan(903, "2026-10-14T01:58:44", "Parcel scanned", "ST-HUBERT"),
    scan(52, "2026-10-13T10:37:11", "Pickup of the parcel confirmed", "ST-HUBERT"),
    scan(910, "2026-10-13T09:17:50", "Driver in route for pickup", ""),
    scan(538, "2026-10-10T12:57:06", "Shipment created", ""),
]
DELIVERED_STATE_ROWS = [
    status_row("Creation", "2026-10-10T12:57:06"),
    status_row("Transit", "2026-10-14T18:21:51"),
    status_row("Delivered", "2026-10-15T16:34:54"),
]


def delivered_sample(code: str = DELIVERED_CODE) -> dict:
    """A delivered one-parcel shipment with a failed first attempt."""
    shipment_id = int(code[:9])
    rows = copy.deepcopy(DELIVERED_STATE_ROWS)
    return shipment(
        shipment_id,
        [
            parcel(
                shipment_id * 100 + 1,
                history=copy.deepcopy(DELIVERED_HISTORY),
                state_rows=[
                    status_row("Delivered", "2026-10-15T16:34:54", "ParcelStatus")
                ],
            )
        ],
        state_rows=rows,
    )


def active_sample(code: str = ACTIVE_CODE) -> dict:
    """An out-for-delivery one-parcel shipment with a forecast day."""
    shipment_id = int(code[:9])
    history = [
        scan(900, "2026-04-29T08:46:00", "Parcel out for delivery"),
        scan(903, "2026-04-28T15:52:17", "Parcel scanned", "ST-HUBERT"),
        scan(538, "2026-04-27T23:03:58", "Shipment created", ""),
    ]
    return shipment(
        shipment_id,
        [
            parcel(
                shipment_id * 100 + 1,
                status="OutForDelivery",
                history=history,
                eta_date="2026-04-29",
            )
        ],
        status="OutForDelivery",
    )


LIVE_CODE = "900000003"
LIVE_NOT_FOUND_BODY = {
    "error": True,
    "url": "https://nationex.com/api/tracking/900000009",
    "statusCode": 404,
    "statusMessage": "Nationex API request failed.",
    "message": "Nationex API request failed.",
}
ROUTE_MISSING_BODY = {
    "error": True,
    "statusCode": 404,
    "statusMessage": "Page not found: /api/tracking/900000009",
    "message": "Page not found: /api/tracking/900000009",
}


def live_scan(at: str, text: str, depot: str = "") -> dict:
    """One scan as the public reply carries it: no code, no media."""
    return {
        "ParcelHistoryId": 2000,
        "ProcessedDate": at,
        "CityDepot": depot,
        "DescriptionShortFr": None,
        "DescriptionShortEn": None,
        "DescriptionFr": "fr",
        "DescriptionEn": text,
    }


LIVE_STATES = [
    ("Creation", "2026-10-07T17:16:11"),
    ("OutForPickup", "2026-10-08T09:08:52"),
    ("Pickup", "2026-10-08T13:20:29"),
    ("Transit", "2026-10-09T02:24:04"),
    ("OutForDelivery", "2026-10-13T07:45:38"),
    ("Delivered", "2026-10-13T10:28:25"),
]
LIVE_HISTORY = [
    live_scan(
        "2026-10-13T10:28:25",
        "Delivery completed - Parcel left at the front door",
        "KINGSTON",
    ),
    live_scan("2026-10-13T10:28:07", "Picture taken"),
    live_scan("2026-10-13T07:45:38", "Parcel out for delivery", "KINGSTON"),
    live_scan("2026-10-11T13:21:53", "Parcel scanned", "KINGSTON"),
    live_scan("2026-10-09T02:24:04", "Parcel scanned", "ST-HUBERT"),
    live_scan("2026-10-08T13:20:29", "Pickup of the parcel confirmed", "SHERBROOKE"),
    live_scan("2026-10-08T09:08:52", "Driver in route for pickup"),
    live_scan("2026-10-07T17:16:11", "Shipment created"),
]


def _live_rows(count: int, key: str) -> list[dict]:
    return [
        {
            key: state,
            "ShipmentStatusFr": "fr",
            "ShipmentStatusEn": state,
            "StatusDate": at,
            "LastLocation": None,
        }
        for state, at in LIVE_STATES[:count]
    ]


def live_sample(code: str = LIVE_CODE, *, states: int = len(LIVE_STATES)) -> dict:
    """A one-parcel shipment in the public reply's shape, cut after ``states``."""
    shipment_id = int(code[:9])
    last = LIVE_STATES[states - 1][0]
    cutoff = LIVE_STATES[states][1] if states < len(LIVE_STATES) else None
    history = [
        dict(row)
        for row in LIVE_HISTORY
        if cutoff is None or row["ProcessedDate"] < cutoff
    ]
    return {
        "ShipmentId": shipment_id,
        "ShipmentStatus": last,
        "ShipmentStatusFr": "fr",
        "ShipmentStatusEn": last,
        "ShipmentType": "PickupDelivery",
        "TotalParcels": 1,
        "IsDelivered": last == "Delivered",
        "IsGreen": False,
        "HasCode390": False,
        "access": "public",
        "Destination": {
            "City": "OTTAWA",
            "ProvinceState": None,
            "PostalCode": "K0K0K0",
            "Geocoding": {"Latitude": 0.0, "Longitude": 0.0},
        },
        "Note": None,
        "Accessory": None,
        "StatusHistories": _live_rows(states, "ShipmentStatus"),
        "Parcels": [
            {
                "ParcelId": shipment_id * 100 + 1,
                "ParcelNumber": 1,
                "Status": last,
                "StatusDescriptionFr": "fr",
                "StatusDescriptionEn": last,
                "EstimatedDeliveryDate": "2026-10-13",
                "EstimatedDeliveryTime": "10:28",
                "EstimatedDeliveryDateRangeFr": "2026-10-13",
                "EstimatedDeliveryDateRangeEn": "2026-10-13",
                "EstimatedDeliveryDateRangeStart": "2026-10-13T00:00:00",
                "EstimatedDeliveryDateRangeEnd": "2026-10-13T00:00:00",
                "EstimatedDeliveryDateTimeStart": None,
                "EstimatedDeliveryDateTimeEnd": None,
                "EstimatedDeliveryTimeFr": "2026-10-13 10:28",
                "EstimatedDeliveryTimeEn": "2026-10-13 10:28AM",
                "EstimatedPercentageBeforeDelivery": None,
                "EstimatedDeliveryWithinFewHours": False,
                "History": history,
                "ParcelStatusHistories": _live_rows(states, "ParcelStatus"),
            }
        ],
        "LastStop": {
            "CurrentStop": None,
            "TotalStop": None,
            "Location": {"Latitude": 0.0, "Longitude": 0.0},
        },
    }
