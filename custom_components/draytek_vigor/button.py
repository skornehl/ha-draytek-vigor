"""Modem reboot button."""
from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import VigorError
from .coordinator import VigorConfigEntry
from .entity import VigorEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: VigorConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([VigorRebootButton(entry.runtime_data, "reboot")])


class VigorRebootButton(VigorEntity, ButtonEntity):
    """Reboots the modem; DSL resyncs, the router behind it dials in again."""

    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG

    @property
    def available(self) -> bool:
        # Stay usable when polling fails - that is when a reboot is needed most.
        return True

    async def async_press(self) -> None:
        try:
            await self.coordinator.client.async_reboot()
        except VigorError as err:
            raise HomeAssistantError(f"Reboot failed: {err}") from err
