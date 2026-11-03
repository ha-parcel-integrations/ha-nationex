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
