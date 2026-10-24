"""Tests with bytes copied from the real tcpdump captures."""

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

PKG = Path(__file__).parents[1] / "custom_components" / "oerre_ghost"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"og.{name}", PKG / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"og.{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


# Load protocol.py and hub.py without importing the HA package __init__.
sys.modules.setdefault("og", type(sys)("og")).__path__ = [str(PKG)]
protocol = _load("protocol")
hub_mod = _load("hub")

MAC = "aa:bb:cc:00:00:01"
HELLO = bytes.fromhex("0300aabbcc00000100001c0003160201 0000".replace(" ", ""))
# Night mode status
STATUS_NIGHT = bytes.fromhex("0100aabbcc000001" + "03010115260000000100000 3c9".replace(" ", ""))
# Auto, humidity low, twilight off, 19 C, 42 %
STATUS_AUTO = bytes.fromhex("0100aabbcc000001" + "01000013 2a01 0000 0000 0101 c9".replace(" ", ""))
CMD_NIGHT = bytes.fromhex("0200aabbcc000001" + "010301010301")
CMD_HUM_MID_DUSK_OFF = bytes.fromhex("0200aabbcc000001" + "010100010101")


def test_lengths():
    assert len(HELLO) == 18 and len(STATUS_NIGHT) == 21 and len(CMD_NIGHT) == 14


def test_parse_status_night():
    s = protocol.parse_status(STATUS_NIGHT)
    assert s.mac == MAC
    assert protocol.MODES[s.mode] == "night"
    assert (s.speed, s.humidity_threshold, s.temperature, s.humidity) == (1, 1, 21, 38)
    assert s.twilight == 3


def test_parse_status_auto():
    s = protocol.parse_status(STATUS_AUTO)
    assert protocol.MODES[s.mode] == "auto"
    assert (s.speed, s.humidity_threshold, s.temperature, s.humidity, s.twilight) == (0, 0, 19, 42, 1)


def test_build_command_matches_capture():
    assert protocol.build_command(MAC, 0x03, 1, 1, 3) == CMD_NIGHT
    assert protocol.build_command(MAC, 0x01, 0, 1, 1) == CMD_HUM_MID_DUSK_OFF
    assert protocol.parse_command(CMD_NIGHT) == (MAC, 3, 1, 1, 3)


def test_framer_split_and_join():
    f = protocol.Framer()
    data = HELLO + STATUS_NIGHT
    assert f.feed(data[:10]) == []
    assert f.feed(data[10:30]) == [HELLO]
    assert f.feed(data[30:]) == [STATUS_NIGHT]
    # unknown type passes through untouched
    assert f.feed(b"\x09\x00abc") == [b"\x09\x00abc"]


@pytest.mark.asyncio
async def test_proxy_end_to_end(socket_enabled):
    cloud_rx = bytearray()
    cloud_conn = {}

    async def cloud(reader, writer):
        cloud_conn["w"] = writer
        while data := await reader.read(1024):
            cloud_rx.extend(data)

    cloud_srv = await asyncio.start_server(cloud, "127.0.0.1", 0)
    cloud_port = cloud_srv.sockets[0].getsockname()[1]

    hub = hub_mod.OerreHub(0, "127.0.0.1", cloud_port)
    hub.listen_port = 0
    await hub.start()
    port = hub._servers[0].sockets[0].getsockname()[1]
    events = []
    hub.add_listener(events.append)
    new_units = []
    hub.add_new_unit_listener(new_units.append)

    # Fake unit connects, says hello and sends status
    r, w = await asyncio.open_connection("127.0.0.1", port)
    w.write(HELLO + STATUS_NIGHT[:7])
    await w.drain()
    await asyncio.sleep(0.1)
    w.write(STATUS_NIGHT[7:])
    await w.drain()
    await asyncio.sleep(0.2)

    assert bytes(cloud_rx) == HELLO + STATUS_NIGHT  # forwarded byte-exact
    assert new_units == [MAC]
    unit = hub.units[MAC]
    assert unit.connected and unit.status.temperature == 21

    # Cloud sends a command -> reaches the unit unchanged
    cloud_conn["w"].write(CMD_NIGHT)
    await cloud_conn["w"].drain()
    assert await asyncio.wait_for(r.readexactly(14), 2) == CMD_NIGHT

    # Unknown 9-byte cloud message passes through too
    cloud_conn["w"].write(b"\x05\x00" + b"\x11" * 7)
    await cloud_conn["w"].drain()
    assert await asyncio.wait_for(r.readexactly(9), 2) == b"\x05\x00" + b"\x11" * 7

    # HA injects: switch to manual, keep the rest from last status
    await hub.async_set(MAC, mode=0x02, speed=2)
    got = await asyncio.wait_for(r.readexactly(14), 2)
    assert got == protocol.build_command(MAC, 0x02, 2, 1, 3)

    # Unit disconnects
    w.close()
    await asyncio.sleep(0.2)
    assert not hub.units[MAC].connected
    with pytest.raises(ConnectionError):
        await hub.async_set(MAC, mode=1)

    await hub.stop()
    cloud_srv.close()


@pytest.mark.asyncio
async def test_local_only_when_cloud_down(socket_enabled):
    hub = hub_mod.OerreHub(0, "127.0.0.1", 1)  # nothing listens on port 1
    await hub.start()
    port = hub._servers[0].sockets[0].getsockname()[1]
    r, w = await asyncio.open_connection("127.0.0.1", port)
    w.write(HELLO + STATUS_AUTO)
    await w.drain()
    await asyncio.sleep(0.3)
    assert hub.units[MAC].status.humidity == 42
    await hub.async_set(MAC, twilight=3)
    assert await asyncio.wait_for(r.readexactly(14), 2) == protocol.build_command(MAC, 1, 0, 0, 3)
    w.close()
    await hub.stop()


# Filter reset captured from a real unit (cloud -> unit)
FILTER_RESET_B = bytes.fromhex("0200aabbcc00000203")
# Unit B before filter reset (filter red), unit C after reset (filter green)
STATUS_B_FILTER_RED = bytes.fromhex("0100aabbcc000002" + "00010117 2a02 0002 0000 0003 c7".replace(" ", ""))
STATUS_C_FILTER_OK = bytes.fromhex("0100aabbcc000003" + "00010117 2501 0000 0000 0002 c5".replace(" ", ""))


def test_filter_reset_and_status():
    assert protocol.build_filter_reset("aa:bb:cc:00:00:02") == FILTER_RESET_B
    assert protocol.parse_status(STATUS_B_FILTER_RED).filter == 2
    assert protocol.parse_status(STATUS_C_FILTER_OK).filter == 0
    assert protocol.parse_status(STATUS_B_FILTER_RED).temperature == 23


def test_framer_short_command():
    f = protocol.Framer()
    assert f.feed(FILTER_RESET_B + CMD_NIGHT) == [FILTER_RESET_B, CMD_NIGHT]
    assert f.feed(FILTER_RESET_B[:5]) == []
    assert f.feed(FILTER_RESET_B[5:]) == [FILTER_RESET_B]


def test_air_quality_byte():
    # app showed unit B "Medium", unit C "Good"
    assert protocol.parse_status(STATUS_B_FILTER_RED).air_quality == 2
    assert protocol.parse_status(STATUS_C_FILTER_OK).air_quality == 1


dns = _load("dns")


def test_dns_roundtrip():
    q = dns.build_query("app-oerre.it", 0x1234)
    # fake answer: header + question + one A record with name pointer
    ans = bytearray(q)
    ans[2:4] = b"\x81\x80"
    ans[6:8] = b"\x00\x01"
    ans += b"\xc0\x0c" + bytes.fromhex("00010001") + b"\x00\x00\x0e\x10\x00\x04" + bytes([62, 97, 61, 164])
    assert dns.parse_response(bytes(ans), 0x1234) == ["62.97.61.164"]
    assert dns.parse_response(bytes(ans), 0x9999) == []


@pytest.mark.asyncio
async def test_resolver_fake_server(socket_enabled):
    loop = asyncio.get_running_loop()

    class Srv(asyncio.DatagramProtocol):
        def connection_made(self, t):
            self.t = t

        def datagram_received(self, data, addr):
            ans = bytearray(data)
            ans[2:4] = b"\x81\x80"
            ans[6:8] = b"\x00\x01"
            ans += b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x0e\x10\x00\x04" + bytes([127, 0, 0, 9])
            self.t.sendto(bytes(ans), addr)

    t, _ = await loop.create_datagram_endpoint(Srv, local_addr=("127.0.0.1", 0))
    port = t.get_extra_info("sockname")[1]
    r = dns.CloudResolver("app-oerre.it", "1.2.3.4", resolvers=(("127.0.0.1", port),))
    assert await r.resolve() == "127.0.0.9"
    t.close()
    # dead resolver -> fallback
    r2 = dns.CloudResolver("app-oerre.it", "1.2.3.4", resolvers=(("127.0.0.1", 9),))
    dns.QUERY_TIMEOUT = 0.3
    assert await r2.resolve() == "1.2.3.4"
    assert await dns.CloudResolver("10.0.0.5").resolve() == "10.0.0.5"
