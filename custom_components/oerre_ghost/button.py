"""Filter reset button."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
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
        lambda hub, mac: [ResetFilterButton(hub, mac)],
        entry.async_on_unload,
    )


class ResetFilterButton(OerreEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hub, mac) -> None:
        super().__init__(hub, mac, "reset_filter")

    async def async_press(self) -> None:
        try:
            await self.hub.async_reset_filter(self.mac)
        except ConnectionError as err:
            raise HomeAssistantError(str(err)) from err
