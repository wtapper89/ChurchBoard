from __future__ import annotations

import asyncio
import json
import re
import socket
from typing import Any


def clamp(value: Any, minimum: float, maximum: float) -> int:
    try:
        return round(max(minimum, min(maximum, float(value))))
    except (TypeError, ValueError):
        return 0


def db_percent(value: Any, floor: float) -> int:
    """Convert an SSC dB/dBm meter to the dashboard's 0–100 scale."""
    return clamp((float(value) - floor) / -floor * 100, 0, 100) if value is not None else 0


def ssc_request(channels: list[int]) -> dict[str, Any]:
    request: dict[str, Any] = {"device": {"product": None, "firmware": None}, "m": {}, "mates": {}}
    for channel in channels:
        request[f"rx{channel}"] = {"name": None, "frequency": None}
        request["m"][f"rx{channel}"] = {"rssi": None, "rsqi": None, "af": None}
        request["mates"][f"tx{channel}"] = {"name": None, "mute": None, "battery": {"gauge": None, "lifetime": None}, "warnings": None}
    return request


def parse_ssc_response(response: dict[str, Any], receiver: dict[str, Any], channels: list[int]) -> list[dict[str, Any]]:
    configured = receiver.get("channel_configs") or []
    receiver_id = str(receiver.get("id") or receiver.get("host") or "sennheiser")
    device = response.get("device") or {}
    output = []
    for channel in channels:
        rx = response.get(f"rx{channel}") or {}
        meter = (response.get("m") or {}).get(f"rx{channel}") or {}
        tx = (response.get("mates") or {}).get(f"tx{channel}") or {}
        battery = tx.get("battery") or {}
        configured_mic = next((item for item in configured if int(item.get("channel") or 1) == channel), {})
        battery_value = battery.get("gauge")
        transmitter_present = battery_value is not None or bool(tx.get("name")) or tx.get("mute") is not None
        warnings = [str(item) for item in (tx.get("warnings") or [])]
        if tx.get("mute"):
            warnings.append("Transmitter muted")
        if clamp(meter.get("rsqi"), 0, 100) < 20 and transmitter_present:
            warnings.append("Weak RF signal")
        if battery_value is not None and clamp(battery_value, 0, 100) <= 10:
            warnings.append("Low battery")
        frequency = rx.get("frequency")
        try:
            frequency_text = f"{float(frequency) / 1000:.3f} MHz" if frequency is not None else ""
        except (TypeError, ValueError):
            frequency_text = str(frequency or "")
        output.append({
            "id": str(configured_mic.get("id") or f"{receiver_id}-{channel}"),
            "receiver": configured_mic.get("receiver_name") or receiver.get("name") or receiver_id,
            "channel": channel,
            "name": str(configured_mic.get("name") or tx.get("name") or rx.get("name") or f"Channel {channel}"),
            "battery_percent": clamp(battery_value, 0, 100),
            "battery_lifetime_minutes": battery.get("lifetime"),
            "rf": clamp(meter.get("rsqi"), 0, 100) or db_percent(meter.get("rssi"), -107),
            "audio": db_percent(meter.get("af"), -60),
            "muted": bool(tx.get("mute")),
            "online": transmitter_present,
            "receiver_online": bool(response),
            "frequency": frequency_text,
            "model": device.get("product") or receiver.get("model") or "Sennheiser",
            "firmware": device.get("firmware") or device.get("version") or "",
            "errors": list(dict.fromkeys(warnings or ([] if transmitter_present else ["Transmitter off"]))),
        })
    return output


class SennheiserClient:
    """Poll EW-DX SSCv1/legacy receivers via JSON-over-UDP (port 45 by default)."""
    def __init__(self, settings: dict[str, Any]):
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.get("enabled") and (self.settings.get("mics") or self.settings.get("receivers")))

    def _configured_receivers(self) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, int], dict[str, Any]] = {}
        for mic in self.settings.get("mics") or []:
            host = str(mic.get("host") or "").strip()
            port = int(mic.get("port") or 45)
            if not host:
                continue
            receiver = grouped.setdefault((host, port), {"id": re.sub(r"[^a-z0-9]+", "-", host.casefold()).strip("-") or "sennheiser", "name": mic.get("receiver_name") or host, "host": host, "port": port, "channel_configs": []})
            receiver["channel_configs"].append(mic)
        return list(grouped.values()) if grouped else list(self.settings.get("receivers") or [])

    async def status(self) -> list[dict[str, Any]]:
        results = await asyncio.gather(*(self._receiver(receiver) for receiver in self._configured_receivers()))
        return [mic for result in results for mic in result]

    async def _receiver(self, receiver: dict[str, Any]) -> list[dict[str, Any]]:
        configs = receiver.get("channel_configs") or []
        channels = sorted({int(item.get("channel") or 1) for item in configs}) if configs else list(range(1, int(receiver.get("channels") or 2) + 1))
        try:
            response = await self._udp_query(str(receiver.get("host") or ""), int(receiver.get("port") or 45), ssc_request(channels))
            return parse_ssc_response(response, receiver, channels)
        except (OSError, asyncio.TimeoutError, ValueError, json.JSONDecodeError) as exc:
            return [{"id": str(next((item.get("id") for item in configs if int(item.get("channel") or 1) == channel), f"{receiver.get('id') or receiver.get('host')}-{channel}")), "receiver": receiver.get("name") or receiver.get("host"), "channel": channel, "name": str(next((item.get("name") for item in configs if int(item.get("channel") or 1) == channel), f"Channel {channel}")), "battery_percent": 0, "rf": 0, "audio": 0, "muted": False, "online": False, "receiver_online": False, "errors": [str(exc) or "Receiver unavailable"]} for channel in channels]

    async def _udp_query(self, host: str, port: int, payload: dict[str, Any]) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)
        try:
            await loop.sock_sendto(sock, json.dumps(payload, separators=(",", ":")).encode(), (host, port))
            data, _ = await asyncio.wait_for(loop.sock_recvfrom(sock, 65535), timeout=1.5)
            return json.loads(data.decode())
        finally:
            sock.close()
