from __future__ import annotations

import asyncio
import json
import re
import socket
from datetime import datetime, timezone
from typing import Any, Callable

MULTICAST_GROUP = "239.255.42.42"
MULTICAST_PORT = 49007
SPL_OFFSET = 140.0
LEVEL_ALIASES = {
    "laeq": ("laeq", "laeq_db", "laeqdb", "la_eq"),
    "lceq": ("lceq", "lceq_db", "lceqdb", "lc_eq"),
    "lzeq": ("lzeq", "lzeq_db", "lzeqdb", "lz_eq"),
    "peak": ("peak", "peak_db", "lpeak", "lpk"),
    "fast": ("fast", "fast_db", "laf", "lafmax"),
    "slow": ("slow", "slow_db", "las", "lasmax"),
}


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if -200 <= number <= 200 else None


def parse_osm_packet(packet: bytes) -> dict[str, Any] | None:
    text = packet.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        raw = {key.casefold(): value for key, value in re.findall(r"([A-Za-z_][\w.-]*)\s*[=:]\s*(-?\d+(?:\.\d+)?)", text)}
    if not isinstance(raw, dict):
        return None
    if raw.get("api") == "Open Sound Meter" and raw.get("message") == "levels" and isinstance(raw.get("data"), dict):
        data = raw["data"]
        def level(weighting: str, response: str) -> float | None:
            raw_level = _number((data.get(weighting) or {}).get(response))
            return max(0.0, raw_level + SPL_OFFSET) if raw_level is not None else None
        a_fast, a_slow = level("A", "Fast"), level("A", "Slow")
        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_id": str(raw.get("source") or ""),
            "source_name": str(raw.get("objectName") or raw.get("source") or "Open Sound Meter"),
            "source_host": str(raw.get("host") or ""),
        }
        for key, value in {"laeq": a_fast, "a_fast": a_fast, "a_slow": a_slow, "b_fast": level("B", "Fast"), "b_slow": level("B", "Slow"), "c_fast": level("C", "Fast"), "c_slow": level("C", "Slow"), "z_fast": level("Z", "Fast"), "z_slow": level("Z", "Slow")}.items():
            if value is not None:
                result[key] = value
        return result if any(key in result for key in ("a_fast", "a_slow", "b_fast", "b_slow", "c_fast", "c_slow", "z_fast", "z_slow")) else None
    values = {str(key).casefold().replace("-", "_"): value for key, value in raw.items()}
    result: dict[str, Any] = {"timestamp": datetime.now(timezone.utc).isoformat()}
    for name, aliases in LEVEL_ALIASES.items():
        number = next((_number(values.get(alias)) for alias in aliases if _number(values.get(alias)) is not None), None)
        if number is not None:
            result[name] = number
    return result if len(result) > 1 else None


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self, on_measurement: Callable[[dict[str, Any]], None]) -> None:
        self.on_measurement = on_measurement

    def datagram_received(self, data: bytes, address: tuple[str, int]) -> None:
        measurement = parse_osm_packet(data)
        if measurement:
            self.on_measurement(measurement)


class OSMListener:
    def __init__(self, on_measurement: Callable[[dict[str, Any]], None]) -> None:
        self.on_measurement = on_measurement
        self.transport: asyncio.DatagramTransport | None = None
        self.key: tuple[str, int, str] | None = None

    async def configure(self, settings: dict[str, Any]) -> None:
        key = (str(settings.get("multicast_group") or MULTICAST_GROUP), int(settings.get("multicast_port") or MULTICAST_PORT), str(settings.get("interface") or "0.0.0.0"))
        if self.key == key and self.transport:
            return
        await self.close()
        group, port, interface = key
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", port))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, socket.inet_aton(group) + socket.inet_aton(interface))
        loop = asyncio.get_running_loop()
        self.transport, _ = await loop.create_datagram_endpoint(lambda: _Protocol(self.on_measurement), sock=sock)
        self.key = key

    async def close(self) -> None:
        if self.transport:
            self.transport.close()
        self.transport, self.key = None, None
