from __future__ import annotations

from typing import Any

import httpx


class ProdMeshRTAClient:
    """Read ProdMesh Remote RTA's public, read-only HTTP API."""

    def __init__(self, settings: dict[str, Any]):
        self.settings = settings
        host = str(settings.get("host") or "127.0.0.1").strip()
        port = int(settings.get("port") or 8517)
        self.base_url = f"http://{host}:{port}"
        self._client = httpx.AsyncClient(timeout=1.5)

    @property
    def configured(self) -> bool:
        return bool(self.settings.get("enabled") and self.settings.get("host"))

    async def levels(self) -> dict[str, Any]:
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
        }

    async def close(self) -> None:
        await self._client.aclose()
