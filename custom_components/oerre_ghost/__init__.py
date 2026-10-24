"""Oerre Ghost App heat recovery units – local proxy integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    CONF_APP_PORT,
    CONF_KNOWN_MACS,
    CONF_LISTEN_PORT,
    CONF_UPSTREAM_HOST,
    CONF_UPSTREAM_PORT,
    FALLBACK_CLOUD_IP,
)
from .hub import OerreHub

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.FAN,
    Platform.SELECT,
    Platform.SENSOR,
]

type OerreConfigEntry = ConfigEntry[OerreHub]


async def async_setup_entry(hass: HomeAssistant, entry: OerreConfigEntry) -> bool:
    hub = OerreHub(
        listen_port=entry.data[CONF_LISTEN_PORT],
        upstream_host=entry.data.get(CONF_UPSTREAM_HOST) or None,
        upstream_port=entry.data[CONF_UPSTREAM_PORT],
        app_port=entry.data.get(CONF_APP_PORT, 0),
        known_macs=list(entry.data.get(CONF_KNOWN_MACS, [])),
        fallback_ip=FALLBACK_CLOUD_IP,
    )
    try:
        await hub.start()
    except OSError as err:
        await hub.stop()
        raise ConfigEntryNotReady(f"Cannot listen on port: {err}") from err

    entry.runtime_data = hub

    @callback
    def _remember_mac(mac: str) -> None:
        macs = list(entry.data.get(CONF_KNOWN_MACS, []))
        if mac not in macs:
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_KNOWN_MACS: [*macs, mac]}
            )

    entry.async_on_unload(hub.add_new_unit_listener(_remember_mac))

    async def _stop(_event) -> None:
        await hub.stop()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _stop))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OerreConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.stop()
    return unloaded
