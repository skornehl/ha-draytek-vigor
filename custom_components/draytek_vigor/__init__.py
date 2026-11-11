"""DrayTek Vigor: DSL line values of a Vigor 167 modem."""
from __future__ import annotations

import aiohttp

from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    EVENT_HOMEASSISTANT_STOP,
    Platform,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import VigorClient
from .const import DOMAIN
from .coordinator import VigorConfigEntry, VigorCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR]
RATE_KEYS = ("rate_down", "rate_up", "attainable_down", "attainable_up")
KBIT = "kbit/s"


@callback
def _rates_to_suggested_unit(hass: HomeAssistant, entry: VigorConfigEntry) -> None:
    """Show rate sensors from before 0.3.0 in Mbit/s, like new ones.

    When 0.3.0 added Mbit/s as suggested unit, Home Assistant kept kbit/s for
    existing entities by storing it as their suggested unit. Ask it once to
    recompute that from the integration; a unit the user picked in the entity
    settings ("sensor" options) is left alone. History is converted by HA.
    """
    registry = er.async_get(hass)
    for key in RATE_KEYS:
        entity_id = registry.async_get_entity_id(Platform.SENSOR, DOMAIN, f"{entry.entry_id}_{key}")
        if entity_id is None or (reg := registry.async_get(entity_id)) is None:
            continue
        if "unit_of_measurement" in reg.options.get("sensor", {}):
            continue
        # Upgraded to 0.3.x: kbit/s stored as suggested unit. Coming straight
        # from 0.2.x: no sensor.private yet, kbit/s only as registry unit.
        if "sensor.private" in reg.options:
            current = reg.options["sensor.private"].get("suggested_unit_of_measurement")
        else:
            current = reg.unit_of_measurement
        if current != KBIT:
            continue
        registry.async_update_entity_options(
            entity_id, "sensor.private", {"refresh_initial_entity_options": True}
        )


def create_client(hass: HomeAssistant, data: dict, auto_cleanup: bool = True) -> VigorClient:
    # Own session: the router's cookie must not leak into HA's shared jar, and
    # unsafe=True is needed to keep cookies set by an IP address. HA owns the
    # session: during entry setup it is detached on unload (auto_cleanup); the
    # config flow passes auto_cleanup=False and detaches it via async_close.
    # Never close() it - HA warns, the connector is shared.
    # Entries from before 0.3.0 have no CONF_SSL and keep plain HTTP. The
    # modem's own certificate is self-signed (and expired), so verification
    # is only on when the user asks for it.
    session = async_create_clientsession(
        hass,
        verify_ssl=data.get(CONF_VERIFY_SSL, False),
        auto_cleanup=auto_cleanup,
        cookie_jar=aiohttp.CookieJar(unsafe=True),
    )
    return VigorClient(
        session,
        normalize_host(data[CONF_HOST]),
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        use_https=data.get(CONF_SSL, False),
    )


def normalize_host(host: str) -> str:
    """'  HTTP://Vigor.local/ ' -> 'vigor.local'."""
    host = host.strip().lower()
    for prefix in ("http://", "https://"):
        host = host.removeprefix(prefix)
    return host.rstrip("/")


async def async_setup_entry(hass: HomeAssistant, entry: VigorConfigEntry) -> bool:
    # The logout is awaited here and in async_unload_entry, never registered
    # with async_on_unload: HA only starts on_unload coroutines as tasks and
    # detaches the session right after, so the logout request died half-way
    # (AttributeError '_timeout_ceil_threshold', "Unclosed connection") and
    # the web session stayed open on the modem.
    client = create_client(hass, entry.data)

    async def _logout_on_stop(_event: Event) -> None:
        # Entries are not unloaded on shutdown; log out so restarts do not
        # leave web sessions behind on the modem.
        await client.async_logout()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _logout_on_stop))
    coordinator = VigorCoordinator(hass, entry, client)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        # Not ready or reauth: the setup is retried with a new client.
        await client.async_logout()
        raise
    entry.runtime_data = coordinator
    _rates_to_suggested_unit(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: VigorConfigEntry) -> bool:
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.client.async_logout()
    return unloaded
