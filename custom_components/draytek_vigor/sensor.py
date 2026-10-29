"""DSL line sensors."""
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
from homeassistant.const import EntityCategory, UnitOfDataRate, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import VigorConfigEntry
from .entity import VigorEntity
from .protocol import DslStatus

DB = "dB"
DOWN, UP, NEAR, FAR = 0, 1, 0, 1


@dataclass(frozen=True, kw_only=True)
class VigorSensorDescription(SensorEntityDescription):
    value: Callable[[DslStatus], Any]


def _stream(row: str, idx: int) -> Callable[[DslStatus], Any]:
    return lambda s: (s.stream.get(row) or (None, None))[idx]


def _end(row: str, idx: int) -> Callable[[DslStatus], Any]:
    return lambda s: (s.end.get(row) or (None, None))[idx]


def _rate(key: str, row: str, idx: int, **kw: Any) -> VigorSensorDescription:
    return VigorSensorDescription(
        key=key,
        value=_stream(row, idx),
        native_unit_of_measurement=UnitOfDataRate.KILOBITS_PER_SECOND,
        device_class=SensorDeviceClass.DATA_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        **kw,
    )


def _db(key: str, value: Callable[[DslStatus], Any]) -> VigorSensorDescription:
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


SENSORS: tuple[VigorSensorDescription, ...] = (
    VigorSensorDescription(key="line_status", value=lambda s: s.status),
    VigorSensorDescription(key="mode", value=lambda s: s.mode, entity_category=EntityCategory.DIAGNOSTIC),
    VigorSensorDescription(key="profile", value=lambda s: s.profile, entity_category=EntityCategory.DIAGNOSTIC),
    VigorSensorDescription(key="annex", value=lambda s: s.annex, entity_category=EntityCategory.DIAGNOSTIC),
    VigorSensorDescription(
        key="dsl_version", value=lambda s: s.dsl_version, entity_category=EntityCategory.DIAGNOSTIC
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
        _counter(f"{name.lower()}_{side}", name, idx, seconds)
        for name, seconds in (("CRC", False), ("ES", True), ("SES", True), ("UAS", True))
        for side, idx in (("near", NEAR), ("far", FAR))
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: VigorConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(VigorSensor(entry.runtime_data, d) for d in SENSORS)


class VigorSensor(VigorEntity, SensorEntity):
    entity_description: VigorSensorDescription

    def __init__(self, coordinator, description: VigorSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value(self.coordinator.data)
