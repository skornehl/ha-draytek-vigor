"""Polls the DSL status page and the dashboard."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.hass_dict import HassKey

from .api import InvalidAuth, VigorClient, VigorError
from .const import DOMAIN, LOGIN_REJECTIONS_BEFORE_REAUTH, SCAN_INTERVAL_SECONDS, SYNC_STATUS
from .protocol import DslStatus, SystemStatus

_LOGGER = logging.getLogger(__name__)

type VigorConfigEntry = ConfigEntry[VigorCoordinator]

# Rejected logins in a row, per config entry. Kept outside the coordinator: a
# failing first refresh retries the whole setup with a new coordinator, and a
# counter on the coordinator would restart at zero every time, so a password
# changed while Home Assistant was down never led to reauth.
LOGIN_REJECTIONS: HassKey[dict[str, int]] = HassKey(f"{DOMAIN}_login_rejections")

# Boot and sync times are "now - uptime", which drifts by the request time on
# every poll. Keep the previous value unless it moved by more than this, so
# the timestamp sensors only change on a real reboot or resync.
SINCE_TOLERANCE = timedelta(seconds=90)


@dataclass
class VigorData:
    dsl: DslStatus
    system: SystemStatus | None = None
    booted_at: datetime | None = None
    line_up_since: datetime | None = None

    @property
    def synced(self) -> bool | None:
        status = self.dsl.status
        return None if status is None else SYNC_STATUS in status.upper()


def _since(seconds: int | None, previous: datetime | None) -> datetime | None:
    if seconds is None:
        return None
    since = (dt_util.utcnow() - timedelta(seconds=seconds)).replace(microsecond=0)
    if previous is not None and abs(since - previous) < SINCE_TOLERANCE:
        return previous
    return since


class VigorCoordinator(DataUpdateCoordinator[VigorData]):
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

    async def _async_update_data(self) -> VigorData:
        entry_id = self.config_entry.entry_id
        try:
            dsl, system = await self.client.async_get_status()
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

        data = VigorData(dsl=dsl, system=system)
        previous = self.data
        if system is not None:
            data.booted_at = _since(system.uptime, previous.booted_at if previous else None)
            if data.synced:
                data.line_up_since = _since(system.line_uptime, previous.line_up_since if previous else None)
        return data
