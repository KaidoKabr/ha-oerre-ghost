"""Resolve the Oerre cloud host via public DNS.

The local DNS points app-oerre.it at Home Assistant itself (that is how the
units are redirected), so the system resolver cannot be used to find the real
cloud server. This sends a plain DNS A query straight to public resolvers.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import random
import struct
import time

_LOGGER = logging.getLogger(__name__)

PUBLIC_RESOLVERS = ("1.1.1.1", "8.8.8.8", "9.9.9.9")
QUERY_TIMEOUT = 3
CACHE_SECONDS = 3600


def is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def build_query(name: str, qid: int) -> bytes:
    header = struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0)
    qname = b"".join(bytes([len(p)]) + p.encode() for p in name.rstrip(".").split(".")) + b"\0"
    return header + qname + struct.pack(">HH", 1, 1)  # type A, class IN


def _skip_name(data: bytes, pos: int) -> int:
    while True:
        length = data[pos]
        if length == 0:
            return pos + 1
        if length & 0xC0 == 0xC0:
            return pos + 2
        pos += length + 1


def parse_response(data: bytes, qid: int) -> list[str]:
    rid, flags, qd, an, _, _ = struct.unpack(">HHHHHH", data[:12])
    if rid != qid or flags & 0x000F:
        return []
    pos = 12
    for _ in range(qd):
        pos = _skip_name(data, pos) + 4
    ips = []
    for _ in range(an):
        pos = _skip_name(data, pos)
        rtype, _rclass, _ttl, rdlen = struct.unpack(">HHIH", data[pos : pos + 10])
        pos += 10
        if rtype == 1 and rdlen == 4:
            ips.append(str(ipaddress.IPv4Address(data[pos : pos + 4])))
        pos += rdlen
    return ips


class _Proto(asyncio.DatagramProtocol):
    def __init__(self, fut: asyncio.Future) -> None:
        self.fut = fut

    def datagram_received(self, data, addr) -> None:
        if not self.fut.done():
            self.fut.set_result(data)

    def error_received(self, exc) -> None:
        if not self.fut.done():
            self.fut.set_exception(exc)


async def query(name: str, server: str, port: int = 53) -> list[str]:
    loop = asyncio.get_running_loop()
    qid = random.randint(0, 0xFFFF)
    fut = loop.create_future()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: _Proto(fut), remote_addr=(server, port)
    )
    try:
        transport.sendto(build_query(name, qid))
        data = await asyncio.wait_for(fut, QUERY_TIMEOUT)
        return parse_response(data, qid)
    finally:
        transport.close()


class CloudResolver:
    """Hostname -> IP with public DNS, caching and a last-known fallback."""

    def __init__(self, host: str, fallback_ip: str | None = None,
                 resolvers: tuple[tuple[str, int], ...] | None = None) -> None:
        self.host = host
        self._ip = fallback_ip
        self._expires = 0.0
        self._resolvers = resolvers or tuple((r, 53) for r in PUBLIC_RESOLVERS)

    async def resolve(self) -> str | None:
        if is_ip(self.host):
            return self.host
        if time.monotonic() < self._expires and self._ip:
            return self._ip
        for server, port in self._resolvers:
            try:
                ips = await query(self.host, server, port)
            except (OSError, asyncio.TimeoutError, struct.error, IndexError) as err:
                _LOGGER.debug("DNS %s via %s failed: %s", self.host, server, err)
                continue
            if ips:
                if ips[0] != self._ip:
                    _LOGGER.info("Oerre cloud %s resolved to %s", self.host, ips[0])
                self._ip = ips[0]
                self._expires = time.monotonic() + CACHE_SECONDS
                return self._ip
        _LOGGER.warning("Could not resolve %s via public DNS, using %s", self.host, self._ip)
        return self._ip
