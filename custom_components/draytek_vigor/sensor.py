"""DSL line and system sensors."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfDataRate, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import VigorConfigEntry, VigorCoordinator, VigorData
from .entity import VigorEntity
from .protocol import PORT_1G, PORT_100M, PORT_DOWN

DB = "dB"
DOWN, UP, NEAR, FAR = 0, 1, 0, 1


@dataclass(frozen=True, kw_only=True)
class VigorSensorDescription(SensorEntityDescription):
    value: Callable[[VigorData], Any]


def _stream(row: str, idx: int) -> Callable[[VigorData], Any]:
    return lambda d: (d.dsl.stream.get(row) or (None, None))[idx]


def _end(row: str, idx: int) -> Callable[[VigorData], Any]:
    return lambda d: (d.dsl.end.get(row) or (None, None))[idx]


def _system(attr: str) -> Callable[[VigorData], Any]:
    return lambda d: getattr(d.system, attr) if d.system is not None else None


def _rate(key: str, row: str, idx: int) -> VigorSensorDescription:
    return VigorSensorDescription(
        key=key,
        value=_stream(row, idx),
        native_unit_of_measurement=UnitOfDataRate.KILOBITS_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        suggested_display_precision=1,
        device_class=SensorDeviceClass.DATA_RATE,
        state_class=SensorStateClass.MEASUREMENT,
    )


def _db(key: str, value: Callable[[VigorData], Any]) -> VigorSensorDescription:
    return VigorSensorDescription(
        key=key,
        value=value,
        native_unit_of_measurement=DB,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    )


def _counter(key: str, row: str, idx: int, seconds: bool) -> VigorSensorDescription:
    # Counters restart at 0 with every resync; total_increasing handles that.
    return VigorSensorDescription(
        key=key,
        value=_end(row, idx),
        native_unit_of_measurement=UnitOfTime.SECONDS if seconds else None,
        device_class=SensorDeviceClass.DURATION if seconds else None,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    )


def _percent(key: str, attr: str) -> VigorSensorDescription:
    return VigorSensorDescription(
        key=key,
        value=_system(attr),
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    )


SENSORS: tuple[VigorSensorDescription, ...] = (
    VigorSensorDescription(key="line_status", value=lambda d: d.dsl.status),
    VigorSensorDescription(key="mode", value=lambda d: d.dsl.mode, entity_category=EntityCategory.DIAGNOSTIC),
    VigorSensorDescription(key="profile", value=lambda d: d.dsl.profile, entity_category=EntityCategory.DIAGNOSTIC),
    VigorSensorDescription(key="annex", value=lambda d: d.dsl.annex, entity_category=EntityCategory.DIAGNOSTIC),
    VigorSensorDescription(
        key="dsl_version", value=lambda d: d.dsl.dsl_version, entity_category=EntityCategory.DIAGNOSTIC
    ),
    _rate("rate_down", "Actual Rate", DOWN),
    _rate("rate_up", "Actual Rate", UP),
    _rate("attainable_down", "Attainable Rate", DOWN),
    _rate("attainable_up", "Attainable Rate", UP),
    _db("snr_down", _stream("SNR Margin", DOWN)),
    _db("snr_up", _stream("SNR Margin", UP)),
    _db("attenuation_near", _end("Attenuation", NEAR)),
    _db("attenuation_far", _end("Attenuation", FAR)),
    *(
        VigorSensorDescription(
            key=f"interleave_{side}",
            value=_stream("Interleave Depth", idx),
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
        )
        for side, idx in (("down", DOWN), ("up", UP))
    ),
    *(
        _counter(f"{key}_{side}", name, idx, seconds)
        for key, name, seconds in (
            ("crc", "CRC", False),
            ("es", "ES", True),
            ("ses", "SES", True),
            ("uas", "UAS", True),
            ("hec", "HEC Errors", False),
            ("los", "LOS Failure", False),
            ("lof", "LOF Failure", False),
            ("lpr", "LPR Failure", False),
            ("lcd", "LCD Failure", False),
        )
        for side, idx in (("near", NEAR), ("far", FAR))
    ),
)

# From the dashboard; only set up when the first poll got it.
SYSTEM_SENSORS: tuple[VigorSensorDescription, ...] = (
    VigorSensorDescription(
        key="line_up_since",
        value=lambda d: d.line_up_since,
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    VigorSensorDescription(
        key="last_restart",
        value=lambda d: d.booted_at,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    _percent("cpu_usage", "cpu"),
    _percent("memory_usage", "memory"),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: VigorConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [VigorSensor(coordinator, d) for d in SENSORS]
    if (system := coordinator.data.system) is not None:
        entities += [VigorSensor(coordinator, d) for d in SYSTEM_SENSORS]
        entities += [VigorPortSpeedSensor(coordinator, port) for port in system.ports]
    async_add_entities(entities)


class VigorSensor(VigorEntity, SensorEntity):
    entity_description: VigorSensorDescription

    def __init__(self, coordinator: VigorCoordinator, description: VigorSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value(self.coordinator.data)


class VigorPortSpeedSensor(VigorEntity, SensorEntity):
    """Link speed class of a LAN port, as the port LED colour shows it."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [PORT_DOWN, PORT_100M, PORT_1G]
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: VigorCoordinator, port: str) -> None:
        super().__init__(coordinator, f"{port.lower()}_speed", "lan_speed", {"port": port})
        self._port = port

    @property
    def native_value(self) -> str | None:
        system = self.coordinator.data.system
        return None if system is None else system.ports.get(self._port)
