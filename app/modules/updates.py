"""Safe, versioned downloads for independently updateable modules."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import tempfile
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_CATALOG_URL = "https://raw.githubusercontent.com/wtapper89/ChurchBoard/main/modules/catalog.json"


class ModuleUpdateError(RuntimeError):
    pass


class ModulePackageManager:
    """Download module files without replacing the ChurchBoard application."""

    def __init__(self, data_dir: Path, catalog_url: str = DEFAULT_CATALOG_URL):
        self.root = data_dir / "modules"
        self.root.mkdir(parents=True, exist_ok=True)
        self.catalog_url = catalog_url

    def _request(self, url: str) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": "ChurchBoard module updater"})
        token = os.getenv("CHURCHBOARD_MODULE_UPDATE_TOKEN", "").strip()
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                return response.read()
        except Exception as exc:
            raise ModuleUpdateError(f"Could not download module data: {exc}") from exc

    def catalog(self) -> dict[str, Any]:
        try:
            payload = json.loads(self._request(self.catalog_url).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ModuleUpdateError("The module catalog is not valid JSON") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("modules"), list):
            raise ModuleUpdateError("The module catalog has an invalid shape")
        return payload

    def update(self, module_id: str, manifest: dict[str, Any]) -> Path:
        version = str(manifest.get("version") or "").strip()
        files = manifest.get("files")
        if not version or not isinstance(files, list) or not files:
            raise ModuleUpdateError(f"Module {module_id} has no downloadable files")
        staging = Path(tempfile.mkdtemp(prefix=f"{module_id}-", dir=self.root)).resolve()
        try:
            for item in files:
                relative = str(item.get("path") or "").strip()
                source = str(item.get("url") or "").strip()
                expected = str(item.get("sha256") or "").lower().strip()
                if not relative or not source or len(expected) != 64:
                    raise ModuleUpdateError(f"Module {module_id} contains an invalid file entry")
                target = (staging / relative).resolve()
                if staging not in target.parents:
                    raise ModuleUpdateError("Module file path escapes its package")
                target.parent.mkdir(parents=True, exist_ok=True)
                content = self._request(source)
                if hashlib.sha256(content).hexdigest() != expected:
                    raise ModuleUpdateError(f"Checksum failed for {relative}")
                target.write_bytes(content)
            destination = self.root / module_id / version
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                shutil.rmtree(destination)
            staging.rename(destination)
            active = destination.parent / "active"
            active.write_text(version, encoding="utf-8")
            return destination
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def active_file(self, module_id: str, relative: str) -> Path | None:
        active = self.root / module_id / "active"
        if not active.exists():
            return None
        version = active.read_text(encoding="utf-8").strip()
        path = (active.parent / version / relative).resolve()
        package_root = active.parent.resolve()
        return path if path.is_file() and package_root in path.parents else None

    def load_class(self, module_id: str, relative: str, name: str, fallback: Any) -> Any:
        """Load an updated class when present, otherwise use the bundled class."""
        path = self.active_file(module_id, relative)
        if path is None:
            return fallback
        spec = importlib.util.spec_from_file_location(f"churchboard_update_{module_id.replace('-', '_')}", path)
        if spec is None or spec.loader is None:
            return fallback
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return getattr(module, name, fallback)
