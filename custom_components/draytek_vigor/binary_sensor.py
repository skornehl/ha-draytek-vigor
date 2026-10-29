"""DSL sync as a connectivity sensor."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import SYNC_STATUS
from .coordinator import VigorConfigEntry
from .entity import VigorEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: VigorConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([VigorSyncSensor(entry.runtime_data, "dsl_sync")])


class VigorSyncSensor(VigorEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self) -> bool | None:
        status = self.coordinator.data.status
        return None if status is None else SYNC_STATUS in status.upper()
