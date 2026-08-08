from __future__ import annotations

import json
import os
import tempfile
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_WIDGETS = [
    {"id": "clock", "type": "clock", "x": 0, "y": 0, "w": 3, "h": 2, "title": "Local Time", "settings": {}},
    {"id": "service", "type": "service", "x": 3, "y": 0, "w": 5, "h": 2, "title": "Service", "settings": {}},
    {"id": "timing", "type": "timing", "x": 8, "y": 0, "w": 4, "h": 2, "title": "Timing", "settings": {}},
    {"id": "assignments", "type": "assignments", "x": 0, "y": 2, "w": 7, "h": 6, "title": "Scheduled Positions & Mics", "settings": {"team_ids": [], "position_keys": [], "position_labels": {}, "positions": [], "display_mode": "photos", "card_grouping": "person", "use_planning_center_icon": False, "unassigned_media_title": "Icon"}},
    {"id": "slides", "type": "slides", "x": 7, "y": 2, "w": 5, "h": 4, "title": "ProPresenter", "settings": {"show_notes": True, "slide_mode": "image", "slide_layout": "full", "show_current": True, "show_next": True, "show_parts": True, "show_slide_count": False}},
    {"id": "order", "type": "order", "x": 7, "y": 6, "w": 5, "h": 2, "title": "Order of Service", "settings": {"display_mode": "current", "limit": 6, "show_leader": False, "show_mic": False}},
    {"id": "playlist", "type": "playlist", "x": 0, "y": 8, "w": 12, "h": 6, "title": "ProPresenter Playlist", "settings": {"allow_remote_trigger": True, "keyboard_control": False, "density": "comfortable", "auto_scroll": True, "active_border_color": "#f5c400"}},
]


def default_data() -> dict[str, Any]:
    main_widgets = deepcopy(DEFAULT_WIDGETS)
    green_room_widgets = deepcopy(DEFAULT_WIDGETS)
    audio_widgets = deepcopy(DEFAULT_WIDGETS)
    next(widget for widget in audio_widgets if widget["id"] == "assignments")["settings"]["display_mode"] = "technical"
    audio_widgets.append({"id": "osm", "type": "spl", "x": 7, "y": 8, "w": 5, "h": 3, "title": "Open Sound Meter", "settings": {"green_max": 75, "orange_max": 85, "reports_enabled": True}})
    return {
        "version": 3,
        "settings": {
            "organization_name": "My Church",
            "timezone": "America/New_York",
            "demo_mode": True,
            "planning_center": {
                "enabled": False,
                "application_id": "",
                "secret": "",
                "service_type_ids": [],
                "service_types": [],
                "open_days_before": 2,
                "open_hours_before": 3,
                "close_hours_after": 3,
                "refresh_seconds": 60,
                "detail_refresh_seconds": 5,
                "live_from_propresenter": {
                    "enabled": False,
                    "auto_take_control": True,
                    "songs_only": True,
                    "allow_previous": False,
                    "match_mode": "exact",
                    "stable_seconds": 2,
                    "refresh_seconds": 0.5,
                },
            },
            "propresenter": {"enabled": False, "host": "127.0.0.1", "port": 50001, "refresh_seconds": 0.075, "remote_control_enabled": False},
            "shure": {"enabled": False, "refresh_seconds": 0.5, "receivers": [], "mics": []},
            "sennheiser": {"enabled": False, "refresh_seconds": 0.5, "receivers": [], "mics": []},
            "open_sound_meter": {
                "enabled": False,
                "reports_enabled": True,
                "report_weighting": "A",
                "report_response": "Fast",
                "source_id": "",
            },
            "restream": {"enabled": False, "client_id": "", "client_secret": "", "access_token": "", "refresh_token": "", "access_token_expires_at": 0, "refresh_seconds": 5},
            "obs": {"enabled": False, "host": "127.0.0.1", "port": 4455, "password": "", "refresh_seconds": 0.5, "dropped_frames_threshold": 2, "preview_url": ""},
            "server": {"port": 8040, "https_enabled": False, "ssl_certfile": "", "ssl_keyfile": ""},
            "position_mic_map": {"Vox 1": "mic-1", "Vox 2": "mic-2"},
            "manual_plan": None,
        },
        "dashboards": [
            {"id": "main", "name": "Main", "slug": "main", "background_color": "#0a0d12", "columns": 12, "row_height": 72, "widgets": main_widgets},
            {"id": "green-room", "name": "Green Room", "slug": "green-room", "background_color": "#0a0d12", "columns": 12, "row_height": 72, "widgets": green_room_widgets},
            {"id": "audio", "name": "Audio Board", "slug": "audio", "background_color": "#0a0d12", "columns": 12, "row_height": 72, "widgets": audio_widgets},
        ],
        "organization": {
            "auth_enabled": False,
            "passwords_required": True,
            "campuses": [{"id": "main", "name": "Main Campus"}],
        },
        "users": [],
        "invitations": [],
        "secrets": {"livestream": {}},
        "producer": {
            "checklist_templates": [],
            "resources": [],
            "completions": [],
            "activity": [],
            "media_tag_rules": [],
        },
    }


class ConfigStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.save(default_data())

    def load(self) -> dict[str, Any]:
        with self._lock:
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raw = default_data()
            baseline = default_data()
            baseline.update(raw)
            baseline["settings"] = {**default_data()["settings"], **raw.get("settings", {})}
            for section in ("planning_center", "propresenter", "shure", "sennheiser", "open_sound_meter", "restream", "obs", "server"):
                baseline["settings"][section] = {
                    **default_data()["settings"][section],
                    **raw.get("settings", {}).get(section, {}),
                }
            baseline["settings"]["planning_center"]["live_from_propresenter"] = {
                **default_data()["settings"]["planning_center"]["live_from_propresenter"],
                **(raw.get("settings", {}).get("planning_center", {}).get("live_from_propresenter") or {}),
            }
            baseline["organization"] = {
                **default_data()["organization"],
                **(raw.get("organization") or {}),
            }
            baseline["organization"]["campuses"] = list(
                baseline["organization"].get("campuses") or default_data()["organization"]["campuses"]
            )
            baseline["users"] = list(raw.get("users") or [])
            baseline["invitations"] = list(raw.get("invitations") or [])
            baseline["secrets"] = {
                "livestream": dict((raw.get("secrets") or {}).get("livestream") or {}),
            }
            baseline["producer"] = {
                **default_data()["producer"],
                **(raw.get("producer") or {}),
            }
            for key in ("checklist_templates", "resources", "completions", "activity", "media_tag_rules"):
                baseline["producer"][key] = list(baseline["producer"].get(key) or [])
            for dashboard in baseline.get("dashboards", []):
                dashboard.pop("theme", None)
                if dashboard.get("id") == "audio" and not any(widget.get("type") == "spl" for widget in dashboard.get("widgets", [])):
                    dashboard.setdefault("widgets", []).append({"id": "osm", "type": "spl", "x": 7, "y": 8, "w": 5, "h": 3, "title": "Open Sound Meter", "settings": {"green_max": 75, "orange_max": 85, "reports_enabled": True}})
                color = str(dashboard.get("background_color") or "").strip().lower()
                valid_color = len(color) == 7 and color.startswith("#") and all(
                    character in "0123456789abcdef" for character in color[1:]
                )
                dashboard["background_color"] = color if valid_color else "#0a0d12"
                for widget in dashboard.get("widgets", []):
                    if widget.get("type") == "mics":
                        widget["type"] = "assignments"
                        if widget.get("title") in {"", "Microphones"}:
                            widget["title"] = "Scheduled Positions & Mics"
                    if widget.get("type") == "assignments":
                        widget["settings"] = {"team_ids": [], "position_keys": [], "position_labels": {}, "display_mode": "photos", "card_grouping": "person", "use_planning_center_icon": False, "unassigned_media_title": "Icon", **widget.get("settings", {})}
                    if widget.get("type") == "slides":
                        widget["settings"] = {"slide_mode": "image", "slide_layout": "full", "show_current": True, "show_next": True, "show_parts": True, "show_slide_count": False, "show_notes": True, "show_grid": False, "allow_remote_trigger": False, **widget.get("settings", {})}
                    if widget.get("type") == "playlist":
                        widget["settings"] = {"allow_remote_trigger": True, "keyboard_control": False, "density": "comfortable", "auto_scroll": True, "active_border_color": "#f5c400", **widget.get("settings", {})}
                    if widget.get("type") == "livestreams":
                        widget["settings"] = {"sources": [], **widget.get("settings", {})}
                    if widget.get("type") == "order":
                        widget["settings"] = {"display_mode": "current", "limit": 6, "show_leader": False, "show_mic": False, **widget.get("settings", {})}
                    if widget.get("type") == "spl":
                        widget["settings"] = {"green_max": 75, "orange_max": 85, "reports_enabled": True, **widget.get("settings", {})}
            baseline["dashboards"] = [dashboard for dashboard in baseline["dashboards"] if dashboard.get("id") != "service-producer"]
            return baseline

    def save(self, data: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix="churchboard-", suffix=".json", dir=self.path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(data, handle, indent=2)
                    handle.write("\n")
                os.chmod(temporary, 0o600)
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return deepcopy(data)

    def public_settings(self) -> dict[str, Any]:
        settings = deepcopy(self.load()["settings"])
        pc = settings.get("planning_center", {})
        pc["secret_configured"] = bool(pc.get("secret"))
        pc["secret"] = ""
        restream = settings.get("restream", {})
        restream["access_token_configured"] = bool(restream.get("access_token"))
        restream["client_secret_configured"] = bool(restream.get("client_secret"))
        restream["access_token"] = ""
        restream["client_secret"] = ""
        restream["refresh_token"] = ""
        obs = settings.get("obs", {})
        obs["password_configured"] = bool(obs.get("password"))
        obs["password"] = ""
        return settings
