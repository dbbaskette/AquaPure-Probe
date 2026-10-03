"""Read-only coordinator for the AquaPure cloud probe."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import COMMAND_GET_HOME, COMMAND_GET_SWC_CONFIG, CONF_EMAIL, CONF_PASSWORD, DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


def _flatten_home(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten the legacy home_screen list without retaining the raw payload."""
    flattened: dict[str, Any] = {}
    for item in payload.get("home_screen", []):
        if isinstance(item, Mapping):
            flattened.update(item)
    return flattened


async def async_read_probe(credentials: Mapping[str, str]) -> dict[str, Any]:
    """Run the two read-only requests and return normalized, non-secret data."""
    try:
        # Home Assistant packages iaqualink 0.7.x, which exposes its client
        # from the client module rather than the package root.
        from iaqualink.client import AqualinkClient
    except ImportError as err:
        raise HomeAssistantError(
            "The iaqualink library used by the Jandy integration is unavailable."
        ) from err

    client = AqualinkClient(credentials[CONF_EMAIL], credentials[CONF_PASSWORD])
    try:
        await client.login()
        systems = await client.get_systems()
        for system in systems.values():
            sender = getattr(system, "_send_session_request", None)
            if sender is None:
                continue

            # No state-changing command is called by this component.
            home_response = await sender(
                COMMAND_GET_HOME,
                {"attached_test": "true", "country": getattr(client, "country", "US")},
            )
            swc_response = await sender(COMMAND_GET_SWC_CONFIG)
            home = _flatten_home(home_response.json())
            swc = swc_response.json()
            return {
                "serial": str(getattr(system, "serial", "unknown")),
                "system_name": str(getattr(system, "name", "Pool")),
                "pool_output": swc.get("poolSWCSP", home.get("swc_set_point")),
                "spa_output": swc.get("spaSWCSP"),
                "boost_status": swc.get("boostStatus", home.get("swc_boost")),
                "boost_hours_remaining": swc.get("remainingBoostHrs"),
                "boost_minutes_remaining": swc.get("remainingBoostMins"),
                "salt_ppm": home.get("pool_salinity"),
                "swc_status": (home.get("swc_info") or {}).get("swcPoolStatus"),
                "low_salt": home.get("swc_low"),
                "probe_response": swc.get("response"),
            }
    except Exception as err:  # Vendor library has several version-specific errors.
        raise HomeAssistantError(f"AquaPure read-only probe failed: {err}") from err
    finally:
        await client.close()

    raise HomeAssistantError("No compatible iAquaLink system was found for the probe.")


class AquaPureProbeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch AquaPure diagnostic values without issuing write commands."""

    def __init__(self, hass: HomeAssistant, credentials: Mapping[str, str]) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.credentials = credentials

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await async_read_probe(self.credentials)
        except HomeAssistantError as err:
            raise UpdateFailed(str(err)) from err
