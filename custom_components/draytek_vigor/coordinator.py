"""Polls the DSL status page."""
from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util.hass_dict import HassKey

from .api import InvalidAuth, VigorClient, VigorError
from .const import DOMAIN, LOGIN_REJECTIONS_BEFORE_REAUTH, SCAN_INTERVAL_SECONDS
from .protocol import DslStatus

_LOGGER = logging.getLogger(__name__)

type VigorConfigEntry = ConfigEntry[VigorCoordinator]

# Rejected logins in a row, per config entry. Kept outside the coordinator: a
# failing first refresh retries the whole setup with a new coordinator, and a
# counter on the coordinator would restart at zero every time, so a password
# changed while Home Assistant was down never led to reauth.
LOGIN_REJECTIONS: HassKey[dict[str, int]] = HassKey(f"{DOMAIN}_login_rejections")


class VigorCoordinator(DataUpdateCoordinator[DslStatus]):
    config_entry: VigorConfigEntry

    def __init__(self, hass: HomeAssistant, entry: VigorConfigEntry, client: VigorClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )
        self.client = client
        self._rejections = hass.data.setdefault(LOGIN_REJECTIONS, {})

    async def _async_update_data(self) -> DslStatus:
        entry_id = self.config_entry.entry_id
        try:
            data = await self.client.async_get_dsl_status()
        except InvalidAuth as err:
            # A rejected login can also mean "too many sessions" or a temporary
            # lockout, so only ask for a new password when it keeps happening.
            rejections = self._rejections.get(entry_id, 0) + 1
            if rejections >= LOGIN_REJECTIONS_BEFORE_REAUTH:
                # Start over once the reauth flow has reloaded the entry.
                self._rejections.pop(entry_id, None)
                raise ConfigEntryAuthFailed(str(err)) from err
            self._rejections[entry_id] = rejections
            raise UpdateFailed(str(err)) from err
        except VigorError as err:
            raise UpdateFailed(str(err)) from err
        self._rejections.pop(entry_id, None)
        return data
