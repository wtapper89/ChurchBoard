from __future__ import annotations

import asyncio
import re
import time
from typing import Any
from urllib.parse import quote

import httpx


class ProPresenterClient:
    def __init__(self, settings: dict[str, Any]):
        self.settings = settings
        self._client: httpx.AsyncClient | None = None
        self._active_payload: dict[str, Any] = {}
        self._active_playlist_payload: dict[str, Any] = {}
        self._playlist_payload: dict[str, Any] = {}
        self._playlist_items_payload: Any = []
        self._transport_payload: dict[str, Any] = {}
        self._presentation_details_payload: dict[str, Any] = {}
        self._presentation_details_uuid = ""
        self._presentation_details_refreshed = 0.0
        self._playlist_presentation_details: dict[str, dict[str, Any]] = {}
        self._playlist_details_key: tuple[str, ...] = ()
        self._playlist_details_refreshed = 0.0
        self._active_refreshed = 0.0
        self._playlist_refreshed = 0.0
        self._transport_refreshed = 0.0
        self._macros_payload: list[dict[str, Any]] = []
        self._macros_refreshed = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.settings.get("enabled") and self.settings.get("host"))

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=2)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def playlist_diagnostics(self) -> dict[str, Any]:
        """Return the raw, read-only playlist responses for local debugging."""
        base = f"http://{self.settings.get('host', '127.0.0.1')}:{int(self.settings.get('port', 50001))}"
        paths = {"active": "/v1/playlist/active", "focused": "/v1/playlist/focused"}
        results: dict[str, Any] = {}
        for name, path in paths.items():
            response = await self._http().get(f"{base}{path}")
            try:
                body: Any = response.json()
            except Exception:
                body = response.text
            results[name] = {"status": response.status_code, "body": body}
        playlist_uuid = next((self._playlist_context(row["body"]).get("playlist_uuid") for row in results.values() if isinstance(row.get("body"), dict) and self._playlist_context(row["body"]).get("playlist_uuid")), "")
        if playlist_uuid:
            response = await self._http().get(f"{base}/v1/playlist/{quote(playlist_uuid, safe='')}")
            try:
                body = response.json()
            except Exception:
                body = response.text
            results["contents"] = {"status": response.status_code, "body": body}
        return results

    async def status(self) -> dict[str, Any]:
        base = f"http://{self.settings.get('host', '127.0.0.1')}:{int(self.settings.get('port', 50001))}"
        clock = time.monotonic()
        fetch_active = not self._active_payload or clock - self._active_refreshed >= 0.25
        fetch_playlist = not self._playlist_payload or clock - self._playlist_refreshed >= 1.5
        fetch_macros = not self._macros_refreshed or clock - self._macros_refreshed >= 2.0
        names = ["slide", "index"]
        requests = [
            self._http().get(f"{base}/v1/status/slide"),
            self._http().get(f"{base}/v1/presentation/slide_index"),
        ]
        if fetch_active:
            names.append("active")
            requests.append(self._http().get(f"{base}/v1/presentation/active"))
        if fetch_playlist:
            names.append("playlist")
            requests.append(self._http().get(f"{base}/v1/playlist/active"))
            names.append("playlist_focused")
            requests.append(self._http().get(f"{base}/v1/playlist/focused"))
        if fetch_macros:
            names.append("macros")
            requests.append(self._http().get(f"{base}/v1/macros"))
        responses = dict(zip(names, await asyncio.gather(*requests)))
        responses["slide"].raise_for_status()
        try:
            slide_payload = responses["slide"].json() if getattr(responses["slide"], "status_code", 200) != 204 else {}
        except (TypeError, ValueError):
            slide_payload = {}
        # ProPresenter returns JSON null for several presentation endpoints
        # after Clear All/Clear Slide. That is a valid "nothing on air" state,
        # not a lost API connection. Keep macros, timers and the playlist
        # available while presenting empty Now/Next data.
        slide = slide_payload if isinstance(slide_payload, dict) else {}
        index_response = responses["index"]
        index_payload = index_response.json() if index_response.is_success else 0
        active_response = responses.get("active")
        if active_response is not None and active_response.is_success:
            active_payload = active_response.json()
            self._active_payload = active_payload if isinstance(active_payload, dict) else {}
            self._active_refreshed = clock
        playlist_response = responses.get("playlist")
        if playlist_response is not None and playlist_response.is_success:
            active_playlist_payload = playlist_response.json()
            active_playlist = active_playlist_payload if isinstance(active_playlist_payload, dict) else {}
            self._active_playlist_payload = active_playlist
            focused_response = responses.get("playlist_focused")
            focused_payload = focused_response.json() if focused_response is not None and focused_response.is_success else {}
            focused_playlist = focused_payload if isinstance(focused_payload, dict) else {}
            # A presentation can be active without its playlist being focused.
            # For the operator browser, the focused playlist is the complete
            # ProPresenter list the operator is currently working from.
            self._playlist_payload = focused_playlist if self._playlist_context(focused_playlist).get("playlist_uuid") else active_playlist
            self._playlist_items_payload = self._playlist_payload
            self._playlist_refreshed = clock
            playlist_uuid = self._playlist_context(self._playlist_payload).get("playlist_uuid")
            if playlist_uuid:
                detail_response = await self._http().get(f"{base}/v1/playlist/{quote(playlist_uuid, safe='')}")
                if detail_response.is_success:
                    self._playlist_items_payload = detail_response.json()
            playlist_rows = self._playlist_presentations(
                self._playlist_items_payload, self._playlist_context(self._playlist_payload)
            )
            presentation_uuids = tuple(dict.fromkeys(
                str(row["presentation_uuid"]) for row in playlist_rows
                if row.get("triggerable") and row.get("presentation_uuid") and "/" not in str(row.get("presentation_uuid"))
            ))
            missing_details = any(uuid not in self._playlist_presentation_details for uuid in presentation_uuids)
            if presentation_uuids and (
                presentation_uuids != self._playlist_details_key
                or (missing_details and clock - self._playlist_details_refreshed >= 5.0)
                or clock - self._playlist_details_refreshed >= 10.0
            ):
                detail_responses = await asyncio.gather(*[
                    self._http().get(f"{base}/v1/presentation/{quote(uuid, safe='')}")
                    for uuid in presentation_uuids
                ], return_exceptions=True)
                for uuid, response in zip(presentation_uuids, detail_responses):
                    if not isinstance(response, Exception) and response.is_success:
                        payload = response.json()
                        if isinstance(payload, dict):
                            self._playlist_presentation_details[uuid] = self._presentation_payload(payload)
                self._playlist_details_key = presentation_uuids
                self._playlist_details_refreshed = clock
        macros_response = responses.get("macros")
        if macros_response is not None and macros_response.is_success:
            payload = macros_response.json()
            self._macros_payload = self._normalize_macros(payload)
            self._macros_refreshed = clock
        active = self._active_payload
        playlist_payload = self._playlist_payload
        current = slide.get("current") or {}
        next_slide = slide.get("next") or {}
        index = self._index(index_payload)
        presentation = active.get("presentation", active)
        presentation_uuid = self._presentation_uuid(presentation)
        # /presentation/active can be intentionally sparse on some
        # ProPresenter versions. Fetch the identified presentation so the
        # playlist widget has every cue, group and label—not just Now/Next.
        if presentation_uuid and (
            presentation_uuid != self._presentation_details_uuid
            or clock - self._presentation_details_refreshed >= 2.0
        ):
            detail_response = await self._http().get(
                f"{base}/v1/presentation/{quote(presentation_uuid, safe='')}"
            )
            if detail_response.is_success and isinstance(detail_response.json(), dict):
                self._presentation_details_payload = self._presentation_payload(detail_response.json())
                self._presentation_details_uuid = presentation_uuid
                self._presentation_details_refreshed = clock
        detailed_presentation = self._presentation_details_payload if self._presentation_details_uuid == presentation_uuid else {}
        if detailed_presentation:
            # The active response can contain the exact arrangement/order now
            # being used while the detail response describes the library
            # presentation. Use details to fill gaps, but never replace live
            # groups or arrangement metadata with the library copy.
            merged_identifier = {
                **(detailed_presentation.get("id") if isinstance(detailed_presentation.get("id"), dict) else {}),
                **(presentation.get("id") if isinstance(presentation.get("id"), dict) else {}),
            }
            presentation = {**detailed_presentation, **presentation}
            if merged_identifier:
                presentation["id"] = merged_identifier
        cue_entries = self._presentation_cue_entries(presentation)
        cue_total = self._cue_total(index_payload, len(cue_entries))
        current_position, next_position = self._cue_positions(cue_entries, current, next_slide, index)
        current_entry = cue_entries[current_position] if 0 <= current_position < len(cue_entries) else {}
        next_entry = cue_entries[next_position] if 0 <= next_position < len(cue_entries) else {}
        current_thumbnail_position = int(current_entry.get("_thumbnail_index", current_position))
        next_thumbnail_position = int(next_entry.get("_thumbnail_index", next_position))
        current_details = current_entry.get("cue", {})
        next_details = next_entry.get("cue", {})
        current_result = self._slide(current)
        next_result = self._slide(next_slide)
        current_result["notes"] = current_result["notes"] or self._notes(current_details)
        next_result["notes"] = next_result["notes"] or self._notes(next_details)
        presentation_uuid = self._presentation_uuid(presentation) or presentation_uuid
        browser_playlist_context = self._playlist_context(playlist_payload)
        active_playlist_context = self._playlist_context(self._active_playlist_payload)
        # The playlist widget intentionally follows the focused playlist, but
        # Planning Center LIVE must follow what is actually on air. Keeping
        # these contexts separate prevents a focused song from masking an
        # active Message (or any other differently named service item).
        if (
            active_playlist_context.get("service_item_title")
            or active_playlist_context.get("service_item_index") is not None
            or active_playlist_context.get("service_item_is_pco")
        ):
            playlist_context = {
                **browser_playlist_context,
                "service_item_title": active_playlist_context.get("service_item_title", ""),
                "service_item_index": active_playlist_context.get("service_item_index"),
                "service_item_is_pco": bool(active_playlist_context.get("service_item_is_pco")),
                "active_playlist_name": active_playlist_context.get("playlist_name", ""),
                "active_playlist_uuid": active_playlist_context.get("playlist_uuid", ""),
            }
        else:
            playlist_context = browser_playlist_context
        playlist_presentations = self._playlist_presentations(self._playlist_items_payload, playlist_context)
        linked_playlist_row = next(
            (
                row for row in playlist_presentations
                if presentation_uuid
                and row.get("presentation_uuid") == presentation_uuid
                and row.get("is_pco")
            ),
            None,
        )
        if linked_playlist_row:
            # A Planning Center-synced presentation can keep a local filename
            # (for example John 1_1-3) while its playlist row is linked to the
            # Planning Center Message item. The row index includes headers and
            # pre-service items, so preserve that absolute index explicitly.
            playlist_context["service_item_index"] = linked_playlist_row["index"]
            playlist_context["service_item_index_is_absolute"] = True
            playlist_context["service_item_is_pco"] = True
            arrangement_uuid = str(linked_playlist_row.get("arrangement_uuid") or "")
            arrangement_name = str(linked_playlist_row.get("arrangement_name") or "")
            if arrangement_uuid or arrangement_name:
                # Planning Center-synced rows carry the exact arrangement that
                # ProPresenter is playing. /presentation/active can leave
                # current_arrangement blank, which previously made us expand
                # the first library arrangement and display duplicated or
                # out-of-order media cues.
                presentation["current_arrangement"] = {
                    "uuid": arrangement_uuid,
                    "name": arrangement_name,
                }
                cue_entries = self._presentation_cue_entries(presentation)
                cue_total = self._cue_total(index_payload, len(cue_entries))
                current_position, next_position = self._cue_positions(cue_entries, current, next_slide, index)
                current_entry = cue_entries[current_position] if 0 <= current_position < len(cue_entries) else {}
                next_entry = cue_entries[next_position] if 0 <= next_position < len(cue_entries) else {}
                current_thumbnail_position = int(current_entry.get("_thumbnail_index", current_position))
                next_thumbnail_position = int(next_entry.get("_thumbnail_index", next_position))
                current_details = current_entry.get("cue", {})
                next_details = next_entry.get("cue", {})
                current_result["notes"] = current_result["notes"] or self._notes(current_details)
                next_result["notes"] = next_result["notes"] or self._notes(next_details)
        active_thumbnail_playlist_uuid = str(
            active_playlist_context.get("playlist_uuid")
            or playlist_context.get("active_playlist_uuid")
            or browser_playlist_context.get("playlist_uuid")
            or ""
        )
        active_thumbnail_item_index = int(linked_playlist_row.get("index")) if linked_playlist_row else playlist_context.get("service_item_index")
        if clock - self._transport_refreshed >= 0.5:
            transport_responses = await asyncio.gather(
                self._http().get(f"{base}/v1/transport/presentation/current"),
                self._http().get(f"{base}/v1/transport/presentation/time"),
                self._http().get(f"{base}/v1/timers/current"),
                self._http().get(f"{base}/v1/timer/video_countdown"),
                return_exceptions=True,
            )
            self._transport_refreshed = clock
            self._transport_payload = {
                **self._transport_status(*transport_responses[:2]),
                "timers": self._timer_status(transport_responses[2]),
                "video_remaining": self._video_countdown(transport_responses[3]),
            }
        media = self._transport_payload.get("media") or {}
        current_timer = self._timer_for_slide(
            self._transport_payload.get("timers") or [],
            current_result.get("text"),
            self._presentation_title(presentation),
            current_details,
        )
        # Presentation transport includes looping slide backgrounds. The
        # dedicated video countdown is the reliable indication that a finite
        # foreground video is playing; it prevents motion backgrounds from
        # appearing as foreground videos on every lyric cue.
        video_remaining = self._transport_payload.get("video_remaining") or ""
        visible_media = (
            {**media, "remaining_text": video_remaining, "is_foreground": True}
            if video_remaining
            and media.get("is_playing")
            and not str(current_result.get("text") or "").strip()
            else {}
        )
        current_result.update({
            "part": current_entry.get("part", ""),
            "color": current_entry.get("color", ""),
            "index": index + 1,
            "total": cue_total,
            "image_url": self._playlist_thumbnail_url(active_thumbnail_playlist_uuid, active_thumbnail_item_index, current_position, current_result["image_uuid"])
            or self._thumbnail_url(presentation_uuid, current_thumbnail_position, current_result["image_uuid"])
            if current_result["image_uuid"] or current_details else "",
            "timer_text": current_timer,
            "media": visible_media,
        })
        next_result.update({
            "part": next_entry.get("part", ""),
            "color": next_entry.get("color", ""),
            "index": index + 2 if index + 1 < cue_total else 0,
            "total": cue_total,
            "image_url": self._playlist_thumbnail_url(active_thumbnail_playlist_uuid, active_thumbnail_item_index, next_position, next_result["image_uuid"])
            or self._thumbnail_url(presentation_uuid, next_thumbnail_position, next_result["image_uuid"])
            if next_result["image_uuid"] or next_details else "",
            "timer_text": self._countdown_text(next_result.get("text")),
        })
        for item in playlist_presentations:
            item_uuid = item.get("presentation_uuid") or ""
            active_row = bool(item.get("active")) or item_uuid == presentation_uuid or (
                playlist_context.get("service_item_index") is not None
                and int(item.get("index", -1)) == int(playlist_context.get("service_item_index"))
            )
            item_details = presentation if active_row else self._playlist_presentation_details.get(item_uuid) or item.get("_presentation_payload") or {}
            if item_details and (item.get("arrangement_uuid") or item.get("arrangement_name")):
                item_details = {
                    **item_details,
                    "current_arrangement": {
                        "uuid": str(item.get("arrangement_uuid") or ""),
                        "name": str(item.get("arrangement_name") or ""),
                    },
                }
            thumbnail_uuid = presentation_uuid if active_row and presentation_uuid else item_uuid
            if active_row and presentation_uuid:
                item["presentation_uuid"] = presentation_uuid
            entries = self._presentation_cue_entries(item_details)
            item["slides_loaded"] = bool(item_details)
            item["slides"] = [
                {
                    "index": position + 1,
                    "text": self._slide(entry.get("cue")).get("text", ""),
                    "notes": self._notes(entry.get("cue")),
                    "part": entry.get("part", ""),
                    "color": entry.get("color", ""),
                    "image_url": self._thumbnail_url(
                        thumbnail_uuid, int(entry.get("_thumbnail_index", position)), self._slide(entry.get("cue")).get("image_uuid", ""),
                    ) if not browser_playlist_context.get("playlist_uuid") else self._playlist_thumbnail_url(
                        str(browser_playlist_context.get("playlist_uuid") or ""), int(item.get("index", -1)), position, self._slide(entry.get("cue")).get("image_uuid", ""),
                    ),
                    "active": active_row and position == current_position,
                }
                for position, entry in enumerate(entries)
            ]
        return {
            "connected": True,
            "title": self._presentation_title(presentation),
            "presentation_uuid": presentation_uuid,
            **playlist_context,
            "current": current_result,
            "next": next_result,
            "timers": self._transport_payload.get("timers") or [],
            "slides": [
                {"index": position + 1, "text": self._slide(entry.get("cue")).get("text", ""), "notes": self._notes(entry.get("cue")), "part": entry.get("part", ""), "color": entry.get("color", ""), "image_url": self._playlist_thumbnail_url(active_thumbnail_playlist_uuid, active_thumbnail_item_index, position, self._slide(entry.get("cue")).get("image_uuid", "")) or self._thumbnail_url(presentation_uuid, int(entry.get("_thumbnail_index", position)), self._slide(entry.get("cue")).get("image_uuid", "")), "active": position == current_position}
                for position, entry in enumerate(cue_entries)
            ],
            "playlist_presentations": playlist_presentations,
            "macros": self._macros_payload,
        }

    @staticmethod
    def _normalize_macros(payload: Any) -> list[dict[str, Any]]:
        rows = payload if isinstance(payload, list) else payload.get("macros", []) if isinstance(payload, dict) else []
        result: list[dict[str, Any]] = []
        for fallback_index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            identifier = row.get("id") if isinstance(row.get("id"), dict) else {}
            uuid = str(identifier.get("uuid") or row.get("uuid") or "").strip()
            name = str(identifier.get("name") or row.get("name") or "").strip()
            if not uuid or not name:
                continue
            color = row.get("color") if isinstance(row.get("color"), dict) else {}
            channels = []
            for channel in ("red", "green", "blue"):
                try:
                    channels.append(max(0, min(255, round(float(color.get(channel, 0)) * 255))))
                except (TypeError, ValueError):
                    channels.append(0)
            try:
                index = int(identifier.get("index", row.get("index", fallback_index)))
            except (TypeError, ValueError):
                index = fallback_index
            result.append({"id": uuid, "name": name, "index": index, "color": "#" + "".join(f"{value:02x}" for value in channels)})
        return sorted(result, key=lambda item: (item["index"], item["name"].casefold()))

    async def trigger_macro(self, macro_id: str) -> None:
        macro_id = str(macro_id or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9-]+", macro_id):
            raise ValueError("Invalid ProPresenter macro ID")
        base = f"http://{self.settings.get('host', '127.0.0.1')}:{int(self.settings.get('port', 50001))}"
        response = await self._http().get(f"{base}/v1/macro/{quote(macro_id, safe='')}/trigger")
        response.raise_for_status()

    async def trigger_active_playlist_item(self, index: int) -> None:
        if index < 0 or index > 10000:
            raise ValueError("Invalid ProPresenter playlist item index")
        base = f"http://{self.settings.get('host', '127.0.0.1')}:{int(self.settings.get('port', 50001))}"
        # The destination-specific active route is not implemented by every
        # ProPresenter build. Resolve the UUID and use the documented explicit
        # playlist route first; this also prevents a focus change from sending
        # the cue to a different playlist.
        focused_response = await self._http().get(f"{base}/v1/playlist/focused")
        focused_payload = focused_response.json() if focused_response.is_success else {}
        active_response = await self._http().get(f"{base}/v1/playlist/active")
        active_payload = active_response.json() if active_response.is_success else {}
        playlist_uuid = (
            self._playlist_context(focused_payload).get("playlist_uuid")
            or self._playlist_context(active_payload).get("playlist_uuid")
        )
        if not playlist_uuid:
            raise ValueError("ProPresenter did not report a focused or active playlist")
        response = await self._http().get(
            f"{base}/v1/playlist/{quote(playlist_uuid, safe='')}/{index}/trigger"
        )
        response.raise_for_status()

    async def trigger_playlist_presentation(self, index: int, presentation_uuid: str | None = None) -> None:
        """Trigger a playlist card, preferring the presentation's own UUID.

        Playlist indexes include headers and media rows, and several ProPresenter
        versions reject those indexes with HTTP 400. A presentation UUID is the
        stable identifier displayed by the playlist API.
        """
        if presentation_uuid and re.fullmatch(r"[A-Za-z0-9-]+", presentation_uuid):
            base = f"http://{self.settings.get('host', '127.0.0.1')}:{int(self.settings.get('port', 50001))}"
            response = await self._http().get(
                f"{base}/v1/presentation/{quote(presentation_uuid, safe='')}/trigger"
            )
            if response.is_success:
                return
            # Planning Center-linked items often expose an arrangement UUID
            # here, not a standalone presentation UUID. Their playlist index
            # remains the authoritative trigger target.
            if response.status_code != 404:
                response.raise_for_status()
        await self.trigger_active_playlist_item(index)

    @classmethod
    def _playlist_presentations(cls, raw: Any, context: dict[str, Any]) -> list[dict[str, Any]]:
        """Normalize the several playlist shapes returned by ProPresenter 7."""
        rows: list[Any] = []
        def visit(value: Any) -> None:
            if isinstance(value, list):
                for child in value:
                    visit(child)
            elif isinstance(value, dict):
                if any(key in value for key in ("presentation", "presentation_id", "presentation_uuid")) or str(value.get("type") or "").casefold() == "presentation":
                    rows.append(value)
                else:
                    found_children = False
                    for key in ("items", "children", "playlist_items"):
                        if key in value:
                            found_children = True
                            visit(value[key])
                    # Some ProPresenter releases omit a `type` field on
                    # playlist rows. A named leaf with an id is still a
                    # triggerable presentation item, so retain it.
                    identifier = value.get("id") if isinstance(value.get("id"), dict) else value
                    kind = str(value.get("type") or "").casefold()
                    if not found_children and (value.get("name") or identifier.get("name")) and (value.get("uuid") or identifier.get("uuid")) and kind not in {"playlist", "folder", "playlist_folder"}:
                        rows.append(value)
        visit(raw)
        results = []
        for position, row in enumerate(rows):
            presentation = row.get("presentation") if isinstance(row.get("presentation"), dict) else row
            title = cls._presentation_title(presentation) or cls._presentation_title(row) or str(row.get("name") or "Presentation")
            presentation_info = row.get("presentation_info") if isinstance(row.get("presentation_info"), dict) else {}
            kind = str(row.get("type") or "presentation").casefold()
            triggerable = kind not in {"playlist", "folder", "playlist_folder", "header", "placeholder"}
            identifier = (str(presentation_info.get("presentation_uuid") or "") or cls._presentation_uuid(presentation) or str(row.get("presentation_uuid") or row.get("presentation_id") or "")) if triggerable else ""
            raw_index = row.get("index")
            if raw_index is None and isinstance(row.get("id"), dict):
                raw_index = row["id"].get("index")
            try:
                index = int(raw_index) if raw_index is not None else position
            except (TypeError, ValueError):
                index = position
            results.append({"index": index, "title": title, "presentation_uuid": identifier, "arrangement_uuid": str(presentation_info.get("arrangement_uuid") or ""), "arrangement_name": str(presentation_info.get("arrangement_name") or ""), "active": index == context.get("service_item_index"), "is_pco": bool(row.get("is_pco")), "type": kind, "triggerable": triggerable, "_presentation_payload": presentation})
        return results

    async def trigger_active_slide(self, index: int) -> None:
        """Trigger a cue in the active presentation through ProPresenter's API."""
        if index < 0 or index > 10000:
            raise ValueError("Invalid ProPresenter slide index")
        base = f"http://{self.settings.get('host', '127.0.0.1')}:{int(self.settings.get('port', 50001))}"
        response = await self._http().get(f"{base}/v1/presentation/active/{index}/trigger")
        response.raise_for_status()

    async def trigger_navigation(self, direction: str) -> None:
        """Move ProPresenter globally, including across playlist items."""
        if direction not in {"next", "previous"}:
            raise ValueError("Invalid ProPresenter navigation direction")
        base = f"http://{self.settings.get('host', '127.0.0.1')}:{int(self.settings.get('port', 50001))}"
        response = await self._http().get(f"{base}/v1/trigger/{direction}")
        response.raise_for_status()

    async def trigger_presentation_slide(self, presentation_uuid: str, index: int) -> None:
        """Trigger a cue by UUID, falling back for PCO-linked presentations."""
        if presentation_uuid and not re.fullmatch(r"[A-Za-z0-9-]+", presentation_uuid):
            raise ValueError("Invalid ProPresenter presentation UUID")
        if index < 0 or index > 10000:
            raise ValueError("Invalid ProPresenter slide index")
        base = f"http://{self.settings.get('host', '127.0.0.1')}:{int(self.settings.get('port', 50001))}"
        response = await self._http().get(
            f"{base}/v1/presentation/{quote(presentation_uuid, safe='')}/{index}/trigger"
        )
        if response.is_success:
            return
        # Some Planning Center-linked playlist items expose a presentation UUID
        # that works for details and thumbnails but is rejected by the direct
        # trigger route. The expanded slides always describe the live
        # presentation, so the documented active cue route is the safe fallback.
        if response.status_code not in {400, 404}:
            response.raise_for_status()
        await self.trigger_active_slide(index)

    async def trigger_playlist_slide(self, playlist_index: int, presentation_uuid: str, cue_index: int, is_pco: bool = False) -> None:
        """Trigger one cue from any presentation in the visible playlist."""
        if not re.fullmatch(r"[A-Za-z0-9-]+", presentation_uuid or ""):
            raise ValueError("Invalid ProPresenter presentation UUID")
        if cue_index < 0 or cue_index > 10000:
            raise ValueError("Invalid ProPresenter slide index")
        base = f"http://{self.settings.get('host', '127.0.0.1')}:{int(self.settings.get('port', 50001))}"
        response = await self._http().get(f"{base}/v1/presentation/{quote(presentation_uuid, safe='')}/{cue_index}/trigger") if presentation_uuid else None
        if response is not None and response.is_success:
            return
        if response is not None and response.status_code not in {400, 404}:
            response.raise_for_status()
        # PCO-linked items can reject their presentation UUID. Activate the
        # playlist row first, then cue its now-active presentation.
        await self.trigger_playlist_presentation(playlist_index, None if is_pco else presentation_uuid)
        await self.trigger_active_slide(cue_index)

    @staticmethod
    def _playlist_context(raw: Any) -> dict[str, Any]:
        destination = raw.get("presentation") if isinstance(raw, dict) else {}
        destination = destination if isinstance(destination, dict) else {}
        if isinstance(raw, dict) and not destination:
            destination = raw
        playlist = destination.get("playlist") if isinstance(destination.get("playlist"), dict) else {}
        if not playlist:
            identifier = destination.get("id") if isinstance(destination.get("id"), dict) else destination
            if destination.get("uuid") or identifier.get("uuid"):
                playlist = destination
        item = destination.get("item") if isinstance(destination.get("item"), dict) else {}
        playlist_item = destination.get("playlist_item") if isinstance(destination.get("playlist_item"), dict) else {}
        identifier = playlist_item.get("id") if isinstance(playlist_item.get("id"), dict) else {}
        index = None
        for raw_index in (item.get("index"), identifier.get("index")):
            try:
                candidate = int(raw_index)
                if 0 <= candidate < 2**31:
                    index = candidate
                    break
            except (TypeError, ValueError):
                continue
        playlist_identifier = playlist.get("id") if isinstance(playlist.get("id"), dict) else playlist
        return {
            "service_item_title": str(item.get("name") or identifier.get("name") or "").strip(),
            "service_item_index": index,
            "service_item_is_pco": bool(playlist_item.get("is_pco")),
            "playlist_name": str(playlist.get("name") or playlist_identifier.get("name") or "").strip(),
            "playlist_uuid": str(playlist.get("uuid") or playlist_identifier.get("uuid") or "").strip(),
        }

    @staticmethod
    def _slide(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return {"text": str(raw or ""), "notes": "", "image_uuid": ""}
        return {
            "text": raw.get("text") or raw.get("label") or raw.get("name") or "",
            "notes": raw.get("notes") or raw.get("slide_notes") or "",
            "image_uuid": raw.get("image_uuid") or raw.get("uuid") or "",
        }

    @staticmethod
    def _countdown_text(value: Any) -> str:
        pattern = r"-?\d{1,3}:\d{2}(?::\d{2})?(?:\.\d{1,2})?"
        lines = [line.strip() for line in str(value or "").splitlines() if line.strip()]
        return next((line for line in reversed(lines) if re.fullmatch(pattern, line)), "")

    @staticmethod
    def _transport_status(current: Any, position: Any) -> dict[str, Any]:
        def payload(response: Any) -> Any:
            if isinstance(response, Exception) or not getattr(response, "is_success", False):
                return None
            try:
                return response.json()
            except Exception:
                return None

        media_raw = payload(current)
        position_raw = payload(position)
        media = {}
        if isinstance(media_raw, dict) and (media_raw.get("uuid") or media_raw.get("is_playing")):
            try:
                current_time = max(0.0, float(position_raw))
            except (TypeError, ValueError):
                current_time = 0.0
            try:
                duration = max(0.0, float(media_raw.get("duration") or media_raw.get("length") or 0))
            except (TypeError, ValueError):
                duration = 0.0
            media = {
                "is_playing": bool(media_raw.get("is_playing")),
                "uuid": str(media_raw.get("uuid") or ""),
                "name": str(media_raw.get("name") or ""),
                "audio_only": bool(media_raw.get("audio_only")),
                "position": current_time,
                "duration": duration,
            }
        return {"media": media}

    @staticmethod
    def _timer_status(response: Any) -> list[dict[str, str]]:
        if isinstance(response, Exception) or not getattr(response, "is_success", False):
            return []
        try:
            raw = response.json()
        except Exception:
            return []
        if not isinstance(raw, list):
            return []
        timers = []
        for row in raw:
            if not isinstance(row, dict):
                continue
            identifier = row.get("id") if isinstance(row.get("id"), dict) else {}
            timers.append({
                "uuid": str(identifier.get("uuid") or ""),
                "name": str(identifier.get("name") or ""),
                "time": str(row.get("time") or ""),
                "state": str(row.get("state") or "").casefold(),
            })
        return timers

    @classmethod
    def _video_countdown(cls, response: Any) -> str:
        if isinstance(response, Exception) or not getattr(response, "is_success", False):
            return ""
        try:
            raw = response.json()
        except Exception:
            return ""
        if isinstance(raw, dict):
            raw = raw.get("time") or raw.get("value") or raw.get("video_countdown") or ""
        countdown = cls._countdown_text(raw)
        if not countdown:
            return ""
        values = [int(value) for value in re.findall(r"\d+", countdown)]
        return countdown if any(values) else ""

    @classmethod
    def _timer_for_slide(cls, timers: list[dict[str, str]], text: Any, title: str, cue: Any) -> str:
        # ProPresenter returns the timer element's design-time placeholder (for
        # example 754:56) as slide text. Only replace that placeholder when an
        # actual ProPresenter timer is active. Video remaining time is not a
        # slide timer and must never be used here.
        if not cls._countdown_text(text):
            return ""
        active_states = {"running", "complete", "overrunning", "overran", "overrun"}
        active = [row for row in timers if row.get("state") in active_states and cls._countdown_text(row.get("time"))]
        if not active:
            return ""

        context_parts = [title]
        if isinstance(cue, dict):
            context_parts.extend(str(cue.get(key) or "") for key in ("label", "name", "notes"))
        context = set(re.findall(r"[a-z0-9]+", " ".join(context_parts).casefold()))

        def score(row: dict[str, str]) -> tuple[int, int]:
            name = set(re.findall(r"[a-z0-9]+", row.get("name", "").casefold()))
            state_priority = 2 if row.get("state") in {"running", "overrunning", "overran", "overrun"} else 1
            return len(context & name), state_priority

        selected = max(active, key=score)
        return cls._countdown_text(selected.get("time"))

    @staticmethod
    def _index(raw: Any) -> int:
        if isinstance(raw, int):
            return raw
        if isinstance(raw, dict):
            for key in ("index", "slide_index", "presentation_index"):
                if key in raw:
                    value = raw[key]
                    if isinstance(value, dict):
                        nested = ProPresenterClient._index(value)
                        if nested >= 0:
                            return nested
                    else:
                        try:
                            return int(value)
                        except (TypeError, ValueError):
                            pass
        return 0

    @classmethod
    def _cue_total(cls, raw: Any, fallback: int) -> int:
        if isinstance(raw, dict):
            try:
                total = int(raw.get("total_cues") or 0)
                if total > 0:
                    return total
            except (TypeError, ValueError):
                pass
            for key in ("presentation_index", "presentation"):
                nested = raw.get(key)
                if isinstance(nested, dict):
                    total = cls._cue_total(nested, 0)
                    if total > 0:
                        return total
        return max(0, fallback)

    @classmethod
    def _presentation_cue_entries(cls, raw: Any) -> list[dict[str, Any]]:
        raw = cls._presentation_payload(raw)
        if not isinstance(raw, dict):
            return []
        groups = raw.get("groups") or []
        arrangements = raw.get("arrangements") or []
        if isinstance(groups, dict):
            groups = list(groups.values())
        if not isinstance(groups, list) or not isinstance(arrangements, list) or not arrangements:
            return cls._cue_entries(raw)

        def identifier(value: Any) -> str:
            if isinstance(value, str):
                return value
            if isinstance(value, dict):
                direct = value.get("uuid")
                if isinstance(direct, str):
                    return direct
                return identifier(value.get("id"))
            return ""

        current = raw.get("current_arrangement")
        current_id = identifier(current)
        current_name = cls._presentation_title(current) if isinstance(current, dict) else str(current or "").strip()
        arrangement = next((row for row in arrangements if isinstance(row, dict) and current_id and identifier(row.get("id")) == current_id), None)
        if arrangement is None and current_name:
            arrangement = next((row for row in arrangements if isinstance(row, dict) and cls._presentation_title(row.get("id")) == current_name), None)
        if arrangement is None:
            def arrangement_order(row: dict[str, Any]) -> int:
                try:
                    return int((row.get("id") or {}).get("index") or 0) if isinstance(row.get("id"), dict) else 0
                except (TypeError, ValueError):
                    return 0

            arrangement = min(
                (row for row in arrangements if isinstance(row, dict)),
                key=arrangement_order,
                default=None,
            )
        sequence = arrangement.get("groups") if isinstance(arrangement, dict) else None
        if not isinstance(sequence, list) or not sequence:
            return cls._cue_entries(raw)

        group_entries: dict[str, list[dict[str, Any]]] = {}
        for group in groups:
            group_id = identifier(group)
            if not isinstance(group, dict) or not group_id:
                continue
            group_entries[group_id] = cls._cue_entries(group)
        sequence_ids = [identifier(value) for value in sequence]
        sequence_ids = [value for value in sequence_ids if value in group_entries]
        if not sequence_ids:
            return cls._cue_entries(raw)

        entries: list[dict[str, Any]] = []
        # ProPresenter's thumbnail endpoint follows the expanded arrangement,
        # not the source cue's position in the presentation library. Reusing a
        # source index for a repeated group can therefore show an unrelated
        # media cue (often the song's opening video background) many times.
        for group_id in sequence_ids:
            entries.extend(dict(entry) for entry in group_entries[group_id])
        for position, entry in enumerate(entries):
            entry["_thumbnail_index"] = position
        return entries

    @classmethod
    def _presentation_payload(cls, raw: Any) -> dict[str, Any]:
        """Normalize wrapped presentation-detail responses across versions."""
        if not isinstance(raw, dict):
            return {}
        for key in ("presentation", "document"):
            nested = raw.get(key)
            if isinstance(nested, dict) and any(
                field in nested for field in ("groups", "arrangements", "cues", "slides")
            ):
                return cls._presentation_payload(nested)
        return raw

    @classmethod
    def _cue_positions(
        cls,
        entries: list[dict[str, Any]],
        current: Any,
        next_slide: Any,
        reported_index: int,
    ) -> tuple[int, int]:
        def identity(raw: Any) -> str:
            slide = cls._slide(raw)
            return " ".join(str(slide.get("text") or "").casefold().split())

        def resolve(raw: Any, fallback: int, minimum: int = 0) -> tuple[int, bool]:
            wanted = identity(raw)
            if wanted:
                candidates = [
                    position
                    for position, entry in enumerate(entries)
                    if position >= minimum and identity(entry.get("cue")) == wanted
                ]
                if candidates:
                    return min(candidates, key=lambda position: (abs(position - fallback), position < fallback, position)), True
            return fallback, False

        current_position, current_matched = resolve(current, reported_index)
        next_position, next_matched = resolve(next_slide, current_position + 1, current_position + 1)
        if not current_matched and next_matched:
            current_position = max(0, next_position - 1)
        if current_matched and not next_matched:
            next_position = current_position + 1
        return current_position, next_position

    @classmethod
    def _cues(cls, raw: Any) -> list[dict[str, Any]]:
        return [entry["cue"] for entry in cls._cue_entries(raw)]

    @classmethod
    def _cue_entries(
        cls,
        raw: Any,
        inherited_part: str = "",
        inherited_color: str = "",
    ) -> list[dict[str, Any]]:
        if not isinstance(raw, dict):
            return []

        part = cls._part_name(raw) or inherited_part
        color = cls._color(cls._raw_color(raw)) or inherited_color
        direct = raw.get("cues") or raw.get("slides")
        if isinstance(direct, list):
            entries: list[dict[str, Any]] = []
            for cue in direct:
                if not isinstance(cue, dict):
                    continue
                # A cue's `label` is a per-slide label, not its Verse/Chorus
                # group. Prefer explicit cue group data, then inherit the group.
                cue_part = cls._cue_part_name(cue) or part
                # ProPresenter also exposes a per-slide color. The part bug
                # should use the enclosing Verse/Chorus group color.
                cue_color = color or cls._color(cls._raw_color(cue))
                entries.append({"cue": cue, "part": cue_part, "color": cue_color})
            return entries

        entries = []
        groups = raw.get("groups") or raw.get("children") or raw.get("items") or []
        if isinstance(groups, dict):
            groups = list(groups.values())
        for group in groups:
            if isinstance(group, dict):
                entries.extend(cls._cue_entries(group, part, color))
        return entries

    @classmethod
    def _presentation_title(cls, raw: Any) -> str:
        if not isinstance(raw, dict):
            return ""
        for key in ("name", "title", "presentation_name", "presentationName"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for key in ("id", "presentation"):
            value = cls._presentation_title(raw.get(key))
            if value:
                return value
        return ""

    @classmethod
    def _cue_part_name(cls, raw: Any) -> str:
        if not isinstance(raw, dict):
            return ""
        for key in ("group_name", "groupName", "part"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        group = raw.get("group")
        if isinstance(group, str) and group.strip():
            return group.strip()
        if isinstance(group, dict):
            for key in ("name", "label"):
                value = group.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return ""

    @staticmethod
    def _presentation_uuid(raw: Any) -> str:
        if not isinstance(raw, dict):
            return ""
        value = raw.get("uuid")
        if isinstance(value, str):
            return value
        identifier = raw.get("id")
        if isinstance(identifier, dict) and isinstance(identifier.get("uuid"), str):
            return identifier["uuid"]
        return ""

    @staticmethod
    def _thumbnail_url(presentation_uuid: str, index: int, revision: str = "") -> str:
        if not presentation_uuid or index < 0 or not re.fullmatch(r"[A-Za-z0-9-]+", presentation_uuid):
            return ""
        url = f"/api/integrations/propresenter/thumbnail/{quote(presentation_uuid, safe='')}/{index}"
        if revision and re.fullmatch(r"[A-Za-z0-9-]+", revision):
            url += f"?revision={quote(revision, safe='')}"
        return url

    @staticmethod
    def _playlist_thumbnail_url(playlist_uuid: str, item_index: Any, cue_index: int, revision: str = "") -> str:
        try:
            item_index = int(item_index)
        except (TypeError, ValueError):
            return ""
        if not playlist_uuid or item_index < 0 or cue_index < 0 or not re.fullmatch(r"[A-Za-z0-9-]+", playlist_uuid):
            return ""
        url = f"/api/integrations/propresenter/playlist-thumbnail/{quote(playlist_uuid, safe='')}/{item_index}/{cue_index}"
        if revision and re.fullmatch(r"[A-Za-z0-9-]+", revision):
            url += f"?revision={quote(revision, safe='')}"
        return url

    async def thumbnail(self, presentation_uuid: str, index: int) -> tuple[bytes, str]:
        if not re.fullmatch(r"[A-Za-z0-9-]+", presentation_uuid) or index < 0:
            raise ValueError("Invalid ProPresenter presentation or slide index")
        base = f"http://{self.settings.get('host', '127.0.0.1')}:{int(self.settings.get('port', 50001))}"
        async with httpx.AsyncClient(timeout=5) as client:
            # Presentation state and trigger routes use zero-based cue indexes,
            # while ProPresenter's thumbnail route uses one-based cue numbers.
            response = await client.get(
                f"{base}/v1/presentation/{quote(presentation_uuid, safe='')}/thumbnail/{index + 1}",
                params={"quality": 960, "thumbnail_type": "jpeg"},
                headers={"Accept": "image/jpeg"},
            )
            response.raise_for_status()
        return response.content, response.headers.get("content-type", "image/jpeg")

    async def playlist_thumbnail(self, playlist_uuid: str, item_index: int, cue_index: int) -> tuple[bytes, str]:
        if not re.fullmatch(r"[A-Za-z0-9-]+", playlist_uuid) or item_index < 0 or cue_index < 0:
            raise ValueError("Invalid ProPresenter playlist item or slide index")
        base = f"http://{self.settings.get('host', '127.0.0.1')}:{int(self.settings.get('port', 50001))}"
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(
                f"{base}/v1/playlist/{quote(playlist_uuid, safe='')}/{item_index}/thumbnail/{cue_index}",
                params={"quality": 960, "thumbnail_type": "jpeg"},
                headers={"Accept": "image/jpeg"},
            )
            response.raise_for_status()
        return response.content, response.headers.get("content-type", "image/jpeg")

    @classmethod
    def _part_name(cls, raw: Any) -> str:
        if not isinstance(raw, dict):
            return ""
        for key in ("group_name", "groupName", "part", "label"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        group = raw.get("group")
        if isinstance(group, str) and group.strip():
            return group.strip()
        for key in ("id", "group"):
            nested = raw.get(key)
            if isinstance(nested, dict):
                for nested_key in ("name", "label"):
                    value = nested.get(nested_key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()

        # Presentation group objects commonly use `name`; avoid interpreting cue
        # names as song parts unless the object also contains slides/cues.
        if any(key in raw for key in ("cues", "slides")):
            value = raw.get("name")
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _raw_color(raw: Any) -> Any:
        if not isinstance(raw, dict):
            return None
        for key in ("group_color", "groupColor", "color"):
            if raw.get(key) is not None:
                return raw[key]
        for key in ("id", "group"):
            nested = raw.get(key)
            if isinstance(nested, dict):
                for color_key in ("group_color", "groupColor", "color"):
                    if nested.get(color_key) is not None:
                        return nested[color_key]
        return None

    @classmethod
    def _color(cls, raw: Any) -> str:
        if isinstance(raw, str):
            value = raw.strip()
            if re.fullmatch(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", value):
                return value
            if re.fullmatch(r"[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", value):
                return f"#{value}"
            numbers = value.replace(",", " ").split()
            if len(numbers) in (3, 4):
                try:
                    return cls._rgba([float(number) for number in numbers])
                except ValueError:
                    return ""
            return ""
        if isinstance(raw, (list, tuple)) and len(raw) in (3, 4):
            try:
                return cls._rgba([float(number) for number in raw])
            except (TypeError, ValueError):
                return ""
        if isinstance(raw, dict):
            keys = ("red", "green", "blue", "alpha") if "red" in raw else ("r", "g", "b", "a")
            if all(key in raw for key in keys[:3]):
                try:
                    return cls._rgba([float(raw[key]) for key in keys if key in raw])
                except (TypeError, ValueError):
                    return ""
        return ""

    @staticmethod
    def _rgba(values: list[float]) -> str:
        normalized = max(values[:3], default=0) <= 1
        rgb = [round(max(0, min(1 if normalized else 255, value)) * (255 if normalized else 1)) for value in values[:3]]
        if len(values) == 4:
            alpha = max(0, min(1, values[3] if values[3] <= 1 else values[3] / 255))
            return f"rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {alpha:g})"
        return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"

    @classmethod
    def _notes(cls, raw: Any) -> str:
        if isinstance(raw, dict):
            for key in ("notes", "slide_notes"):
                value = raw.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            for key in ("slide", "presentation", "action"):
                value = cls._notes(raw.get(key))
                if value:
                    return value
        return ""
