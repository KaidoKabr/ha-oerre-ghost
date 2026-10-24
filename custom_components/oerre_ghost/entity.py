"""Base entity for Oerre Ghost units."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .hub import OerreHub, UnitState


class OerreEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: OerreHub, mac: str, key: str) -> None:
        self.hub = hub
        self.mac = mac
        self._attr_unique_id = f"{mac}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mac)},
            connections={(CONNECTION_NETWORK_MAC, mac)},
            manufacturer="O.ERRE",
            model="Ghost App",
            name=f"Oerre Ghost {mac[-5:].replace(':', '').upper()}",
        )

    @property
    def unit(self) -> UnitState:
        return self.hub.units[self.mac]

    @property
    def available(self) -> bool:
        return self.unit.connected and self.unit.status is not None

    async def async_added_to_hass(self) -> None:
        @callback
        def _update(mac: str) -> None:
            if mac == self.mac:
                self.async_write_ha_state()

        self.async_on_remove(self.hub.add_listener(_update))


def setup_platform_entities(
    hass: HomeAssistant,
    hub: OerreHub,
    async_add_entities: AddEntitiesCallback,
    factory: Callable[[OerreHub, str], list[Entity]],
    on_unload: Callable[[Callable[[], None]], None],
) -> None:
    """Add entities for known units now and for new units as they appear."""
    entities: list[Entity] = []
    for mac in hub.units:
        entities.extend(factory(hub, mac))
    async_add_entities(entities)

    @callback
    def _new_unit(mac: str) -> None:
        async_add_entities(factory(hub, mac))

    on_unload(hub.add_new_unit_listener(_new_unit))
