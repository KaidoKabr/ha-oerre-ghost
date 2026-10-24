"""Connectivity binary sensor."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import OerreConfigEntry
from .entity import OerreEntity, setup_platform_entities


async def async_setup_entry(
    hass: HomeAssistant, entry: OerreConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    setup_platform_entities(
        hass,
        entry.runtime_data,
        async_add_entities,
        lambda hub, mac: [OerreConnected(hub, mac)],
        entry.async_on_unload,
    )


class OerreConnected(OerreEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hub, mac) -> None:
        super().__init__(hub, mac, "connected")

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self.unit.connected

    @property
    def extra_state_attributes(self):
        u = self.unit
        return {"ip": u.ip, "hello": u.hello.hex(" ") if u.hello else None}
