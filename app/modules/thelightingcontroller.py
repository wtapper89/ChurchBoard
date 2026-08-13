from __future__ import annotations

import asyncio
from typing import Any
from xml.etree import ElementTree


class TheLightingControllerClient:
    """TLC/ShowXpress External Application client, contributed by WorshipWarehouse."""

    APP_NAME = "thelightingcontrollerclient"

    def __init__(self, settings: dict[str, Any]):
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.get("enabled") and str(self.settings.get("host") or "").strip())

    async def _send(self, writer: asyncio.StreamWriter, *parts: str) -> None:
        writer.write(("|".join(parts) + "\r\n").encode("ascii")); await writer.drain()

    async def _connect(self):
        host, port = str(self.settings.get("host") or "").strip(), int(self.settings.get("port") or 7348)
        if not 1 <= port <= 65535: raise ValueError("External App port must be between 1 and 65535")
        try: reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), 3)
        except (OSError, asyncio.TimeoutError) as exc: raise ConnectionError(f"Could not connect to {host}:{port}: {exc}") from exc
        await self._send(writer, "HELLO", self.APP_NAME, str(self.settings.get("password") or ""))
        while True:
            line = await asyncio.wait_for(reader.readline(), 3)
            text = line.decode("utf-8", "replace").strip()
            if text == "HELLO": return reader, writer
            if not line or text.startswith("ERROR|"): writer.close(); await writer.wait_closed(); raise ConnectionError(text.partition("|")[2] or "Lighting controller rejected the connection")

    async def _button_list(self, reader, writer) -> list[dict[str, Any]]:
        await self._send(writer, "BUTTON_LIST")
        while True:
            text = (await asyncio.wait_for(reader.readline(), 3)).decode("utf-8", "replace").strip()
            if text.startswith("ERROR|"): raise ValueError(text.partition("|")[2])
            if not text: raise ConnectionError("Lighting controller closed the connection")
            if text.startswith("BUTTON_LIST|"):
                root = ElementTree.fromstring(text.partition("|")[2]); result = []
                for page in root.findall("page"):
                    elements = list(page.findall("button")); offset = 1 if any(e.get(a) == "0" for e in elements for a in ("column", "line")) else 0
                    for element in elements:
                        name = (element.text or "").strip()
                        if name: result.append({"name": name, "page": page.get("name") or "Lighting", "page_columns": int(page.get("columns") or 0), "column": int(element.get("column") or 0)+offset, "line": int(element.get("line") or 0)+offset, "color": element.get("color") or "#4c6b8a", "pressed": element.get("pressed") == "1", "flash": element.get("flash") == "1"})
                return sorted(result, key=lambda item: (item["page"].casefold(), item["line"], item["column"]))

    async def buttons(self) -> list[dict[str, Any]]:
        reader, writer = await self._connect()
        try: return await self._button_list(reader, writer)
        finally: writer.close(); await writer.wait_closed()

    async def trigger_button(self, name: str, mode: str = "toggle") -> None:
        if not name or any(c in name for c in "|\r\n") or mode not in {"press", "release", "toggle"}: raise ValueError("Invalid lighting button request")
        reader, writer = await self._connect()
        try:
            buttons = await self._button_list(reader, writer)
            button = next((item for item in buttons if item["name"] == name), None)
            if not button: raise ValueError("That lighting button is no longer available")
            if mode == "toggle" and button["flash"]:
                await self._send(writer, "BUTTON_PRESS", name); await self._send(writer, "BUTTON_RELEASE", name)
            else:
                command = "BUTTON_PRESS" if mode == "press" or (mode == "toggle" and not button["pressed"]) else "BUTTON_RELEASE"
                await self._send(writer, command, name)
        finally: writer.close(); await writer.wait_closed()
