"""Tests for Nationex diagnostics."""

from datetime import timedelta
import json
from unittest.mock import MagicMock

from custom_components.nationex.diagnostics import async_get_config_entry_diagnostics
from custom_components.nationex.parcels import normalize_parcel

from .payloads import delivered_sample

REDACTED = "**REDACTED**"


def _coordinator(data):
    coordinator = MagicMock()
    coordinator.current_tier_minutes = 15
    coordinator.update_interval = timedelta(minutes=15)
    coordinator.data = data
    coordinator.delivered = []
    coordinator.delivered_codes = set()
    return coordinator


async def test_diagnostics_redacts_every_identifying_field(hass):
    """Diagnostics get pasted into public issues — nothing identifying may survive."""
    raw = delivered_sample()
    raw["trackingNumber"] = "900000001"
    raw["Note"] = "Leave at the back"
    raw["StatusHistories"][0]["LastLocation"] = "SECRET-TOWN"
    raw["Parcels"][0]["ParcelStatusHistories"][0]["LastLocation"] = "SECRET-TOWN"
    raw["Parcels"][0]["History"][0]["CityDepot"] = "SECRET-TOWN"
    raw["CustomerId"] = "12345"
    raw["BillingAccount"] = "67890"
    raw["Photos"] = ["p"]
    raw["Parcels"][0]["History"][0]["PhotoId"] = "ph"
    raw["Parcels"][0]["History"][0]["SignatureId"] = "sg"
    raw["Parcels"][0]["History"][0]["Photos"] = ["p"]
    raw["Parcels"][0]["ParcelTooltipEn"] = "Your order from Example Shop"
    raw["StatusHistories"][0]["SomeTooltipFr"] = "Example Shop"
    entry = MagicMock()
    entry.options = {"parcels": [{"tracking_code": "900000001"}]}
    entry.runtime_data.coordinator = _coordinator([normalize_parcel(raw)])

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert "SECRET-TOWN" not in str(result)
    assert result["counts"] == {
        "incoming_active": 1,
        "delivered": 0,
        "skipped_from_fetch": 0,
    }
    assert result["polling"]["suspended"] is False
    assert result["entry_options"]["parcels"][0]["tracking_code"] == REDACTED
    parcel = result["incoming"][0]
    assert parcel["barcode"] == REDACTED
    assert parcel["url"] == REDACTED
    out = parcel["raw"]
    for key in (
        "trackingNumber",
        "ShipmentId",
        "ConsolId",
        "CustomerId",
        "BillingAccount",
        "ReferenceNumber",
        "Note",
        "Sender",
        "Destination",
        "LastStop",
        "Photos",
        "ShipmentStatusTooltipEn",
    ):
        assert out[key] == REDACTED, key
    scan = out["Parcels"][0]["History"][0]
    assert out["Parcels"][0]["ParcelId"] == REDACTED
    assert out["Parcels"][0]["ReferenceNumber"] == REDACTED
    assert out["Parcels"][0]["Contact"] == REDACTED
    assert out["Parcels"][0]["ParcelTooltipEn"] == REDACTED
    assert out["StatusHistories"][0]["SomeTooltipFr"] == REDACTED
    for key in (
        "Geocoding",
        "Contact",
        "PhotoId",
        "SignatureId",
        "ParcelHistoryId",
        "Photos",
    ):
        assert scan[key] == REDACTED, key
    text = json.dumps(result)
    for leak in (
        "Example Shop",
        "Jane Doe",
        "H0H0H0",
        "K0K0K0",
        "Example Street",
        "900000001",
    ):
        assert leak not in text, leak
    # non-identifying fields survive, or the diagnostics would be useless
    assert parcel["status"] == "delivered"
    assert scan["ExceptionId"] == 119


async def test_diagnostics_reports_suspended_polling(hass):
    """update_interval None (the full stop) must be visible, not just absent."""
    entry = MagicMock()
    entry.options = {"parcels": []}
    coordinator = _coordinator([])
    coordinator.current_tier_minutes = None
    coordinator.update_interval = None
    entry.runtime_data.coordinator = coordinator

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["polling"] == {
        "tier_minutes": None,
        "update_interval_seconds": None,
        "suspended": True,
    }
