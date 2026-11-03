"""Diagnostics support for the Nationex parcel tracker integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import NationexConfigEntry

# Diagnostics are pasted into public issues, so redact anything that
# identifies a person, an address or a specific parcel. Over-redacting is
# cheap; under-redacting leaks a user's home address into a GitHub thread.
#
TO_REDACT = {
    # canonical fields we publish ourselves
    "tracking_code",
    "barcode",
    "sender",
    "receiver",
    "url",
    # carrier payload fields
    "trackingNumber",
    "ShipmentId",
    "ConsolId",
    "CustomerId",
    "BillingAccount",
    "ParcelId",
    "ReferenceNumber",
    "Note",
    "Sender",
    "Destination",
    "LastStop",
    "Geocoding",
    "Contact",
    "PhotoId",
    "SignatureId",
    "ParcelHistoryId",
    "LastLocation",
    "CityDepot",
    "Photos",
}


def _tooltip_keys(data: Any) -> set[str]:
    """Collect every key holding a tooltip text, which can name the sender."""
    keys: set[str] = set()
    if isinstance(data, dict):
        for key, value in data.items():
            if "Tooltip" in str(key):
                keys.add(key)
            keys |= _tooltip_keys(value)
    elif isinstance(data, list):
        for item in data:
            keys |= _tooltip_keys(item)
    return keys


def _redact(data: Any) -> Any:
    return async_redact_data(data, TO_REDACT | _tooltip_keys(data))


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: NationexConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for the Nationex config entry."""
    coordinator = entry.runtime_data.coordinator

    return {
        "entry_options": _redact(dict(entry.options)),
        "counts": {
            "incoming_active": len(coordinator.data or []),
            "delivered": len(coordinator.delivered or []),
            "skipped_from_fetch": len(coordinator.delivered_codes),
        },
        "polling": {
            "tier_minutes": coordinator.current_tier_minutes,
            "update_interval_seconds": (
                coordinator.update_interval.total_seconds()
                if coordinator.update_interval
                else None
            ),
            "suspended": coordinator.update_interval is None,
        },
        "incoming": _redact(coordinator.data or []),
        "delivered": _redact(coordinator.delivered or []),
    }
