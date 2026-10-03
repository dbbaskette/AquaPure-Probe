"""AquaPure Probe integration setup."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import PLATFORMS
from .coordinator import AquaPureProbeCoordinator

AquaPureProbeConfigEntry = ConfigEntry[AquaPureProbeCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: AquaPureProbeConfigEntry) -> bool:
    """Set up the read-only diagnostic probe from a config entry."""
    coordinator = AquaPureProbeCoordinator(hass, entry.data)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AquaPureProbeConfigEntry) -> bool:
    """Unload the diagnostic probe."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
