from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx


class RestreamClient:
    """Read-only client for Restream's documented v2 Events and Channels APIs."""
    base_url = "https://api.restream.io/v2"

    def __init__(self, settings: dict[str, Any]):
        self.settings = settings
        self.token = str(settings.get("access_token") or "").strip()
        self._client: httpx.AsyncClient | None = None

    async def exchange_code(self, code: str, redirect_uri: str) -> dict[str, Any]:
        return await self._token_request({"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri})

    async def refresh_access_token(self) -> dict[str, Any]:
        return await self._token_request({"grant_type": "refresh_token", "refresh_token": str(self.settings.get("refresh_token") or "")})

    async def _token_request(self, data: dict[str, str]) -> dict[str, Any]:
        client_id, client_secret = str(self.settings.get("client_id") or ""), str(self.settings.get("client_secret") or "")
        if not client_id or not client_secret:
            raise RuntimeError("Restream Client ID and Client Secret are required")
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.post("https://api.restream.io/oauth/token", data=data, auth=(client_id, client_secret))
            response.raise_for_status()
            return response.json()

    @property
    def configured(self) -> bool:
        return bool(self.settings.get("enabled") and self.token)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _request(self, path: str) -> Any:
        if not self.configured:
            raise RuntimeError("Restream is not configured")
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=8.0)
        response = await self._client.get(path, headers={"Authorization": f"Bearer {self.token}"})
        response.raise_for_status()
        return response.json()

    async def test_connection(self) -> dict[str, Any]:
        data = await self._request("/user/channels")
        return {"connected": True, "count": len(data.get("channels", data if isinstance(data, list) else []))}

    async def status(self) -> dict[str, Any]:
        live, upcoming, channels_data = await asyncio.gather(
            self._request("/user/events/in-progress"), self._request("/user/events/upcoming?scheduled=true"), self._request("/user/channels")
        )
        live_events = live if isinstance(live, list) else live.get("items", [])
        upcoming_events = upcoming if isinstance(upcoming, list) else upcoming.get("items", [])
        channels = channels_data.get("channels", channels_data if isinstance(channels_data, list) else [])
        event = next(iter(live_events), None)
        phase = "live" if event else "preparing" if upcoming_events else "offline"
        if event is None and upcoming_events:
            event = upcoming_events[0]
        linked = {str(item.get("channelId")): item for item in (event or {}).get("destinations", [])}
        destinations = [{
            "id": channel.get("id"), "name": channel.get("displayName") or channel.get("channelUrl") or "Streaming destination",
            "url": channel.get("channelUrl") or channel.get("url") or linked.get(str(channel.get("id")), {}).get("externalUrl") or "",
            "platform_id": channel.get("platformId") or channel.get("streamingPlatformId"), "active": str(channel.get("id")) in linked,
            "status": "healthy" if phase == "live" and str(channel.get("id")) in linked else "scheduled" if phase == "preparing" and str(channel.get("id")) in linked else "offline",
        } for channel in channels]
        viewers = None
        if phase == "live" and event and event.get("id"):
            try:
                analytics = await self._request(f"/user/events/{event['id']}/analytics/viewers")
                points = (analytics.get("total") or {}).get("viewersPerMinute") or []
                viewers = points[-1].get("viewers") if points else (analytics.get("total") or {}).get("mean")
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in {403, 404}:
                    raise
        started = (event or {}).get("startedAt")
        duration = max(0, int(datetime.now(timezone.utc).timestamp() - float(started))) if phase == "live" and started else 0
        return {"connected": True, "status": phase, "title": (event or {}).get("title") or "No active broadcast", "event_id": (event or {}).get("id"), "scheduled_for": (event or {}).get("scheduledFor"), "started_at": started, "duration_seconds": duration, "viewers": viewers, "bitrate_kbps": None, "health": "unavailable", "destinations": destinations, "message": "Encoder bitrate and health are not provided by the Restream public API."}
