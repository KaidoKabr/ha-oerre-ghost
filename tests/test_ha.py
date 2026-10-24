"""Run the integration inside a real Home Assistant test instance."""

import asyncio
import socket

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.oerre_ghost.const import DOMAIN
from custom_components.oerre_ghost.protocol import build_command

MAC = "aa:bb:cc:00:00:01"
HELLO = bytes.fromhex("0300aabbcc00000100001c00031602010000")
STATUS_NIGHT = bytes.fromhex("0100aabbcc000001030101152600000001000003c9")
STATUS_OFF = bytes.fromhex("0100aabbcc0000010b0101152600000001000003c9")


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def socket_enabled_all(socket_enabled):
    yield


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


async def test_full_flow(hass: HomeAssistant, socket_enabled) -> None:
    cloud_rx = bytearray()

    async def cloud(reader, writer):
        while data := await reader.read(1024):
            cloud_rx.extend(data)

    cloud_srv = await asyncio.start_server(cloud, "127.0.0.1", 0)
    cloud_port = cloud_srv.sockets[0].getsockname()[1]
    port = _free_port()

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"listen_port": port, "upstream_host": "127.0.0.1",
         "upstream_port": cloud_port, "app_port": 0},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    r, w = await asyncio.open_connection("127.0.0.1", port)
    w.write(HELLO + STATUS_NIGHT)
    await w.drain()
    for _ in range(20):
        await asyncio.sleep(0.05)
        await hass.async_block_till_done()

    assert bytes(cloud_rx) == HELLO + STATUS_NIGHT
    ent = er.async_get(hass)
    fan_id = ent.async_get_entity_id("fan", DOMAIN, f"{MAC}_ventilation")
    temp_id = ent.async_get_entity_id("sensor", DOMAIN, f"{MAC}_temperature")
    mode_id = ent.async_get_entity_id("select", DOMAIN, f"{MAC}_mode")
    print(fan_id, temp_id, mode_id)
    assert hass.states.get(temp_id).state == "21"
    hum_id = ent.async_get_entity_id("sensor", DOMAIN, f"{MAC}_humidity")
    assert hass.states.get(hum_id).state == "38"
    fan = hass.states.get(fan_id)
    assert fan.state == "on"
    assert fan.attributes["preset_mode"] == "night"
    assert fan.attributes["percentage"] == 66
    assert hass.states.get(mode_id).state == "night"

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.data["known_macs"] == [MAC]

    await hass.services.async_call(
        "fan", "set_percentage", {"entity_id": fan_id, "percentage": 100}, blocking=True
    )
    assert await asyncio.wait_for(r.readexactly(14), 2) == build_command(MAC, 3, 2, 1, 3)

    await hass.services.async_call(
        "select", "select_option", {"entity_id": mode_id, "option": "manual"}, blocking=True
    )
    assert await asyncio.wait_for(r.readexactly(14), 2) == build_command(MAC, 2, 1, 1, 3)

    tw_id = ent.async_get_entity_id("select", DOMAIN, f"{MAC}_twilight_sensor")
    await hass.services.async_call(
        "select", "select_option", {"entity_id": tw_id, "option": "off"}, blocking=True
    )
    assert await asyncio.wait_for(r.readexactly(14), 2) == build_command(MAC, 3, 1, 1, 1)

    await hass.services.async_call("fan", "turn_off", {"entity_id": fan_id}, blocking=True)
    assert await asyncio.wait_for(r.readexactly(14), 2) == build_command(MAC, 0x0B, 1, 1, 3)

    # unit reports off; turning on restores last mode (night)
    w.write(STATUS_OFF)
    await w.drain()
    for _ in range(10):
        await asyncio.sleep(0.05)
        await hass.async_block_till_done()
    assert hass.states.get(fan_id).state == "off"
    await hass.services.async_call("fan", "turn_on", {"entity_id": fan_id}, blocking=True)
    assert await asyncio.wait_for(r.readexactly(14), 2) == build_command(MAC, 3, 1, 1, 3)

    btn_id = ent.async_get_entity_id("button", DOMAIN, f"{MAC}_reset_filter")
    await hass.services.async_call("button", "press", {"entity_id": btn_id}, blocking=True)
    assert await asyncio.wait_for(r.readexactly(9), 2) == bytes.fromhex("0200aabbcc00000103")
    filt_id = ent.async_get_entity_id("sensor", DOMAIN, f"{MAC}_filter")
    assert hass.states.get(filt_id).state == "ok"

    w.close()
    for _ in range(10):
        await asyncio.sleep(0.05)
        await hass.async_block_till_done()
    assert hass.states.get(fan_id).state == "unavailable"
    conn_id = ent.async_get_entity_id("binary_sensor", DOMAIN, f"{MAC}_connected")
    assert hass.states.get(conn_id).state == "off"

    # reload keeps entities from known_macs
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(fan_id).state == "unavailable"

    assert await hass.config_entries.async_unload(entry.entry_id)
    cloud_srv.close()
