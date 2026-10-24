"""Oerre Ghost App cloud protocol (TCP port 11000, unencrypted).

Reverse-engineered from captured traffic. All messages start with a
2-byte type followed by the 6-byte MAC address of the unit:

  03 00 | MAC | 10 bytes              device -> cloud, hello (18 B)
  01 00 | MAC | 13 bytes              device -> cloud, status (21 B)
  02 00 | MAC | 01 MM SS HH DD 01     cloud -> device, command (14 B)

Command fields: MM = mode, SS = fan speed (0..2), HH = humidity threshold
(0..2), DD = twilight sensor (1 = off, 2 = low, 3 = high).

Status payload (bytes after the MAC):
  [0] mode  [1] speed  [2] humidity threshold  [3] temperature (int8, C)
  [4] relative humidity %  [5] air quality (0 very good, 1 good, 2 medium)  [6] 0
  [7] filter (0 = ok, 2 = replace)  [8] flag  [9] unknown
  [10] active mode (follows the set mode with a delay)
  [11] twilight sensor setting  [12] unknown (probably air quality)
"""

from __future__ import annotations

from dataclasses import dataclass, field

MSG_STATUS = 0x01
MSG_COMMAND = 0x02
MSG_HELLO = 0x03

MSG_LENGTHS = {MSG_STATUS: 21, MSG_COMMAND: 14, MSG_HELLO: 18}

CMD_SETTINGS = 0x01  # 02 00 MAC 01 mode speed hum twilight 01
CMD_FILTER_RESET = 0x03  # 02 00 MAC 03

FILTER_LEVELS = ["ok", "warning", "replace"]  # status byte 15: 0, 1, 2
AIR_QUALITY_LEVELS = ["very_good", "good", "medium", "poor"]  # status byte 13: 0..3

MODES: dict[int, str] = {
    0x00: "smart",
    0x01: "auto",
    0x02: "manual",
    0x03: "night",
    0x04: "away",
    0x05: "surveillance",
    0x06: "timed_extraction",
    0x07: "extraction",
    0x08: "intake",
    0x09: "master_slave",
    0x0A: "slave_master",
    0x0B: "off",
}
MODE_CODES = {name: code for code, name in MODES.items()}
MODE_OFF = 0x0B

SPEEDS = ["1", "2", "3"]  # wire values 0, 1, 2
HUMIDITY_LEVELS = ["low", "medium", "high"]  # wire values 0, 1, 2
TWILIGHT_LEVELS = ["off", "low", "high"]  # wire values 1, 2, 3
TWILIGHT_OFFSET = 1


def format_mac(raw: bytes) -> str:
    return ":".join(f"{b:02x}" for b in raw)


def parse_mac(mac: str) -> bytes:
    return bytes(int(part, 16) for part in mac.split(":"))


@dataclass
class Status:
    mac: str
    mode: int
    speed: int
    humidity_threshold: int
    temperature: int
    humidity: int
    active_mode: int
    twilight: int
    air_quality_raw: int
    filter: int
    air_quality: int
    raw: bytes = field(repr=False)


def parse_status(msg: bytes) -> Status:
    if len(msg) != 21 or msg[0] != MSG_STATUS:
        raise ValueError(f"not a status message: {msg.hex()}")
    p = msg[8:]
    temperature = p[3] - 256 if p[3] > 127 else p[3]
    return Status(
        mac=format_mac(msg[2:8]),
        mode=p[0],
        speed=p[1],
        humidity_threshold=p[2],
        temperature=temperature,
        humidity=p[4],
        active_mode=p[10],
        twilight=p[11],
        air_quality_raw=p[12],
        filter=p[7],
        air_quality=p[5],
        raw=bytes(msg),
    )


def build_filter_reset(mac: str) -> bytes:
    return bytes([MSG_COMMAND, 0x00]) + parse_mac(mac) + bytes([CMD_FILTER_RESET])


def parse_command(msg: bytes) -> tuple[str, int, int, int, int]:
    """Return (mac, mode, speed, humidity_threshold, twilight)."""
    if len(msg) != 14 or msg[0] != MSG_COMMAND:
        raise ValueError(f"not a command message: {msg.hex()}")
    return format_mac(msg[2:8]), msg[9], msg[10], msg[11], msg[12]


def build_command(
    mac: str, mode: int, speed: int, humidity_threshold: int, twilight: int
) -> bytes:
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode}")
    if not 0 <= speed <= 2 or not 0 <= humidity_threshold <= 2:
        raise ValueError("speed / humidity threshold out of range")
    if not 1 <= twilight <= 3:
        raise ValueError("twilight out of range")
    return (
        bytes([MSG_COMMAND, 0x00])
        + parse_mac(mac)
        + bytes([0x01, mode, speed, humidity_threshold, twilight, 0x01])
    )


class Framer:
    """Split a TCP byte stream into known messages.

    Returns (messages, passthrough): known complete messages, plus bytes that
    could not be framed (unknown type) which the caller forwards unchanged.
    Incomplete known messages stay buffered until the rest arrives.
    """

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        """Return a list of chunks in stream order. Each chunk is either a
        complete known message or an opaque blob of unknown bytes."""
        self._buf += data
        out: list[bytes] = []
        while self._buf:
            length = MSG_LENGTHS.get(self._buf[0])
            if self._buf[0] == MSG_COMMAND:
                # 02 00 MAC 01 ... = settings (14 B); 02 00 MAC xx = short (9 B)
                if len(self._buf) < 9:
                    break
                length = 14 if self._buf[8] == CMD_SETTINGS else 9
            if length is None or (len(self._buf) >= 2 and self._buf[1] != 0x00):
                # Unknown framing: pass everything through and resync later.
                out.append(bytes(self._buf))
                self._buf.clear()
                break
            if len(self._buf) < length:
                break
            out.append(bytes(self._buf[:length]))
            del self._buf[:length]
        return out

    def flush(self) -> bytes:
        data = bytes(self._buf)
        self._buf.clear()
        return data
