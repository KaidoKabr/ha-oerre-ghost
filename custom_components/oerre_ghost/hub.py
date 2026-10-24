"""Transparent TCP proxy between Oerre Ghost units and the Oerre cloud.

The units are pointed at this proxy (local DNS record for app-oerre.it).
Every byte is forwarded unchanged in both directions, so the O.Tech app keeps
working. On the way through, status messages are decoded, and commands can be
injected towards a unit. No Home Assistant imports here: it is plain asyncio.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from .dns import CloudResolver
from .protocol import (
    MODE_OFF,
    MSG_HELLO,
    MSG_STATUS,
    Framer,
    Status,
    build_command,
    build_filter_reset,
    format_mac,
    parse_status,
)

_LOGGER = logging.getLogger(__name__)

PARTIAL_FLUSH_DELAY = 0.5
UPSTREAM_RETRY = 60
CONNECT_TIMEOUT = 10


@dataclass
class UnitState:
    mac: str
    connected: bool = False
    status: Status | None = None
    hello: bytes | None = None
    ip: str | None = None
    last_on_mode: int = 0x01  # auto
    _session: _Session | None = field(default=None, repr=False)


class _Session:
    """One unit connection and its upstream cloud connection."""

    def __init__(self, hub: OerreHub, reader, writer) -> None:
        self.hub = hub
        self.dev_reader: asyncio.StreamReader = reader
        self.dev_writer: asyncio.StreamWriter = writer
        self.up_reader: asyncio.StreamReader | None = None
        self.up_writer: asyncio.StreamWriter | None = None
        self.mac: str | None = None
        self.hello: bytes | None = None
        self.dev_lock = asyncio.Lock()
        self.up_lock = asyncio.Lock()
        self._down_framer = Framer()
        self._down_flush: asyncio.TimerHandle | None = None
        self._tasks: list[asyncio.Task] = []
        self._closed = asyncio.Event()
        peer = writer.get_extra_info("peername")
        self.ip = peer[0] if peer else None

    async def run(self) -> None:
        await self._connect_upstream()
        self._tasks.append(asyncio.create_task(self._device_to_cloud()))
        self._tasks.append(asyncio.create_task(self._upstream_supervisor()))
        await self._closed.wait()
        await self.close()

    # -- upstream ---------------------------------------------------------
    async def _connect_upstream(self) -> bool:
        host = await self.hub.cloud_ip()
        if not host:
            return False
        try:
            self.up_reader, self.up_writer = await asyncio.wait_for(
                asyncio.open_connection(host, self.hub.upstream_port),
                CONNECT_TIMEOUT,
            )
        except (OSError, asyncio.TimeoutError) as err:
            _LOGGER.warning(
                "Oerre cloud %s:%s not reachable (%s); unit %s runs local-only",
                host, self.hub.upstream_port, err, self.mac or self.ip,
            )
            self.up_reader = self.up_writer = None
            return False
        if self.hello:
            # Reconnect mid-session: introduce the unit to the cloud again.
            await self._send_up(self.hello)
        return True

    async def _upstream_supervisor(self) -> None:
        while not self._closed.is_set():
            if self.up_reader is None:
                await asyncio.sleep(UPSTREAM_RETRY)
                if not self._closed.is_set():
                    await self._connect_upstream()
                continue
            await self._cloud_to_device()
            # Cloud dropped: drop the writer and retry later.
            if self.up_writer:
                self.up_writer.close()
            self.up_reader = self.up_writer = None

    async def _cloud_to_device(self) -> None:
        reader = self.up_reader
        while True:
            try:
                data = await reader.read(4096)
            except OSError:
                data = b""
            if not data:
                _LOGGER.info("Oerre cloud closed connection for %s", self.mac)
                return
            for chunk in self._down_framer.feed(data):
                await self._send_dev(chunk)
            self._schedule_down_flush()

    def _schedule_down_flush(self) -> None:
        if self._down_flush:
            self._down_flush.cancel()
        self._down_flush = asyncio.get_running_loop().call_later(
            PARTIAL_FLUSH_DELAY,
            lambda: asyncio.create_task(self._flush_down()),
        )

    async def _flush_down(self) -> None:
        data = self._down_framer.flush()
        if data:
            await self._send_dev(data)

    # -- device -----------------------------------------------------------
    async def _device_to_cloud(self) -> None:
        framer = Framer()
        try:
            while True:
                data = await self.dev_reader.read(4096)
                if not data:
                    break
                await self._send_up(data)  # forward first, untouched
                for chunk in framer.feed(data):
                    self._inspect(chunk)
        except OSError:
            pass
        finally:
            self._closed.set()

    def _inspect(self, msg: bytes) -> None:
        if len(msg) < 8:
            return
        if msg[0] == MSG_HELLO and len(msg) == 18:
            self.hello = msg
            self._bind(format_mac(msg[2:8]))
        elif msg[0] == MSG_STATUS and len(msg) == 21:
            mac = format_mac(msg[2:8])
            if self.mac and mac != self.mac:
                return
            self._bind(mac)
            try:
                self.hub._handle_status(parse_status(msg))
            except ValueError:
                pass

    def _bind(self, mac: str) -> None:
        if self.mac == mac:
            return
        self.mac = mac
        self.hub._attach(self, mac)

    async def _send_up(self, data: bytes) -> None:
        writer = self.up_writer
        if writer is None:
            return
        async with self.up_lock:
            try:
                writer.write(data)
                await writer.drain()
            except OSError:
                pass

    async def _send_dev(self, data: bytes) -> None:
        async with self.dev_lock:
            self.dev_writer.write(data)
            await self.dev_writer.drain()

    async def send_command(self, cmd: bytes) -> None:
        await self._send_dev(cmd)

    async def close(self) -> None:
        self._closed.set()
        for task in self._tasks:
            if task is not asyncio.current_task():
                task.cancel()
        if self._down_flush:
            self._down_flush.cancel()
        for writer in (self.dev_writer, self.up_writer):
            if writer:
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()
        if self.mac:
            self.hub._detach(self, self.mac)


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except OSError:
        pass
    finally:
        writer.close()


class OerreHub:
    """Listens for units, keeps per-unit state, sends commands."""

    def __init__(
        self,
        listen_port: int,
        upstream_host: str | None,
        upstream_port: int,
        app_port: int = 0,
        known_macs: list[str] | None = None,
        fallback_ip: str | None = None,
    ) -> None:
        self.listen_port = listen_port
        self.upstream_host = upstream_host
        self._resolver = (
            CloudResolver(upstream_host, fallback_ip) if upstream_host else None
        )
        self.upstream_port = upstream_port
        self.app_port = app_port
        self.units: dict[str, UnitState] = {
            mac: UnitState(mac) for mac in (known_macs or [])
        }
        self._servers: list[asyncio.base_events.Server] = []
        self._sessions: set[_Session] = set()
        self._listeners: list[Callable[[str], None]] = []
        self._new_unit_listeners: list[Callable[[str], None]] = []

    # -- lifecycle --------------------------------------------------------
    async def start(self) -> None:
        self._servers.append(
            await asyncio.start_server(self._on_unit, "0.0.0.0", self.listen_port)
        )
        if self.app_port and self.upstream_host:
            self._servers.append(
                await asyncio.start_server(self._on_app, "0.0.0.0", self.app_port)
            )
        _LOGGER.info("Oerre Ghost proxy listening on %s", self.listen_port)

    async def stop(self) -> None:
        for server in self._servers:
            server.close()
        for session in list(self._sessions):
            await session.close()
        for server in self._servers:
            with contextlib.suppress(Exception):
                await server.wait_closed()
        self._servers.clear()

    async def _on_unit(self, reader, writer) -> None:
        session = _Session(self, reader, writer)
        self._sessions.add(session)
        try:
            await session.run()
        finally:
            self._sessions.discard(session)

    async def cloud_ip(self) -> str | None:
        return await self._resolver.resolve() if self._resolver else None

    async def _on_app(self, reader, writer) -> None:
        """Plain pass-through for the O.Tech app port (TLS, never touched)."""
        host = await self.cloud_ip()
        if not host:
            writer.close()
            return
        try:
            up_r, up_w = await asyncio.wait_for(
                asyncio.open_connection(host, self.app_port),
                CONNECT_TIMEOUT,
            )
        except (OSError, asyncio.TimeoutError):
            writer.close()
            return
        await asyncio.gather(_pipe(reader, up_w), _pipe(up_r, writer))

    # -- listeners --------------------------------------------------------
    def add_listener(self, cb: Callable[[str], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb)

    def add_new_unit_listener(self, cb: Callable[[str], None]) -> Callable[[], None]:
        self._new_unit_listeners.append(cb)
        return lambda: self._new_unit_listeners.remove(cb)

    def _notify(self, mac: str) -> None:
        for cb in list(self._listeners):
            cb(mac)

    # -- session callbacks ------------------------------------------------
    def _unit(self, mac: str) -> UnitState:
        unit = self.units.get(mac)
        if unit is None:
            unit = self.units[mac] = UnitState(mac)
            for cb in list(self._new_unit_listeners):
                cb(mac)
        return unit

    def _attach(self, session: _Session, mac: str) -> None:
        unit = self._unit(mac)
        old = unit._session
        unit._session = session
        unit.connected = True
        unit.ip = session.ip
        if session.hello:
            unit.hello = session.hello
        if old and old is not session:
            asyncio.create_task(old.close())
        _LOGGER.info("Oerre Ghost %s connected from %s", mac, session.ip)
        self._notify(mac)

    def _detach(self, session: _Session, mac: str) -> None:
        unit = self.units.get(mac)
        if unit and unit._session is session:
            unit._session = None
            unit.connected = False
            _LOGGER.info("Oerre Ghost %s disconnected", mac)
            self._notify(mac)

    def _handle_status(self, status: Status) -> None:
        unit = self._unit(status.mac)
        unit.status = status
        if status.mode != MODE_OFF:
            unit.last_on_mode = status.mode
        self._notify(status.mac)

    # -- commands ---------------------------------------------------------
    async def async_set(
        self,
        mac: str,
        *,
        mode: int | None = None,
        speed: int | None = None,
        humidity_threshold: int | None = None,
        twilight: int | None = None,
    ) -> None:
        unit = self.units.get(mac)
        if unit is None or unit._session is None:
            raise ConnectionError(f"Oerre Ghost {mac} is not connected")
        st = unit.status
        cmd = build_command(
            mac,
            mode if mode is not None else (st.mode if st else 0x01),
            speed if speed is not None else (st.speed if st else 1),
            humidity_threshold
            if humidity_threshold is not None
            else (st.humidity_threshold if st else 1),
            twilight if twilight is not None else (st.twilight if st else 3),
        )
        _LOGGER.debug("Sending to %s: %s", mac, cmd.hex())
        await unit._session.send_command(cmd)

    async def async_reset_filter(self, mac: str) -> None:
        unit = self.units.get(mac)
        if unit is None or unit._session is None:
            raise ConnectionError(f"Oerre Ghost {mac} is not connected")
        cmd = build_filter_reset(mac)
        _LOGGER.debug("Filter reset to %s: %s", mac, cmd.hex())
        await unit._session.send_command(cmd)
