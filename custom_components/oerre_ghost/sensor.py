"""Sensors: temperature, humidity, plus diagnostics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import OerreConfigEntry
from .entity import OerreEntity, setup_platform_entities
from .hub import UnitState
from .protocol import AIR_QUALITY_LEVELS, FILTER_LEVELS, MODES


@dataclass(frozen=True, kw_only=True)
class OerreSensorDescription(SensorEntityDescription):
    value_fn: Callable[[UnitState], str | int | None]


SENSORS = (
    OerreSensorDescription(
        key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda u: u.status.temperature,
    ),
    OerreSensorDescription(
        key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda u: u.status.humidity,
    ),
    OerreSensorDescription(
        key="filter",
        device_class=SensorDeviceClass.ENUM,
        options=FILTER_LEVELS,
        value_fn=lambda u: FILTER_LEVELS[u.status.filter]
        if 0 <= u.status.filter < len(FILTER_LEVELS)
        else None,
    ),
    OerreSensorDescription(
        key="air_quality",
        device_class=SensorDeviceClass.ENUM,
        options=AIR_QUALITY_LEVELS,
        value_fn=lambda u: AIR_QUALITY_LEVELS[u.status.air_quality]
        if 0 <= u.status.air_quality < len(AIR_QUALITY_LEVELS)
        else None,
    ),
    OerreSensorDescription(
        key="active_mode",
        device_class=SensorDeviceClass.ENUM,
        options=list(MODES.values()),
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda u: MODES.get(u.status.active_mode),
    ),
    OerreSensorDescription(
        key="air_quality_raw",  # last byte, meaning unknown
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda u: u.status.air_quality_raw,
    ),
    OerreSensorDescription(
        key="raw_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda u: u.status.raw[8:].hex(" "),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: OerreConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    setup_platform_entities(
        hass,
        entry.runtime_data,
        async_add_entities,
        lambda hub, mac: [OerreSensor(hub, mac, d) for d in SENSORS],
        entry.async_on_unload,
    )


class OerreSensor(OerreEntity, SensorEntity):
    entity_description: OerreSensorDescription

    def __init__(self, hub, mac, description: OerreSensorDescription) -> None:
        super().__init__(hub, mac, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        if self.unit.status is None:
            return None
        return self.entity_description.value_fn(self.unit)
