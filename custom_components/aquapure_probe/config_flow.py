"""Configuration flow for the read-only AquaPure probe."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_EMAIL, CONF_PASSWORD, DOMAIN
from .coordinator import async_read_probe


class AquaPureProbeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Collect iAquaLink credentials through Home Assistant's normal form."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                result = await async_read_probe(user_input)
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(f"aquapure_probe_{result['serial']}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"AquaPure Probe — {result['system_name']}",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )
