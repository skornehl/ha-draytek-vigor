"""DSL sync and LAN port links as connectivity sensors."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import VigorConfigEntry, VigorCoordinator
from .entity import VigorEntity
from .protocol import PORT_DOWN


async def async_setup_entry(
    hass: HomeAssistant, entry: VigorConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [VigorSyncSensor(coordinator, "dsl_sync")]
    if (system := coordinator.data.system) is not None:
        entities += [VigorPortLinkSensor(coordinator, port) for port in system.ports]
    async_add_entities(entities)


class VigorSyncSensor(VigorEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.synced


class VigorPortLinkSensor(VigorEntity, BinarySensorEntity):
    """Link on a LAN port, from the port LEDs on the dashboard."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator: VigorCoordinator, port: str) -> None:
        super().__init__(coordinator, f"{port.lower()}_link", "lan_link", {"port": port})
        self._port = port

    @property
    def is_on(self) -> bool | None:
        system = self.coordinator.data.system
        if system is None or (link := system.ports.get(self._port)) is None:
            return None
        return link != PORT_DOWN
