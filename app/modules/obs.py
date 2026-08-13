from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import uuid
from typing import Any

import websockets


# General, Scenes, Inputs, Outputs, and InputVolumeMeters.  This is a passive
# subscription; ChurchBoard never asks OBS to change stream, record, or scenes.
EVENT_SUBSCRIPTIONS = 1 | 4 | 8 | 64 | 65536


def _authentication(password: str, salt: str, challenge: str) -> str:
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()


class OBSClient:
    """Read-only obs-websocket v5 monitor with event-backed audio telemetry."""
    def __init__(self, settings: dict[str, Any]):
        self.settings = settings
        self.ws: Any = None
        self._events: dict[str, Any] = {"audio": {}, "alerts": []}

    @property
    def configured(self) -> bool:
        return bool(self.settings.get("enabled") and str(self.settings.get("host") or "").strip())

    async def close(self) -> None:
        if self.ws:
            await self.ws.close()
            self.ws = None

    async def _connect(self) -> None:
        # websockets 14+ uses ``ClientConnection.state`` instead of the old
        # ``.closed`` attribute. Runtime clears this reference whenever a
        # request fails, so a retained socket is the active monitor session.
        # Checking the removed attribute here made OBS connect successfully,
        # then disconnect on ChurchBoard's next telemetry refresh.
        if self.ws is not None:
            return
        host, port = str(self.settings.get("host") or "").strip(), int(self.settings.get("port") or 4455)
        self.ws = await websockets.connect(f"ws://{host}:{port}", open_timeout=3, close_timeout=1, subprotocols=["obswebsocket.json"])
        hello = json.loads(await asyncio.wait_for(self.ws.recv(), 3))
        if hello.get("op") != 0:
            raise RuntimeError("OBS did not return an obs-websocket v5 hello")
        auth = hello.get("d", {}).get("authentication") or {}
        identify: dict[str, Any] = {"rpcVersion": 1, "eventSubscriptions": EVENT_SUBSCRIPTIONS}
        if auth:
            identify["authentication"] = _authentication(str(self.settings.get("password") or ""), str(auth.get("salt") or ""), str(auth.get("challenge") or ""))
        await self.ws.send(json.dumps({"op": 1, "d": identify}))
        identified = json.loads(await asyncio.wait_for(self.ws.recv(), 3))
        if identified.get("op") != 2:
            raise RuntimeError("OBS rejected ChurchBoard's monitor connection")

    def _event(self, payload: dict[str, Any]) -> None:
        data = payload.get("d") or {}
        event_type = data.get("eventType")
        event_data = data.get("eventData") or {}
        if event_type == "InputVolumeMeters":
            for input_data in event_data.get("inputs") or []:
                levels = input_data.get("inputLevelsMul") or []
                peak = max((float(channel[1] if len(channel) > 1 else channel[0]) for channel in levels if channel), default=0.0)
                self._events["audio"][str(input_data.get("inputName") or "Master")] = 20 * math.log10(max(peak, 1e-6))
        elif event_type in {"StreamStateChanged", "RecordStateChanged"}:
            self._events[event_type] = event_data

    async def _request(self, request_type: str, request_data: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = uuid.uuid4().hex
        await self.ws.send(json.dumps({"op": 6, "d": {"requestType": request_type, "requestId": request_id, "requestData": request_data or {}}}))
        while True:
            packet = json.loads(await asyncio.wait_for(self.ws.recv(), 3))
            if packet.get("op") == 5:
                self._event(packet)
                continue
            if packet.get("op") == 7 and packet.get("d", {}).get("requestId") == request_id:
                data = packet["d"]
                if not data.get("requestStatus", {}).get("result"):
                    raise RuntimeError(data.get("requestStatus", {}).get("comment") or f"OBS rejected {request_type}")
                return data.get("responseData") or {}

    async def _optional_request(self, request_type: str, request_data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return an empty value for OBS features that are legitimately off.

        Preview-scene status is only available with Studio Mode. It must never
        turn a read-only health monitor into a failed connection.
        """
        try:
            return await self._request(request_type, request_data)
        except RuntimeError:
            return {}

    async def status(self) -> dict[str, Any]:
        await self._connect()
        # Requests are intentionally sequential: obs-websocket can emit events
        # between responses, and one socket must have only one active reader.
        stream = await self._request("GetStreamStatus")
        record = await self._request("GetRecordStatus")
        stats = await self._request("GetStats")
        program = await self._request("GetCurrentProgramScene")
        preview = await self._optional_request("GetCurrentPreviewScene")
        scenes = await self._optional_request("GetSceneItemList", {"sceneName": program.get("currentProgramSceneName", "")}) if program.get("currentProgramSceneName") else {}
        for _ in range(3):
            try:
                packet = json.loads(await asyncio.wait_for(self.ws.recv(), .03))
                if packet.get("op") == 5: self._event(packet)
            except asyncio.TimeoutError: break
        total = int(stream.get("outputTotalFrames") or 0)
        dropped = int(stream.get("outputSkippedFrames") or 0)
        dropped_percent = round(dropped / total * 100, 2) if total else 0.0
        threshold = float(self.settings.get("dropped_frames_threshold") or 2)
        audio = self._events["audio"]
        return {"connected": True, "streaming": bool(stream.get("outputActive")), "recording": bool(record.get("outputActive")), "stream_timecode": stream.get("outputTimecode", "00:00:00"), "record_timecode": record.get("outputTimecode", "00:00:00"), "bitrate_kbps": round(float(stream.get("outputBytes") or 0) * 8 / max(float(stream.get("outputDuration") or 1), 1) / 1000, 1), "fps": round(float(stats.get("activeFps") or 0), 1), "cpu_percent": round(float(stats.get("cpuUsage") or 0), 1), "disk_free_mb": int(stats.get("availableDiskSpace") or 0), "dropped_frames": dropped, "dropped_percent": dropped_percent, "program_scene": program.get("currentProgramSceneName", ""), "preview_scene": preview.get("currentPreviewSceneName", ""), "sources": [{"name": row.get("sourceName", ""), "visible": bool(row.get("sceneItemEnabled"))} for row in scenes.get("sceneItems", [])], "audio_db": round(max(audio.values(), default=-60), 1), "audio_sources": audio, "preview_url": str(self.settings.get("preview_url") or ""), "alert": "Dropped frames exceed threshold" if dropped_percent > threshold else ("Stream stopped" if not stream.get("outputActive") else "")}
