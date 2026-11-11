"""Shared base entity."""
from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_SSL
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo, format_mac
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import VigorCoordinator


class VigorEntity(CoordinatorEntity[VigorCoordinator]):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: VigorCoordinator,
        key: str,
        translation_key: str | None = None,
        placeholders: dict[str, str] | None = None,
    ) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = translation_key or key
        if placeholders:
            self._attr_translation_placeholders = placeholders
        scheme = "https" if entry.data.get(CONF_SSL) else "http"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer="DrayTek",
            model="Vigor",
            name="DrayTek Vigor",
            configuration_url=f"{scheme}://{entry.data[CONF_HOST]}",
        )
        if (system := coordinator.data.system) is not None:
            # Model and firmware come from the dashboard; the MAC lets Home
            # Assistant match the modem with e.g. a network integration.
            if system.model:
                self._attr_device_info["model"] = system.model
            if system.firmware:
                self._attr_device_info["sw_version"] = system.firmware
            if system.mac:
                self._attr_device_info["connections"] = {(CONNECTION_NETWORK_MAC, format_mac(system.mac))}
