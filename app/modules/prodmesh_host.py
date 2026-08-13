from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import shutil
import tarfile
from pathlib import Path
from typing import Any

from app.config import DATA_DIR, ROOT_DIR


class HostedProdMeshRTA:
    """Start and supervise the ProdMesh Remote RTA bundled with ChurchBoard."""

    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._key: tuple[Any, ...] | None = None
        self._error = ""
        self._started_at = 0.0
        self._lock = threading.RLock()

    @staticmethod
    def executable() -> Path | None:
        configured = str(os.getenv("CHURCHBOARD_PRODMESH_RTA_PATH") or "").strip()
        candidates = [Path(configured).expanduser()] if configured else []
        archive = ROOT_DIR / "prodmesh-rta-bundle.tar.gz"
        if archive.is_file():
            runtime_root = DATA_DIR / "runtime" / "prodmesh-rta"
            marker = runtime_root / ".bundle-version"
            archive_stat = archive.stat()
            signature = f"{archive_stat.st_size}:{archive_stat.st_mtime_ns}"
            try:
                current_signature = marker.read_text(encoding="utf-8")
            except OSError:
                current_signature = ""
            if current_signature != signature:
                temporary = runtime_root.with_name("prodmesh-rta.new")
                shutil.rmtree(temporary, ignore_errors=True)
                temporary.mkdir(parents=True, exist_ok=True)
                with tarfile.open(archive, "r:gz") as bundle:
                    bundle.extractall(temporary, filter="data")
                shutil.rmtree(runtime_root, ignore_errors=True)
                temporary.rename(runtime_root)
                marker.write_text(signature, encoding="utf-8")
            candidates.extend([
                runtime_root / "ProdMeshRemoteRTA.app" / "Contents" / "MacOS" / "ProdMeshRemoteRTA",
                runtime_root / "ProdMeshRemoteRTA.exe",
                runtime_root / "ProdMeshRemoteRTA",
            ])
            candidates.extend(runtime_root.rglob("ProdMeshRemoteRTA.app/Contents/MacOS/ProdMeshRemoteRTA"))
            candidates.extend(runtime_root.rglob("ProdMeshRemoteRTA.exe"))
            candidates.extend(path for path in runtime_root.rglob("ProdMeshRemoteRTA") if path.parent.name != "MacOS")
        candidates.extend([
            ROOT_DIR / "build" / "prodmesh-rta" / "ProdMeshRemoteRTA.app" / "Contents" / "MacOS" / "ProdMeshRemoteRTA",
            ROOT_DIR / "prodmesh-rta" / "ProdMeshRemoteRTA.app" / "Contents" / "MacOS" / "ProdMeshRemoteRTA",
            ROOT_DIR / "prodmesh-rta" / "Contents" / "MacOS" / "ProdMeshRemoteRTA",
            ROOT_DIR / "build" / "prodmesh-rta" / "ProdMeshRemoteRTA.exe",
            ROOT_DIR / "prodmesh-rta" / "ProdMeshRemoteRTA.exe",
            ROOT_DIR / "build" / "prodmesh-rta" / "ProdMeshRemoteRTA",
            ROOT_DIR / "prodmesh-rta" / "ProdMeshRemoteRTA",
        ])
        return next((path for path in candidates if path.is_file()), None)

    @staticmethod
    def embedded(settings: dict[str, Any]) -> bool:
        return bool(settings.get("enabled") and str(settings.get("mode") or "embedded") == "embedded")

    def configure(self, settings: dict[str, Any]) -> None:
        key = (self.embedded(settings), int(settings.get("port") or 8517))
        with self._lock:
            if key == self._key and self.running:
                return
            self.stop()
            self._key = key
            if key[0]:
                self.start(key[1])

    @property
    def running(self) -> bool:
        return bool(self._process is not None and self._process.poll() is None)

    def start(self, port: int) -> None:
        executable = self.executable()
        if executable is None:
            self._error = "This ChurchBoard build does not contain the embedded ProdMesh RTA engine"
            return
        options: dict[str, Any] = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if sys.platform == "win32":
            options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        environment = os.environ.copy()
        plugin_directory = executable.parent / "plugins"
        if plugin_directory.is_dir():
            environment.setdefault("QT_PLUGIN_PATH", str(plugin_directory))
        if sys.platform.startswith("linux"):
            environment["LD_LIBRARY_PATH"] = os.pathsep.join(filter(None, [str(executable.parent), environment.get("LD_LIBRARY_PATH", "")]))
        options["env"] = environment
        try:
            self._process = subprocess.Popen([str(executable), "--api", str(port)], **options)
            self._started_at = time.time()
            self._error = ""
        except OSError as exc:
            self._process = None
            self._error = str(exc)

    def stop(self) -> None:
        process, self._process = self._process, None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)

    def restart(self, settings: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.stop()
            self._key = None
            self.configure(settings)
            return self.status(settings)

    def open(self, settings: dict[str, Any]) -> dict[str, Any]:
        # ProdMesh is a native application. Starting it shows its input,
        # calibration, alarm, and API controls; an already-running instance is
        # left intact so measurements are never interrupted just to show it.
        with self._lock:
            if not self.running:
                self._key = None
                self.configure(settings)
            elif sys.platform == "darwin":
                app_bundle = next((parent for parent in executable.parents if parent.suffix == ".app"), None) if (executable := self.executable()) else None
                if app_bundle:
                    subprocess.run(["/usr/bin/open", str(app_bundle)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return self.status(settings)

    def status(self, settings: dict[str, Any] | None = None) -> dict[str, Any]:
        settings = settings or {}
        executable = self.executable()
        return {
            "embedded": self.embedded(settings),
            "available": executable is not None,
            "running": self.running,
            "pid": self._process.pid if self.running else None,
            "started_at": self._started_at or None,
            "engine_path": str(executable) if executable else "",
            "error": self._error,
        }
