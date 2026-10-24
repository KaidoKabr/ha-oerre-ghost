"""Fan entity: on/off, 3 speeds, mode as preset."""

from __future__ import annotations

from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.percentage import (
    ordered_list_item_to_percentage,
    percentage_to_ordered_list_item,
)

from . import OerreConfigEntry
from .entity import OerreEntity, setup_platform_entities
from .protocol import MODE_CODES, MODE_OFF, MODES, SPEEDS

PRESETS = [name for code, name in MODES.items() if code != MODE_OFF]


async def async_setup_entry(
    hass: HomeAssistant, entry: OerreConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    setup_platform_entities(
        hass,
        entry.runtime_data,
        async_add_entities,
        lambda hub, mac: [OerreFan(hub, mac)],
        entry.async_on_unload,
    )


class OerreFan(OerreEntity, FanEntity):
    _attr_name = None  # main entity of the device
    _attr_speed_count = len(SPEEDS)
    _attr_preset_modes = PRESETS
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.PRESET_MODE
        | FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
    )

    def __init__(self, hub, mac) -> None:
        super().__init__(hub, mac, "ventilation")
        self._attr_translation_key = "ventilation"

    @property
    def is_on(self) -> bool | None:
        st = self.unit.status
        return None if st is None else st.mode != MODE_OFF

    @property
    def percentage(self) -> int | None:
        st = self.unit.status
        if st is None or st.mode == MODE_OFF or not 0 <= st.speed < len(SPEEDS):
            return 0 if st else None
        return ordered_list_item_to_percentage(SPEEDS, SPEEDS[st.speed])

    @property
    def preset_mode(self) -> str | None:
        st = self.unit.status
        if st is None or st.mode == MODE_OFF:
            return None
        return MODES.get(st.mode)

    async def _send(self, **kwargs: Any) -> None:
        try:
            await self.hub.async_set(self.mac, **kwargs)
        except ConnectionError as err:
            raise HomeAssistantError(str(err)) from err

    async def async_set_percentage(self, percentage: int) -> None:
        if percentage == 0:
            await self.async_turn_off()
            return
        speed = SPEEDS.index(percentage_to_ordered_list_item(SPEEDS, percentage))
        kwargs: dict[str, Any] = {"speed": speed}
        if not self.is_on:
            kwargs["mode"] = self.unit.last_on_mode
        await self._send(**kwargs)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        await self._send(mode=MODE_CODES[preset_mode])

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        cmd: dict[str, Any] = {
            "mode": MODE_CODES[preset_mode] if preset_mode else self.unit.last_on_mode
        }
        if percentage:
            cmd["speed"] = SPEEDS.index(percentage_to_ordered_list_item(SPEEDS, percentage))
        await self._send(**cmd)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._send(mode=MODE_OFF)
