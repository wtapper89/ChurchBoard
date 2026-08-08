from __future__ import annotations

import os
import json
import sys
from dataclasses import dataclass
from pathlib import Path


if getattr(sys, "frozen", False):
    ROOT_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    DATA_DIR = Path(os.getenv("CHURCHBOARD_DATA_DIR", Path.home() / ".churchboard"))
else:
    ROOT_DIR = Path(__file__).resolve().parents[1]
    DATA_DIR = Path(os.getenv("CHURCHBOARD_DATA_DIR", ROOT_DIR / "data"))


@dataclass(frozen=True)
class AppConfig:
    host: str
    port: int
    data_file: Path
    ssl_certfile: Path | None = None
    ssl_keyfile: Path | None = None

    @property
    def scheme(self) -> str:
        return "https" if self.ssl_certfile and self.ssl_keyfile else "http"


def load_config() -> AppConfig:
    data_file = Path(os.getenv("CHURCHBOARD_DATA_FILE", DATA_DIR / "churchboard.json"))
    saved: dict = {}
    try:
        payload = json.loads(data_file.read_text(encoding="utf-8"))
        saved = (payload.get("settings") or {}).get("server") or {}
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    https_enabled = bool(saved.get("https_enabled"))
    cert = os.getenv("CHURCHBOARD_SSL_CERTFILE", str(saved.get("ssl_certfile") or "") if https_enabled else "").strip()
    key = os.getenv("CHURCHBOARD_SSL_KEYFILE", str(saved.get("ssl_keyfile") or "") if https_enabled else "").strip()
    if bool(cert) != bool(key):
        raise ValueError("Set both CHURCHBOARD_SSL_CERTFILE and CHURCHBOARD_SSL_KEYFILE to enable HTTPS")
    return AppConfig(
        host=os.getenv("CHURCHBOARD_HOST", "0.0.0.0"),
        port=int(os.getenv("CHURCHBOARD_PORT", str(saved.get("port") or 8040))),
        data_file=data_file,
        ssl_certfile=Path(cert).expanduser() if cert else None,
        ssl_keyfile=Path(key).expanduser() if key else None,
    )
