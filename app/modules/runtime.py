from __future__ import annotations

import asyncio
from difflib import SequenceMatcher
import json
import re
import time
import unicodedata
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.modules.planning_center import (
    PlanningCenterClient,
    calculate_timing,
    parse_time,
    people_for_service_time,
    selected_service_time,
    service_items,
)
from app.modules.propresenter import ProPresenterClient
from app.modules.shure import ShureClient
from app.modules.sennheiser import SennheiserClient
from app.modules.spl_reports import SPLReportStore
from app.modules.osm import OSMListener
from app.modules.obs import OBSClient
from app.modules.restream import RestreamClient
from app.modules.media_cache import PlanningCenterMediaCache
from app.modules.ndi import NDIRuntime
from app.modules.livekit import HostedIntercomServer
from app.modules.prodmesh_rta import ProdMeshRTAClient
from app.modules.prodmesh_host import HostedProdMeshRTA
from app.store import ConfigStore


class RuntimeService:
    def __init__(self, store: ConfigStore, spl_reports: SPLReportStore | None = None):
        self.store = store
        self.spl_reports = spl_reports or SPLReportStore(store.path.with_name("spl-samples.jsonl"))
        self.state: dict[str, Any] = self.demo_state()
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._last_refresh = {"planning_center": 0.0, "planning_center_detail": 0.0, "planning_center_live": 0.0, "propresenter": 0.0, "shure": 0.0, "sennheiser": 0.0, "prodmesh_host": 0.0, "prodmesh_rta": 0.0, "restream": 0.0, "obs": 0.0, "streams": 0.0}
        self._service_control: dict[str, Any] = {"active": False}
        self._pp_live_candidate = ""
        self._pp_live_candidate_since = 0.0
        self._pp_live_handled = ""
        self._last_live: dict[str, Any] | None = None
        self._rehearsal_clock: dict[str, Any] = {}
        self._propresenter_client: ProPresenterClient | None = None
        self._propresenter_key: tuple[Any, ...] | None = None
        self._planning_center_detail_task: asyncio.Task | None = None
        self._osm_listener = OSMListener(self.record_osm_measurement)
        self._osm_sources: dict[str, dict[str, Any]] = {}
        self._osm_auto_source_key = ""
        self._restream_client: RestreamClient | None = None
        self._restream_key: tuple[Any, ...] | None = None
        self._obs_client: OBSClient | None = None
        self._obs_key: tuple[Any, ...] | None = None
        self._prodmesh_client: ProdMeshRTAClient | None = None
        self._prodmesh_key: tuple[Any, ...] | None = None
        self._last_prodmesh_report_at = 0.0
        self.prodmesh_host = HostedProdMeshRTA()
        self.media_cache = PlanningCenterMediaCache(store.path)
        self.ndi = NDIRuntime()
        self.intercom = HostedIntercomServer(store.path)

    @staticmethod
    def _manual_service_time_id(config: dict[str, Any], service: dict[str, Any] | None) -> str:
        manual = config.get("manual_service_time") or {}
        if not service or str(manual.get("plan_id") or "") != str(service.get("id") or ""):
            return ""
        return str(manual.get("id") or "")

    def _apply_plan_detail(self, state: dict[str, Any], detail: dict[str, Any] | None, config: dict[str, Any]) -> None:
        """Apply a plan and its time-specific roster as one atomic state change."""
        state["service"] = detail
        state["manual_service_time"] = config.get("manual_service_time")
        if not detail:
            state["people"] = []
            state["timing"] = calculate_timing(None)
            return
        manual_id = self._manual_service_time_id(config, detail)
        chosen = selected_service_time(detail, manual_id=manual_id)
        chosen_id = str(chosen.get("id") or "") if chosen else ""
        state["people"] = people_for_service_time(detail.get("people") or [], chosen_id)
        state["timing"] = calculate_timing(detail, service_time_id=manual_id)

    def record_spl_measurement(self, measurement: dict[str, Any], metric_key: str = "a_fast", metric_label: str = "A-weighted Fast") -> None:
        """Persist a normalized bridge reading against the current LIVE item."""
        state = self.state
        timing = state.get("timing") or {}
        self.spl_reports.record(measurement, state.get("service") or {}, timing.get("current_item"), metric_key, metric_label, timing=timing)

    def record_prodmesh_measurement(self, measurement: dict[str, Any], state: dict[str, Any], clock: float) -> None:
        """Store one ProdMesh sample per second against the active service item."""
        if clock - self._last_prodmesh_report_at < 1.0:
            return
        timing = state.get("timing") or {}
        item = timing.get("current_item")
        service = state.get("service") or {}
        if not service.get("id") or not item or not measurement.get("connected"):
            return
        program = str(measurement.get("mode") or "").casefold() == "program"
        metric_key = "lufsS" if program else "fast_db"
        metric_label = "Short-term loudness" if program else f"{str(measurement.get('weighting') or 'A')}-weighted Fast"
        unit = "LUFS" if program else "dB SPL"
        self.spl_reports.record(measurement, service, item, metric_key, metric_label, timing=timing, source="ProdMesh RTA", unit=unit)
        self._last_prodmesh_report_at = clock

    def record_osm_measurement(self, measurement: dict[str, Any]) -> None:
        osm_settings = self.store.load()["settings"].get("open_sound_meter", {})
        reports_enabled = bool(osm_settings.get("reports_enabled", True))
        weighting = str(osm_settings.get("report_weighting") or "A").upper()
        response = str(osm_settings.get("report_response") or "Fast").capitalize()
        if weighting not in {"A", "B", "C", "Z"}:
            weighting = "A"
        if response not in {"Fast", "Slow"}:
            response = "Fast"
        metric_key = f"{weighting.lower()}_{response.lower()}"
        metric_label = f"{weighting}-weighted {response}"
        source_id = str(measurement.get("source_id") or "")
        source_host = str(measurement.get("source_host") or "")
        source_key = f"{source_host}:{source_id}" if source_host else source_id
        if not source_key:
            source_key = "legacy"
        self._osm_sources[source_key] = {**measurement, "source_key": source_key}
        configured_source = str(osm_settings.get("source_id") or "")
        if not self._osm_auto_source_key:
            self._osm_auto_source_key = source_key
        selected_key = configured_source or self._osm_auto_source_key
        selected = self._osm_sources.get(selected_key)
        if selected is None:
            current = self.state.get("osm") or {}
            self.state["osm"] = {**current, "connected": False, "message": "The selected OSM source is not currently sending levels", "sources": self._osm_source_catalog(metric_key), "selected_source_id": selected_key}
            return
        if source_key != selected["source_key"]:
            current = self.state.get("osm") or {}
            self.state["osm"] = {**current, "sources": self._osm_source_catalog(metric_key), "selected_source_id": selected["source_key"]}
            return
        if reports_enabled:
            self.record_spl_measurement(selected, metric_key, metric_label)
        self.state["osm"] = {"connected": True, "reports_enabled": reports_enabled, "report_metric_key": metric_key, "report_metric_label": metric_label, "selected_source_id": selected["source_key"], "sources": self._osm_source_catalog(metric_key), "last_measurement_at": selected.get("timestamp"), **selected}

    def _osm_source_catalog(self, metric_key: str) -> list[dict[str, Any]]:
        return [
            {
                "id": source["source_key"],
                "name": source.get("source_name") or source["source_key"],
                "host": source.get("source_host") or "",
                "level": source.get(metric_key),
                "updated_at": source.get("timestamp"),
            }
            for source in self._osm_sources.values()
        ]
    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._run())

    async def close(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._propresenter_client is not None:
            await self._propresenter_client.close()
            self._propresenter_client = None
        if self._restream_client is not None:
            await self._restream_client.close()
            self._restream_client = None
        if self._obs_client is not None:
            await self._obs_client.close()
            self._obs_client = None
        if self._prodmesh_client is not None:
            await self._prodmesh_client.close()
            self._prodmesh_client = None
        self.prodmesh_host.stop()
        if self._planning_center_detail_task is not None:
            self._planning_center_detail_task.cancel()
            try:
                await self._planning_center_detail_task
            except asyncio.CancelledError:
                pass
            self._planning_center_detail_task = None
        await self._osm_listener.close()
        self.ndi.close()
        self.intercom.stop()

    async def _run(self) -> None:
        while not self._stop.is_set():
            await self.refresh()
            try:
                # The fastest external source (ProPresenter) is cached at a
                # quarter-second cadence. A 100 ms coordinator tick remains
                # responsive without rereading settings 25 times per second.
                await asyncio.wait_for(self._stop.wait(), 0.10)
            except asyncio.TimeoutError:
                pass

    async def refresh(self, force: bool = False) -> dict[str, Any]:
        stored_data = self.store.load()
        config = stored_data["settings"]
        self.ndi.configure(config.get("ndi", {}))
        self.intercom.configure(config.get("intercom", {}))
        host_clock = time.monotonic()
        if force or host_clock - self._last_refresh["prodmesh_host"] >= 1.0:
            self._last_refresh["prodmesh_host"] = host_clock
            await asyncio.to_thread(self.prodmesh_host.configure, config.get("prodmesh_rta", {}))
        osm_settings = config.get("open_sound_meter", {})
        if osm_settings.get("enabled"):
            try:
                await self._osm_listener.configure(osm_settings)
                self.state.setdefault("osm", {"connected": False, "message": "Waiting for OSM multicast data"})
                osm_state = self.state.get("osm") or {}
                last_measurement = str(osm_state.get("last_measurement_at") or "")
                if osm_state.get("connected") and last_measurement:
                    try:
                        age = (datetime.now(timezone.utc) - datetime.fromisoformat(last_measurement.replace("Z", "+00:00"))).total_seconds()
                    except ValueError:
                        age = 0
                    if age > 3:
                        self.state["osm"] = {**osm_state, "connected": False, "message": "The selected OSM source stopped sending levels"}
            except OSError as exc:
                self.state["osm"] = {"connected": False, "message": f"Could not join OSM multicast: {exc}"}
        else:
            await self._osm_listener.close()
        configured_media_titles = self._configured_media_titles(stored_data)
        configured_resource_tags = self._configured_resource_tags(stored_data)
        configured_stream_sources = self._configured_stream_sources(stored_data)
        if config.get("demo_mode"):
            demo = deepcopy(self.state) if self.state.get("service", {}).get("id") == "demo" else self.demo_state()
            demo["organization_name"] = config.get("organization_name", "My Church")
            demo["timezone"] = config.get("timezone", "")
            demo["updated_at"] = datetime.now(timezone.utc).isoformat()
            demo["timing"] = calculate_timing(demo.get("service"))
            demo["manual_plan"] = config.get("manual_plan")
            demo["manual_service_time"] = config.get("manual_service_time")
            demo["planning_center_live"] = {"enabled": bool((config.get("planning_center", {}).get("live_from_propresenter") or {}).get("enabled")), "state": "demo", "message": "Services LIVE automation is available when demonstration data is off"}
            demo["restream"] = {"connected": False, "status": "offline", "title": "Restream monitoring is unavailable in demo mode", "destinations": []}
            demo["livestreams"] = [{**self._public_stream_source(source), "label": source.get("label") or str(source.get("provider") or "Stream").title(), "live": False, "status": "demo", "checked": False} for source in configured_stream_sources]
            self._apply_service_control(demo)
            self.state = demo
            return self.state
        next_state = deepcopy(self.state)
        next_state.update({"organization_name": config.get("organization_name", "ChurchBoard"), "timezone": config.get("timezone", ""), "updated_at": datetime.now(timezone.utc).isoformat(), "manual_plan": config.get("manual_plan"), "manual_service_time": config.get("manual_service_time")})
        live_config = config.get("planning_center", {}).get("live_from_propresenter") or {}
        if not live_config.get("enabled") or not self._apply_cached_live_timing(next_state):
            self._apply_plan_detail(next_state, next_state.get("service"), config)
        clock = time.monotonic()
        prodmesh_settings = config.get("prodmesh_rta", {})
        prodmesh_mode = str(prodmesh_settings.get("mode") or "embedded")
        prodmesh_host = "127.0.0.1" if prodmesh_mode == "embedded" else str(prodmesh_settings.get("host") or "")
        effective_prodmesh_settings = {**prodmesh_settings, "host": prodmesh_host}
        prodmesh_key = (bool(prodmesh_settings.get("enabled")), prodmesh_mode, prodmesh_host, int(prodmesh_settings.get("port") or 8517))
        if self._prodmesh_client is None or prodmesh_key != self._prodmesh_key:
            if self._prodmesh_client is not None: await self._prodmesh_client.close()
            self._prodmesh_client, self._prodmesh_key = ProdMeshRTAClient(effective_prodmesh_settings), prodmesh_key
        prodmesh_due = clock - self._last_refresh["prodmesh_rta"] >= max(.08, float(prodmesh_settings.get("refresh_seconds") or .1))
        if self._prodmesh_client.configured and (force or prodmesh_due):
            self._last_refresh["prodmesh_rta"] = clock
            try:
                next_state["prodmesh_rta"] = {**await self._prodmesh_client.levels(), "host": self.prodmesh_host.status(prodmesh_settings)}
                if prodmesh_settings.get("reports_enabled", True):
                    self.record_prodmesh_measurement(next_state["prodmesh_rta"], next_state, clock)
            except Exception as exc: next_state["prodmesh_rta"] = {"connected": False, "error": str(exc), "host": self.prodmesh_host.status(prodmesh_settings)}
        elif not self._prodmesh_client.configured:
            next_state["prodmesh_rta"] = {"connected": False, "error": "ProdMesh RTA is not enabled"}
        propresenter_settings = config.get("propresenter", {})
        propresenter_key = (
            bool(propresenter_settings.get("enabled")),
            str(propresenter_settings.get("host") or ""),
            int(propresenter_settings.get("port") or 50001),
        )
        if self._propresenter_client is None or propresenter_key != self._propresenter_key:
            if self._propresenter_client is not None:
                await self._propresenter_client.close()
            self._propresenter_client = ProPresenterClient(propresenter_settings)
            self._propresenter_key = propresenter_key
        propresenter = self._propresenter_client
        configured_pp_interval = float(propresenter_settings.get("refresh_seconds", 0.075))
        pp_interval = max(0.04, min(configured_pp_interval, 0.075))
        pp_due = clock - self._last_refresh["propresenter"] >= pp_interval
        if propresenter.configured and (force or pp_due):
            self._last_refresh["propresenter"] = clock
            try:
                previous_presentation = next_state.get("propresenter") or {}
                fresh_presentation = await propresenter.status()
                same_presentation = (
                    fresh_presentation.get("presentation_uuid")
                    and fresh_presentation.get("presentation_uuid") == previous_presentation.get("presentation_uuid")
                ) or (
                    not fresh_presentation.get("presentation_uuid")
                    and fresh_presentation.get("title") == previous_presentation.get("title")
                )
                if same_presentation:
                    for key in ("planning_center_item_id", "planning_center_item_title"):
                        if previous_presentation.get(key) and not fresh_presentation.get(key):
                            fresh_presentation[key] = previous_presentation[key]
                service = next_state.get("service") or {}
                if live_config.get("enabled") and fresh_presentation.get("connected") and service.get("items"):
                    current_id = str(((next_state.get("timing") or {}).get("current_item") or {}).get("id") or "")
                    preliminary_match = self._match_presentation_item(
                        str(fresh_presentation.get("title") or ""),
                        service.get("items") or [],
                        current_id,
                        live_config,
                        service_item_title=str(fresh_presentation.get("service_item_title") or ""),
                        service_item_index=fresh_presentation.get("service_item_index"),
                        service_item_index_is_absolute=bool(fresh_presentation.get("service_item_index_is_absolute")),
                        is_pco_item=bool(fresh_presentation.get("service_item_is_pco")),
                    )
                    if preliminary_match:
                        fresh_presentation["planning_center_item_id"] = preliminary_match.get("id")
                        fresh_presentation["planning_center_item_title"] = preliminary_match.get("title")
                        self._apply_provisional_rehearsal_target(next_state, preliminary_match, fresh_presentation)
                next_state["propresenter"] = fresh_presentation
            except Exception as exc:
                next_state["propresenter"] = {"connected": False, "error": str(exc), "current": {}, "next": {}}
        # Publish slide changes before slower cloud integrations finish so a
        # Planning Center refresh cannot hold up the local ProPresenter view.
        self.state = deepcopy(next_state)
        pc = PlanningCenterClient(config.get("planning_center", {}))
        if self._planning_center_detail_task is not None and self._planning_center_detail_task.done():
            try:
                detail = self._planning_center_detail_task.result()
                if str(detail.get("id") or "") == str((next_state.get("service") or {}).get("id") or ""):
                    self._apply_plan_detail(next_state, detail, config)
                    next_state["planning_center"] = {"connected": True, "error": ""}
            except Exception as exc:
                next_state["planning_center"] = {"connected": False, "error": str(exc)}
            finally:
                self._planning_center_detail_task = None
        planning_center_settings = config.get("planning_center", {})
        pc_due = clock - self._last_refresh["planning_center"] >= float(planning_center_settings.get("refresh_seconds", 60))
        detail_due = clock - self._last_refresh["planning_center_detail"] >= max(
            2.0,
            float(planning_center_settings.get("detail_refresh_seconds", 5)),
        )
        if pc.configured and (force or pc_due):
            if self._planning_center_detail_task is not None:
                self._planning_center_detail_task.cancel()
                self._planning_center_detail_task = None
            self._last_refresh["planning_center"] = clock
            self._last_refresh["planning_center_detail"] = clock
            try:
                candidates = await pc.candidate_plans()
                active = pc.select_plan(candidates, config.get("manual_plan"))
                detail = await pc.plan_detail(active) if active else None
                next_state.update({"plans": candidates, "planning_center": {"connected": True, "error": ""}})
                self._apply_plan_detail(next_state, detail, config)
                media_by_title = {}
                media_errors = []
                for media_title in configured_media_titles:
                    try:
                        media = await pc.media_by_title(media_title)
                        if media and media.get("image_url"):
                            media_by_title[media_title.casefold()] = media
                    except Exception as media_exc:
                        media_errors.append(f"{media_title}: {media_exc}")
                next_state["planning_center_media"] = {
                    "by_title": media_by_title,
                    "icon": media_by_title.get("icon"),
                    "error": "; ".join(media_errors),
                }
                tagged_resources = {}
                tag_sync_complete = True
                for tag_id in configured_resource_tags:
                    try:
                        tagged_resources[tag_id] = await pc.media_for_tag(tag_id)
                    except Exception as media_exc:
                        media_errors.append(f"tag {tag_id}: {media_exc}")
                        tag_sync_complete = False
                if tag_sync_complete:
                    try:
                        tagged_resources = await self.media_cache.sync(pc, tagged_resources)
                    except Exception as media_exc:
                        media_errors.append(f"local resource cache: {media_exc}")
                next_state["planning_center_resources"] = tagged_resources
            except Exception as exc:
                next_state["planning_center"] = {"connected": False, "error": str(exc)}
        elif pc.configured and detail_due and (next_state.get("service") or {}).get("id"):
            # The plan catalog is relatively expensive to scan, but an active
            # plan is commonly edited during rehearsal. Refresh just that
            # plan's people and items frequently so additions appear quickly
            # without re-fetching every candidate plan and service time.
            if self._planning_center_detail_task is None:
                self._last_refresh["planning_center_detail"] = clock
                self._planning_center_detail_task = asyncio.create_task(
                    pc.plan_detail(deepcopy(next_state["service"]))
                )
        if live_config.get("enabled"):
            self._apply_cached_live_timing(next_state)
        if live_config.get("enabled"):
            await self._sync_propresenter_live(next_state, pc, live_config, clock, force)
        else:
            next_state["planning_center_live"] = {"enabled": False, "state": "disabled", "message": "ProPresenter is not controlling Services LIVE"}
            self._pp_live_candidate = ""
            self._pp_live_handled = ""
            self._last_live = None
            self._rehearsal_clock = {}
        shure = ShureClient(config.get("shure", {}))
        sennheiser = SennheiserClient(config.get("sennheiser", {}))
        shure_due = clock - self._last_refresh["shure"] >= float(config.get("shure", {}).get("refresh_seconds", 0.5))
        sennheiser_due = clock - self._last_refresh["sennheiser"] >= float(config.get("sennheiser", {}).get("refresh_seconds", 0.5))
        if (shure.configured and (force or shure_due)) or (sennheiser.configured and (force or sennheiser_due)):
            shure_status, sennheiser_status = await asyncio.gather(
                shure.status() if shure.configured else asyncio.sleep(0, result=[]),
                sennheiser.status() if sennheiser.configured else asyncio.sleep(0, result=[]),
            )
            next_state["mics"] = shure_status + sennheiser_status
            self._last_refresh["shure"] = clock
            self._last_refresh["sennheiser"] = clock
        elif not shure.configured and not sennheiser.configured:
            # Runtime starts with demonstration content so the first launch is
            # useful. Once demo mode is off, never carry those sample mics into
            # a real Planning Center plan that has no wireless configuration.
            next_state["mics"] = []
        restream_settings = config.get("restream", {})
        expires_at = float(restream_settings.get("access_token_expires_at") or 0)
        if restream_settings.get("refresh_token") and expires_at and expires_at <= datetime.now(timezone.utc).timestamp() + 120:
            refresh_client = RestreamClient(restream_settings)
            try:
                token = await refresh_client.refresh_access_token()
                restream_settings.update({"access_token": token.get("access_token") or token.get("accessToken") or "", "refresh_token": token.get("refresh_token") or token.get("refreshToken") or "", "access_token_expires_at": token.get("expires") or token.get("accessTokenExpiresEpoch") or 0})
                stored_data["settings"]["restream"] = restream_settings
                self.store.save(stored_data)
            except Exception as exc:
                next_state["restream"] = {"connected": False, "status": "offline", "title": "Restream authorization expired", "destinations": [], "error": str(exc)}
            finally:
                await refresh_client.close()
        restream_key = (bool(restream_settings.get("enabled")), str(restream_settings.get("access_token") or ""))
        if self._restream_client is None or restream_key != self._restream_key:
            if self._restream_client is not None:
                await self._restream_client.close()
            self._restream_client = RestreamClient(restream_settings)
            self._restream_key = restream_key
        restream_due = clock - self._last_refresh["restream"] >= max(2.0, float(restream_settings.get("refresh_seconds", 5)))
        if self._restream_client.configured and (force or restream_due):
            self._last_refresh["restream"] = clock
            try:
                next_state["restream"] = await self._restream_client.status()
            except Exception as exc:
                next_state["restream"] = {"connected": False, "status": "offline", "title": "Restream unavailable", "destinations": [], "error": str(exc)}
        elif not self._restream_client.configured:
            next_state["restream"] = {"connected": False, "status": "offline", "title": "Restream is not connected", "destinations": []}
        obs_settings = config.get("obs", {})
        obs_key = (bool(obs_settings.get("enabled")), str(obs_settings.get("host") or ""), int(obs_settings.get("port") or 4455), str(obs_settings.get("password") or ""))
        if self._obs_client is None or obs_key != self._obs_key:
            if self._obs_client is not None: await self._obs_client.close()
            self._obs_client, self._obs_key = OBSClient(obs_settings), obs_key
        obs_due = clock - self._last_refresh["obs"] >= max(.25, float(obs_settings.get("refresh_seconds", .5)))
        if self._obs_client.configured and (force or obs_due):
            self._last_refresh["obs"] = clock
            try: next_state["obs"] = await self._obs_client.status()
            except Exception as exc:
                await self._obs_client.close()
                next_state["obs"] = {"connected": False, "streaming": False, "recording": False, "alert": "OBS unavailable", "error": str(exc), "sources": []}
        elif not self._obs_client.configured:
            next_state["obs"] = {"connected": False, "streaming": False, "recording": False, "alert": "", "sources": []}
        stream_sources = configured_stream_sources
        streams_due = clock - self._last_refresh["streams"] >= 15.0
        if stream_sources and (force or streams_due):
            self._last_refresh["streams"] = clock
            next_state["livestreams"] = await self._livestream_statuses(stream_sources, next_state.get("restream") or {}, next_state.get("livestreams") or [])
        elif not stream_sources:
            next_state["livestreams"] = []
        self._apply_assignments(next_state, config.get("position_mic_map", {}))
        self._apply_service_control(next_state)
        self.state = next_state
        return self.state

    async def _sync_propresenter_live(self, state: dict[str, Any], pc: PlanningCenterClient, settings: dict[str, Any], clock: float, force: bool = False) -> None:
        service, presentation = state.get("service") or {}, state.get("propresenter") or {}
        base_status = {"enabled": True, "state": "waiting", "message": "Waiting for an active Planning Center service and ProPresenter presentation"}
        if not pc.configured:
            state["planning_center_live"] = {**base_status, "state": "error", "message": "Planning Center is not connected"}
            return
        if not service.get("id") or not service.get("items"):
            state["planning_center_live"] = base_status
            return

        configured_live_interval = float(settings.get("refresh_seconds", 0.5))
        live_interval = max(0.25, min(configured_live_interval, 0.5))
        poll_due = clock - self._last_refresh["planning_center_live"] >= live_interval
        live = None
        if force or poll_due:
            self._last_refresh["planning_center_live"] = clock
            try:
                live = await pc.live_status(service)
                if live:
                    self._remember_live(service, live)
                    self._apply_live_timing(state, live)
                    state["planning_center_live"] = self._live_status_payload(live, state.get("planning_center_live"))
                else:
                    self._last_live = None
            except Exception as exc:
                state["planning_center_live"] = {**base_status, "state": "error", "message": f"Services LIVE status failed: {exc}"}
        elif str((self._last_live or {}).get("_service_id") or "") == str(service.get("id") or ""):
            live = self._last_live

        title = str(presentation.get("title") or "").strip()
        service_item_title = str(presentation.get("service_item_title") or "").strip()
        service_item_index = presentation.get("service_item_index")
        service_item_index_is_absolute = bool(presentation.get("service_item_index_is_absolute"))
        is_pco_item = bool(presentation.get("service_item_is_pco"))
        match_title = service_item_title if is_pco_item and service_item_title else title
        if not presentation.get("connected") or not match_title:
            state["planning_center_live"] = {**base_status, "message": "Waiting for an active ProPresenter presentation"}
            return
        current_item_id = str((live or {}).get("current_item_id") or ((state.get("timing") or {}).get("current_item") or {}).get("id") or "")
        target = self._match_presentation_item(title, service.get("items") or [], current_item_id, settings, service_item_title=service_item_title, service_item_index=service_item_index, service_item_index_is_absolute=service_item_index_is_absolute, is_pco_item=is_pco_item)
        if target:
            presentation["planning_center_item_id"] = target.get("id")
            presentation["planning_center_item_title"] = target.get("title")
        signature = "|".join((str(service.get("id")), str(presentation.get("presentation_uuid") or ""), str(service_item_index if service_item_index is not None else ""), self._normalize_title(match_title)))
        if signature != self._pp_live_candidate:
            self._pp_live_candidate = signature
            self._pp_live_candidate_since = clock
            state["planning_center_live"] = {**base_status, "state": "stabilizing", "presentation_title": title, "service_item_title": service_item_title, "message": f"Waiting for “{match_title}” to remain active"}
            return
        stable_seconds = max(0.0, float(settings.get("stable_seconds", 2)))
        if clock - self._pp_live_candidate_since < stable_seconds:
            state["planning_center_live"] = {**base_status, "state": "stabilizing", "presentation_title": title, "service_item_title": service_item_title, "message": f"Waiting for “{match_title}” to remain active"}
            return
        already_handled = signature == self._pp_live_handled
        if already_handled and str((live or {}).get("current_item_id") or "") == str((target or {}).get("id") or ""):
            state["planning_center_live"] = {**self._live_status_payload(live), "state": "synced", "presentation_title": title, "service_item_title": service_item_title, "target_item_id": target.get("id"), "target_item_title": target.get("title"), "message": f"Following {target.get('title')} from ProPresenter"}
            return
        if not target:
            self._pp_live_handled = signature
            state["planning_center_live"] = {**base_status, "state": "no_match", "presentation_title": title, "service_item_title": service_item_title, "message": f"No Planning Center item matched “{match_title}”"}
            return
        try:
            live = live or await pc.live_status(service, create=bool(settings.get("auto_take_control", True)))
            if not live:
                state["planning_center_live"] = {**base_status, "state": "needs_live", "presentation_title": title, "target_item_id": target.get("id"), "target_item_title": target.get("title"), "message": "Open Services LIVE for this plan, then change to the presentation again"}
                return
            if not live.get("has_control"):
                can_claim_control = bool(live.get("can_control") or live.get("can_take_control"))
                if settings.get("auto_take_control", True) and can_claim_control:
                    live = await pc.live_action(service, live, "toggle_control") or live
                else:
                    reason = "This Planning Center token cannot take control" if not can_claim_control else "Take control in Services LIVE first"
                    state["planning_center_live"] = {**base_status, "state": "needs_control", "presentation_title": title, "target_item_id": target.get("id"), "target_item_title": target.get("title"), "message": reason}
                    self._pp_live_candidate_since = clock
                    return
            if not live.get("has_control"):
                raise ValueError("ChurchBoard requested control, but Planning Center did not assign it")
            items = service.get("items") or []
            current_index = next((index for index, item in enumerate(items) if str(item.get("id")) == str(live.get("current_item_id"))), -1)
            target_index = next((index for index, item in enumerate(items) if str(item.get("id")) == str(target.get("id"))), -1)
            if target_index < 0:
                raise ValueError("The matching item is not in the active Planning Center plan")
            if current_index < 0:
                next_index = next((index for index, item in enumerate(items) if str(item.get("id")) == str(live.get("next_item_id"))), -1)
                # A newly opened Services LIVE session can be positioned
                # before the first plan item, with neither current nor next
                # populated. Advance from that pre-start position.
                difference = target_index + 1 if next_index < 0 else target_index - next_index + 1
            else:
                difference = target_index - current_index
            linked_pco_item = bool(is_pco_item and service_item_title)
            if difference < 0 and not settings.get("allow_previous", False) and not linked_pco_item:
                self._pp_live_handled = signature
                state["planning_center_live"] = {**self._live_status_payload(live), "state": "behind", "presentation_title": title, "target_item_id": target.get("id"), "target_item_title": target.get("title"), "message": f"“{title}” is behind the current LIVE item; backward movement is disabled"}
                return
            if abs(difference) > 20:
                raise ValueError("The matching item is more than 20 service items away")
            action = "go_to_next_item" if difference > 0 else "go_to_previous_item"
            for _ in range(abs(difference)):
                live = await pc.live_action(service, live, action) or live
            self._service_control = {"active": False}
            self._remember_live(service, live)
            self._apply_live_timing(state, live)
            self._pp_live_handled = signature
            source = "Planning Center playlist" if is_pco_item and service_item_title else "presentation title"
            state["planning_center_live"] = {**self._live_status_payload(live), "state": "synced", "presentation_title": title, "service_item_title": service_item_title, "match_source": source, "target_item_id": target.get("id"), "target_item_title": target.get("title"), "message": f"Matched {target.get('title')} from the {source}"}
        except Exception as exc:
            # Let the same presentation retry after the stability delay. This
            # is important when an operator grants LIVE control after an error.
            self._pp_live_handled = ""
            self._pp_live_candidate_since = clock
            state["planning_center_live"] = {**base_status, "state": "error", "presentation_title": title, "target_item_id": target.get("id"), "target_item_title": target.get("title"), "message": f"Services LIVE control failed: {exc}"}

    @staticmethod
    def _normalize_title(value: str) -> str:
        value = str(value).casefold().replace("&", " and ").replace("'", "").replace("’", "")
        value = unicodedata.normalize("NFKD", value)
        value = "".join(character if character.isalnum() else " " for character in value)
        value = value.encode("ascii", "ignore").decode("ascii")
        return " ".join(value.split())

    @classmethod
    def _title_variants(cls, value: str) -> set[str]:
        raw = str(value or "").strip()
        variants = {cls._normalize_title(raw)}
        for pattern in (r"\s+-\s+.*$", r"\s+\|\s+.*$", r"\s*\[[^]]+\]\s*$", r"\s*\([^)]*(?:pco|planning\s+center|acoustic|live|version)[^)]*\)\s*$"):
            shortened = re.sub(pattern, "", raw, flags=re.IGNORECASE).strip()
            if shortened:
                variants.add(cls._normalize_title(shortened))
        return {variant for variant in variants if variant}

    @classmethod
    def _title_score(cls, left: str, right: str) -> float:
        scores = []
        for first in cls._title_variants(left):
            for second in cls._title_variants(right):
                if first == second:
                    return 1.0
                if min(len(first), len(second)) >= 5 and (first in second or second in first):
                    scores.append(0.92)
                first_tokens, second_tokens = set(first.split()), set(second.split())
                overlap = len(first_tokens & second_tokens)
                token_score = (2 * overlap / (len(first_tokens) + len(second_tokens))) if first_tokens and second_tokens else 0
                scores.append(max(SequenceMatcher(None, first, second).ratio(), token_score))
        return max(scores, default=0.0)

    @classmethod
    def _pco_playlist_items(cls, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return the plan rows that occupy indexes in a PCO ProPresenter playlist.

        ProPresenter omits Planning Center headers and the pre-service rows that
        precede the main service section. Planning Center's API still returns
        both, so indexing directly into ``plan.items`` can point several rows
        early (for example Message resolving to Center).

        Items excluded from a particular service time intentionally remain in
        this list because ProPresenter's synced playlist can still contain
        them; service-time exclusions are applied later when rendering timing.
        """
        first_song_index = next(
            (
                index
                for index, item in enumerate(items)
                if str(item.get("item_type") or "").casefold() == "song"
            ),
            None,
        )
        start_index = 0
        if first_song_index is not None:
            leading_headers = [
                index
                for index, item in enumerate(items[:first_song_index])
                if str(item.get("item_type") or "").casefold() == "header"
            ]
            if leading_headers:
                start_index = leading_headers[-1] + 1
        else:
            service_headers = [
                index
                for index, item in enumerate(items)
                if str(item.get("item_type") or "").casefold() == "header"
                and cls._normalize_title(item.get("title") or "") in {"service", "main service", "worship service"}
            ]
            if service_headers:
                start_index = service_headers[-1] + 1
        return [
            item
            for item in items[start_index:]
            if str(item.get("item_type") or "").casefold() != "header"
        ]

    @classmethod
    def _pco_pre_service_indexed_item(cls, items: list[dict[str, Any]], service_item_index: int | None) -> dict[str, Any] | None:
        """Resolve indexes exposed while ProPresenter is in a pre-service section.

        ProPresenter reports the top-level Planning Center row index before the
        main Service header, but reports an index relative to the main section
        once that section is active. Keeping the pre-service rows available is
        what lets a locally named presentation such as Announcements resolve
        back to Planning Center's Pre-Service Slides item.
        """
        if not isinstance(service_item_index, int) or not 0 <= service_item_index < len(items):
            return None
        first_main_item = next((item for item in cls._pco_playlist_items(items)), None)
        main_start = items.index(first_main_item) if first_main_item in items else 0
        candidate = items[service_item_index]
        if service_item_index >= main_start or str(candidate.get("item_type") or "").casefold() == "header":
            return None
        return candidate

    @classmethod
    def _match_presentation_item(cls, title: str, items: list[dict[str, Any]], current_item_id: str, settings: dict[str, Any], *, service_item_title: str = "", service_item_index: int | None = None, service_item_index_is_absolute: bool = False, is_pco_item: bool = False) -> dict[str, Any] | None:
        candidates = list(items)
        if is_pco_item and service_item_index_is_absolute and isinstance(service_item_index, int) and 0 <= service_item_index < len(items):
            linked_item = items[service_item_index]
            if str(linked_item.get("item_type") or "").casefold() != "header":
                return linked_item
        song_candidates = [item for item in candidates if str(item.get("item_type") or "").casefold() == "song"]
        preferred = candidates if is_pco_item or not settings.get("songs_only", True) else song_candidates
        source_title = service_item_title if is_pco_item and service_item_title else title
        matches = [item for item in preferred if cls._title_score(source_title, item.get("title") or "") == 1]
        playlist_items = cls._pco_playlist_items(items) if is_pco_item else []
        indexed_item = playlist_items[service_item_index] if isinstance(service_item_index, int) and 0 <= service_item_index < len(playlist_items) else None
        pre_service_item = cls._pco_pre_service_indexed_item(items, service_item_index) if is_pco_item else None
        if matches:
            # The ProPresenter playlist omits some Planning Center rows (for
            # example headers and countdowns), so its index is not necessarily
            # an index into the complete plan. An exact linked item title is
            # the stronger signal.
            current_index = next((index for index, item in enumerate(items) if str(item.get("id")) == str(current_item_id)), 0)
            indexed_matches = [(index, item) for index, item in enumerate(items) if item in matches]
            return min(indexed_matches, key=lambda pair: (pair[0] < current_index, abs(pair[0] - current_index)))[1]
        if pre_service_item:
            return pre_service_item
        if indexed_item:
            # ProPresenter's is_pco flag means this playlist was created from
            # the Planning Center plan. Its playlist index remains linked to
            # that plan item even when the local presentation has a completely
            # different filename (for example John 1_1-3 → Message).
            return indexed_item
        if not matches and preferred is not candidates:
            # A precise Planning Center item title is safe even when song
            # matching is preferred; this allows Message, Welcome, etc.
            matches = [item for item in candidates if cls._title_score(source_title, item.get("title") or "") == 1]
        if not matches:
            threshold = 0.74 if bool(is_pco_item and service_item_title) or settings.get("match_mode") == "flexible" else 0.9
            scored = [(cls._title_score(source_title, item.get("title") or ""), item) for item in candidates]
            best = max((score for score, _item in scored), default=0.0)
            if best >= threshold:
                matches = [item for score, item in scored if score >= best - 0.02]
        if not matches:
            return None
        current_index = next((index for index, item in enumerate(items) if str(item.get("id")) == str(current_item_id)), 0)
        indexed_matches = [(index, item) for index, item in enumerate(items) if item in matches]
        return min(indexed_matches, key=lambda pair: (pair[0] < current_index, abs(pair[0] - current_index)))[1]

    @staticmethod
    def _live_status_payload(live: dict[str, Any], previous: dict[str, Any] | None = None) -> dict[str, Any]:
        return {**(previous or {}), "enabled": True, "state": "live", "live_id": live.get("id"), "can_control": bool(live.get("can_control")), "can_take_control": bool(live.get("can_take_control")), "has_control": bool(live.get("has_control")), "controller": live.get("controller") or "", "current_item_id": live.get("current_item_id"), "message": "Connected to Planning Center Services LIVE"}

    def _remember_live(self, service: dict[str, Any], live: dict[str, Any]) -> None:
        self._last_live = {**live, "_service_id": str(service.get("id") or "")}

    def _apply_cached_live_timing(self, state: dict[str, Any]) -> bool:
        service = state.get("service") or {}
        live = self._last_live or {}
        if not service.get("id") or str(live.get("_service_id") or "") != str(service.get("id")):
            return False
        self._apply_live_timing(state, live)
        return (state.get("timing") or {}).get("source") == "planning_center_live"

    @staticmethod
    def _outside_scheduled_service_window(state: dict[str, Any]) -> bool:
        service, timing = state.get("service") or {}, state.get("timing") or {}
        start = parse_time(timing.get("service_start_at") or service.get("starts_at"))
        if not start:
            return False
        service_time_id = str(timing.get("service_time_id") or "")
        chosen_time = next(
            (row for row in service.get("times") or [] if str(row.get("id") or "") == service_time_id),
            None,
        )
        end = parse_time((chosen_time or {}).get("ends_at"))
        if end is None:
            end = start + timedelta(seconds=max(1, int(service.get("planned_length") or 0)))
        now = datetime.now(timezone.utc)
        return now < start - timedelta(minutes=30) or now > end + timedelta(minutes=30)

    def _apply_provisional_rehearsal_target(
        self,
        state: dict[str, Any],
        target: dict[str, Any],
        presentation: dict[str, Any],
    ) -> None:
        timing = state.get("timing") or {}
        current_id = str((timing.get("current_item") or {}).get("id") or "")
        target_id = str(target.get("id") or "")
        if not target_id or not self._outside_scheduled_service_window(state):
            return
        if current_id == target_id and timing.get("rehearsal"):
            return
        started_at = datetime.now(timezone.utc).isoformat()
        provisional_live = {
            "current_item_id": target_id,
            "current_item_time_id": f"propresenter:{presentation.get('presentation_uuid') or target_id}",
            "current_live_start_at": started_at,
        }
        self._apply_live_timing(state, provisional_live)
        if (state.get("timing") or {}).get("rehearsal"):
            state["timing"]["source"] = "propresenter_rehearsal"

    def _apply_live_timing(self, state: dict[str, Any], live: dict[str, Any]) -> None:
        service, current_id = state.get("service") or {}, str(live.get("current_item_id") or "")
        if not service or not current_id:
            self._rehearsal_clock = {}
            return
        current_start = live.get("current_live_start_at")
        for item in service.get("items") or []:
            if str(item.get("id")) == current_id:
                if current_start:
                    item["live_start_at"] = current_start
                item["live_end_at"] = live.get("current_live_end_at")
            elif item.get("live_start_at") and not item.get("live_end_at") and current_start:
                item["live_end_at"] = current_start
        timing = calculate_timing(service, service_time_id=str((state.get("timing") or {}).get("service_time_id") or ""))
        visible_items = timing.get("service_items") or service.get("items") or []
        current_index = next((index for index, item in enumerate(visible_items) if str(item.get("id")) == current_id), -1)
        if current_index >= 0:
            timing["current_item"] = visible_items[current_index]
            timing["next_item"] = visible_items[current_index + 1] if current_index + 1 < len(visible_items) else None
            self._apply_rehearsal_timing(timing, service, visible_items, current_index, live)
        elif not timing.get("rehearsal"):
            self._rehearsal_clock = {}
        state["timing"] = {**timing, "state": "live", "source": "planning_center_live"}

    def _apply_rehearsal_timing(
        self,
        timing: dict[str, Any],
        service: dict[str, Any],
        items: list[dict[str, Any]],
        current_index: int,
        live: dict[str, Any],
    ) -> None:
        if not timing.get("rehearsal"):
            self._rehearsal_clock = {}
            return
        current = items[current_index]
        current_id = str(current.get("id") or "")
        service_id = str(service.get("id") or "")
        clock = time.monotonic()
        live_token = "|".join(
            (
                str(live.get("current_item_time_id") or ""),
                str(live.get("current_live_start_at") or ""),
            )
        )
        tracker = self._rehearsal_clock
        same_session = tracker.get("service_id") == service_id
        same_item = same_session and tracker.get("current_item_id") == current_id
        same_live_token = same_item and tracker.get("live_token") == live_token

        # The provisional ProPresenter clock is intentionally visible before
        # Services LIVE finishes its cloud round trips. When LIVE catches up
        # to the same item, keep that already-running local clock instead of
        # resetting it from an older Planning Center rehearsal timestamp.
        if same_item and not same_live_token:
            tracker["live_token"] = live_token
            same_live_token = True

        if not same_live_token:
            seed_elapsed = 0
            live_start = parse_time(live.get("current_live_start_at"))
            # Planning Center can retain a LIVE timestamp from an earlier
            # rehearsal. Only seed from it when it is recent enough to be the
            # current run; otherwise begin a fresh local rehearsal timer.
            if live_start:
                age = int((datetime.now(timezone.utc) - live_start).total_seconds())
                recent_limit = max(900, int(current.get("length") or 0) * 2)
                if 0 <= age <= recent_limit:
                    seed_elapsed = age
            previous_index = int(tracker.get("current_index", -1)) if same_session else -1
            normal_forward = same_session and not same_item and current_index == previous_index + 1
            service_origin = float(tracker.get("service_origin", clock)) if normal_forward else clock - int(current.get("starts_after") or 0) - seed_elapsed
            tracker = {
                "service_id": service_id,
                "current_item_id": current_id,
                "current_index": current_index,
                "live_token": live_token,
                "item_started": clock - seed_elapsed,
                "service_origin": service_origin,
            }
            self._rehearsal_clock = tracker

        item_elapsed = max(0, int(clock - float(tracker.get("item_started", clock))))
        service_elapsed = max(0, int(clock - float(tracker.get("service_origin", clock))))
        planned_progress = int(current.get("starts_after") or 0) + min(item_elapsed, int(current.get("length") or 0))
        timing.update({
            "item_elapsed": item_elapsed,
            "item_delta": item_elapsed - int(current.get("length") or 0),
            "service_elapsed": service_elapsed,
            "overall_delta": service_elapsed - planned_progress,
        })

    async def service_control(self, action: str) -> dict[str, Any]:
        config = self.store.load()["settings"]
        live_settings = config.get("planning_center", {}).get("live_from_propresenter") or {}
        service = self.state.get("service") or {}
        if live_settings.get("enabled") and not config.get("demo_mode") and service.get("id"):
            pc = PlanningCenterClient(config.get("planning_center", {}))
            try:
                live = await pc.live_status(service, create=action == "take")
                if not live:
                    raise ValueError("Open Services LIVE for the active plan first")
                if action == "take":
                    if not live.get("has_control"):
                        if not (live.get("can_control") or live.get("can_take_control")):
                            raise ValueError("This Planning Center token cannot take control of Services LIVE")
                        live = await pc.live_action(service, live, "toggle_control") or live
                elif action == "release":
                    if live.get("has_control"):
                        live = await pc.live_action(service, live, "toggle_control") or live
                elif action in {"next", "previous"}:
                    if not live.get("has_control"):
                        can_claim_control = bool(live.get("can_control") or live.get("can_take_control"))
                        if not live_settings.get("auto_take_control", True) or not can_claim_control:
                            raise ValueError("Take control of Services LIVE first")
                        live = await pc.live_action(service, live, "toggle_control") or live
                    if not live.get("has_control"):
                        raise ValueError("ChurchBoard requested control, but Planning Center did not assign it")
                    live = await pc.live_action(service, live, "go_to_next_item" if action == "next" else "go_to_previous_item") or live
                else:
                    raise ValueError("Unknown service control action")
                self._service_control = {"active": False}
                self._remember_live(service, live)
                self._apply_live_timing(self.state, live)
                self._pp_live_handled = ""
                self.state["planning_center_live"] = {**self._live_status_payload(live), "state": "live", "message": "Services LIVE was updated manually"}
                return self.state
            except ValueError:
                raise
            except Exception as exc:
                raise ValueError(f"Planning Center Services LIVE control failed: {exc}") from exc

        return self._local_service_control(action)

    def _local_service_control(self, action: str) -> dict[str, Any]:
        service = self.state.get("service") or {}
        timing = self.state.get("timing") or {}
        items = timing.get("service_items") or service_items(service, timing.get("service_time_id"))
        if not items:
            raise ValueError("The active service has no items")
        current_item = (self.state.get("timing") or {}).get("current_item") or {}
        current_id = current_item.get("id")
        current_index = next((index for index, item in enumerate(items) if item.get("id") == current_id), 0)
        if action == "release":
            self._service_control = {"active": False}
        else:
            if not self._service_control.get("active") or self._service_control.get("service_id") != service.get("id"):
                self._service_control = {"active": True, "service_id": service.get("id"), "index": current_index, "started": time.monotonic()}
            if action == "next":
                self._service_control["index"] = min(len(items) - 1, int(self._service_control.get("index", 0)) + 1)
                self._service_control["started"] = time.monotonic()
            elif action == "previous":
                self._service_control["index"] = max(0, int(self._service_control.get("index", 0)) - 1)
                self._service_control["started"] = time.monotonic()
            elif action != "take":
                raise ValueError("Unknown service control action")
        self._apply_service_control(self.state)
        return self.state

    def _apply_service_control(self, state: dict[str, Any]) -> None:
        service = state.get("service") or {}
        timing = state.get("timing") or {}
        items = timing.get("service_items") or service_items(service, timing.get("service_time_id"))
        control = self._service_control
        if not control.get("active") or control.get("service_id") != service.get("id") or not items:
            state["service_control"] = {"active": False}
            if control.get("active") and control.get("service_id") != service.get("id"):
                self._service_control = {"active": False}
            return
        index = max(0, min(len(items) - 1, int(control.get("index", 0))))
        elapsed = max(0, int(time.monotonic() - float(control.get("started", time.monotonic()))))
        current = items[index]
        state["timing"] = {
            **(state.get("timing") or {}), "state": "controlled", "live": True,
            "current_item": current, "next_item": items[index + 1] if index + 1 < len(items) else None,
            "item_elapsed": elapsed, "item_delta": elapsed - int(current.get("length") or 0),
        }
        state["service_control"] = {"active": True, "index": index, "item_id": current.get("id"), "item_title": current.get("title")}

    @staticmethod
    def _apply_assignments(state: dict[str, Any], mapping: dict[str, str]) -> None:
        people: dict[str, dict[str, Any]] = {}
        for person in state.get("people", []):
            position = str(person.get("position") or "").strip().casefold()
            position_key = str(person.get("position_key") or "").strip()
            if position:
                people[position] = person
            if position_key:
                people[position_key] = person
            for scheduled_position in person.get("positions") or []:
                scheduled_key = str(scheduled_position.get("key") or "").strip()
                scheduled_name = str(scheduled_position.get("name") or "").strip().casefold()
                if scheduled_key:
                    people[scheduled_key] = person
                if scheduled_name:
                    people[scheduled_name] = person
        mic_by_id = {mic.get("id"): mic for mic in state.get("mics", [])}
        for position, mic_id in mapping.items():
            if mic_id in mic_by_id:
                lookup = str(position).strip()
                person = people.get(lookup) or people.get(lookup.casefold())
                fallback_position = lookup.split("::", 1)[-1] if "::" in lookup else lookup
                fallback_team = lookup.split("::", 1)[0] if "::" in lookup else ""
                person = person or {"name": "Unassigned", "photo": "", "position": fallback_position, "position_key": lookup, "team_id": fallback_team}
                # Retain the consolidated person's complete role list while
                # attaching this microphone to the exact configured role.
                mic_by_id[mic_id]["assignment"] = {
                    **person,
                    "position": fallback_position,
                    "position_key": lookup,
                    "team_id": fallback_team or person.get("team_id", ""),
                }

    @staticmethod
    def _configured_media_titles(data: dict[str, Any]) -> list[str]:
        titles = {"Icon"}
        for dashboard in data.get("dashboards", []):
            for widget in dashboard.get("widgets", []):
                if widget.get("type") not in {"assignments", "mics"}:
                    continue
                settings = widget.get("settings") or {}
                if not settings.get("use_planning_center_icon"):
                    continue
                title = str(settings.get("unassigned_media_title") or "Icon").strip()
                if title:
                    titles.add(title)
        return sorted(titles, key=str.casefold)

    @staticmethod
    def _configured_resource_tags(data: dict[str, Any]) -> list[str]:
        return sorted({
            str(rule.get("tag_id") or "")
            for rule in (data.get("producer", {}).get("media_tag_rules") or [])
            if rule.get("tag_id")
        })

    @staticmethod
    def _configured_stream_sources(data: dict[str, Any]) -> list[dict[str, Any]]:
        sources: dict[str, dict[str, Any]] = {}
        vault = (data.get("secrets") or {}).get("livestream") or {}
        for dashboard in data.get("dashboards", []):
            for widget in dashboard.get("widgets", []):
                if widget.get("type") != "livestreams":
                    continue
                for source in (widget.get("settings") or {}).get("sources") or []:
                    if not source.get("enabled", True):
                        continue
                    key = str(source.get("id") or source.get("provider") or source.get("label") or "").strip()
                    if key:
                        secret_key = f"{dashboard.get('id')}:{widget.get('id')}:{key.casefold()}"
                        sources[key] = {**source, "id": key, "api_token": str(vault.get(secret_key) or "")}
        return list(sources.values())

    @staticmethod
    def _public_stream_source(source: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in source.items() if key not in {"api_token", "clear_api_token", "_secret_key"}}

    @staticmethod
    def _payload_is_live(payload: Any, keyword: str = "") -> bool:
        if keyword:
            return keyword.casefold() in json.dumps(payload, default=str).casefold()
        live_keys = {"live", "is_live", "islive", "is_live_now", "islivenow", "online", "streaming", "broadcasting"}
        live_values = {"live", "live_now", "online", "healthy", "streaming", "broadcasting"}
        if isinstance(payload, dict):
            for key, value in payload.items():
                normalized = re.sub(r"[^a-z]", "", str(key).casefold())
                if normalized in {re.sub(r"[^a-z]", "", item) for item in live_keys}:
                    if value is True or str(value).casefold() in live_values:
                        return True
                if normalized in {"status", "state", "broadcaststatus", "streamstatus"} and str(value).casefold() in live_values:
                    return True
                if isinstance(value, (dict, list)) and RuntimeService._payload_is_live(value):
                    return True
        elif isinstance(payload, list):
            return any(RuntimeService._payload_is_live(value) for value in payload)
        return False

    @staticmethod
    def _payload_value(payload: Any, names: set[str]) -> Any:
        wanted = {re.sub(r"[^a-z]", "", name.casefold()) for name in names}
        if isinstance(payload, dict):
            for key, value in payload.items():
                if re.sub(r"[^a-z]", "", str(key).casefold()) in wanted and value not in (None, ""):
                    return value
            for value in payload.values():
                found = RuntimeService._payload_value(value, names)
                if found not in (None, ""):
                    return found
        elif isinstance(payload, list):
            for value in payload:
                found = RuntimeService._payload_value(value, names)
                if found not in (None, ""):
                    return found
        return None

    @staticmethod
    def _stream_result(result: dict[str, Any], payload: Any, previous: dict[str, Any] | None = None) -> dict[str, Any]:
        live = bool(result.get("live"))
        started = RuntimeService._payload_value(payload, {"actualStartTime", "started_at", "start_time", "startedAt", "live_started_at", "creation_time"})
        viewers = RuntimeService._payload_value(payload, {"currentViewers", "concurrentViewers", "current_viewers", "live_viewers", "live_views", "viewers"})
        duration = RuntimeService._payload_value(payload, {"duration_seconds", "elapsed_seconds", "live_duration"})
        if live and not started and previous and previous.get("live"):
            started = previous.get("started_at")
        if live and not started:
            started = datetime.now(timezone.utc).isoformat()
        if live and not duration and started:
            parsed = parse_time(str(started))
            duration = max(0, int((datetime.now(timezone.utc) - parsed).total_seconds())) if parsed else 0
        try: viewers = int(viewers) if viewers not in (None, "") else None
        except (TypeError, ValueError): viewers = None
        try: duration = max(0, int(float(duration or 0)))
        except (TypeError, ValueError): duration = 0
        return {**result, "started_at": str(started or "") if live else "", "duration_seconds": duration if live else 0, "viewers": viewers}

    @staticmethod
    async def _livestream_statuses(sources: list[dict[str, Any]], restream: dict[str, Any], previous: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        destinations = restream.get("destinations") or []
        previous_by_id = {str(item.get("id") or item.get("provider") or ""): item for item in (previous or [])}
        async with httpx.AsyncClient(timeout=4, follow_redirects=True, headers={"User-Agent": "ChurchBoard livestream monitor"}) as client:
            async def check(source: dict[str, Any]) -> dict[str, Any]:
                provider = str(source.get("provider") or "custom").casefold()
                label = str(source.get("label") or provider.title())
                public = RuntimeService._public_stream_source(source)
                token = str(source.get("api_token") or "").strip()
                api_url = str(source.get("api_url") or source.get("status_url") or "").strip()
                channel_url = str(source.get("channel_url") or "").strip()
                keyword = str(source.get("live_keyword") or "").strip()
                try:
                    if provider == "restream" and not api_url:
                        live = str(restream.get("status") or "").casefold() in {"live", "online", "healthy", "streaming"} or any(
                            str(row.get("status") or "").casefold() in {"live", "online", "healthy", "streaming"} for row in destinations
                        )
                        result = {**public, "label": label, "live": live, "status": "live" if live else "offline", "checked": bool(restream.get("connected"))}
                        return RuntimeService._stream_result(result, restream, previous_by_id.get(str(public.get("id") or provider)))
                    if provider == "youtube" and token and channel_url:
                        channel_id_match = re.search(r"youtube\.com/channel/(UC[\w-]+)", channel_url, re.I)
                        channel_id = channel_id_match.group(1) if channel_id_match else ""
                        if not channel_id:
                            channel_page = await client.get(channel_url)
                            channel_id_match = re.search(r'(?:"channelId"|"externalId")\s*:\s*"(UC[\w-]+)"', channel_page.text)
                            channel_id = channel_id_match.group(1) if channel_id_match else ""
                        if channel_id:
                            response = await client.get("https://www.googleapis.com/youtube/v3/search", params={"part": "snippet", "channelId": channel_id, "eventType": "live", "type": "video", "maxResults": 1, "key": token})
                            response.raise_for_status()
                            search_items = (response.json() or {}).get("items") or []
                            live = bool(search_items)
                            details: Any = {}
                            if live:
                                video_id = str(((search_items[0].get("id") or {}).get("videoId") or ""))
                                if video_id:
                                    detail_response = await client.get("https://www.googleapis.com/youtube/v3/videos", params={"part": "liveStreamingDetails", "id": video_id, "key": token})
                                    if detail_response.is_success: details = detail_response.json()
                            result = {**public, "label": label, "live": live, "status": "live" if live else "offline", "checked": True}
                            return RuntimeService._stream_result(result, details, previous_by_id.get(str(public.get("id") or provider)))
                    if provider == "facebook" and token and channel_url and not api_url:
                        page_match = re.search(r"facebook\.com/(?:pages/[^/?#]+/)?([^/?#]+)", channel_url, re.I)
                        page_reference = page_match.group(1) if page_match else ""
                        if page_reference.casefold() in {"", "live", "videos", "watch", "plugins"}:
                            return {**public, "label": label, "live": False, "status": "invalid Page URL", "checked": False}
                        response = await client.get(
                            f"https://graph.facebook.com/{page_reference}/live_videos",
                            params={
                                "access_token": token,
                                "broadcast_status": "LIVE",
                                "fields": "status,title,live_views,creation_time,permalink_url",
                                "limit": 1,
                            },
                        )
                        response.raise_for_status()
                        payload = response.json() or {}
                        broadcasts = payload.get("data") if isinstance(payload, dict) else []
                        live = any(
                            str(row.get("status") or "").casefold() in {"live", "live_now", "broadcasting"}
                            for row in broadcasts or [] if isinstance(row, dict)
                        )
                        result = {**public, "label": label, "live": live, "status": "live" if live else "offline", "checked": True}
                        return RuntimeService._stream_result(result, payload, previous_by_id.get(str(public.get("id") or provider)))
                    if api_url:
                        headers = {"Authorization": f"Bearer {token}"} if token else None
                        response = await client.get(api_url, headers=headers)
                        response.raise_for_status()
                        try:
                            payload: Any = response.json()
                        except ValueError:
                            payload = response.text
                        live = RuntimeService._payload_is_live(payload, keyword)
                        result = {**public, "label": label, "live": live, "status": "live" if live else "offline", "checked": True}
                        return RuntimeService._stream_result(result, payload, previous_by_id.get(str(public.get("id") or provider)))
                    if provider in {"facebook", "youtube"} and channel_url:
                        live_url = channel_url.rstrip("/")
                        if provider == "youtube" and "/watch" not in live_url:
                            live_url += "/live"
                        elif provider == "facebook" and "/live" not in live_url.casefold():
                            live_url += "/live"
                        response = await client.get(live_url)
                        response.raise_for_status()
                        compact = re.sub(r"\s+", "", response.text).casefold()
                        live = (
                            (provider == "youtube" and "/watch" in str(response.url))
                            or '"islivenow":true' in compact
                            or '"islive":true' in compact
                            or '"livebroadcastcontent":"live"' in compact
                            or '"is_live_streaming":true' in compact
                            or '"broadcast_status":"live"' in compact
                        )
                        # Facebook no longer includes dependable broadcast state
                        # in an anonymous Page response. Do not turn a missing
                        # marker into a false "offline" result; a Page access
                        # token enables the official live_videos check above.
                        status = "live" if live else ("Page access token required" if provider == "facebook" else "offline")
                        result = {**public, "label": label, "live": live, "status": status, "checked": live or provider != "facebook"}
                        return RuntimeService._stream_result(result, response.text, previous_by_id.get(str(public.get("id") or provider)))
                    return {**public, "label": label, "live": False, "status": "not configured", "checked": False}
                except Exception as exc:
                    return {**public, "label": label, "live": False, "status": "unreachable", "checked": True, "error": str(exc)}
            return list(await asyncio.gather(*(check(source) for source in sources)))

    @staticmethod
    def demo_state(now: datetime | None = None) -> dict[str, Any]:
        people = [
            {"id": "1", "name": "Jordan Lee", "position": "Vox 1", "position_key": "band::vox 1", "team_id": "band", "team_name": "Band", "photo": "/static/demo-people/jordan-lee.jpg", "status": "Confirmed"},
            {"id": "2", "name": "Morgan Reed", "position": "Vox 2", "position_key": "band::vox 2", "team_id": "band", "team_name": "Band", "photo": "/static/demo-people/morgan-reed.jpg", "status": "Confirmed"},
            {"id": "3", "name": "Taylor Brooks", "position": "Worship Leader", "position_key": "band::worship leader", "team_id": "band", "team_name": "Band", "photo": "/static/demo-people/taylor-brooks.jpg", "status": "Confirmed"},
        ]
        items = [
            {"id": "service-header", "title": "Service", "item_type": "header", "length": 0, "starts_after": 0, "notes": []},
            {"id": "1", "title": "Welcome", "length": 180, "starts_after": 0, "notes": [], "leader": "Morgan Reed"},
            {"id": "2", "title": "Worship", "length": 1200, "starts_after": 180, "notes": [], "leader": "Jordan Lee"},
            {"id": "3", "title": "Message", "length": 2100, "starts_after": 1380, "notes": ["Testing"], "note_fields": [{"name": "Vocals", "content": "Testing sermon notes from Planning Center."}]},
            {"id": "4", "title": "Closing", "length": 300, "starts_after": 3480, "notes": []},
        ]
        now = now or datetime.now(timezone.utc)
        start = now.timestamp() - 450
        started_at = datetime.fromtimestamp(start, timezone.utc)
        demo_time = {"id": "demo-time", "starts_at": started_at.isoformat(), "ends_at": datetime.fromtimestamp(start + 3780, timezone.utc).isoformat(), "time_type": "service"}
        service = {"id": "demo", "service_type_id": "demo", "title": "Sunday Worship", "dates": now.strftime("%B %d").replace(" 0", " "), "starts_at": started_at.isoformat(), "planned_length": 3780, "times": [demo_time], "items": items, "people": people}
        mics = [
            {"id": "mic-1", "receiver": "QLX-D Rack A", "channel": 1, "name": "VOX 1", "battery_percent": 80, "rf": 91, "audio": 36, "online": True, "errors": [], "assignment": {"position": "Vox 1", **people[0]}},
            {"id": "mic-2", "receiver": "QLX-D Rack A", "channel": 2, "name": "VOX 2", "battery_percent": 40, "rf": 84, "audio": 58, "online": True, "errors": [], "assignment": {"position": "Vox 2", **people[1]}},
            {"id": "mic-3", "receiver": "ULX-D Rack B", "channel": 1, "name": "WL", "battery_percent": 20, "rf": 72, "audio": 15, "online": True, "errors": [], "assignment": {"position": "Worship Leader", **people[2]}},
            {"id": "mic-4", "receiver": "ULX-D Rack B", "channel": 2, "name": "PASTOR", "battery_percent": 0, "rf": 0, "audio": 0, "online": False, "errors": ["Transmitter offline"], "assignment": {"position": "Pastor", "position_key": "speaking::pastor", "team_id": "speaking", "team_name": "Speaking", "name": "Alex Morgan", "photo": ""}},
        ]
        demo_slides = [
            {"index": index, "text": text, "notes": "Band: build into the chorus" if index == 3 else "", "part": part, "color": color, "image_url": "", "active": index == 3}
            for index, text, part, color in [
                (1, "Welcome to ChurchBoard", "Welcome", "#45b7d1"),
                (2, "Service begins soon", "Welcome", "#45b7d1"),
                (3, "Current worship slide", "Chorus", "#9c6cff"),
                (4, "Next worship slide", "Verse 2", "#45b7d1"),
                (5, "Follow the service flow", "Verse 2", "#45b7d1"),
                (6, "Keep the team together", "Verse 2", "#45b7d1"),
                (7, "Production notes", "Bridge", "#f2a23a"),
                (8, "Ready for what is next", "Tag", "#5cda8b"),
            ]
        ]
        return {
            "organization_name": "My Church", "timezone": "America/New_York", "updated_at": now.isoformat(), "service": service, "plans": [service], "people": people,
            "timing": calculate_timing(service, now), "mics": mics,
            "planning_center": {"connected": True, "demo": True, "error": ""},
            "propresenter": {
                "connected": True, "demo": True, "title": "Amazing Grace", "playlist_name": "Sunday Worship", "presentation_uuid": "demo-amazing-grace",
                "current": {"text": "Current worship slide", "notes": "Band: build into the chorus", "image_uuid": "", "image_url": "", "part": "Chorus", "color": "#9c6cff", "index": 3, "total": 8},
                "next": {"text": "Next worship slide", "notes": "", "image_uuid": "", "image_url": "", "part": "Verse 2", "color": "#45b7d1", "index": 4, "total": 8},
                "slides": demo_slides,
                "playlist_presentations": [{"index": 0, "title": "Amazing Grace", "presentation_uuid": "demo-amazing-grace", "active": True, "triggerable": True, "is_pco": True, "slides": demo_slides}],
            },
        }
