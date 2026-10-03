"""Read-only coordinator for the AquaPure cloud probe."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import logging
import re
import time
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from iaqualink.client import AqualinkClient

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.ssl import SSL_ALPN_HTTP11_HTTP2

from .const import (
    COMMAND_GET_HOME,
    COMMAND_GET_SWC_CONFIG,
    CONF_EMAIL,
    CONF_PASSWORD,
    DOMAIN,
    UPDATE_INTERVAL,
)
from .salt_cache import numeric_salt, retain_salt, valid_cache

_LOGGER = logging.getLogger(__name__)

_WEBTOUCH_INIT_URL = "https://prm.iaqualink.net/v2/webtouch/init"
_WEBTOUCH_COMMAND_URL = "https://prm.iaqualink.net/v2/webtouch/command"
_WEBTOUCH_V1_INIT_URL = "https://prm.iaqualink.net/webtouch/init"
_WEBTOUCH_V1_COMMAND_URL = "https://prm.iaqualink.net/webtouch/command"
_PORTAL_USER_ID_URL = "https://prm.iaqualink.net/v2/userId"
_PORTAL_LOCATIONS_URL = "https://prm.iaqualink.net/v2/users/{user_id}/locations"
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

    session = async_get_clientsession(hass)
    headers = {"Authorization": str(token)}

    async def get_portal_touch_links() -> list[str]:
        """Resolve candidate WebTouch links used by the Owner's Portal."""

        portal_headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        try:
            async with session.get(
                _PORTAL_USER_ID_URL,
                headers=portal_headers,
                timeout=10,
            ) as response:
                if response.status != 200:
                    return []
                user_payload = await response.json(content_type=None)
            if not isinstance(user_payload, Mapping):
                return []
            user_id = (
                user_payload.get("session_user_id")
                or user_payload.get("user_id")
                or user_payload.get("id")
            )
            if not user_id:
                return []

            async with session.get(
                _PORTAL_LOCATIONS_URL.format(user_id=quote(str(user_id), safe="")),
                headers=portal_headers,
                timeout=10,
            ) as response:
                if response.status != 200:
                    return []
                locations = await response.json(content_type=None)
        except (asyncio.TimeoutError, ValueError):
            return []
        except Exception:
            return []

        candidates: list[tuple[str, set[str], set[str]]] = []

        def visit(
            value: Any,
            inherited_identifiers: set[str] | None = None,
            inherited_names: set[str] | None = None,
        ) -> None:
            if isinstance(value, Mapping):
                identifiers = set(inherited_identifiers or ())
                names = set(inherited_names or ())
                identifiers.update(
                    str(candidate)
                    for key in (
                        "serial_number",
                        "serialNumber",
                        "serial",
                        "deviceId",
                        "Id",
                        "id",
                    )
                    if (candidate := value.get(key))
                )
                names.update(
                    str(candidate).casefold()
                    for key in (
                        "name",
                        "locationName",
                        "systemName",
                        "deviceName",
                        "label",
                    )
                    if (candidate := value.get(key))
                )
                touch_link = value.get("touchLink") or value.get("touch_link")
                if touch_link:
                    candidates.append((str(touch_link), identifiers, names))
                for child in value.values():
                    visit(child, identifiers, names)
            elif isinstance(value, list):
                for child in value:
                    visit(child, inherited_identifiers, inherited_names)

        visit(locations)
        system_name = str(getattr(system, "name", "")).casefold()
        preferred_links = [
            touch_link
            for touch_link, identifiers, names in candidates
            if str(serial) in identifiers or (system_name and system_name in names)
        ]
        all_links = [touch_link for touch_link, _, _ in candidates]
        return list(dict.fromkeys([*preferred_links, *all_links]))

    portal_touch_links = await get_portal_touch_links()

    # The official Owner's Portal launches WebTouch with ``device.touchLink``.
    # Keep the mobile API's record ID and serial only as compatibility fallbacks.
    action_ids = [
        str(value)
        for value in (
            *portal_touch_links,
            data.get("touchLink"),
            data.get("id"),
            serial,
        )
        if value
    ]

    async def start_data(
        action_id: str,
    ) -> tuple[Mapping[str, Any], str] | None:
        """Try both publicly shipped WebTouch authentication branches."""
        try:
            async with session.get(
                _WEBTOUCH_INIT_URL,
                params={"actionID": action_id},
                headers=headers,
                timeout=10,
            ) as response:
                if response.status != 200:
                    payload = None
                else:
                    payload = await response.json(content_type=None)
                if isinstance(payload, Mapping) and (
                    payload.get("serverConnection") or payload.get("mobileTouchUrl")
                ):
                    return payload, "v2"
        except (asyncio.TimeoutError, ValueError):
            pass
        except Exception:  # A display probe must never break normal SWC data.
            pass

        # The public WebTouch page itself supports this older sessionID route.
        # RS systems commonly use it, whereas newer systems use the OAuth path.
        session_id = getattr(client, "client_id", None)
        if not session_id:
            return None
        try:
            async with session.get(
                _WEBTOUCH_V1_INIT_URL,
                params={"actionID": action_id, "sessionID": str(session_id)},
                timeout=10,
            ) as response:
                if response.status != 200:
                    return None
                payload = await response.json(content_type=None)
                if isinstance(payload, Mapping) and (
                    payload.get("serverConnection") or payload.get("mobileTouchUrl")
                ):
                    return payload, "v1"
        except (asyncio.TimeoutError, ValueError):
            return None
        except Exception:
            return None
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

    connected_without_salt = False
    target_name = str(getattr(system, "name", "")).casefold()
    for action_id in dict.fromkeys(action_ids):
        result = await start_data(action_id)
        if result is None:
            continue
        init_data, protocol = result

        # Accounts can contain more than one pool. The initialized display's
        # label is authoritative, so do not open a different controller merely
        # because its link appeared first in the locations response.
        display_label = init_data.get("label")
        if (
            target_name
            and isinstance(display_label, str)
            and display_label.casefold() != target_name
        ):
            continue

        # The mobile app may turn the controller identifier into a short-lived
        # display action ID before the actual WebTouch session is initialized.
        # Follow only that signed handoff and keep no URL, token, or body.
        mobile_link = init_data.get("mobileTouchUrl")
        if isinstance(mobile_link, str):
            redirected_action = await follow_mobile_link(mobile_link)
            if not redirected_action:
                continue
            result = await start_data(redirected_action)
            if result is None:
                continue
            init_data, protocol = result

        stream_url = init_data.get("serverConnection")
        start_action = init_data.get("actionIdMasterStart")
        status_action = init_data.get("actionIdMasterId")
        if not isinstance(stream_url, str) or not start_action or not status_action:
            continue

        stream_started = asyncio.Event()

        async def consume_stream() -> int | None:
            text = ""
            try:
                # The official page authenticates this long-lived request with
                # the cookie set by ``init``; it does not attach the OAuth
                # header used by the command endpoint.
                async with session.get(stream_url, timeout=20) as stream:
                    if stream.status != 200:
                        return None
                    async for chunk in stream.content.iter_any():
                        stream_started.set()
                        text = (text + chunk.decode("utf-8", "ignore"))[-16384:]
                        match = _SALT_PATTERN.search(text)
                        if match:
                            return int(match.group(1))
            except (asyncio.TimeoutError, ValueError):
                return None
            return None

        stream_task = asyncio.create_task(consume_stream())
        try:
            async def send_display_command(
                action_id: Any, command_id: str
            ) -> tuple[bool, int | None]:
                """Send a WebTouch display-navigation command."""
                if protocol == "v1":
                    request = session.get(
                        _WEBTOUCH_V1_COMMAND_URL,
                        params={
                            "actionID": str(action_id),
                            "command": command_id,
                            "dt": str(round(time.time() * 1000)),
                            "sessionID": str(getattr(client, "client_id", "")),
                        },
                        timeout=10,
                    )
                else:
                    request = session.post(
                        _WEBTOUCH_COMMAND_URL,
                        json={
                            "actionID": str(action_id),
                            "command": command_id,
                            "dt": str(round(time.time() * 1000)),
                        },
                        headers=headers,
                        timeout=10,
                    )
                async with request as response:
                    body = await response.text()
                    match = _SALT_PATTERN.search(body)
                    salt = int(match.group(1)) if match else None
                    return response.status == 200, salt

            # The vendor page opens the stream first and waits 2.5 seconds
            # before sending its display-start command. Match that handshake
            # timing, then navigate to the read-only Status page where
            # AquaPure renders the salt PPM line.
            await asyncio.sleep(2.5)
            started, salt = await send_display_command(start_action, "1")
            if not started:
                stream_task.cancel()
                await asyncio.gather(stream_task, return_exceptions=True)
                continue
            connected_without_salt = True
            if salt is not None:
                stream_task.cancel()
                await asyncio.gather(stream_task, return_exceptions=True)
                return salt, "connected"

            await asyncio.wait_for(stream_started.wait(), timeout=8)
            await asyncio.sleep(1)
            status_opened, salt = await send_display_command(status_action, "6")
            if not status_opened:
                stream_task.cancel()
                await asyncio.gather(stream_task, return_exceptions=True)
                continue
            if salt is not None:
                stream_task.cancel()
                await asyncio.gather(stream_task, return_exceptions=True)
                return salt, "connected"

            salt = await stream_task
            if salt is not None:
                return salt, "connected"
        except (asyncio.TimeoutError, ValueError):
            stream_task.cancel()
            await asyncio.gather(stream_task, return_exceptions=True)
        except Exception:
            stream_task.cancel()
            await asyncio.gather(stream_task, return_exceptions=True)

    return (
        None,
        "connected; salt not rendered"
        if connected_without_salt
        else "not available",
    )


async def async_read_probe(
    hass: HomeAssistant, credentials: Mapping[str, str]
) -> dict[str, Any]:
    """Run the two read-only requests and return normalized, non-secret data."""
    client = AqualinkClient(
        credentials[CONF_EMAIL],
        credentials[CONF_PASSWORD],
        httpx_client=get_async_client(
            hass, alpn_protocols=SSL_ALPN_HTTP11_HTTP2
        ),
    )
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
            home_salt = numeric_salt(home.get("pool_salinity"))
            return {
                "serial": str(getattr(system, "serial", "unknown")),
                "system_name": str(getattr(system, "name", "Pool")),
                "pool_output": swc.get("poolSWCSP", home.get("swc_set_point")),
                "spa_output": swc.get("spaSWCSP"),
                "boost_status": swc.get("boostStatus", home.get("swc_boost")),
                "boost_hours_remaining": swc.get("remainingBoostHrs"),
                "boost_minutes_remaining": swc.get("remainingBoostMins"),
                "salt_ppm": home_salt if home_salt is not None else webtouch_salt,
                "swc_status": (home.get("swc_info") or {}).get("swcPoolStatus"),
                "low_salt": home.get("swc_low"),
                "probe_response": swc.get("response"),
                "webtouch_status": webtouch_status,
            }
    except Exception as err:  # Vendor library has several version-specific errors.
        error_name = type(err).__name__
        _LOGGER.exception("AquaPure read-only probe failed (%s)", error_name)
        raise HomeAssistantError(
            f"AquaPure read-only probe failed ({error_name})"
        ) from err
    finally:
        await client.close()

    raise HomeAssistantError("No compatible iAquaLink system was found for the probe.")


class AquaPureProbeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch AquaPure diagnostic values without issuing write commands."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=UPDATE_INTERVAL,
        )
        self.credentials = entry.data
        self._salt_cache: dict[str, Any] | None = None
        self._salt_store = Store(hass, 1, f"{DOMAIN}.salt.{entry.entry_id}")

    async def _async_setup(self) -> None:
        self._salt_cache = valid_cache(await self._salt_store.async_load())

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            data = await async_read_probe(self.hass, self.credentials)
            data["probe_available"] = True
        except HomeAssistantError as err:
            if self._salt_cache is None:
                raise UpdateFailed(str(err)) from err
            # Retain only salt on a failed poll, never stale control/status data.
            data = {
                "serial": self._salt_cache["serial"],
                "system_name": self._salt_cache["system_name"],
                "probe_available": False,
                "webtouch_status": "update failed; showing last known salt",
            }
        data, cached = retain_salt(data, self._salt_cache, dt_util.utcnow().isoformat())
        if cached != self._salt_cache:
            self._salt_cache = cached
            await self._salt_store.async_save(cached)
        return data
