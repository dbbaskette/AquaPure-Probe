"""Read-only coordinator for the AquaPure cloud probe."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import logging
import re
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import COMMAND_GET_HOME, COMMAND_GET_SWC_CONFIG, CONF_EMAIL, CONF_PASSWORD, DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)

_WEBTOUCH_INIT_URL = "https://prm.iaqualink.net/v2/webtouch/init"
_WEBTOUCH_COMMAND_URL = "https://prm.iaqualink.net/v2/webtouch/command"
_SALT_PATTERN = re.compile(r"\bSalt\s+(\d{3,5})\s*PPM\b", re.IGNORECASE)
_ACTION_ID_PATTERN = re.compile(r"[?&]actionID=([^&#'\"\s]+)")


def _flatten_home(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten the legacy home_screen list without retaining the raw payload."""
    flattened: dict[str, Any] = {}
    for item in payload.get("home_screen", []):
        if isinstance(item, Mapping):
            flattened.update(item)
    return flattened


async def _read_webtouch_salt(
    hass: HomeAssistant,
    client: Any,
    system: Any,
) -> tuple[int | None, str]:
    """Read the legacy WebTouch display stream without issuing equipment commands.

    WebTouch has a separate, server-pushed display protocol.  Its initial
    ``command=1`` opens that display session; it is not an AquaLink controller
    command and this code never sends a circuit, setpoint, or SWC command.
    """
    token = getattr(client, "id_token", None)
    serial = getattr(system, "serial", None)
    data = getattr(system, "data", {})
    if not token or not serial or not isinstance(data, Mapping):
        return None, "not available"

    # The app's Web launch uses a controller identifier.  Current and older
    # API responses have used either the numeric record id or serial number.
    action_ids = [str(value) for value in (data.get("id"), serial) if value]
    session = async_get_clientsession(hass)
    headers = {"Authorization": str(token)}

    async def start_data(action_id: str) -> Mapping[str, Any] | None:
        try:
            async with session.get(
                _WEBTOUCH_INIT_URL,
                params={"actionID": action_id},
                headers=headers,
                timeout=10,
            ) as response:
                if response.status != 200:
                    return None
                payload = await response.json(content_type=None)
                return payload if isinstance(payload, Mapping) else None
        except (asyncio.TimeoutError, ValueError):
            return None
        except Exception:  # A display probe must never break normal SWC data.
            return None

    async def follow_mobile_link(url: str) -> str | None:
        """Follow the app's Web handoff without retaining its signed URL."""
        try:
            async with session.get(
                url, headers=headers, allow_redirects=True, timeout=10
            ) as response:
                # Some app handoffs are HTTP redirects; others are a short
                # HTML page that performs the same redirect in JavaScript.
                query = parse_qs(urlparse(str(response.url)).query)
                action_ids = query.get("actionID")
                if action_ids:
                    return action_ids[0]
                body = await response.text()
                match = _ACTION_ID_PATTERN.search(body)
                return match.group(1) if match else None
        except (asyncio.TimeoutError, ValueError):
            return None
        except Exception:
            return None

    for action_id in dict.fromkeys(action_ids):
        init_data = await start_data(action_id)
        if init_data is None:
            continue

        # The mobile app may turn the controller identifier into a short-lived
        # display action ID before the actual WebTouch session is initialized.
        # Follow only that signed handoff and keep no URL, token, or body.
        mobile_link = init_data.get("mobileTouchUrl")
        if isinstance(mobile_link, str):
            redirected_action = await follow_mobile_link(mobile_link)
            if not redirected_action:
                continue
            init_data = await start_data(redirected_action)
            if init_data is None:
                continue

        stream_url = init_data.get("serverConnection")
        start_action = init_data.get("actionIdMasterStart")
        if not isinstance(stream_url, str) or not isinstance(start_action, str):
            continue

        async def consume_stream() -> int | None:
            text = ""
            try:
                async with session.get(
                    stream_url, headers=headers, timeout=12
                ) as stream:
                    if stream.status != 200:
                        return None
                    async for chunk in stream.content.iter_any():
                        text = (text + chunk.decode("utf-8", "ignore"))[-16384:]
                        match = _SALT_PATTERN.search(text)
                        if match:
                            return int(match.group(1))
            except (asyncio.TimeoutError, ValueError):
                return None
            return None

        stream_task = asyncio.create_task(consume_stream())
        try:
            # This mirrors the WebTouch browser's initial display handshake.
            # It starts no pool equipment and carries no equipment identifier.
            async with session.post(
                _WEBTOUCH_COMMAND_URL,
                json={
                    "actionID": start_action,
                    "command": "1",
                    "dt": str(round(time.time() * 1000)),
                },
                headers=headers,
                timeout=10,
            ) as response:
                if response.status != 200:
                    stream_task.cancel()
                    await asyncio.gather(stream_task, return_exceptions=True)
                    continue
            salt = await stream_task
            return salt, "connected" if salt is not None else "connected; salt not rendered"
        except (asyncio.TimeoutError, ValueError):
            stream_task.cancel()
            await asyncio.gather(stream_task, return_exceptions=True)
        except Exception:
            stream_task.cancel()
            await asyncio.gather(stream_task, return_exceptions=True)

    return None, "not available"


async def async_read_probe(
    hass: HomeAssistant, credentials: Mapping[str, str]
) -> dict[str, Any]:
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
            webtouch_salt, webtouch_status = await _read_webtouch_salt(
                hass, client, system
            )
            return {
                "serial": str(getattr(system, "serial", "unknown")),
                "system_name": str(getattr(system, "name", "Pool")),
                "pool_output": swc.get("poolSWCSP", home.get("swc_set_point")),
                "spa_output": swc.get("spaSWCSP"),
                "boost_status": swc.get("boostStatus", home.get("swc_boost")),
                "boost_hours_remaining": swc.get("remainingBoostHrs"),
                "boost_minutes_remaining": swc.get("remainingBoostMins"),
                "salt_ppm": home.get("pool_salinity") or webtouch_salt,
                "swc_status": (home.get("swc_info") or {}).get("swcPoolStatus"),
                "low_salt": home.get("swc_low"),
                "probe_response": swc.get("response"),
                "webtouch_status": webtouch_status,
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
            return await async_read_probe(self.hass, self.credentials)
        except HomeAssistantError as err:
            raise UpdateFailed(str(err)) from err
