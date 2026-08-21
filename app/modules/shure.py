from __future__ import annotations

import asyncio
import re
from typing import Any


FRAME = re.compile(r"<\s*(?:REP|REPLY|REPORT|SAMPLE)\s+(\d+)\s+([A-Z_]+)(?:\s+\{?([^>}]*)\}?)?\s*>")


def percent(value: str, maximum: int) -> int:
    try:
        return max(0, min(100, round(int(value.strip()) / maximum * 100)))
    except (TypeError, ValueError):
        return 0


def battery_percent(value: str) -> int | None:
    """Convert Shure's 0-5 battery bars without treating 255/unknown as full."""
    try:
        bars = int(value.strip())
    except (AttributeError, TypeError, ValueError):
        return None
    if not 0 <= bars <= 5:
        return None
    return round(bars / 5 * 100)


def transmitter_active(state: dict[str, Any]) -> bool:
    tx_type = str(state.get("tx_type") or "").strip().upper()
    identified = bool(tx_type and tx_type not in {"UNKN", "UNKNOWN", "NONE", "OFF", "N/A"})
    battery_seen = bool(state.get("_battery_valid")) and int(state.get("battery_percent") or 0) > 0
    return bool(state.get("receiver_online") and (identified or battery_seen))


class ShureClient:
    def __init__(self, settings: dict[str, Any]):
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.get("enabled") and (self.settings.get("mics") or self.settings.get("receivers")))

    async def status(self) -> list[dict[str, Any]]:
        receivers = self._configured_receivers()
        results = await asyncio.gather(*(self._receiver(receiver) for receiver in receivers))
        return [mic for receiver in results for mic in receiver]

    def _configured_receivers(self) -> list[dict[str, Any]]:
        configured_mics = self.settings.get("mics") or []
        if not configured_mics:
            return self.settings.get("receivers", [])
        grouped: dict[tuple[str, int], dict[str, Any]] = {}
        for mic in configured_mics:
            host = str(mic.get("host") or "").strip()
            port = int(mic.get("port") or 2202)
            model = str(mic.get("model") or "qlx-ulx").strip().lower()
            if not host:
                continue
            receiver = grouped.setdefault((host, port), {
                "id": re.sub(r"[^a-z0-9]+", "-", host.casefold()).strip("-") or "receiver",
                "name": mic.get("receiver_name") or host,
                "host": host,
                "port": port,
                "model": model,
                "channel_configs": [],
            })
            receiver["channel_configs"].append(mic)
        return list(grouped.values())

    async def _receiver(self, receiver: dict[str, Any]) -> list[dict[str, Any]]:
        channel_configs = receiver.get("channel_configs") or []
        channel_numbers = sorted({int(item.get("channel") or 1) for item in channel_configs}) if channel_configs else list(range(1, int(receiver.get("channels", 2)) + 1))
        states = {index: {"name": f"Channel {index}", "battery_percent": 0, "rf": 0, "audio": 0, "online": False, "receiver_online": False, "errors": [], "_battery_valid": False} for index in channel_numbers}
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(str(receiver.get("host", "")), int(receiver.get("port", 2202))), timeout=2)
            for channel in states:
                for key in ("CHAN_NAME", "BATT_BARS", "FREQUENCY", "TX_TYPE"):
                    writer.write(f"< GET {channel} {key} >".encode())
                writer.write(f"< SET {channel} METER_RATE 100 >".encode())
            await writer.drain()
            raw = b""
            deadline = asyncio.get_running_loop().time() + 1.25
            try:
                while len(raw) < 32768:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        break
                    chunk = await asyncio.wait_for(reader.read(4096), timeout=min(0.45, remaining))
                    if not chunk:
                        break
                    raw += chunk
                    seen = {(int(match.group(1)), match.group(2)) for match in FRAME.finditer(raw.decode(errors="ignore"))}
                    if all((channel, "BATT_BARS") in seen and (channel, "TX_TYPE") in seen and (channel, "ALL") in seen for channel in states):
                        break
            except asyncio.TimeoutError:
                pass
            writer.close()
            await writer.wait_closed()
            text = raw.decode(errors="ignore")
            for match in FRAME.finditer(text):
                channel, key, value = int(match.group(1)), match.group(2), (match.group(3) or "").strip()
                if channel not in states:
                    continue
                state = states[channel]
                state["receiver_online"] = True
                if key == "CHAN_NAME": state["name"] = value.replace("_", " ").strip()
                elif key == "BATT_BARS":
                    battery = battery_percent(value)
                    state["_battery_valid"] = battery is not None
                    state["battery_percent"] = battery if battery is not None else 0
                elif key == "FREQUENCY": state["frequency"] = value
                elif key == "TX_TYPE": state["tx_type"] = value
                elif key == "ALL":
                    parts = value.split()
                    if len(parts) >= 3:
                        state["rf"], state["audio"] = percent(parts[-2], 115), percent(parts[-1], 50)
        except (OSError, asyncio.TimeoutError) as exc:
            for state in states.values():
                state["errors"] = [str(exc) or "Receiver unavailable"]
        output = []
        receiver_id = str(receiver.get("id") or receiver.get("host") or "receiver")
        receiver_model = str(receiver.get("model") or "qlx-ulx").strip().lower()
        for channel, state in states.items():
            state["online"] = transmitter_active(state)
            state.pop("_battery_valid", None)
            if state["receiver_online"] and not state["online"] and not state["errors"]:
                state["errors"] = ["Transmitter off"]
            elif not state["receiver_online"] and not state["errors"]:
                state["errors"] = ["Receiver did not return status"]
            config = next((item for item in channel_configs if int(item.get("channel") or 1) == channel), {})
            configured_name = str(config.get("name") or "").strip()
            output.append({
                "id": str(config.get("id") or f"{receiver_id}-{channel}"),
                "receiver": config.get("receiver_name") or receiver.get("name") or receiver_id,
                "channel": channel,
                "model": str(config.get("model") or receiver_model),
                "default_photo": str(config.get("default_photo") or ""),
                **state,
                "name": configured_name or state["name"],
            })
        return output
