from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from app.store import ConfigStore


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def add_activity(data: dict[str, Any], user: dict[str, Any], action: str, detail: str, campus_id: str = "main") -> None:
    rows = data.setdefault("producer", {}).setdefault("activity", [])
    rows.insert(0, {
        "id": uuid4().hex,
        "at": now_iso(),
        "user_id": user.get("id"),
        "user_name": user.get("name") or "ChurchBoard user",
        "action": action,
        "detail": detail,
        "campus_id": campus_id or "main",
    })
    del rows[500:]


def visible_for_user(item: dict[str, Any], user: dict[str, Any]) -> bool:
    if user.get("role") == "admin":
        return True
    campus_id = str(item.get("campus_id") or "main")
    return campus_id in (user.get("campus_ids") or ["main"])


def producer_context(store: ConfigStore, runtime: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    data = store.load()
    producer = data.get("producer") or {}
    service = runtime.get("service") or {}
    people = list(runtime.get("people") or [])
    if user.get("role") == "volunteer":
        person_id = str(user.get("planning_center_person_id") or "")
        user_name = str(user.get("name") or "").casefold()
        people = [person for person in people if (person_id and str(person.get("id") or "") == person_id) or str(person.get("name") or "").casefold() == user_name]
    position_keys = {
        str(key)
        for person in people
        for key in (person.get("position_keys") or [person.get("position_key")])
        if key
    }
    templates = [item for item in producer.get("checklist_templates", []) if visible_for_user(item, user)]
    resources = [item for item in producer.get("resources", []) if visible_for_user(item, user)]
    media_tag_rules = list(producer.get("media_tag_rules") or [])
    tagged_resources = runtime.get("planning_center_resources") or {}
    if user.get("role") == "volunteer":
        templates = [item for item in templates if not item.get("position_keys") or position_keys.intersection(item.get("position_keys") or [])]
        resources = [item for item in resources if not item.get("position_keys") or position_keys.intersection(item.get("position_keys") or [])]
        media_tag_rules = [item for item in media_tag_rules if str(item.get("position_key") or "") in position_keys]
    visible_tag_ids = {str(item.get("tag_id") or "") for item in media_tag_rules if item.get("tag_id")}
    tagged_resource_count = len({
        str(item.get("id") or item.get("url") or item.get("title") or "")
        for tag_id in visible_tag_ids
        for item in tagged_resources.get(tag_id, [])
    })
    service_id = str(service.get("id") or "unscheduled")
    completions = [item for item in producer.get("completions", []) if str(item.get("service_id")) == service_id]
    activity = [item for item in producer.get("activity", []) if visible_for_user(item, user)][:80]
    return {
        "user": user,
        "organization": data.get("organization") or {},
        "service": service,
        "plans": runtime.get("plans") or [],
        "manual_plan": data.get("settings", {}).get("manual_plan"),
        "people": people,
        "templates": templates,
        "resources": resources,
        "media_tag_rules": media_tag_rules,
        "tagged_resources": tagged_resources,
        "completions": completions,
        "activity": activity,
        "summary": {
            "positions": len(position_keys),
            "templates": len(templates),
            "resources": len(resources) + tagged_resource_count,
            "completed": sum(1 for item in completions if item.get("completed")),
        },
    }


def save_template(store: ConfigStore, payload: dict[str, Any], user: dict[str, Any], template_id: str | None = None) -> dict[str, Any]:
    data = store.load()
    rows = data.setdefault("producer", {}).setdefault("checklist_templates", [])
    existing = next((item for item in rows if item.get("id") == template_id), None) if template_id else None
    tasks = []
    for index, task in enumerate(payload.get("tasks") or []):
        title = str(task.get("title") or "").strip()
        if title:
            tasks.append({"id": str(task.get("id") or uuid4().hex), "title": title[:200], "required": bool(task.get("required", True)), "order": index})
    title = str(payload.get("title") or "").strip()
    if not title or not tasks:
        raise HTTPException(400, "A checklist needs a title and at least one task")
    row = {
        "id": str(existing.get("id") if existing else uuid4().hex),
        "title": title[:160],
        "description": str(payload.get("description") or "").strip()[:1000],
        "position_keys": [str(value) for value in payload.get("position_keys") or [] if value],
        "campus_id": str(payload.get("campus_id") or "main"),
        "tasks": tasks,
        "version": int(existing.get("version", 0) + 1 if existing else 1),
        "updated_at": now_iso(),
        "updated_by": user.get("id"),
    }
    if existing:
        rows[rows.index(existing)] = row
        action = "updated checklist"
    else:
        rows.append(row)
        action = "created checklist"
    add_activity(data, user, action, row["title"], row["campus_id"])
    store.save(data)
    return row


def save_resource(store: ConfigStore, payload: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    data = store.load()
    title = str(payload.get("title") or "").strip()
    url = str(payload.get("url") or "").strip()
    if not title:
        raise HTTPException(400, "Enter a resource title")
    row = {
        "id": uuid4().hex,
        "title": title[:160],
        "description": str(payload.get("description") or "").strip()[:1000],
        "kind": str(payload.get("kind") or "link")[:30],
        "url": url[:2000],
        "filename": "",
        "content_type": "",
        "position_keys": [str(value) for value in payload.get("position_keys") or [] if value],
        "campus_id": str(payload.get("campus_id") or "main"),
        "created_at": now_iso(),
        "created_by": user.get("id"),
    }
    data.setdefault("producer", {}).setdefault("resources", []).append(row)
    add_activity(data, user, "added resource", row["title"], row["campus_id"])
    store.save(data)
    return row


def set_completion(store: ConfigStore, payload: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    data = store.load()
    producer = data.setdefault("producer", {})
    rows = producer.setdefault("completions", [])
    identity = (
        str(payload.get("service_id") or "unscheduled"),
        str(payload.get("template_id") or ""),
        str(payload.get("task_id") or ""),
        str(payload.get("person_id") or user.get("planning_center_person_id") or user.get("id") or ""),
    )
    if not all(identity[1:]):
        raise HTTPException(400, "Checklist completion is missing an identifier")
    existing = next((item for item in rows if tuple(str(item.get(key) or "") for key in ("service_id", "template_id", "task_id", "person_id")) == identity), None)
    row = {
        "id": str(existing.get("id") if existing else uuid4().hex),
        "service_id": identity[0],
        "template_id": identity[1],
        "task_id": identity[2],
        "person_id": identity[3],
        "position_key": str(payload.get("position_key") or ""),
        "completed": bool(payload.get("completed")),
        "completed_at": now_iso() if payload.get("completed") else "",
        "completed_by": user.get("id"),
    }
    if existing:
        rows[rows.index(existing)] = row
    else:
        rows.append(row)
    template = next((item for item in producer.get("checklist_templates", []) if item.get("id") == identity[1]), {})
    task = next((item for item in template.get("tasks", []) if item.get("id") == identity[2]), {})
    add_activity(data, user, "completed task" if row["completed"] else "reopened task", str(task.get("title") or "Checklist task"))
    store.save(data)
    return row
