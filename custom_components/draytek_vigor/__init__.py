"""DrayTek Vigor: DSL line values of a Vigor 167 modem."""
from __future__ import annotations

import aiohttp

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import VigorClient
from .coordinator import VigorConfigEntry, VigorCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]


def create_client(hass: HomeAssistant, data: dict) -> VigorClient:
    # Own session: the router's cookie must not leak into HA's shared jar, and
    # unsafe=True is needed to keep cookies set by an IP address.
    # Closed by the caller (entry unload, end of config-flow validation).
    session = async_create_clientsession(hass, cookie_jar=aiohttp.CookieJar(unsafe=True))
    return VigorClient(session, normalize_host(data[CONF_HOST]), data[CONF_USERNAME], data[CONF_PASSWORD])


def normalize_host(host: str) -> str:
    """'  HTTP://Vigor.local/ ' -> 'vigor.local'."""
    host = host.strip().lower()
    for prefix in ("http://", "https://"):
        host = host.removeprefix(prefix)
    return host.rstrip("/")


async def async_setup_entry(hass: HomeAssistant, entry: VigorConfigEntry) -> bool:
    client = create_client(hass, entry.data)
    entry.async_on_unload(client.async_close)
    coordinator = VigorCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: VigorConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
