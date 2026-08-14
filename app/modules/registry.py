from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from pathlib import Path
import json

from app.modules.builtin import BUILTIN_MODULES
from app.modules.updates import ModulePackageManager, ModuleUpdateError


def _version_key(value: str) -> tuple[int, ...]:
    pieces: list[int] = []
    for piece in str(value or "0").split("."):
        digits = "".join(character for character in piece if character.isdigit())
        pieces.append(int(digits or 0))
    return tuple(pieces)


class ModuleRegistry:
    """Catalog, dependency, capability, and lifecycle registry for ChurchBoard modules.

    V2 keeps modules bundled while the module API stabilizes. The registry is the
    boundary used by Setup, dashboards, Producer pages, and the runtime so a
    module can later be installed or updated independently without adding another
    hard-coded integration branch to the ChurchBoard shell.
    """

    def __init__(self, data_dir=None, module_dirs=None) -> None:
        self._catalog = {item["id"]: deepcopy(item) for item in BUILTIN_MODULES}
        self.updater = ModulePackageManager(data_dir) if data_dir is not None else None
        self._remote: dict[str, dict[str, Any]] = {}
        self._discover_local_modules(module_dirs)

    def _discover_local_modules(self, module_dirs=None) -> None:
        """Add developer modules dropped into a modules/ directory.

        A local manifest is intentionally additive: bundled modules remain the
        safe fallback, while new module IDs become installable immediately.
        """
        roots = [Path(item) for item in (module_dirs or [])]
        for root in roots:
            if not root.is_dir():
                continue
            for manifest_path in root.glob("*/manifest.json"):
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    module_id = str(manifest.get("id") or manifest_path.parent.name).strip()
                    if module_id and module_id not in self._catalog:
                        manifest["id"] = module_id
                        self._catalog[module_id] = manifest
                except (OSError, json.JSONDecodeError, TypeError):
                    continue

    def manifest(self, module_id: str) -> dict[str, Any]:
        manifest = self._catalog.get(module_id)
        if not manifest:
            raise KeyError(module_id)
        return deepcopy(manifest)

    def widget_owner(self, widget_type: str) -> str | None:
        for module_id, manifest in self._catalog.items():
            if any(widget.get("type") == widget_type for widget in manifest.get("widgets", [])):
                return module_id
        return None

    @staticmethod
    def _settings_keys(manifest: dict[str, Any]) -> list[str]:
        keys = list(manifest.get("settings_keys") or [])
        legacy_key = str(manifest.get("settings_key") or "")
        if legacy_key and legacy_key not in keys:
            keys.append(legacy_key)
        return keys

    def _legacy_install_set(self, data: dict[str, Any]) -> set[str]:
        installed = {module_id for module_id, item in self._catalog.items() if item.get("core")}
        configured = data.get("settings") or {}
        widget_types = {
            str(widget.get("type") or "")
            for dashboard in data.get("dashboards") or []
            for widget in dashboard.get("widgets") or []
        }
        for module_id, manifest in self._catalog.items():
            settings_keys = self._settings_keys(manifest)
            owns_widget = any(widget.get("type") in widget_types for widget in manifest.get("widgets", []))
            enabled = any(bool((configured.get(key) or {}).get("enabled")) for key in settings_keys)
            if owns_widget or enabled or manifest.get("default_installed"):
                installed.add(module_id)
        return self.resolve_dependencies(installed)

    def resolve_dependencies(self, module_ids: set[str] | list[str]) -> set[str]:
        resolved = {module_id for module_id in module_ids if module_id in self._catalog}
        pending = list(resolved)
        while pending:
            module_id = pending.pop()
            for dependency in self._catalog[module_id].get("dependencies", []):
                if dependency not in resolved and dependency in self._catalog:
                    resolved.add(dependency)
                    pending.append(dependency)
        return resolved

    def reconcile(self, data: dict[str, Any]) -> bool:
        changed = False
        state = data.setdefault("modules", {})
        installed = state.setdefault("installed", {})
        legacy_wireless = [installed.pop(module_id) for module_id in ("shure-wireless", "sennheiser-wireless") if module_id in installed]
        if legacy_wireless:
            previous = installed.get("mics") or {}
            installed["mics"] = {
                **legacy_wireless[0],
                **previous,
                "version": self._catalog["mics"]["version"],
                "enabled": previous.get("enabled", any(item.get("enabled", True) for item in legacy_wireless)),
                "auto_update": previous.get("auto_update", any(item.get("auto_update", True) for item in legacy_wireless)),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            changed = True
        if not installed:
            now = datetime.now(timezone.utc).isoformat()
            for module_id in self._legacy_install_set(data):
                installed[module_id] = {
                    "version": self._catalog[module_id]["version"],
                    "enabled": True,
                    "auto_update": True,
                    "installed_at": now,
                }
            changed = True
        required = self.resolve_dependencies({module_id for module_id, item in installed.items() if item.get("enabled", True)})
        for module_id in required:
            if module_id not in installed:
                installed[module_id] = {
                    "version": self._catalog[module_id]["version"],
                    "enabled": True,
                    "auto_update": True,
                    "installed_at": datetime.now(timezone.utc).isoformat(),
                }
                changed = True
        for module_id, module_state in installed.items():
            manifest = self._catalog.get(module_id)
            if not manifest or not module_state.get("auto_update", True):
                continue
            available_version = str(manifest.get("version") or "0")
            installed_version = str(module_state.get("version") or "0")
            if _version_key(available_version) > _version_key(installed_version):
                module_state["version"] = available_version
                module_state["updated_at"] = datetime.now(timezone.utc).isoformat()
                changed = True
        return changed

    def install_for_widget_types(self, data: dict[str, Any], widget_types: set[str] | list[str]) -> list[str]:
        """Install owners and dependencies needed by an imported or saved page."""
        requested = {
            owner
            for widget_type in widget_types
            if (owner := self.widget_owner(str(widget_type))) is not None
        }
        added: set[str] = set()
        for module_id in requested:
            added.update(self.install(data, module_id))
        return sorted(added)

    def catalog(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        self.reconcile(data)
        installed = (data.get("modules") or {}).get("installed") or {}
        results = []
        for module_id, manifest in self._catalog.items():
            state = installed.get(module_id) or {}
            installed_version = str(state.get("version") or "")
            available_version = str(manifest.get("version") or "0")
            remote = self._remote.get(module_id) or {}
            if _version_key(str(remote.get("version") or "0")) > _version_key(available_version):
                available_version = str(remote["version"])
            item = deepcopy(manifest)
            item.update({
                "installed": module_id in installed,
                "enabled": bool(state.get("enabled", True)) if module_id in installed else False,
                "installed_version": installed_version,
                "available_version": available_version,
                "update_available": bool(installed_version and _version_key(available_version) > _version_key(installed_version)),
                "auto_update": bool(state.get("auto_update", True)),
                "remote_update": bool(remote),
            })
            results.append(item)
        return results

    def install(self, data: dict[str, Any], module_id: str) -> list[str]:
        if module_id not in self._catalog:
            raise KeyError(module_id)
        self.reconcile(data)
        installed = data["modules"]["installed"]
        requested = self.resolve_dependencies({module_id})
        added: list[str] = []
        now = datetime.now(timezone.utc).isoformat()
        for dependency in requested:
            manifest = self._catalog[dependency]
            if dependency not in installed:
                added.append(dependency)
            installed[dependency] = {
                **installed.get(dependency, {}),
                "version": manifest["version"],
                "enabled": True,
                "auto_update": installed.get(dependency, {}).get("auto_update", True),
                "installed_at": installed.get(dependency, {}).get("installed_at", now),
                "updated_at": now,
            }
        return sorted(added)

    def uninstall(self, data: dict[str, Any], module_id: str) -> None:
        manifest = self.manifest(module_id)
        if manifest.get("core"):
            raise ValueError("Core ChurchBoard modules cannot be removed")
        self.reconcile(data)
        installed = data["modules"]["installed"]
        dependents = [
            candidate
            for candidate, candidate_manifest in self._catalog.items()
            if candidate in installed and module_id in candidate_manifest.get("dependencies", [])
        ]
        if dependents:
            names = ", ".join(self._catalog[item]["name"] for item in dependents)
            raise ValueError(f"Remove {names} first because they require {manifest['name']}")
        installed.pop(module_id, None)
        for settings_key in self._settings_keys(manifest):
            if settings_key in (data.get("settings") or {}):
                data["settings"][settings_key]["enabled"] = False

    def update(self, data: dict[str, Any], module_id: str) -> None:
        if module_id not in self._catalog:
            raise KeyError(module_id)
        remote = self._remote.get(module_id)
        if remote and self.updater is not None:
            self.updater.update(module_id, remote)
            self.reconcile(data)
            data["modules"]["installed"].setdefault(module_id, {})["version"] = str(remote["version"])
            data["modules"]["installed"][module_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
            return
        self.install(data, module_id)

    def refresh_remote(self) -> dict[str, Any]:
        if self.updater is None:
            return {"updated": False, "error": "Module updates are unavailable in this runtime"}
        try:
            payload = self.updater.catalog()
            self._remote = {str(item.get("id")): item for item in payload.get("modules", []) if item.get("id")}
            # A catalog can introduce a brand-new module; no core release is
            # required for it to appear in Setup and become installable.
            for module_id, manifest in self._remote.items():
                if module_id not in self._catalog:
                    self._catalog[module_id] = deepcopy(manifest)
            return {"updated": True, "modules": sorted(self._remote)}
        except ModuleUpdateError as exc:
            return {"updated": False, "error": str(exc)}

    def set_auto_update(self, data: dict[str, Any], module_id: str, enabled: bool) -> None:
        self.reconcile(data)
        installed = data["modules"]["installed"]
        if module_id not in installed:
            raise ValueError("Install the module before changing its update policy")
        installed[module_id]["auto_update"] = bool(enabled)

    def public_frontend(self, data: dict[str, Any]) -> dict[str, Any]:
        items = self.catalog(data)
        return {
            "modules": [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "installed": item["installed"] and item["enabled"],
                    "frontend": item.get("frontend") or {},
                    "widgets": item.get("widgets") or [],
                    "pages": item.get("pages") or [],
                }
                for item in items
            ]
        }
