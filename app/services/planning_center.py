from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Any

import httpx


API_ROOT = "https://api.planningcenteronline.com/services/v2"


def item_leader(attributes: dict[str, Any], notes: list[dict[str, Any]]) -> str:
    def clean(value: Any) -> str:
        text = re.sub(r"<[^>]+>", " ", str(value or ""))
        return " ".join(text.replace("&nbsp;", " ").split()).strip()

    for key in ("song_leader", "item_leader", "leader", "led_by"):
        value = clean(attributes.get(key))
        if value:
            return value
    for note in notes:
        label = " ".join(str(note.get(key) or "") for key in ("category_name", "name", "title", "label")).casefold()
        content = clean(note.get("content"))
        if content and "leader" in label:
            return content
        match = re.search(r"(?:song|item)?\s*leader\s*:\s*([^\n<]+)", content, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def selected_service_time(plan: dict[str, Any], now: datetime | None = None) -> dict[str, Any] | None:
    now = now or datetime.now(timezone.utc)
    rows = []
    for row in plan.get("times") or []:
        start = parse_time(row.get("starts_at"))
        if start:
            rows.append((start, parse_time(row.get("ends_at")), row))
    rows.sort(key=lambda entry: entry[0])
    if not rows:
        return None
    active = [entry for entry in rows if entry[0] <= now <= (entry[1] or entry[0] + timedelta(seconds=int(plan.get("planned_length") or 0)))]
    if active:
        return max(active, key=lambda entry: entry[0])[2]
    upcoming = [entry for entry in rows if entry[0] > now]
    return upcoming[0][2] if upcoming else rows[-1][2]


def _main_service_header_index(items: list[dict[str, Any]]) -> int | None:
    """Locate the header whose following item begins at the service time.

    Planning Center includes pre-service and post-service sections in the same
    plan. The PlanTime starts_at value belongs to the main service header, not
    the first pre-service row.
    """
    for index, item in enumerate(items):
        if str(item.get("item_type") or "").casefold() != "header":
            continue
        title = " ".join(re.sub(r"[^a-z0-9]+", " ", str(item.get("title") or "").casefold()).split())
        words = set(title.split())
        if title in {"service", "main service", "worship service"} or (
            "service" in words and not words.intersection({"pre", "preservice", "post", "postservice", "after"})
        ):
            return index
    return None


def service_items(plan: dict[str, Any], service_time_id: str | None) -> list[dict[str, Any]]:
    result = []
    for item in plan.get("items") or []:
        matching = next((row for row in item.get("service_times") or [] if str(row.get("plan_time_id") or "") == str(service_time_id or "")), None)
        if matching and matching.get("exclude"):
            continue
        row = {**item}
        if matching:
            row["live_start_at"] = item.get("live_start_at") or matching.get("live_start_at")
            row["live_end_at"] = item.get("live_end_at") or matching.get("live_end_at")
        result.append(row)
    anchor = _main_service_header_index(result)
    elapsed = -sum(int(item.get("length") or 0) for item in result[:anchor]) if anchor is not None else 0
    for row in result:
        row["starts_after"] = elapsed
        elapsed += int(row.get("length") or 0)
    return result


def consolidate_people(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Combine a person's scheduled positions while retaining plan order.

    Planning Center returns one PlanPerson per position.  The dashboard, mic
    assignment, and item-leader features instead need a single representation
    of that human, with every scheduled position available for lookup.
    """
    people: list[dict[str, Any]] = []
    by_identity: dict[str, dict[str, Any]] = {}
    for row in rows:
        person_id = str(row.get("person_id") or "").strip()
        # A missing Person relationship must not merge unrelated unlinked
        # PlanPerson rows merely because their display names happen to match.
        identity = f"person:{person_id}" if person_id else f"plan-person:{row.get('id')}"
        position = {
            "name": str(row.get("position") or ""),
            "key": str(row.get("position_key") or ""),
            "team_id": str(row.get("team_id") or ""),
            "team_name": str(row.get("team_name") or ""),
        }
        person = by_identity.get(identity)
        if person is None:
            person = {**row, "positions": [position], "position_keys": [position["key"]] if position["key"] else []}
            by_identity[identity] = person
            people.append(person)
            continue
        if position["key"] and position["key"] not in person["position_keys"]:
            person["positions"].append(position)
            person["position_keys"].append(position["key"])
        for field in ("name", "photo", "status"):
            if not person.get(field) and row.get(field):
                person[field] = row[field]
    return people


class PlanningCenterClient:
    def __init__(self, settings: dict[str, Any]):
        self.settings = settings
        self.auth = (str(settings.get("application_id", "")), str(settings.get("secret", "")))

    @property
    def configured(self) -> bool:
        return bool(self.settings.get("enabled") and all(self.auth))

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(auth=self.auth, timeout=12, headers={"Accept": "application/json"}) as client:
            response = await client.get(f"{API_ROOT}{path}", params=params)
            response.raise_for_status()
            return response.json()

    async def _post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(auth=self.auth, timeout=12, headers={"Accept": "application/json"}) as client:
            response = await client.post(f"{API_ROOT}{path}", json=payload)
            response.raise_for_status()
            return response.json() if response.content else {}

    async def _get_all(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = {**(params or {}), "per_page": 100}
        offset = 0
        rows: list[dict[str, Any]] = []
        included: dict[tuple[str, str], dict[str, Any]] = {}
        while True:
            payload = await self._get(path, {**query, "offset": offset})
            page = payload.get("data", [])
            rows.extend(page)
            for item in payload.get("included", []):
                included[(str(item.get("type")), str(item.get("id")))] = item
            total = payload.get("meta", {}).get("total_count")
            if len(page) < 100 or (total is not None and len(rows) >= int(total)):
                break
            offset += len(page)
        return {"data": rows, "included": list(included.values())}

    async def service_types(self) -> list[dict[str, Any]]:
        payload = await self._get_all("/service_types")
        return [{"id": row["id"], "name": row.get("attributes", {}).get("name", "Service")} for row in payload.get("data", [])]

    async def position_catalog(self) -> list[dict[str, Any]]:
        service_types = await self.service_types()
        allowed = {str(value) for value in self.settings.get("service_type_ids", []) if value}
        if allowed:
            service_types = [row for row in service_types if row["id"] in allowed]
        teams: dict[str, dict[str, Any]] = {}
        for service_type in service_types:
            payload = await self._get_all(
                f"/service_types/{service_type['id']}/team_positions",
                {"include": "team", "order": "name"},
            )
            included = {(row["type"], row["id"]): row for row in payload.get("included", [])}
            for row in payload.get("data", []):
                team_rel = row.get("relationships", {}).get("team", {}).get("data") or {}
                team_id = str(team_rel.get("id") or "")
                if not team_id:
                    continue
                team_row = included.get((team_rel.get("type", "Team"), team_id), {})
                team_name = team_row.get("attributes", {}).get("name") or f"Team {team_id}"
                team = teams.setdefault(team_id, {
                    "id": team_id,
                    "name": team_name,
                    "service_type_id": service_type["id"],
                    "service_type_name": service_type["name"],
                    "positions": [],
                })
                position_name = str(row.get("attributes", {}).get("name") or "").strip()
                if position_name:
                    team["positions"].append({
                        "id": str(row["id"]),
                        "name": position_name,
                        "key": position_key(team_id, position_name),
                    })
        result = sorted(teams.values(), key=lambda team: (team["service_type_name"].casefold(), team["name"].casefold()))
        for team in result:
            team["positions"].sort(key=lambda position: position["name"].casefold())
        return result

    async def media_by_title(self, title: str) -> dict[str, Any] | None:
        requested_title = str(title or "").strip()
        if not requested_title:
            return None
        payload = await self._get(
            "/media",
            {
                "where[title]": requested_title,
                "include": "attachments",
                "filter": "not_archived",
                "order": "-updated_at",
                "per_page": 100,
            },
        )
        included = {
            (str(row.get("type")), str(row.get("id"))): row
            for row in payload.get("included", [])
        }
        for row in payload.get("data", []):
            attrs = row.get("attributes", {})
            if str(attrs.get("title") or "").strip().casefold() != requested_title.casefold():
                continue
            attachments = []
            for relation in row.get("relationships", {}).get("attachments", {}).get("data", []):
                attachment = included.get((str(relation.get("type")), str(relation.get("id"))), {})
                attachment_attrs = attachment.get("attributes", {})
                if attachment_attrs:
                    attachments.append(attachment_attrs)
            image_attachment = next(
                (
                    attachment
                    for attachment in attachments
                    if str(attachment.get("content_type") or "").casefold().startswith("image/")
                    or str(attachment.get("filetype") or "").casefold() == "image"
                ),
                {},
            )
            image_url = (
                attrs.get("image_url")
                or attrs.get("thumbnail_url")
                or attrs.get("preview_url")
                or image_attachment.get("thumbnail_url")
                or ""
            )
            return {
                "id": str(row.get("id") or ""),
                "title": str(attrs.get("title") or requested_title),
                "media_type": str(attrs.get("media_type") or ""),
                "image_url": str(image_url or ""),
                "updated_at": attrs.get("updated_at"),
            }
        return None

    async def media_tag_catalog(self) -> list[dict[str, Any]]:
        groups = await self._get_all("/tag_groups", {"filter": "media", "order": "name"})
        result = []
        for group in groups.get("data", []):
            group_id = str(group.get("id") or "")
            attrs = group.get("attributes") or {}
            if not group_id or str(attrs.get("tags_for") or "").casefold() != "media":
                continue
            tags = await self._get_all(f"/tag_groups/{group_id}/tags", {"order": "name"})
            result.append({
                "id": group_id,
                "name": str(attrs.get("name") or "Media"),
                "tags": [
                    {"id": str(row.get("id") or ""), "name": str((row.get("attributes") or {}).get("name") or "")}
                    for row in tags.get("data", [])
                    if row.get("id") and (row.get("attributes") or {}).get("name")
                ],
            })
        return result

    async def media_for_tag(self, tag_id: str) -> list[dict[str, Any]]:
        payload = await self._get_all("/media", {
            "where[media_tag_ids][]": str(tag_id),
            "include": "attachments",
            "filter": "not_archived",
            "order": "title",
        })
        included = {(str(row.get("type")), str(row.get("id"))): row for row in payload.get("included", [])}
        resources = []
        for row in payload.get("data", []):
            attrs = row.get("attributes") or {}
            attachments = [
                included.get((str(rel.get("type")), str(rel.get("id"))), {})
                for rel in (((row.get("relationships") or {}).get("attachments") or {}).get("data") or [])
            ]
            attachment_attrs = next(((attachment.get("attributes") or {}) for attachment in attachments if attachment.get("attributes")), {})
            url = str(attachment_attrs.get("url") or attachment_attrs.get("linked_url") or "")
            resources.append({
                "id": str(row.get("id") or ""),
                "title": str(attrs.get("title") or attachment_attrs.get("display_name") or "Planning Center media"),
                "description": str(attachment_attrs.get("display_name") or attrs.get("media_type_name") or ""),
                "kind": str(attachment_attrs.get("filetype") or attrs.get("media_type") or "media"),
                "url": url,
                "image_url": str(attrs.get("image_url") or attrs.get("thumbnail_url") or attachment_attrs.get("thumbnail_url") or ""),
                "source": "Planning Center",
                "tag_id": str(tag_id),
            })
        return resources

    async def candidate_plans(self, now: datetime | None = None) -> list[dict[str, Any]]:
        now = now or datetime.now(timezone.utc)
        service_types = await self.service_types()
        allowed = {str(value) for value in self.settings.get("service_type_ids", []) if value}
        if allowed:
            service_types = [row for row in service_types if row["id"] in allowed]
        candidates: list[dict[str, Any]] = []
        for service_type in service_types:
            payload = await self._get(
                f"/service_types/{service_type['id']}/plans",
                {"order": "-sort_date", "per_page": 25},
            )
            for row in payload.get("data", []):
                attrs = row.get("attributes", {})
                plan = {
                    "id": str(row["id"]),
                    "service_type_id": service_type["id"],
                    "series_id": str((((row.get("relationships") or {}).get("series") or {}).get("data") or {}).get("id") or ""),
                    "service_type_name": service_type["name"],
                    "title": attrs.get("title") or service_type["name"],
                    "dates": attrs.get("dates", ""),
                    "sort_date": attrs.get("sort_date"),
                }
                times = await self._get(f"/service_types/{service_type['id']}/plans/{row['id']}/plan_times", {"per_page": 100})
                service_times = []
                for time_row in times.get("data", []):
                    time_attrs = time_row.get("attributes", {})
                    if time_attrs.get("time_type") == "service":
                        service_times.append({"id": time_row["id"], **time_attrs})
                if not service_times:
                    continue
                service_times.sort(key=lambda item: item.get("starts_at") or "")
                start = parse_time(service_times[0].get("starts_at"))
                end = parse_time(service_times[-1].get("ends_at")) or start
                plan.update({"starts_at": start.isoformat() if start else None, "ends_at": end.isoformat() if end else None, "times": service_times})
                candidates.append(plan)
        candidates.sort(key=lambda plan: plan.get("starts_at") or "")
        return candidates

    async def people_catalog(self) -> list[dict[str, Any]]:
        people = []
        offset = 0
        while offset < 1000:
            payload = await self._get("/people", {"order": "name", "per_page": 100, "offset": offset})
            rows = payload.get("data", [])
            for row in rows:
                attrs = row.get("attributes", {})
                name = str(attrs.get("name") or " ".join(filter(None, [attrs.get("first_name"), attrs.get("last_name")]))).strip()
                if name:
                    people.append({
                        "id": str(row.get("id") or ""),
                        "name": name,
                        "email": str(attrs.get("email") or ""),
                        "photo": str(attrs.get("photo_url") or attrs.get("photo_thumbnail_url") or ""),
                    })
            if len(rows) < 100:
                break
            offset += 100
        return people

    def select_plan(self, candidates: list[dict[str, Any]], manual: dict[str, str] | None, now: datetime | None = None) -> dict[str, Any] | None:
        now = now or datetime.now(timezone.utc)
        if manual:
            match = next((p for p in candidates if p["id"] == str(manual.get("id")) and p["service_type_id"] == str(manual.get("service_type_id"))), None)
            if match:
                return match
        opens = timedelta(days=float(self.settings.get("open_days_before", 2)), hours=float(self.settings.get("open_hours_before", 3)))
        closes = timedelta(hours=float(self.settings.get("close_hours_after", 3)))
        eligible = []
        for plan in candidates:
            start, end = parse_time(plan.get("starts_at")), parse_time(plan.get("ends_at"))
            if start and start - opens <= now <= (end or start) + closes:
                eligible.append(plan)
        return min(eligible, key=lambda plan: abs((parse_time(plan["starts_at"]) - now).total_seconds())) if eligible else None

    async def plan_detail(self, plan: dict[str, Any]) -> dict[str, Any]:
        prefix = f"/service_types/{plan['service_type_id']}/plans/{plan['id']}"
        people_payload = await self._get(f"{prefix}/team_members", {"filter": "not_declined", "include": "person,team", "per_page": 100})
        people_included = {(row["type"], row["id"]): row for row in people_payload.get("included", [])}
        people = []
        for row in people_payload.get("data", []):
            attrs = row.get("attributes", {})
            team_rel = row.get("relationships", {}).get("team", {}).get("data") or {}
            team_id = str(team_rel.get("id") or "")
            team_row = people_included.get((team_rel.get("type", "Team"), team_id), {})
            team_name = team_row.get("attributes", {}).get("name", "")
            person_rel = row.get("relationships", {}).get("person", {}).get("data") or {}
            person_id = str(person_rel.get("id") or "")
            person_row = people_included.get((person_rel.get("type", "Person"), person_id), {})
            person_attrs = person_row.get("attributes", {})
            position_name = attrs.get("team_position_name", "")
            people.append({
                "id": row["id"],
                "person_id": person_id,
                "name": attrs.get("name", ""),
                "position": position_name,
                "position_key": position_key(team_id, position_name),
                "team_id": team_id,
                "team_name": team_name,
                "photo": person_attrs.get("photo_url") or attrs.get("photo_thumbnail") or person_attrs.get("photo_thumbnail_url") or "",
                "status": attrs.get("status", ""),
            })
        people = consolidate_people(people)
        people_by_person_id = {person["person_id"]: person for person in people if person["person_id"]}
        item_payload = await self._get(
            f"{prefix}/items",
            {"include": "item_assignments,item_times,item_notes", "per_page": 100},
        )
        included = {(row["type"], row["id"]): row for row in item_payload.get("included", [])}
        items = []
        elapsed = 0
        for row in sorted(item_payload.get("data", []), key=lambda value: value.get("attributes", {}).get("sequence", 0)):
            attrs = row.get("attributes", {})
            length = int(attrs.get("length") or 0)
            notes = []
            note_rows = []
            for rel in row.get("relationships", {}).get("item_notes", {}).get("data", []):
                note = included.get((rel.get("type"), rel.get("id")), {}).get("attributes", {})
                note_rows.append(note)
                if note.get("content"):
                    notes.append(note["content"])
            item_times = []
            for rel in row.get("relationships", {}).get("item_times", {}).get("data", []):
                item_time_row = included.get((rel.get("type"), rel.get("id")), {})
                item_time = item_time_row.get("attributes", {})
                plan_time = item_time_row.get("relationships", {}).get("plan_time", {}).get("data") or {}
                if item_time:
                    item_times.append({"plan_time_id": str(plan_time.get("id") or ""), **item_time})
            assigned_leaders = []
            leader_person_ids = []
            for rel in row.get("relationships", {}).get("item_assignments", {}).get("data", []):
                assignment = included.get((rel.get("type"), rel.get("id")), {})
                assignable = assignment.get("relationships", {}).get("assignable", {}).get("data") or {}
                if str(assignable.get("type") or "").casefold() != "person":
                    continue
                person_id = str(assignable.get("id") or "")
                person = people_by_person_id.get(person_id)
                if person_id:
                    leader_person_ids.append(person_id)
                if person and person.get("name"):
                    assigned_leaders.append(person["name"])
            fallback_leader = item_leader(attrs, note_rows)
            item = {
                "id": row["id"], "title": attrs.get("title") or attrs.get("description") or "Untitled",
                "length": length, "sequence": attrs.get("sequence", 0), "starts_after": elapsed, "notes": notes,
                "item_type": attrs.get("item_type") or "item", "key_name": attrs.get("key_name") or "",
                "leader": ", ".join(dict.fromkeys(assigned_leaders)) or fallback_leader,
                "leader_person_ids": list(dict.fromkeys(leader_person_ids)),
                "service_times": item_times,
            }
            elapsed += length
            items.append(item)
        return {**plan, "people": people, "items": items, "planned_length": elapsed}

    async def live_status(self, plan: dict[str, Any], create: bool = False) -> dict[str, Any] | None:
        service_type_id, plan_id = str(plan.get("service_type_id") or ""), str(plan.get("id") or "")
        if not service_type_id or not plan_id:
            return None
        service_prefix = f"/service_types/{service_type_id}/plans/{plan_id}"
        payload = await self._get(f"{service_prefix}/live", {"include": "controller,current_item_time,next_item_time"})
        rows = payload.get("data") or []
        if isinstance(rows, dict):
            rows = [rows]
        if not rows and create:
            await self._post(f"{service_prefix}/live", {"data": {"type": "Live"}})
            return await self.live_status(plan, create=False)
        if not rows:
            return None

        live = rows[0]
        live_id = str(live.get("id") or "")
        links = live.get("links") or {}
        action_paths = {}
        for action in ("toggle_control", "go_to_next_item", "go_to_previous_item"):
            url = str(links.get(action) or "")
            if url.startswith(API_ROOT):
                action_paths[action] = url[len(API_ROOT):]
        series_id = str(plan.get("series_id") or "")
        if not series_id and not action_paths:
            try:
                series_payload = await self._get(f"{service_prefix}/series")
                series_data = series_payload.get("data") or {}
                if isinstance(series_data, list):
                    series_data = series_data[0] if series_data else {}
                series_id = str(series_data.get("id") or "")
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:
                    raise

        included = {(str(row.get("type")), str(row.get("id"))): row for row in payload.get("included", [])}
        controller_relation = (((live.get("relationships") or {}).get("controller") or {}).get("data") or {})
        controller_id = str(controller_relation.get("id") or "")
        controller_row = included.get((str(controller_relation.get("type")), controller_id), {})
        controller_attributes = controller_row.get("attributes") or {}
        current_relation = (((live.get("relationships") or {}).get("current_item_time") or {}).get("data") or {})
        current_time = included.get((str(current_relation.get("type")), str(current_relation.get("id"))))
        current_link = str(links.get("current_item_time") or "")
        if current_time is None and current_link.startswith(API_ROOT):
            try:
                current_payload = await self._get(current_link[len(API_ROOT):])
                current_time = current_payload.get("data") or {}
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:
                    raise
                current_time = {}
        current_time = current_time or {}
        item_relation = ((((current_time.get("relationships") or {}).get("item") or {}).get("data")) or {})
        next_relation = (((live.get("relationships") or {}).get("next_item_time") or {}).get("data") or {})
        next_time = included.get((str(next_relation.get("type")), str(next_relation.get("id")))) or {}
        next_link = str(links.get("next_item_time") or "")
        if not next_time and next_link.startswith(API_ROOT):
            try:
                next_payload = await self._get(next_link[len(API_ROOT):])
                next_time = next_payload.get("data") or {}
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:
                    raise
        next_item_relation = ((((next_time.get("relationships") or {}).get("item") or {}).get("data")) or {})
        attributes = live.get("attributes") or {}
        time_attributes = current_time.get("attributes") or {}
        return {
            "id": live_id,
            "series_id": series_id,
            "action_paths": action_paths,
            "can_control": bool(attributes.get("can_control")),
            "can_take_control": bool(attributes.get("can_take_control")),
            # can_control describes permission/availability. A controller
            # relationship is the signal that this user actually owns LIVE.
            "has_control": bool(controller_id and attributes.get("can_control")),
            "controller_id": controller_id,
            "controller": controller_attributes.get("full_name") or attributes.get("controller_name") or "",
            "current_item_id": str(item_relation.get("id") or ""),
            "current_item_time_id": str(current_time.get("id") or ""),
            "current_live_start_at": time_attributes.get("live_start_at"),
            "current_live_end_at": time_attributes.get("live_end_at"),
            "next_item_id": str(next_item_relation.get("id") or ""),
        }

    async def live_action(self, plan: dict[str, Any], live: dict[str, Any], action: str) -> dict[str, Any] | None:
        if action not in {"toggle_control", "go_to_next_item", "go_to_previous_item"}:
            raise ValueError("Unknown Planning Center LIVE action")
        direct_path = str((live.get("action_paths") or {}).get(action) or "")
        if direct_path:
            try:
                await self._post(direct_path)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 403:
                    raise ValueError("Planning Center denied the LIVE action. Take control first and confirm that the token user has Services LIVE control permission.") from exc
                raise
            return await self.live_status(plan)
        series_id, plan_id, live_id = str(live.get("series_id") or plan.get("series_id") or ""), str(plan.get("id") or ""), str(live.get("id") or "")
        if not series_id or not plan_id or not live_id:
            raise ValueError("Planning Center LIVE did not provide an action link or the series, plan, and live IDs")
        try:
            await self._post(f"/series/{series_id}/plans/{plan_id}/live/{live_id}/{action}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403:
                raise ValueError("Planning Center denied the LIVE action. Take control first and confirm that the token user has Services LIVE control permission.") from exc
            raise
        return await self.live_status({**plan, "series_id": series_id})


def calculate_timing(plan: dict[str, Any] | None, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if not plan:
        return {"state": "idle", "current_item": None, "next_item": None, "item_delta": 0, "overall_delta": 0}
    chosen_time = selected_service_time(plan, now)
    start = parse_time(chosen_time.get("starts_at")) if chosen_time else parse_time(plan.get("starts_at"))
    items = service_items(plan, str(chosen_time.get("id") or "") if chosen_time else None)
    timing_context = {
        "service_start_at": start.isoformat() if start else None,
        "service_time_id": str(chosen_time.get("id") or "") if chosen_time else "",
        "service_time_name": chosen_time.get("name") if chosen_time else "",
        "service_time_index": next((index + 1 for index, row in enumerate(plan.get("times") or []) if str(row.get("id")) == str(chosen_time.get("id"))), 1) if chosen_time else 1,
        "service_time_count": len(plan.get("times") or []) or 1,
        "service_items": items,
    }
    if not start or not items:
        return {"state": "scheduled", "current_item": None, "next_item": items[0] if items else None, "item_delta": 0, "overall_delta": 0, **timing_context}
    elapsed = int((now - start).total_seconds())
    # Services LIVE is also used for rehearsals, which can happen hours or
    # days before the first scheduled service. An open LIVE item must win over
    # the wall-clock schedule or the timing bar incorrectly stays at 0:00.
    current_index = next((index for index, item in enumerate(items) if item.get("live_start_at") and not item.get("live_end_at")), None)
    live = current_index is not None
    for index, item in enumerate(items):
        if current_index is not None:
            break
        if item["starts_after"] <= elapsed < item["starts_after"] + item["length"]:
            current_index = index
            break
    if current_index is None:
        current_index = 0 if elapsed < 0 else len(items) - 1
    current = items[current_index]
    live_start = parse_time(current.get("live_start_at"))
    item_elapsed = int((now - live_start).total_seconds()) if live_start else elapsed - current["starts_after"]
    if not live and elapsed < 0:
        item_elapsed = 0
    item_elapsed = max(0, item_elapsed)
    planned_progress = current["starts_after"] + max(0, min(item_elapsed, current["length"]))
    service_elapsed = elapsed
    if live:
        # Convert every known LIVE start into an implied service origin. The
        # earliest origin preserves delay accumulated by previous items, while
        # still producing useful timing if only the current item is known.
        live_origins = [
            item_start - timedelta(seconds=int(item.get("starts_after") or 0))
            for item in items
            if (item_start := parse_time(item.get("live_start_at")))
        ]
        if live_origins:
            service_elapsed = max(0, int((now - min(live_origins)).total_seconds()))
    service_end = parse_time(chosen_time.get("ends_at")) if chosen_time else None
    if start and service_end is None:
        service_end = start + timedelta(seconds=max(1, int(plan.get("planned_length") or 0)))
    # A Services LIVE session well outside the scheduled service window is a
    # rehearsal. A 30-minute grace period avoids labeling an early start or a
    # slightly long service as a rehearsal.
    in_service_window = bool(
        start
        and service_end
        and start - timedelta(minutes=30) <= now <= service_end + timedelta(minutes=30)
    )
    rehearsal = bool(live and not in_service_window)
    return {
        "state": "running" if live or elapsed >= 0 else "upcoming",
        "current_item": current,
        "next_item": items[current_index + 1] if current_index + 1 < len(items) else None,
        "item_delta": item_elapsed - current["length"] if live or elapsed >= 0 else 0,
        "item_elapsed": item_elapsed,
        "overall_delta": service_elapsed - planned_progress if live or elapsed >= 0 else 0,
        "service_elapsed": service_elapsed,
        "live": live,
        "rehearsal": rehearsal,
        **timing_context,
    }


def position_key(team_id: str, position_name: str) -> str:
    return f"{str(team_id).strip()}::{str(position_name).strip().casefold()}"
