# AquaPure Probe for Home Assistant

This is a deliberately **read-only** custom integration for testing whether a
Jandy iAquaLink controller accepts the undocumented/unsupported AquaPure cloud
read command. It issues only `get_home` and `get_swc_config`; it never sends
commands that change chlorine output, boost, schedules, or equipment state.

The probe is intended for the user's RS-8 Combo / iQ30 setup. It is not a
general-purpose, supported Jandy integration.

## What it looks for

- pool and spa AquaPure set points
- boost state and remaining timer
- salt PPM and SWC status when the cloud response supplies them

When the normal cloud response omits salt, the probe also opens the same
read-only legacy WebTouch display session used by the iAquaLink app and looks
only for the rendered `Salt … PPM` text. It does not send commands to any pool
equipment.

## Installation

Copy `custom_components/aquapure_probe` into the Home Assistant configuration
directory, restart Home Assistant, then add **AquaPure Probe** from Devices &
Services. Sign in with the existing iAquaLink account using Home Assistant's
normal configuration form.

The component uses the `iaqualink` dependency that is already used by Home
Assistant's Jandy iAquaLink integration. It does not log credentials, tokens,
or complete response bodies.
