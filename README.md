# AquaPure Probe for Home Assistant

This is a deliberately **read-only** custom integration for testing whether a
Jandy iAquaLink controller exposes AquaPure diagnostics through its cloud APIs.
It issues only `get_home`, `get_swc_config`, and WebTouch display-navigation
requests; it never sends commands that change chlorine output, boost,
schedules, or equipment state.

The probe is intended for the user's RS-8 Combo / iQ30 setup. It is not a
general-purpose, supported Jandy integration.

## What it looks for

- pool and spa AquaPure set points
- boost state and remaining timer
- salt PPM and SWC status when the cloud response supplies them

When the normal mobile API omits salt, the probe resolves the controller's
`touchLink` from the Owner's Portal API, opens the same WebTouch display session
used by the iAquaLink app, and navigates to its read-only Status page. It parses
only the rendered `Salt … PPM` text and never sends a circuit, setpoint, boost,
or equipment command.

All sensor entities are created even when a value is temporarily unavailable,
so a chlorinator that is off during Home Assistant startup can recover on a
later refresh without recreating the integration.

## Installation

Copy `custom_components/aquapure_probe` into the Home Assistant configuration
directory, restart Home Assistant, then add **AquaPure Probe** from Devices &
Services. Sign in with the existing iAquaLink account using Home Assistant's
normal configuration form.

The component uses the `iaqualink` dependency that is already used by Home
Assistant's Jandy iAquaLink integration. It does not log credentials, tokens,
or complete response bodies.

## Pool dashboard

`examples/pool-dashboard.json` contains the deployed pool dashboard configuration
(JSON is also valid YAML in Home Assistant's raw dashboard editor). Adjust the
entity IDs for your installation before importing it.

Water readings from all integrations appear together first in eight gauges:
salt, free chlorine, pH, water temperature, alkalinity, stabilizer, calcium
hardness, and flow.
Controls, heating settings, and equipment maintenance appear below. The sample
age remains visible because chemistry readings are not necessarily live.

The salt gauge highlights the **3,000–3,500 ppm** range recommended in the
[Jandy AquaPure/PureLink manual, section 4.7](https://www.jandy.com/-/media/zodiac/global/downloads/jandy/water-sanitizers/h0325600.pdf).
The dashboard suggests **about 3,200 ppm** as a practical aim within that range;
this is not a separate manufacturer-specified exact setpoint. The pH gauge's
green band reflects the manual's 7.4–7.6 recommendation. Chemistry green bands
also follow section 4.5: free chlorine 1–3 ppm, alkalinity 80–120 ppm,
stabilizer 50–75 ppm, and calcium hardness 175–400 ppm. Yellow and red mark
progressively larger departures for dashboard attention; their transitions are
display choices, not manufacturer dosing or swimming-safety limits. Chlorine
must be interpreted alongside stabilizer and sample age. Temperature and flow
remain neutral blue because their targets depend on comfort and equipment.

### Optional dashboard artwork

The `assets/aquapure-salt-hero.png` image is included for a Home Assistant
`picture-elements` card. Copy it to Home Assistant's `config/www` directory and
reference it as `/local/aquapure-salt-hero.png`; a `state-label` for the salt
sensor can then be positioned over the blank panel on the carton.
