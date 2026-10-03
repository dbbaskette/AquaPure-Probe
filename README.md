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

Water readings from all integrations appear together first in paired gauges:
chlorine/pH, salt/temperature, alkalinity/stabilizer, and hardness/flow. Each
gauge has a compact native history graph directly beneath it showing the rolling
last 24 hours from Home Assistant Recorder. No extra database or custom card is
required. History begins with the data Home Assistant has recorded; this does
not backfill measurements from WaterGuru. Flat lines can represent an unchanged
last test rather than continuous sampling, especially for retained salt values.

The Backyard Ring live-view card (`camera.backyard_live_view`) follows the
readings, alongside sample age and reading status. Controls, heating settings,
and equipment maintenance appear below. Ring streaming depends on the configured
integration and cloud connection; tapping the card opens its camera details.

Every gauge is shown only for a numeric sensor state. An identically sized
"Reading unavailable" card replaces it for missing, `unknown`, `unavailable`,
or nonnumeric readings, then disappears automatically when data returns.
Missing readings are never converted to zero. Salt is deliberately different:
the integration retains its last valid observation, persists it across restarts,
and exposes `stale`, `last_successful_reading`, and `update_status` attributes.
The dashboard labels salt as "last reported" and displays a prominent warning
and the original confirmation time when a poll cannot update it. Failed polls
never advance that timestamp. No value is fabricated when no history exists.
The cache is scoped to the configuration entry and controller serial; it cannot
be carried over to a different pool. Other readings are not cached by this change.

WebTouch can connect without rendering salt; this has been observed while the
chlorinator reports standby. This display fallback does not fix that upstream
omission or change any equipment settings. Existing installations can seed the
new cache from a verified recorder observation (including its actual timestamp);
never seed it from the dashboard target or a guessed value.

Run regression checks with `python3 -m unittest discover -s tests -v`.

The salt gauge highlights the **3,000–3,500 ppm** range recommended in the
[Jandy AquaPure/PureLink manual, section 4.7](https://www.jandy.com/-/media/zodiac/global/downloads/jandy/water-sanitizers/h0325600.pdf).
The dashboard suggests **about 3,200 ppm** as a practical aim within that range;
this is not a separate manufacturer-specified exact setpoint. Salt's yellow/red
margins are dashboard attention bands, not manufacturer limits.

Chemistry and skimmer-flow gauges use the **pool-specific ranges returned by
WaterGuru's dashboard service**, captured October 3, 2026. These take precedence
over generic chemistry charts. The vendor's `GREEN_NORMAL` becomes the labeled
target; `GREEN_MIN` and `GREEN_MAX` define the green band. Yellow/red bands also
come from its `floatRanges`/`intRanges`, not invented warning margins.

| Reading | Target | Green range | Yellow outer bounds | Scale |
|---|---:|---|---|---|
| Free chlorine (ppm) | 3 | 1.6–5.4 | 0.6–8.4 | 0–10 |
| pH | 7.6 | 7.5–7.7 | 7.3–7.9 | 6.5–8.5 |
| Alkalinity (ppm) | 80 | 50–130 | 40–160 | 0–240 |
| Stabilizer/CYA (ppm) | 65 | 30–100 | 20–200 | 0–300 |
| Calcium hardness (ppm) | 400 | 300–500 | 200–800 | 0–1,600 |
| Skimmer flow (gal/min) | 15 | 5–79 | 2–89 | 0–90 |

Green takes precedence inside the yellow outer bounds; readings beyond the
yellow outer bounds are red. Upper transitions use a 0.01 offset so inclusive
vendor maxima remain in their band at the sensors' reported precision.
Temperature remains neutral blue. Gauge bands are a **static snapshot** and
should be refreshed if WaterGuru changes the pool's configuration; live sensor
readings continue to update normally.

[WaterGuru's saltwater guidance](https://support.waterguru.com/hc/en-us/articles/52236844676635-Why-does-WaterGuru-recommend-a-Calcium-Hardness-level-of-400-ppm-for-my-Saltwater-chlorine-generator-pool)
independently confirms pH 7.6 and calcium hardness 400 ppm targets. Its
[CYA guidance](https://support.waterguru.com/hc/en-us/articles/4413641143323-Low-Cyanuric-Acid-CYA-Advice)
explains that the target depends on sunlight and pool cover. These are this
account's display ranges, not universal dosing or swimming-safety limits.
Interpret chlorine alongside stabilizer, sample age, and WaterGuru advice.

### Optional dashboard artwork

The `assets/aquapure-salt-hero.png` image is included for a Home Assistant
`picture-elements` card. Copy it to Home Assistant's `config/www` directory and
reference it as `/local/aquapure-salt-hero.png`; a `state-label` for the salt
sensor can then be positioned over the blank panel on the carton.
