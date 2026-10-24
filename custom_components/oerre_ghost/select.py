"""Select entities: mode, humidity threshold, twilight sensor."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import OerreConfigEntry
from .entity import OerreEntity, setup_platform_entities
from .protocol import HUMIDITY_LEVELS, MODE_CODES, MODES, TWILIGHT_LEVELS, TWILIGHT_OFFSET


async def async_setup_entry(
    hass: HomeAssistant, entry: OerreConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    setup_platform_entities(
        hass,
        entry.runtime_data,
        async_add_entities,
        lambda hub, mac: [
            ModeSelect(hub, mac),
            HumiditySelect(hub, mac),
            TwilightSelect(hub, mac),
        ],
        entry.async_on_unload,
    )


class _Base(OerreEntity, SelectEntity):
    async def _send(self, **kwargs) -> None:
        try:
            await self.hub.async_set(self.mac, **kwargs)
        except ConnectionError as err:
            raise HomeAssistantError(str(err)) from err


class ModeSelect(_Base):
    _attr_options = list(MODES.values())

    def __init__(self, hub, mac) -> None:
        super().__init__(hub, mac, "mode")

    @property
    def current_option(self) -> str | None:
        st = self.unit.status
        return MODES.get(st.mode) if st else None

    async def async_select_option(self, option: str) -> None:
        await self._send(mode=MODE_CODES[option])


class HumiditySelect(_Base):
    _attr_options = HUMIDITY_LEVELS
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hub, mac) -> None:
        super().__init__(hub, mac, "humidity_threshold")

    @property
    def current_option(self) -> str | None:
        st = self.unit.status
        if st is None or not 0 <= st.humidity_threshold < len(HUMIDITY_LEVELS):
            return None
        return HUMIDITY_LEVELS[st.humidity_threshold]

    async def async_select_option(self, option: str) -> None:
        await self._send(humidity_threshold=HUMIDITY_LEVELS.index(option))


class TwilightSelect(_Base):
    _attr_options = TWILIGHT_LEVELS
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hub, mac) -> None:
        super().__init__(hub, mac, "twilight_sensor")

    @property
    def current_option(self) -> str | None:
        st = self.unit.status
        if st is None:
            return None
        idx = st.twilight - TWILIGHT_OFFSET
        return TWILIGHT_LEVELS[idx] if 0 <= idx < len(TWILIGHT_LEVELS) else None

    async def async_select_option(self, option: str) -> None:
        await self._send(twilight=TWILIGHT_LEVELS.index(option) + TWILIGHT_OFFSET)
