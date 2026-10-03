"""Constants for the read-only AquaPure probe."""

from datetime import timedelta

DOMAIN = "aquapure_probe"
PLATFORMS = ["sensor"]

CONF_EMAIL = "email"
CONF_PASSWORD = "password"

UPDATE_INTERVAL = timedelta(minutes=30)

# These are intentionally read commands. Do not add write commands to this
# diagnostic integration.
COMMAND_GET_HOME = "get_home"
COMMAND_GET_SWC_CONFIG = "get_swc_config"
