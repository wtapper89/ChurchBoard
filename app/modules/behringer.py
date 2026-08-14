from __future__ import annotations

import asyncio
import math
import socket
import struct
import time
from typing import Any


def x32_fader_to_db(value: float) -> float:
    value = max(0.0, min(1.0, float(value)))
    if value >= .5:
        return value * 40 - 30
    if value >= .25:
        return value * 80 - 50
    if value >= .0625:
        return value * 160 - 70
    if value > 0:
        return value * 480 - 90
    return -math.inf


def db_to_x32_fader(db: float) -> float:
    db = float(db)
    if db < -90:
        return 0.0
    if db < -60:
        return (db + 90) / 480
    if db < -30:
        return (db + 70) / 160
    if db < -10:
        return (db + 50) / 80
    if db <= 10:
        return (db + 30) / 40
    return 1.0


def _osc_string(value: str) -> bytes:
    raw = value.encode("utf-8") + b"\0"
    return raw + b"\0" * ((4 - len(raw) % 4) % 4)


def osc_message(address: str, value: float | int | None = None) -> bytes:
    if value is None:
        return _osc_string(address)
    if isinstance(value, int):
        return _osc_string(address) + _osc_string(",i") + struct.pack(">i", value)
    return _osc_string(address) + _osc_string(",f") + struct.pack(">f", float(value))


def _read_string(data: bytes, offset: int = 0) -> tuple[str, int]:
    end = data.index(b"\0", offset)
    return data[offset:end].decode("utf-8", "replace"), (end + 4) & ~3


def parse_osc(data: bytes) -> list[tuple[str, Any]]:
    if data.startswith(b"#bundle"):
        _, offset = _read_string(data)
        offset += 8
        messages: list[tuple[str, Any]] = []
        while offset + 4 <= len(data):
            size = struct.unpack_from(">i", data, offset)[0]
            offset += 4
            messages.extend(parse_osc(data[offset:offset + size]))
            offset += size
        return messages
    address, offset = _read_string(data)
    if offset >= len(data) or data[offset:offset + 1] != b",":
        return [(address, None)]
    tags, offset = _read_string(data, offset)
    values: list[Any] = []
    for tag in tags[1:]:
        if tag == "f":
            values.append(struct.unpack_from(">f", data, offset)[0]); offset += 4
        elif tag == "i":
            values.append(struct.unpack_from(">i", data, offset)[0]); offset += 4
        elif tag == "s":
            value, offset = _read_string(data, offset); values.append(value)
        elif tag in "TF":
            values.append(tag == "T")
    return [(address, values[0] if len(values) == 1 else values)]


def _osc_scalar(value: Any) -> Any:
    """Return the first OSC value when a console sends a multi-argument reply.

    X32/WING firmware can reply with a one-element argument array even for a
    single fader or mute query.  Treat that equivalent to the scalar form so a
    status poll cannot fail with ``float(list)``.
    """
    while isinstance(value, (list, tuple)) and value:
        value = value[0]
    return value


def strip_paths(model: str, strip: dict[str, Any]) -> tuple[str, str, bool]:
    model = str(model or "x32").casefold()
    kind = str(strip.get("kind") or "channel").casefold()
    number = max(1, int(strip.get("number") or 1))
    target = max(1, int(strip.get("target_bus") or 1))
    if model == "wing":
        if kind == "send":
            return f"/ch/{number}/send/{target}/lvl", f"/ch/{number}/send/{target}/on", True
        root = {"channel": "ch", "aux": "aux", "bus": "bus", "dca": "dca", "main": "main"}.get(kind, "ch")
        return f"/{root}/{number}/fdr", f"/{root}/{number}/mute", False
    if kind == "dca":
        return f"/dca/{number}/fader", f"/dca/{number}/on", True
    if kind == "main":
        root = "/main/st" if number == 1 else "/main/m"
        return f"{root}/mix/fader", f"{root}/mix/on", True
    root = {"channel": f"/ch/{number:02d}", "aux": f"/auxin/{number:02d}", "bus": f"/bus/{number:02d}"}.get(kind, f"/ch/{number:02d}")
    if kind == "send":
        return f"/ch/{number:02d}/mix/{target:02d}/level", f"/ch/{number:02d}/mix/{target:02d}/on", True
    return f"{root}/mix/fader", f"{root}/mix/on", True


class BehringerClient:
    def __init__(self, settings: dict[str, Any]):
        self.settings = settings
        self.model = str(settings.get("model") or "x32").casefold()
        self.host = str(settings.get("host") or "").strip()
        self.port = int(settings.get("port") or (2223 if self.model == "wing" else 10023))
        self._lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.settings.get("enabled") and self.host)

    def _exchange(self, paths: list[str], writes: list[tuple[str, float | int]] | None = None) -> dict[str, Any]:
        answers: dict[str, Any] = {}
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(.04)
            for address, value in writes or []:
                sock.sendto(osc_message(address, value), (self.host, self.port))
            for address in dict.fromkeys(paths):
                sock.sendto(osc_message(address), (self.host, self.port))
            deadline = time.monotonic() + .24
            while time.monotonic() < deadline and len(answers) < len(set(paths)):
                try:
                    packet, _ = sock.recvfrom(65535)
                except socket.timeout:
                    continue
                for address, value in parse_osc(packet):
                    answers[address] = value
        return answers

    async def status(self, strips: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.configured:
            return {"connected": False, "error": "Behringer mixer is not enabled", "strips": []}
        paths = [path for strip in strips for path in strip_paths(self.model, strip)[:2]]
        async with self._lock:
            values = await asyncio.to_thread(self._exchange, paths)
        rows = []
        for strip in strips:
            fader_path, mute_path, on_means_unmuted = strip_paths(self.model, strip)
            raw = _osc_scalar(values.get(fader_path))
            db = float(raw) if self.model == "wing" and raw is not None else x32_fader_to_db(float(raw)) if raw is not None else None
            if db is not None and not math.isfinite(db):
                db = -100.0
            mute_raw = _osc_scalar(values.get(mute_path))
            muted = (not bool(mute_raw)) if on_means_unmuted and mute_raw is not None else bool(mute_raw) if mute_raw is not None else None
            rows.append({**strip, "fader_path": fader_path, "mute_path": mute_path, "db": db, "position": db_to_x32_fader(db) if db is not None else 0, "muted": muted, "online": raw is not None or mute_raw is not None})
        return {"connected": bool(values), "model": self.model, "host": self.host, "strips": rows}

    async def control(self, strip: dict[str, Any], level_db: float | None = None, muted: bool | None = None) -> None:
        if not self.configured:
            raise RuntimeError("Behringer mixer is not configured")
        fader_path, mute_path, on_means_unmuted = strip_paths(self.model, strip)
        writes: list[tuple[str, float | int]] = []
        if level_db is not None:
            writes.append((fader_path, float(level_db) if self.model == "wing" else db_to_x32_fader(level_db)))
        if muted is not None:
            writes.append((mute_path, int(not muted) if on_means_unmuted else int(muted)))
        async with self._lock:
            await asyncio.to_thread(self._exchange, [], writes)
