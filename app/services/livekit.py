from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def _url64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def access_token(
    api_key: str,
    api_secret: str,
    identity: str,
    name: str,
    room: str,
    metadata: dict[str, Any],
    ttl_seconds: int = 3600,
) -> str:
    """Create a LiveKit-compatible HS256 room token without another SDK."""
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": api_key,
        "sub": identity,
        "name": name,
        "nbf": now - 10,
        "exp": now + max(60, ttl_seconds),
        "metadata": json.dumps(metadata, separators=(",", ":")),
        "video": {
            "roomJoin": True,
            "room": room,
            "canPublish": True,
            "canSubscribe": True,
            "canPublishData": True,
            "canPublishSources": ["microphone"],
        },
    }
    signing_input = f"{_url64(json.dumps(header, separators=(',', ':')).encode())}.{_url64(json.dumps(payload, separators=(',', ':')).encode())}"
    signature = hmac.new(api_secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_url64(signature)}"


class HostedIntercomServer:
    """Run ChurchBoard's bundled LiveKit server as a managed local service."""

    SIGNAL_PORT = 7880
    TCP_PORT = 7881
    UDP_PORT = 7882

    def __init__(self, data_file: Path):
        self.directory = data_file.parent / "intercom"
        self.process: subprocess.Popen | None = None
        self.binary_path = ""
        self.error = ""
        self._settings_key: tuple[Any, ...] | None = None
        self._log_handle = None
        self._last_start = 0.0

    @staticmethod
    def _binary_candidates() -> list[Path]:
        name = "livekit-server.exe" if sys.platform == "win32" else "livekit-server"
        roots = [
            os.getenv("CHURCHBOARD_LIVEKIT_SERVER_PATH", ""),
            os.getenv("CHURCHBOARD_LIVEKIT_SERVER", ""),
        ]
        if getattr(sys, "frozen", False):
            bundle = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
            roots.extend([str(bundle / "livekit-server" / name), str(bundle / name)])
        project = Path(__file__).resolve().parents[2]
        roots.extend([
            str(project / "livekit-server" / name),
            str(project / "packaging" / "runtime" / name),
            shutil.which(name) or "",
            "/opt/homebrew/bin/livekit-server",
            "/usr/local/bin/livekit-server",
            "C:/Program Files/ChurchBoard/livekit-server.exe",
        ])
        candidates: list[Path] = []
        seen: set[str] = set()
        for raw in roots:
            if not raw:
                continue
            path = Path(raw).expanduser()
            key = str(path)
            if key not in seen:
                seen.add(key)
                candidates.append(path)
        return candidates

    @classmethod
    def find_binary(cls) -> Path | None:
        return next((path for path in cls._binary_candidates() if path.is_file()), None)

    def _write_config(self, api_key: str, api_secret: str) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        config = self.directory / "livekit.yaml"
        # Credentials are generated and stored by ChurchBoard. Quoted JSON
        # strings are also valid YAML scalars and prevent punctuation from
        # changing the structure of this private configuration file.
        config.write_text(
            "\n".join([
                f"port: {self.SIGNAL_PORT}",
                "rtc:",
                f"  tcp_port: {self.TCP_PORT}",
                f"  udp_port: {self.UDP_PORT}",
                "  use_external_ip: false",
                "keys:",
                f"  {json.dumps(api_key)}: {json.dumps(api_secret)}",
                "logging:",
                "  level: warn",
                "room:",
                "  enabled_codecs:",
                "    - mime: audio/opus",
                "",
            ]),
            encoding="utf-8",
        )
        try:
            config.chmod(0o600)
        except OSError:
            pass
        return config

    @staticmethod
    def _port_ready(port: int) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.04):
                return True
        except OSError:
            return False

    def _last_log_line(self) -> str:
        try:
            lines = (self.directory / "livekit.log").read_text(encoding="utf-8", errors="replace").splitlines()
            return lines[-1][-300:] if lines else ""
        except OSError:
            return ""

    def configure(self, settings: dict[str, Any]) -> None:
        enabled = bool(settings.get("enabled"))
        api_key = str(settings.get("api_key") or "")
        api_secret = str(settings.get("api_secret") or "")
        desired_key = (enabled, api_key, api_secret)
        if not enabled:
            self.stop()
            self.error = ""
            self._settings_key = desired_key
            return
        if not api_key or not api_secret:
            self.stop()
            self.error = "ChurchBoard has not generated the intercom credentials yet"
            return
        if self.process is not None and self.process.poll() is None and desired_key == self._settings_key:
            return
        if desired_key == self._settings_key and time.monotonic() - self._last_start < 5:
            return
        self.stop()
        binary = self.find_binary()
        if binary is None:
            self.error = "The hosted intercom engine is missing from this ChurchBoard installation"
            self.binary_path = ""
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        config = self._write_config(api_key, api_secret)
        log_path = self.directory / "livekit.log"
        try:
            self._log_handle = log_path.open("a", encoding="utf-8")
            options: dict[str, Any] = {
                "stdout": self._log_handle,
                "stderr": subprocess.STDOUT,
                "stdin": subprocess.DEVNULL,
            }
            if sys.platform == "win32":
                options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            else:
                options["start_new_session"] = True
            self.process = subprocess.Popen(
                [str(binary), "--config", str(config)],
                **options,
            )
            self.binary_path = str(binary)
            self._settings_key = desired_key
            self._last_start = time.monotonic()
            self.error = ""
        except OSError as exc:
            self.stop()
            self.error = f"Could not start the hosted intercom engine: {exc}"

    def stop(self) -> None:
        process, self.process = self.process, None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        if self._log_handle is not None:
            try:
                self._log_handle.close()
            except OSError:
                pass
            self._log_handle = None

    def status(self) -> dict[str, Any]:
        running = self.process is not None and self.process.poll() is None
        ready = running and self._port_ready(self.SIGNAL_PORT)
        error = self.error
        if self.process is not None and self.process.poll() is not None and not error:
            detail = self._last_log_line()
            error = f"The hosted intercom engine stopped unexpectedly{': ' + detail if detail else ''}"
        return {
            "running": running,
            "ready": ready,
            "error": error,
            "binary_path": self.binary_path,
            "signal_port": self.SIGNAL_PORT,
            "tcp_port": self.TCP_PORT,
            "udp_port": self.UDP_PORT,
        }
