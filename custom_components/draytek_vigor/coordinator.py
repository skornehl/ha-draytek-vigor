"""Polls the DSL status page."""
from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import InvalidAuth, VigorClient, VigorError
from .const import DOMAIN, SCAN_INTERVAL_SECONDS
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

    async def _async_update_data(self) -> DslStatus:
        try:
            return await self.client.async_get_dsl_status()
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except VigorError as err:
            raise UpdateFailed(str(err)) from err
