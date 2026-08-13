from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx
import websockets


class ProdMeshRTAClient:
    """Consume ProdMesh's native level stream, with HTTP compatibility fallback."""

    def __init__(self, settings: dict[str, Any]):
        self.settings = settings
        host = str(settings.get("host") or "127.0.0.1").strip()
        port = int(settings.get("port") or 8517)
        self.base_url = f"http://{host}:{port}"
        self.stream_url = f"ws://{host}:{port}/api/stream"
        self._client = httpx.AsyncClient(timeout=1.5)
        self._stream_task: asyncio.Task | None = None
        self._latest: dict[str, Any] | None = None
        self._latest_at = 0.0
        self._latest_sequence = 0
        self._latest_event = asyncio.Event()
        self._frame_condition = asyncio.Condition()
        self._stream_error = ""
        self._closed = False
        self._fallback: dict[str, Any] | None = None
        self._fallback_at = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.settings.get("enabled") and self.settings.get("host"))

    @staticmethod
    def normalize_stream_frame(payload: dict[str, Any]) -> dict[str, Any] | None:
        if payload.get("type") != "levels":
            return None
        return {**payload, "connected": True, "transport": "websocket"}

    async def _stream(self) -> None:
        delay = .15
        while not self._closed and self.configured:
            try:
                async with websockets.connect(self.stream_url, open_timeout=1.5, close_timeout=.5, ping_interval=10, ping_timeout=3) as socket:
                    self._stream_error = ""
                    delay = .15
                    async for message in socket:
                        try:
                            payload = json.loads(message)
                        except (json.JSONDecodeError, TypeError):
                            continue
                        frame = self.normalize_stream_frame(payload) if isinstance(payload, dict) else None
                        if frame is None:
                            continue
                        self._latest = frame
                        self._latest_at = time.monotonic()
                        self._latest_sequence += 1
                        self._latest_event.set()
                        async with self._frame_condition:
                            self._frame_condition.notify_all()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._stream_error = str(exc)
                await asyncio.sleep(delay)
                delay = min(2.0, delay * 2)

    def _ensure_stream(self) -> None:
        if self._stream_task is None or self._stream_task.done():
            self._stream_task = asyncio.create_task(self._stream())

    async def _http_levels(self) -> dict[str, Any]:
        spl_response, rta_response = await self._client.get(f"{self.base_url}/api/spl"), await self._client.get(f"{self.base_url}/api/rta")
        spl_response.raise_for_status()
        rta_response.raise_for_status()
        spl, rta = spl_response.json(), rta_response.json()
        return {
            **spl,
            "connected": True,
            "centers_hz": rta.get("centers_hz") or [],
            "bands_db": rta.get("bands_db") or [],
            "peaks_db": rta.get("peaks_db") or [],
            "cal_db": rta.get("cal_db", spl.get("cal_db")),
            "transport": "http-fallback",
        }

    async def levels(self) -> dict[str, Any]:
        self._ensure_stream()
        if self._latest is None:
            self._latest_event.clear()
            try:
                await asyncio.wait_for(self._latest_event.wait(), .35)
            except asyncio.TimeoutError:
                pass
        if self._latest is not None and time.monotonic() - self._latest_at <= 2.0:
            return {**self._latest, "stream_age_ms": round((time.monotonic() - self._latest_at) * 1000)}
        now = time.monotonic()
        if self._fallback is not None and now - self._fallback_at < .5:
            return self._fallback
        self._fallback = await self._http_levels()
        self._fallback_at = now
        if self._stream_error:
            self._fallback["stream_error"] = self._stream_error
        return self._fallback

    async def wait_for_frame(self, after_sequence: int = 0, timeout: float = 2.0) -> tuple[int, dict[str, Any]]:
        """Wait for the next pushed analyzer frame for browser relay clients."""
        self._ensure_stream()
        if self._latest is not None and self._latest_sequence > after_sequence:
            return self._latest_sequence, {**self._latest, "stream_age_ms": round((time.monotonic() - self._latest_at) * 1000)}
        async with self._frame_condition:
            try:
                await asyncio.wait_for(self._frame_condition.wait_for(lambda: self._latest_sequence > after_sequence), timeout)
            except asyncio.TimeoutError:
                pass
        if self._latest is None:
            return self._latest_sequence, await self.levels()
        return self._latest_sequence, {**self._latest, "stream_age_ms": round((time.monotonic() - self._latest_at) * 1000)}

    async def close(self) -> None:
        self._closed = True
        if self._stream_task is not None:
            self._stream_task.cancel()
            try:
                await self._stream_task
            except asyncio.CancelledError:
                pass
            self._stream_task = None
        await self._client.aclose()
