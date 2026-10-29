"""Polls the DSL status page."""
from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import InvalidAuth, VigorClient, VigorError
from .const import DOMAIN, LOGIN_REJECTIONS_BEFORE_REAUTH, SCAN_INTERVAL_SECONDS
from .protocol import DslStatus

_LOGGER = logging.getLogger(__name__)

type VigorConfigEntry = ConfigEntry[VigorCoordinator]


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
        self._login_rejections = 0

    async def _async_update_data(self) -> DslStatus:
        try:
            data = await self.client.async_get_dsl_status()
        except InvalidAuth as err:
            # A rejected login can also mean "too many sessions" or a temporary
            # lockout, so only ask for a new password when it keeps happening.
            self._login_rejections += 1
            if self._login_rejections >= LOGIN_REJECTIONS_BEFORE_REAUTH:
                raise ConfigEntryAuthFailed(str(err)) from err
            raise UpdateFailed(str(err)) from err
        except VigorError as err:
            raise UpdateFailed(str(err)) from err
        self._login_rejections = 0
        return data
