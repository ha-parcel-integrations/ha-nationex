# Nationex Parcel Tracker

[![Release](https://img.shields.io/github/v/release/ha-parcel-integrations/ha-nationex.svg)](https://github.com/ha-parcel-integrations/ha-nationex/releases)
[![Downloads](https://img.shields.io/github/downloads/ha-parcel-integrations/ha-nationex/total.svg)](https://github.com/ha-parcel-integrations/ha-nationex/releases)
[![HACS](https://img.shields.io/badge/HACS-Default-41BDF5.svg)](https://github.com/hacs/integration)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> 📦 Part of [**ha-parcel-integrations**](https://ha-parcel-integrations.github.io/), a family of package-tracking integrations for Home Assistant that all publish the same parcel format, statuses and events, so they plug into cross-carrier automations and the optional [Parcel Aggregator](https://github.com/ha-parcel-integrations/ha-parcel-aggregator). Browse the other carriers on the website.
>
> 💬 Questions or feedback? Join the discussion on the [Home Assistant community](https://community.home-assistant.io/t/packages-postnl-dhl-nl-dpd-and-gls-parcel-integration/112433/).

A custom Home Assistant integration that tracks your [Nationex](https://nationex.com) parcels in Canada. No account is needed — you enter the tracking number yourself, just like on the Nationex website.

> **Good to know.** Built from delivered parcels only. States such as returns, refusals, holds, cancellations and partner hand-offs, and shipments with several parcels, have not been seen yet. When Nationex reports a status, scan or field this integration does not know, it falls back to the newest scan it does recognise, shows `unknown` if there is none, and logs one warning that names the status or code, never the values. Please [open an issue](https://github.com/ha-parcel-integrations/ha-nationex/issues/new?template=unrecognised_status.yml) when you see it.

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Options](#options)
- [Removal](#removal)
- [Sensors](#sensors)
- [Parcel status reference](#parcel-status-reference)
- [Events](#events)
- [Services](#services)
- [Examples](#examples)
- [Debugging](#debugging)
- [Troubleshooting](#troubleshooting)
- [Related integrations](#related-integrations)
- [Disclaimer](#disclaimer)
- [Contributing](#contributing)
- [License](#license)

## Features

- Track any number of Nationex parcels by tracking number — no account needed
- Per-parcel sensor with the canonical status (`registered` / `in_transit` / `out_for_delivery` / `delivered` / …), the carrier's own status text, the expected delivery day when Nationex gives one, weight and dimensions, the scan history and a tracking deep-link
- Summary sensors: incoming parcels, next delivery, recently delivered parcels
- Read-only **Deliveries** calendar with the expected delivery day, when Nationex gives one
- `nationex.track_parcel` / `nationex.untrack_parcel` services, so a dashboard button can add a parcel
- Events + device triggers for no-code automations (parcel registered, status changed, delivered, delivery time changed)
- Opt-in per-parcel status history
- Manual refresh button and a diagnostic last-update sensor

## Requirements

- Home Assistant 2025.12 or newer
- A Nationex tracking number: 9 digits for a shipment, or 11 digits for one
  parcel of it. It is in the shipping confirmation email. No account is needed.

## Installation

### HACS (recommended)

1. Open HACS and search for **Nationex**.
2. Install it.
3. Restart Home Assistant.

Or click the button below to open it directly in HACS:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ha-parcel-integrations&repository=ha-nationex&category=integration)

### Manual

Copy `custom_components/nationex` into your `config/custom_components/` folder and restart Home Assistant.

## Configuration

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=nationex)

Add the integration via **Settings → Devices & Services → Add Integration → Nationex**. There is nothing to fill in: the hub is created immediately (Nationex tracking needs no account).

Then add parcels via the integration's **Configure** dialog, the [`nationex.track_parcel`](#services) service, or a [dashboard button](examples/dashboards/add_parcel_card.yaml). Enter the 9-digit shipment number, or the 11-digit number of one parcel. Delivery-notice numbers and sender references are not supported.

## Options

Open **Configure** on the integration entry:

| Section | Option | Default | Description |
|---|---|---|---|
| Parcels | Add / remove | — | Manage the tracked tracking codes. Changes apply immediately, no restart. |
| Delivered parcels | Filter by / amount | last 7 days | How long delivered parcels stay visible on the delivered sensor. |
| Parcel history | Include status history | off | Adds a `history` attribute per parcel with each status update. |

Polling isn't one of these settings: the integration polls on a dynamic,
status-driven schedule with nothing to configure.

## Dynamic polling

Polling isn't a setting here — the integration adjusts its own cadence to
what your tracked parcels are actually doing:

- **Quiet hours** — no polling between 00:00–06:00 local time, aside from one
  catch-up check at each end of that window (around midnight and around 6
  AM), so an overnight update is never missed.
- **Hot (every 15 minutes)** — while any tracked parcel is out for delivery
  today, starting an hour before its delivery window opens (or immediately if
  no window is known yet).
- **Normal (every 45 minutes)** — for anything else still on its way.
- **Fully paused** — once every tracked parcel has been delivered, or nothing
  is tracked at all, polling stops until you add a parcel back (adding one
  always triggers an immediate check, regardless of the pause).
- A small, fixed per-hub offset is added on top, so not every Nationex
  hub out there polls at exactly the same second.

So far Nationex has only been seen forecasting a delivery day, not a time window. That day is used as the parcel's delivery window, so a parcel that is out for delivery is checked every 15 minutes from the start of that day.

## Removal

Standard HA removal applies: **Settings → Devices & Services → Nationex → ⋮ → Delete**. Nothing is stored on Nationex's side.

## Sensors

| Entity | Description |
|---|---|
| `sensor.nationex_incoming_parcels` | Number of active tracked parcels, full list under the `parcels` attribute |
| `sensor.nationex_parcel_<code>` | One per tracked parcel; state is the canonical status, attributes carry the full normalised parcel |
| `sensor.nationex_next_delivery` | Earliest expected delivery moment across all active parcels |
| `sensor.nationex_delivered_parcels` | Recently delivered parcels (see the retention option) |
| `calendar.nationex_deliveries` | Read-only calendar of expected deliveries, no extra API calls |
| `sensor.nationex_last_successful_update` | Diagnostic: when Nationex was last polled successfully |

A delivered parcel moves from its per-parcel sensor to the delivered sensor automatically.

## Parcel status reference

The `status` field is the carrier-agnostic enum shared by the whole integration family:

| Status | Meaning |
|---|---|
| `registered` | Shipment created, or a driver is on the way to pick it up |
| `in_transit` | Picked up and moving through the Nationex network, including a shipment of which only some parcels are delivered |
| `out_for_delivery` | With the courier today |
| `delivered` | Delivered |
| `returning` | Going back to the sender, or already back with them |
| `problem` | A delivery attempt failed, or Nationex reports an attention, refusal, hold or cancellation |
| `unknown` | Not found yet, or a status we have not mapped yet |

A failed delivery attempt shows as `problem` until the parcel is scanned again, even though Nationex itself reports the parcel as in transit again.

The carrier's own human-readable text is available as `raw_status`.

## Events

The integration fires these on the event bus (also available as device triggers on the Nationex device):

| Event | When |
|---|---|
| `nationex_parcel_registered` | A new parcel appears in the active list |
| `nationex_parcel_status_changed` | A parcel's canonical status changes (`old_status` / `new_status` in the payload), except the final hop to delivered |
| `nationex_parcel_delivered` | A parcel is delivered |
| `nationex_parcel_delivery_time_changed` | The expected delivery window changes |

Every payload is the full normalised parcel plus the hub's `device_id`. Events are suppressed on the first refresh after start-up.

## Services

| Service | Fields | Description |
|---|---|---|
| `nationex.track_parcel` | `tracking_code` | Start tracking a parcel |
| `nationex.untrack_parcel` | `tracking_code` | Stop tracking a parcel |

## Examples

Ready-to-paste automations and dashboard snippets live in [`examples/`](examples/), including tracking a new parcel straight from a dashboard.

### Community Lovelace cards

Third-party cards that work with this integration's sensors:

- [jonisnet/hki-parcels-card](https://github.com/jonisnet/hki-parcels-card)
- [klaptafel/ha-package-tracker-card](https://github.com/klaptafel/ha-package-tracker-card)

## Debugging

```yaml
logger:
  logs:
    custom_components.nationex: debug
```

## Troubleshooting

- **A parcel shows `unknown`** — Nationex does not know the number (yet, or any more: old shipments are removed), or it was mistyped. It will pick up automatically once Nationex lists it.
- **A warning says "Unrecognised Nationex" status, scan code or field** — please [open an issue](https://github.com/ha-parcel-integrations/ha-nationex/issues/new?template=unrecognised_status.yml) with the logged line so the mapping can be extended.

## Related integrations

This integration is part of [**ha-parcel-integrations**](https://ha-parcel-integrations.github.io/) — a family of
parcel-carrier integrations that all publish the same canonical parcel format,
statuses and events.

- [**Parcel Aggregator**](https://github.com/ha-parcel-integrations/ha-parcel-aggregator) rolls every installed carrier
  up into one set of sensors.
- Browse [the organisation](https://ha-parcel-integrations.github.io/) for the current list of supported carriers.

## Disclaimer

This is an independent, community-built project. It is not affiliated with, endorsed by, sponsored by, or supported by Nationex, Home Assistant, or any other third party referenced in this project. Please don't contact Nationex for support with this integration.

All third-party trademarks, trade names, product names, logos, and other brand assets are the property of their respective owners. References to them are solely to identify the relevant carrier or service and do not imply affiliation, sponsorship, or endorsement. Nothing in this project grants or implies any licence or right to use third-party brand assets.

This integration may rely on public, unofficial, or undocumented carrier interfaces, accessed without an account. These may change or be withdrawn without notice and may be subject to Nationex's terms. Data is sent only to Nationex's own services or those of its group; this project operates no servers of its own. You are responsible for ensuring that your use complies with applicable law and those terms. Use is at your own risk; see the [licence](LICENSE) for warranty limitations.

This integration uses the same public tracking endpoint as the Nationex consumer website.

## Contributing

Pull requests and issues are welcome. Please open an issue before
submitting a large change.

## License

[MIT](LICENSE)
