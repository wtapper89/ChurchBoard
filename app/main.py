from __future__ import annotations

from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import ipaddress
import asyncio
import json
import re
import secrets
import threading
from pathlib import Path
from uuid import uuid4
from zoneinfo import available_timezones

import uvicorn
import httpx
import websockets
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import ROOT_DIR, load_config
from app.auth import AuthManager, password_hash, public_user, require_role, require_user
from app.models import Dashboard, SettingsUpdate
from app.modules import ModuleRegistry
from app.producer import add_activity, producer_context, save_resource, save_template, set_completion
from app.services.runtime import RuntimeService
from app.services.spl_reports import SPLReportStore
from app.services.planning_center import PlanningCenterClient
from app.services.propresenter import ProPresenterClient
from app.services.restream import RestreamClient
from app.services.livekit import access_token as livekit_access_token
from app.store import ConfigStore
from app.update import download_update, update_status
from app.version import __version__


class ActivePlanRequest(BaseModel):
    id: str | None = None
    service_type_id: str | None = None


class ActiveServiceTimeRequest(BaseModel):
    id: str | None = None
    plan_id: str | None = None


class OSMMeasurement(BaseModel):
    laeq: float | None = None
    lceq: float | None = None
    lzeq: float | None = None
    peak: float | None = None
    fast: float | None = None
    slow: float | None = None
    a_fast: float | None = None
    a_slow: float | None = None
    b_fast: float | None = None
    b_slow: float | None = None
    c_fast: float | None = None
    c_slow: float | None = None
    z_fast: float | None = None
    z_slow: float | None = None
    timestamp: str | None = None


class ProPresenterSlideTrigger(BaseModel):
    index: int
    presentation_uuid: str | None = None
    playlist_index: int | None = None
    is_pco: bool = False
    dashboard_slug: str | None = None
    widget_id: str | None = None


class ProPresenterNavigationRequest(BaseModel):
    dashboard_slug: str | None = None
    widget_id: str | None = None


class MediaTagRulesRequest(BaseModel):
    items: list[dict] = Field(default_factory=list)


class CredentialsRequest(BaseModel):
    name: str = ""
    email: str
    password: str = ""


class UserRequest(BaseModel):
    name: str
    email: str
    password: str = ""
    role: str = "volunteer"
    campus_ids: list[str] = Field(default_factory=lambda: ["main"])
    planning_center_person_id: str = ""


class CampusRequest(BaseModel):
    name: str


class OrganizationAuthRequest(BaseModel):
    passwords_required: bool = True


class AdminRecoveryRequest(BaseModel):
    email: str
    password: str


class ProducerPayload(BaseModel):
    data: dict = Field(default_factory=dict)


class ModulePolicyRequest(BaseModel):
    auto_update: bool = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_config()
    store = ConfigStore(config.data_file)
    modules = ModuleRegistry()
    module_data = store.load()
    if modules.reconcile(module_data):
        store.save(module_data)
    runtime = RuntimeService(store, SPLReportStore(config.data_file.with_name("spl-samples.jsonl")))
    app.state.instance_id = uuid4().hex
    app.state.store = store
    app.state.auth = AuthManager(store)
    app.state.modules = modules
    app.state.runtime = runtime
    await runtime.start()
    try:
        yield
    finally:
        await runtime.close()


app = FastAPI(title="ChurchBoard", version=__version__, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT_DIR / "app" / "static"), name="static")


class ProducerPortalApp:
    """Mark requests arriving on the volunteer-only listener."""

    def __init__(self, wrapped: FastAPI):
        self.wrapped = wrapped

    async def __call__(self, scope, receive, send):
        if scope.get("type") in {"http", "websocket"}:
            scope = {**scope, "churchboard_producer_portal": True}
        await self.wrapped(scope, receive, send)


producer_portal_app = ProducerPortalApp(app)


@app.websocket("/rtc")
@app.websocket("/rtc/{subpath:path}")
async def hosted_intercom_websocket(websocket: WebSocket, subpath: str = "") -> None:
    """Proxy LiveKit signaling through ChurchBoard's existing HTTP/HTTPS listener."""
    runtime = getattr(websocket.app.state, "runtime", None)
    status = runtime.intercom.status() if runtime is not None else {"ready": False}
    if not status.get("ready"):
        await websocket.close(code=1013, reason="ChurchBoard intercom is not ready")
        return
    query = websocket.scope.get("query_string", b"").decode("ascii", "ignore")
    suffix = f"/{subpath}" if subpath else ""
    target = f"ws://127.0.0.1:{status['signal_port']}/rtc{suffix}{('?' + query) if query else ''}"
    offered = [value.strip() for value in str(websocket.headers.get("sec-websocket-protocol") or "").split(",") if value.strip()]
    try:
        async with websockets.connect(target, subprotocols=offered or None, max_size=None, compression=None) as upstream:
            await websocket.accept(subprotocol=upstream.subprotocol)

            async def browser_to_intercom() -> None:
                while True:
                    message = await websocket.receive()
                    if message["type"] == "websocket.disconnect":
                        return
                    if message.get("bytes") is not None:
                        await upstream.send(message["bytes"])
                    elif message.get("text") is not None:
                        await upstream.send(message["text"])

            async def intercom_to_browser() -> None:
                async for message in upstream:
                    if isinstance(message, bytes):
                        await websocket.send_bytes(message)
                    else:
                        await websocket.send_text(message)

            tasks = [asyncio.create_task(browser_to_intercom()), asyncio.create_task(intercom_to_browser())]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                task.result()
    except (OSError, WebSocketDisconnect, websockets.ConnectionClosed):
        try:
            await websocket.close(code=1011)
        except RuntimeError:
            pass


@app.middleware("http")
async def prevent_stale_dashboard_assets(request: Request, call_next):
    portal_only = bool(request.scope.get("churchboard_producer_portal"))
    request.state.portal_only = portal_only
    if portal_only:
        path = request.url.path
        if path == "/":
            return RedirectResponse("/producer", status_code=303)
        allowed_page = path in {"/login", "/producer"} or path.startswith("/static/")
        allowed_api = (
            path.startswith(("/api/auth/", "/api/producer/", "/api/users", "/api/campuses"))
            or path in {
                "/api/app-info", "/api/organization/auth", "/api/active-plan",
                "/api/active-service-time", "/api/runtime/refresh",
                "/api/integrations/planning-center/catalog",
                "/api/integrations/planning-center/media-tags",
                "/api/integrations/planning-center/people",
            }
        )
        if not allowed_page and not allowed_api:
            if path.startswith("/api/"):
                return JSONResponse({"detail": "This listener is limited to the ChurchBoard production workspace"}, status_code=404)
            return RedirectResponse("/producer", status_code=303)
    auth = getattr(request.app.state, "auth", None)
    if auth is not None:
        request.state.user = auth.current_user(request)
        protected_page = request.url.path in {"/admin", "/producer"} or request.url.path.startswith("/editor/")
        if request.url.path == "/producer" and not store_from(request).load().get("users"):
            return RedirectResponse("/login?next=/producer", status_code=303)
        if protected_page and auth.enabled() and not request.state.user:
            return RedirectResponse(f"/login?next={request.url.path}", status_code=303)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    if request.url.path.startswith(("/static/", "/api/producer/", "/api/users", "/api/campuses")) or request.url.path in {"/admin", "/desktop", "/producer"} or request.url.path.startswith(("/display/", "/editor/")):
        response.headers["Cache-Control"] = "no-store"
    return response


def store_from(request: Request) -> ConfigStore:
    return request.app.state.store


def dashboard_or_404(store: ConfigStore, identifier: str) -> dict:
    dashboard = next((item for item in store.load()["dashboards"] if item["id"] == identifier or item["slug"] == identifier), None)
    if not dashboard:
        raise HTTPException(404, "Dashboard not found")
    return dashboard


def persist_livestream_secrets(data: dict, dashboard: dict, previous_id: str | None = None) -> dict:
    """Move per-widget stream credentials out of the public dashboard document."""
    vault = data.setdefault("secrets", {}).setdefault("livestream", {})
    dashboard_id = str(dashboard.get("id") or "")
    valid_keys: set[str] = set()
    for widget in dashboard.get("widgets") or []:
        if widget.get("type") != "livestreams":
            continue
        for source in (widget.get("settings") or {}).get("sources") or []:
            provider = str(source.get("id") or source.get("provider") or "").strip().casefold()
            if not provider:
                continue
            key = f"{dashboard_id}:{widget.get('id')}:{provider}"
            valid_keys.add(key)
            token = str(source.pop("api_token", "") or "").strip()
            clear = bool(source.pop("clear_api_token", False))
            if token:
                vault[key] = token
            elif clear:
                vault.pop(key, None)
            source["api_token_configured"] = bool(vault.get(key))
    for key in list(vault):
        if key.startswith(f"{dashboard_id}:") and key not in valid_keys:
            vault.pop(key, None)
        if previous_id and previous_id != dashboard_id and key.startswith(f"{previous_id}:"):
            vault.pop(key, None)
    return dashboard


@app.get("/")
async def root() -> RedirectResponse:
    return RedirectResponse("/desktop")


@app.get("/desktop")
async def desktop_page() -> FileResponse:
    return FileResponse(ROOT_DIR / "app" / "static" / "desktop.html")


@app.get("/login")
async def login_page() -> FileResponse:
    return FileResponse(ROOT_DIR / "app" / "static" / "login.html")


@app.get("/producer")
async def producer_page() -> FileResponse:
    return FileResponse(ROOT_DIR / "app" / "static" / "producer.html")


@app.get("/admin")
async def admin_page() -> FileResponse:
    return FileResponse(ROOT_DIR / "app" / "static" / "admin.html")


@app.get("/modules")
async def modules_page() -> FileResponse:
    return FileResponse(ROOT_DIR / "app" / "static" / "modules.html")


@app.get("/display/{slug}")
async def display_page(slug: str) -> FileResponse:
    return FileResponse(ROOT_DIR / "app" / "static" / "display.html")


@app.get("/editor/{slug}")
async def editor_page(slug: str) -> FileResponse:
    return FileResponse(ROOT_DIR / "app" / "static" / "editor.html")


@app.get("/api/dashboards")
async def list_dashboards(request: Request) -> dict:
    return {"items": store_from(request).load()["dashboards"]}


@app.get("/api/modules/frontend")
async def module_frontend_catalog(request: Request) -> dict:
    store = store_from(request)
    data = store.load()
    modules: ModuleRegistry = request.app.state.modules
    changed = modules.reconcile(data)
    if changed:
        store.save(data)
    return modules.public_frontend(data)


@app.get("/api/modules")
async def module_catalog(request: Request) -> dict:
    require_role(request, "admin")
    store = store_from(request)
    data = store.load()
    modules: ModuleRegistry = request.app.state.modules
    changed = modules.reconcile(data)
    if changed:
        store.save(data)
    return {"items": modules.catalog(data)}


@app.post("/api/modules/{module_id}/install")
async def install_module(module_id: str, request: Request) -> dict:
    require_role(request, "admin")
    store = store_from(request)
    data = store.load()
    modules: ModuleRegistry = request.app.state.modules
    try:
        added = modules.install(data, module_id)
    except KeyError:
        raise HTTPException(404, "Module not found")
    store.save(data)
    return {"installed": added, "items": modules.catalog(data)}


@app.post("/api/modules/{module_id}/update")
async def update_module(module_id: str, request: Request) -> dict:
    require_role(request, "admin")
    store = store_from(request)
    data = store.load()
    modules: ModuleRegistry = request.app.state.modules
    try:
        modules.update(data, module_id)
    except KeyError:
        raise HTTPException(404, "Module not found")
    store.save(data)
    return {"items": modules.catalog(data)}


@app.put("/api/modules/{module_id}/policy")
async def update_module_policy(module_id: str, payload: ModulePolicyRequest, request: Request) -> dict:
    require_role(request, "admin")
    store = store_from(request)
    data = store.load()
    modules: ModuleRegistry = request.app.state.modules
    try:
        modules.set_auto_update(data, module_id, payload.auto_update)
    except KeyError:
        raise HTTPException(404, "Module not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    store.save(data)
    return {"items": modules.catalog(data)}


@app.delete("/api/modules/{module_id}", status_code=204)
async def uninstall_module(module_id: str, request: Request) -> None:
    require_role(request, "admin")
    store = store_from(request)
    data = store.load()
    modules: ModuleRegistry = request.app.state.modules
    try:
        modules.uninstall(data, module_id)
    except KeyError:
        raise HTTPException(404, "Module not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    store.save(data)
    await request.app.state.runtime.refresh(force=True)


@app.get("/api/dashboards/{identifier}")
async def get_dashboard(identifier: str, request: Request) -> dict:
    return dashboard_or_404(store_from(request), identifier)


@app.post("/api/dashboards", status_code=201)
async def create_dashboard(payload: Dashboard, request: Request) -> dict:
    require_role(request, "admin", "editor")
    store = store_from(request)
    data = store.load()
    if any(item["id"] == payload.id or item["slug"] == payload.slug for item in data["dashboards"]):
        raise HTTPException(409, "Dashboard ID and URL must be unique")
    dashboard = persist_livestream_secrets(data, payload.model_dump())
    request.app.state.modules.install_for_widget_types(data, {widget["type"] for widget in dashboard.get("widgets", [])})
    data["dashboards"].append(dashboard)
    store.save(data)
    return dashboard


@app.put("/api/dashboards/{identifier}")
async def update_dashboard(identifier: str, payload: Dashboard, request: Request) -> dict:
    require_role(request, "admin", "editor")
    store = store_from(request)
    data = store.load()
    index = next((i for i, item in enumerate(data["dashboards"]) if item["id"] == identifier or item["slug"] == identifier), None)
    if index is None:
        raise HTTPException(404, "Dashboard not found")
    if any(i != index and (item["id"] == payload.id or item["slug"] == payload.slug) for i, item in enumerate(data["dashboards"])):
        raise HTTPException(409, "Dashboard ID and URL must be unique")
    previous_id = str(data["dashboards"][index].get("id") or "")
    data["dashboards"][index] = persist_livestream_secrets(data, payload.model_dump(), previous_id)
    request.app.state.modules.install_for_widget_types(data, {widget["type"] for widget in data["dashboards"][index].get("widgets", [])})
    store.save(data)
    return data["dashboards"][index]


@app.delete("/api/dashboards/{identifier}", status_code=204)
async def delete_dashboard(identifier: str, request: Request) -> None:
    require_role(request, "admin")
    store = store_from(request)
    data = store.load()
    original = len(data["dashboards"])
    removed_ids = {str(item.get("id") or "") for item in data["dashboards"] if item.get("id") == identifier or item.get("slug") == identifier}
    data["dashboards"] = [item for item in data["dashboards"] if item["id"] != identifier and item["slug"] != identifier]
    if len(data["dashboards"]) == original:
        raise HTTPException(404, "Dashboard not found")
    if not data["dashboards"]:
        raise HTTPException(400, "ChurchBoard must have at least one dashboard")
    vault = data.setdefault("secrets", {}).setdefault("livestream", {})
    for key in list(vault):
        if any(key.startswith(f"{dashboard_id}:") for dashboard_id in removed_ids):
            vault.pop(key, None)
    store.save(data)


@app.get("/api/settings")
async def get_settings(request: Request) -> dict:
    require_role(request, "admin")
    settings = store_from(request).public_settings()
    intercom = request.app.state.runtime.intercom.status()
    if intercom.get("ready"):
        settings["intercom"]["server_status"] = "Hosted intercom server is ready"
    elif settings["intercom"].get("enabled"):
        settings["intercom"]["server_status"] = intercom.get("error") or "Hosted intercom server is starting…"
    return settings


@app.put("/api/settings")
async def update_settings(payload: SettingsUpdate, request: Request) -> dict:
    require_role(request, "admin")
    store = store_from(request)
    data = store.load()
    settings = payload.model_dump()
    server = settings.get("server") or {}
    try:
        port = int(server.get("port") or 8040)
    except (TypeError, ValueError):
        raise HTTPException(400, "Web server port must be a number")
    if not 1 <= port <= 65535:
        raise HTTPException(400, "Web server port must be between 1 and 65535")
    server["port"] = port
    try:
        producer_port = int(server.get("producer_port") or 80)
    except (TypeError, ValueError):
        raise HTTPException(400, "Producer workspace port must be a number")
    if not 1 <= producer_port <= 65535:
        raise HTTPException(400, "Producer workspace port must be between 1 and 65535")
    if server.get("producer_port_enabled", True) and producer_port == port:
        raise HTTPException(400, "The dashboard and producer workspace must use different ports")
    server["producer_port"] = producer_port
    if server.get("https_enabled") and not (str(server.get("ssl_certfile") or "").strip() and str(server.get("ssl_keyfile") or "").strip()):
        raise HTTPException(400, "Choose both a TLS certificate and private key to enable HTTPS")
    if server.get("https_enabled"):
        missing = [label for label, value in (("certificate", server.get("ssl_certfile")), ("private key", server.get("ssl_keyfile"))) if not Path(str(value)).expanduser().is_file()]
        if missing:
            raise HTTPException(400, f"The TLS {' and '.join(missing)} file could not be found")
    existing_secret = data["settings"].get("planning_center", {}).get("secret", "")
    if not settings.get("planning_center", {}).get("secret"):
        settings.setdefault("planning_center", {})["secret"] = existing_secret
    existing_restream = data["settings"].get("restream", {})
    for secret_name in ("client_secret", "access_token", "refresh_token"):
        if not settings.get("restream", {}).get(secret_name):
            settings.setdefault("restream", {})[secret_name] = existing_restream.get(secret_name, "")
    if not settings.get("obs", {}).get("password"):
        settings.setdefault("obs", {})["password"] = data["settings"].get("obs", {}).get("password", "")
    intercom = settings.setdefault("intercom", {})
    existing_intercom = data["settings"].get("intercom", {})
    if intercom.get("enabled"):
        intercom["api_key"] = str(existing_intercom.get("api_key") or f"churchboard-{secrets.token_hex(8)}")
        existing_intercom_secret = str(existing_intercom.get("api_secret") or "")
        intercom["api_secret"] = existing_intercom_secret if len(existing_intercom_secret) >= 32 else secrets.token_urlsafe(36)
    else:
        intercom["api_key"] = str(existing_intercom.get("api_key") or "")
        intercom["api_secret"] = str(existing_intercom.get("api_secret") or "")
    party_lines = []
    used_party_line_ids = set()
    for raw in intercom.get("party_lines") or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()[:80]
        identifier = re.sub(r"[^a-z0-9]+", "-", str(raw.get("id") or name).casefold()).strip("-")[:60]
        if not name or not identifier or identifier in used_party_line_ids:
            continue
        used_party_line_ids.add(identifier)
        party_lines.append({"id": identifier, "name": name})
        if len(party_lines) >= 12:
            break
    intercom["hosted"] = True
    intercom["url"] = ""
    intercom["party_lines"] = party_lines or [{"id": "production", "name": "Production"}]
    data["settings"] = settings
    store.save(data)
    await request.app.state.runtime.refresh(force=True)
    return store.public_settings()


@app.get("/api/auth/status")
async def auth_status(request: Request) -> dict:
    auth: AuthManager = request.app.state.auth
    data = store_from(request).load()
    passwordless = not bool(data.get("organization", {}).get("passwords_required", True))
    return {
        "enabled": auth.enabled(),
        "requires_setup": not bool(data.get("users")),
        "passwords_required": not passwordless,
        "users": [{"name": user.get("name"), "email": user.get("email")} for user in data.get("users", []) if user.get("active", True)] if passwordless else [],
        "user": auth.current_user(request),
    }


@app.post("/api/auth/bootstrap")
async def bootstrap_auth(payload: CredentialsRequest, request: Request, response: Response) -> dict:
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    return request.app.state.auth.bootstrap(payload.name, payload.email, payload.password, response, secure)


@app.post("/api/auth/login")
async def login_auth(payload: CredentialsRequest, request: Request, response: Response) -> dict:
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    return request.app.state.auth.login(payload.email, payload.password, response, secure)


@app.post("/api/auth/logout")
async def logout_auth(request: Request, response: Response) -> dict:
    request.app.state.auth.logout(request, response)
    return {"ok": True}


@app.get("/api/auth/me")
async def auth_me(request: Request) -> dict:
    return require_user(request)


@app.get("/api/users")
async def list_users(request: Request) -> dict:
    require_role(request, "admin")
    return {"items": [public_user(user) for user in store_from(request).load().get("users", [])]}


@app.post("/api/users", status_code=201)
async def create_user(payload: UserRequest, request: Request) -> dict:
    actor = require_role(request, "admin")
    if payload.role not in {"admin", "editor", "volunteer"}:
        raise HTTPException(400, "Choose Admin, Editor, or Volunteer")
    data = store_from(request).load()
    if data.get("organization", {}).get("passwords_required", True) and not payload.password:
        raise HTTPException(400, "Enter a password, or turn off password sign-in for the organization")
    if any(str(user.get("email") or "").casefold() == payload.email.strip().casefold() for user in data.get("users", [])):
        raise HTTPException(409, "A user with that email already exists")
    try:
        encoded = password_hash(payload.password)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    user = {"id": uuid4().hex, "name": payload.name.strip(), "email": payload.email.strip().lower(), "role": payload.role, "campus_ids": payload.campus_ids or ["main"], "planning_center_person_id": payload.planning_center_person_id.strip(), "active": True, "created_at": datetime.now(timezone.utc).isoformat(), "password_hash": encoded}
    data.setdefault("users", []).append(user)
    add_activity(data, actor, "created user", user["name"])
    store_from(request).save(data)
    return public_user(user)


@app.put("/api/users/{user_id}")
async def update_user(user_id: str, payload: UserRequest, request: Request) -> dict:
    actor = require_role(request, "admin")
    data = store_from(request).load()
    user = next((item for item in data.get("users", []) if item.get("id") == user_id), None)
    if not user:
        raise HTTPException(404, "User not found")
    if payload.role not in {"admin", "editor", "volunteer"}:
        raise HTTPException(400, "Choose Admin, Editor, or Volunteer")
    if data.get("organization", {}).get("passwords_required", True) and not (payload.password or user.get("password_hash")):
        raise HTTPException(400, "Enter a password, or turn off password sign-in for the organization")
    email = payload.email.strip().lower()
    if any(item.get("id") != user_id and str(item.get("email") or "").casefold() == email.casefold() for item in data.get("users", [])):
        raise HTTPException(409, "A user with that email already exists")
    if user.get("role") == "admin" and payload.role != "admin" and sum(1 for item in data.get("users", []) if item.get("role") == "admin" and item.get("active", True)) <= 1:
        raise HTTPException(400, "ChurchBoard must have at least one administrator")
    user.update({"name": payload.name.strip(), "email": email, "role": payload.role, "campus_ids": payload.campus_ids or ["main"], "planning_center_person_id": payload.planning_center_person_id.strip()})
    if payload.password:
        user["password_hash"] = password_hash(payload.password)
    add_activity(data, actor, "updated user", user.get("name") or email)
    store_from(request).save(data)
    return public_user(user)


@app.delete("/api/users/{user_id}", status_code=204)
async def delete_user(user_id: str, request: Request) -> None:
    actor = require_role(request, "admin")
    if actor.get("id") == user_id:
        raise HTTPException(400, "You cannot delete the account you are currently using")
    data = store_from(request).load()
    user = next((item for item in data.get("users", []) if item.get("id") == user_id), None)
    if not user:
        raise HTTPException(404, "User not found")
    if user.get("role") == "admin" and sum(1 for item in data.get("users", []) if item.get("role") == "admin" and item.get("active", True)) <= 1:
        raise HTTPException(400, "ChurchBoard must have at least one administrator")
    data["users"].remove(user)
    add_activity(data, actor, "deleted user", user.get("name") or user.get("email") or "User")
    store_from(request).save(data)


@app.put("/api/organization/auth")
async def update_organization_auth(payload: OrganizationAuthRequest, request: Request) -> dict:
    actor = require_role(request, "admin")
    data = store_from(request).load()
    data.setdefault("organization", {})["passwords_required"] = payload.passwords_required
    if payload.passwords_required and any(not user.get("password_hash") for user in data.get("users", [])):
        raise HTTPException(400, "Set passwords for every user before requiring passwords")
    add_activity(data, actor, "enabled passwords" if payload.passwords_required else "disabled passwords", "Organization sign-in")
    store_from(request).save(data)
    return {"passwords_required": payload.passwords_required}


@app.put("/api/auth/recover-admin")
async def recover_admin(payload: AdminRecoveryRequest, request: Request) -> dict:
    require_local_desktop(request)
    data = store_from(request).load()
    user = next((item for item in data.get("users", []) if item.get("role") == "admin" and str(item.get("email") or "").casefold() == payload.email.strip().casefold()), None)
    if not user:
        raise HTTPException(404, "No administrator has that email address")
    if not payload.password:
        raise HTTPException(400, "Enter a new password")
    user["password_hash"] = password_hash(payload.password)
    data.setdefault("organization", {})["passwords_required"] = True
    add_activity(data, {"id": "local-recovery", "name": "Local recovery"}, "reset administrator credentials", user.get("email") or "Administrator")
    store_from(request).save(data)
    return {"reset": True, "email": user.get("email")}


@app.get("/api/campuses")
async def list_campuses(request: Request) -> dict:
    require_user(request)
    return {"items": store_from(request).load().get("organization", {}).get("campuses", [])}


@app.post("/api/campuses", status_code=201)
async def create_campus(payload: CampusRequest, request: Request) -> dict:
    actor = require_role(request, "admin")
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "Enter a campus name")
    data = store_from(request).load()
    campus = {"id": re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") or uuid4().hex[:8], "name": name[:120]}
    if any(item.get("id") == campus["id"] for item in data.get("organization", {}).get("campuses", [])):
        raise HTTPException(409, "That campus already exists")
    data.setdefault("organization", {}).setdefault("campuses", []).append(campus)
    add_activity(data, actor, "created campus", campus["name"], campus["id"])
    store_from(request).save(data)
    return campus


@app.put("/api/campuses/{campus_id}")
async def update_campus(campus_id: str, payload: CampusRequest, request: Request) -> dict:
    actor = require_role(request, "admin")
    data = store_from(request).load()
    campus = next((item for item in data.get("organization", {}).get("campuses", []) if item.get("id") == campus_id), None)
    if not campus:
        raise HTTPException(404, "Campus not found")
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "Enter a campus name")
    campus["name"] = name[:120]
    add_activity(data, actor, "renamed campus", campus["name"], campus_id)
    store_from(request).save(data)
    return campus


@app.delete("/api/campuses/{campus_id}", status_code=204)
async def delete_campus(campus_id: str, request: Request) -> None:
    actor = require_role(request, "admin")
    data = store_from(request).load()
    campuses = data.get("organization", {}).get("campuses", [])
    campus = next((item for item in campuses if item.get("id") == campus_id), None)
    if not campus:
        raise HTTPException(404, "Campus not found")
    if len(campuses) <= 1:
        raise HTTPException(400, "ChurchBoard must have at least one campus")
    campuses.remove(campus)
    fallback = str(campuses[0]["id"])
    for user in data.get("users", []):
        user["campus_ids"] = [value for value in user.get("campus_ids", []) if value != campus_id] or [fallback]
    for collection in ("checklist_templates", "resources"):
        for item in data.get("producer", {}).get(collection, []):
            if item.get("campus_id") == campus_id:
                item["campus_id"] = fallback
    add_activity(data, actor, "deleted campus", campus.get("name") or campus_id, fallback)
    store_from(request).save(data)


@app.get("/api/producer/context")
async def get_producer_context(request: Request) -> dict:
    return producer_context(store_from(request), request.app.state.runtime.state, require_user(request))


@app.get("/api/producer/intercom")
async def get_intercom_configuration(request: Request) -> dict:
    require_user(request)
    settings = store_from(request).load()["settings"].get("intercom", {})
    status = request.app.state.runtime.intercom.status()
    return {
        "enabled": bool(settings.get("enabled")),
        "party_lines": settings.get("party_lines") or [{"id": "production", "name": "Production"}],
        "server": status,
    }


@app.post("/api/producer/intercom/token")
async def create_intercom_token(payload: ProducerPayload, request: Request) -> dict:
    user = require_user(request)
    settings = store_from(request).load()["settings"].get("intercom", {})
    if not settings.get("enabled"):
        raise HTTPException(409, "The intercom is not enabled")
    party_lines = settings.get("party_lines") or [{"id": "production", "name": "Production"}]
    party_line_id = str(payload.data.get("party_line_id") or "production")
    party_line = next((row for row in party_lines if str(row.get("id") or "") == party_line_id), None)
    if not party_line:
        raise HTTPException(404, "Party line not found")
    api_key, api_secret = str(settings.get("api_key") or ""), str(settings.get("api_secret") or "")
    status = request.app.state.runtime.intercom.status()
    if not (api_key and api_secret):
        raise HTTPException(409, "ChurchBoard has not generated the hosted intercom credentials")
    if not status.get("ready"):
        raise HTTPException(503, status.get("error") or "The hosted intercom server is still starting")
    scheme = "wss" if request.url.scheme == "https" else "ws"
    url = f"{scheme}://{request.headers.get('host') or request.url.netloc}"
    room = f"churchboard-{party_line_id}"
    token = livekit_access_token(
        api_key, api_secret, f"churchboard-{user['id']}-{uuid4().hex[:8]}", str(user.get("name") or "ChurchBoard user"),
        room, {"role": user.get("role"), "user_id": user.get("id"), "party_line_id": party_line_id},
    )
    return {"url": url, "token": token, "room": room, "party_line": party_line}


@app.get("/api/producer/planning-center-media/{media_id}/content")
async def view_planning_center_media(media_id: str, request: Request) -> Response:
    """Serve an authorized resource from ChurchBoard's local PCO mirror."""
    user = require_user(request)
    context = producer_context(store_from(request), request.app.state.runtime.state, user)
    visible_tag_ids = {str(rule.get("tag_id") or "") for rule in context.get("media_tag_rules") or []}
    resource = next((
        item
        for tag_id in visible_tag_ids
        for item in (context.get("tagged_resources") or {}).get(tag_id, [])
        if str(item.get("id") or "") == media_id
    ), None)
    if not resource:
        raise HTTPException(404, "Planning Center resource not found")
    cached = request.app.state.runtime.media_cache.file_for(media_id)
    if not cached:
        raise HTTPException(404, "This resource has not finished downloading to ChurchBoard")
    path, metadata = cached
    filename = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(str(metadata.get("display_name") or path.name)).name)[:160]
    return FileResponse(
        path,
        media_type=str(metadata.get("content_type") or resource.get("content_type") or "application/octet-stream"),
        filename=filename or "resource",
        content_disposition_type="inline",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@app.get("/api/producer/plans")
async def get_producer_plans(request: Request) -> dict:
    require_user(request)
    state = request.app.state.runtime.state
    return {
        "items": state.get("plans") or [],
        "service": state.get("service") or {},
        "manual_plan": store_from(request).load().get("settings", {}).get("manual_plan"),
        "planning_center": state.get("planning_center") or {},
    }


@app.get("/api/integrations/planning-center/media-tags")
async def planning_center_media_tags(request: Request) -> dict:
    require_role(request, "admin", "editor")
    client = PlanningCenterClient(store_from(request).load()["settings"].get("planning_center", {}))
    if not client.configured:
        raise HTTPException(400, "Connect Planning Center first")
    try:
        items = await client.media_tag_catalog()
    except Exception as exc:
        raise HTTPException(502, f"Could not load Planning Center Media tags: {exc}") from exc
    return {"items": items}


@app.put("/api/producer/media-tag-rules")
async def update_media_tag_rules(payload: MediaTagRulesRequest, request: Request) -> dict:
    actor = require_role(request, "admin", "editor")
    data = store_from(request).load()
    items = []
    for raw in payload.items[:200]:
        position_key, tag_id = str(raw.get("position_key") or "").strip(), str(raw.get("tag_id") or "").strip()
        if position_key and tag_id:
            items.append({"position_key": position_key[:200], "tag_id": tag_id[:80], "tag_label": str(raw.get("tag_label") or "")[:160]})
    data.setdefault("producer", {})["media_tag_rules"] = items
    add_activity(data, actor, "updated Planning Center resource tags", f"{len(items)} position mappings")
    store_from(request).save(data)
    await request.app.state.runtime.refresh(force=True)
    return {"items": items}


@app.post("/api/producer/templates", status_code=201)
async def create_checklist(payload: ProducerPayload, request: Request) -> dict:
    return save_template(store_from(request), payload.data, require_role(request, "admin", "editor"))


@app.put("/api/producer/templates/{template_id}")
async def update_checklist(template_id: str, payload: ProducerPayload, request: Request) -> dict:
    return save_template(store_from(request), payload.data, require_role(request, "admin", "editor"), template_id)


@app.delete("/api/producer/templates/{template_id}", status_code=204)
async def delete_checklist(template_id: str, request: Request) -> None:
    actor = require_role(request, "admin", "editor")
    data = store_from(request).load()
    rows = data.setdefault("producer", {}).setdefault("checklist_templates", [])
    existing = next((item for item in rows if item.get("id") == template_id), None)
    if not existing:
        raise HTTPException(404, "Checklist not found")
    rows.remove(existing)
    add_activity(data, actor, "deleted checklist", str(existing.get("title") or "Checklist"))
    store_from(request).save(data)


@app.post("/api/producer/resources", status_code=201)
async def create_position_resource(payload: ProducerPayload, request: Request) -> dict:
    return save_resource(store_from(request), payload.data, require_role(request, "admin", "editor"))


@app.put("/api/producer/resources/{resource_id}/content")
async def upload_position_resource(resource_id: str, request: Request, filename: str = "resource") -> dict:
    actor = require_role(request, "admin", "editor")
    content = await request.body()
    if not content or len(content) > 25 * 1024 * 1024:
        raise HTTPException(400, "Choose a file smaller than 25 MB")
    data = store_from(request).load()
    resource = next((item for item in data.get("producer", {}).get("resources", []) if item.get("id") == resource_id), None)
    if not resource:
        raise HTTPException(404, "Resource not found")
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(filename).name)[:160] or "resource"
    directory = store_from(request).path.parent / "resources"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{resource_id}-{safe_name}"
    path.write_bytes(content)
    resource.update({"filename": safe_name, "content_type": request.headers.get("content-type") or "application/octet-stream", "url": f"/api/producer/resources/{resource_id}/content"})
    add_activity(data, actor, "uploaded resource file", resource.get("title") or safe_name, resource.get("campus_id") or "main")
    store_from(request).save(data)
    return resource


@app.get("/api/producer/resources/{resource_id}/content")
async def download_position_resource(resource_id: str, request: Request) -> FileResponse:
    require_user(request)
    resource = next((item for item in store_from(request).load().get("producer", {}).get("resources", []) if item.get("id") == resource_id), None)
    if not resource or not resource.get("filename"):
        raise HTTPException(404, "Resource file not found")
    path = store_from(request).path.parent / "resources" / f"{resource_id}-{resource['filename']}"
    if not path.is_file():
        raise HTTPException(404, "Resource file not found")
    return FileResponse(path, media_type=resource.get("content_type") or None, filename=resource["filename"])


@app.put("/api/producer/completions")
async def update_completion(payload: ProducerPayload, request: Request) -> dict:
    return set_completion(store_from(request), payload.data, require_user(request))


@app.get("/api/layouts/export")
async def export_dashboards(request: Request) -> Response:
    require_role(request, "admin", "editor")
    content = {"format": "churchboard-layouts", "version": 1, "exported_at": datetime.now(timezone.utc).isoformat(), "items": store_from(request).load().get("dashboards", [])}
    return Response(json.dumps(content, indent=2), media_type="application/json", headers={"Content-Disposition": 'attachment; filename="churchboard-layouts.json"'})


@app.get("/api/layouts/{identifier}/export")
async def export_dashboard(identifier: str, request: Request) -> Response:
    require_role(request, "admin", "editor")
    content = {"format": "churchboard-layout", "version": 1, "exported_at": datetime.now(timezone.utc).isoformat(), "dashboard": dashboard_or_404(store_from(request), identifier)}
    return Response(json.dumps(content, indent=2), media_type="application/json", headers={"Content-Disposition": f'attachment; filename="churchboard-{identifier}.json"'})


@app.post("/api/layouts/import")
async def import_dashboards(request: Request) -> dict:
    require_role(request, "admin", "editor")
    payload = await request.json()
    incoming = payload.get("items") if payload.get("format") == "churchboard-layouts" else [payload.get("dashboard")]
    if not incoming or any(not isinstance(item, dict) for item in incoming):
        raise HTTPException(400, "This is not a ChurchBoard layout backup")
    data = store_from(request).load()
    imported = []
    for raw in incoming:
        candidate = Dashboard.model_validate(raw).model_dump()
        original_slug = candidate["slug"]
        number = 2
        while any(item.get("slug") == candidate["slug"] or item.get("id") == candidate["id"] for item in data["dashboards"]):
            candidate["slug"] = f"{original_slug}-{number}"
            candidate["id"] = candidate["slug"]
            number += 1
        if candidate["slug"] != original_slug:
            candidate["name"] = f"{candidate['name']} (imported)"
        request.app.state.modules.install_for_widget_types(data, {widget["type"] for widget in candidate.get("widgets", [])})
        data["dashboards"].append(candidate)
        imported.append(candidate)
    store_from(request).save(data)
    return {"items": imported, "count": len(imported)}


@app.get("/api/runtime")
async def get_runtime(request: Request, compact: bool = False) -> dict:
    state = deepcopy(request.app.state.runtime.state)
    if not compact:
        return state

    # ProPresenter is polled quickly, while the Planning Center plan, people,
    # photos, and media catalog change slowly and are cached by the display.
    timing = state.get("timing") or {}
    timing.pop("service_items", None)
    propresenter = state.get("propresenter") or {}
    propresenter.pop("playlist_presentations", None)
    propresenter.pop("slides", None)
    payload = {
        key: state.get(key)
        for key in (
            "updated_at",
            "timing",
            "mics",
            "propresenter",
            "planning_center_live",
            "service_control",
            "osm",
            "restream",
            "livestreams",
            "obs",
        )
    }
    payload["propresenter"] = propresenter
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    etag = f'"{sha256(encoded).hexdigest()}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return Response(encoded, media_type="application/json", headers={"ETag": etag})


@app.post("/api/integrations/osm/measurement", status_code=202)
async def ingest_osm_measurement(payload: OSMMeasurement, request: Request) -> dict:
    measurement = payload.model_dump(exclude_none=True)
    if not any(key in measurement for key in ("laeq", "lceq", "lzeq", "peak", "fast", "slow", "a_fast", "a_slow", "b_fast", "b_slow", "c_fast", "c_slow", "z_fast", "z_slow")):
        raise HTTPException(400, "Measurement does not contain an SPL level")
    runtime = request.app.state.runtime
    runtime.record_spl_measurement(measurement)
    runtime.state["osm"] = {"connected": True, "last_measurement_at": measurement.get("timestamp"), **measurement}
    return {"accepted": True}


@app.post("/api/integrations/osm/test")
async def test_osm_connection(request: Request) -> dict:
    settings = store_from(request).load()["settings"].get("open_sound_meter", {})
    if not settings.get("enabled"):
        raise HTTPException(400, "Enable Open Sound Meter monitoring and save settings first")
    osm = request.app.state.runtime.state.get("osm") or {}
    timestamp = str(osm.get("last_measurement_at") or "")
    try:
        age = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(timestamp.replace("Z", "+00:00"))).total_seconds())
    except ValueError:
        age = None
    if osm.get("connected") and age is not None and age <= 3:
        return {"connected": True, "age_seconds": round(age, 1), "message": f"Receiving OSM levels · A Fast {float(osm.get('a_fast', osm.get('laeq'))):.1f} dBA"}
    return {"connected": False, "message": "No recent valid OSM level packet. Confirm OSM Remote API Server and multicast network access."}


@app.get("/api/integrations/ndi/sources")
async def list_ndi_sources(request: Request) -> dict:
    require_role(request, "admin", "editor")
    runtime = request.app.state.runtime.ndi
    items = await asyncio.to_thread(runtime.sources, 650)
    return {"items": items, **runtime.status()}


@app.get("/api/integrations/ndi/snapshot")
async def ndi_snapshot(source: str, request: Request) -> Response:
    settings = store_from(request).load()["settings"].get("ndi", {})
    if not settings.get("enabled"):
        raise HTTPException(404, "NDI is not enabled")
    try:
        frame = await asyncio.to_thread(request.app.state.runtime.ndi.snapshot, source)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return Response(frame, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/reports/services")
async def list_spl_report_services(request: Request) -> dict:
    return {"items": request.app.state.runtime.spl_reports.services()}


@app.get("/api/reports/services/{service_id}/spl-averages.csv")
async def download_spl_averages(service_id: str, request: Request) -> PlainTextResponse:
    content = request.app.state.runtime.spl_reports.csv(service_id)
    return PlainTextResponse(content, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="churchboard-{service_id}-spl-averages.csv"'})


@app.get("/api/reports/services/{service_id}/spl-graph.html")
async def download_spl_graph(service_id: str, request: Request) -> Response:
    content = request.app.state.runtime.spl_reports.graph_html(service_id)
    return Response(content, media_type="text/html", headers={"Content-Disposition": f'attachment; filename="churchboard-{service_id}-spl-graph.html"'})


@app.get("/api/app-info")
async def get_app_info(request: Request) -> dict:
    return {
        "instance_id": request.app.state.instance_id,
        "version": request.app.version,
        "desktop_tray": bool(getattr(request.app.state, "desktop_tray", False)),
        "macos_launchservices": bool(getattr(request.app.state, "macos_launchservices", False)),
        "producer_portal": bool(getattr(request.state, "portal_only", False)),
    }


def require_local_desktop(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host == "testclient":
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise HTTPException(403, "Desktop controls are only available on the computer running ChurchBoard")


@app.get("/api/desktop/update")
async def check_desktop_update(request: Request) -> dict:
    require_local_desktop(request)
    result = await update_status()
    result.pop("_asset", None)
    return result


@app.post("/api/desktop/update")
async def install_desktop_update(request: Request) -> dict:
    require_local_desktop(request)
    return await download_update()


@app.post("/api/desktop/quit")
async def quit_desktop(request: Request) -> dict:
    require_local_desktop(request)
    callback = getattr(request.app.state, "desktop_quit", None)
    if not callback:
        raise HTTPException(409, "This ChurchBoard process is not running with a desktop icon")
    threading.Timer(0.3, callback).start()
    return {"stopping": True}


@app.get("/api/timezones")
async def list_timezones() -> dict:
    return {"items": sorted(available_timezones())}


@app.post("/api/runtime/refresh")
async def refresh_runtime(request: Request) -> dict:
    require_user(request)
    return await request.app.state.runtime.refresh(force=True)


@app.put("/api/active-plan")
async def select_active_plan(payload: ActivePlanRequest, request: Request) -> dict:
    require_role(request, "admin", "editor")
    store = store_from(request)
    data = store.load()
    data["settings"]["manual_plan"] = (
        {"id": payload.id, "service_type_id": payload.service_type_id}
        if payload.id and payload.service_type_id
        else None
    )
    data["settings"]["manual_service_time"] = None
    store.save(data)
    return await request.app.state.runtime.refresh(force=True)


@app.put("/api/active-service-time")
async def select_active_service_time(payload: ActiveServiceTimeRequest, request: Request) -> dict:
    require_role(request, "admin", "editor")
    store = store_from(request)
    data = store.load()
    active_plan_id = str((request.app.state.runtime.state.get("service") or {}).get("id") or "")
    if payload.id and str(payload.plan_id or active_plan_id) != active_plan_id:
        raise HTTPException(409, "That service time belongs to a different service")
    data["settings"]["manual_service_time"] = (
        {"id": str(payload.id), "plan_id": active_plan_id}
        if payload.id and active_plan_id
        else None
    )
    store.save(data)
    return await request.app.state.runtime.refresh(force=True)


@app.post("/api/service-control/{action}")
async def service_control(action: str, request: Request) -> dict:
    require_role(request, "admin", "editor")
    try:
        return await request.app.state.runtime.service_control(action)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/integrations/planning-center/test")
async def test_planning_center(request: Request) -> dict:
    settings = store_from(request).load()["settings"].get("planning_center", {})
    client = PlanningCenterClient(settings)
    if not client.configured:
        raise HTTPException(400, "Enable Planning Center and save both the Application ID and secret first")
    try:
        service_types = await client.service_types()
    except Exception as exc:
        raise HTTPException(502, f"Planning Center connection failed: {exc}") from exc
    return {"connected": True, "items": service_types, "count": len(service_types)}


@app.post("/api/integrations/restream/test")
async def test_restream(request: Request) -> dict:
    client = RestreamClient(store_from(request).load()["settings"].get("restream", {}))
    try:
        return await client.test_connection()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(exc.response.status_code, "Restream rejected the access token") from exc
    except Exception as exc:
        raise HTTPException(502, f"Restream connection failed: {exc}") from exc
    finally:
        await client.close()


RESTREAM_CALLBACK_PATH = "/api/integrations/restream/callback"


@app.get("/api/integrations/restream/connect")
async def connect_restream(request: Request) -> RedirectResponse:
    settings = store_from(request).load()["settings"].get("restream", {})
    if not settings.get("client_id") or not settings.get("client_secret"):
        raise HTTPException(400, "Save the Restream Client ID and Client Secret first")
    state = secrets.token_urlsafe(32)
    request.app.state.restream_oauth_state = state
    callback = str(request.base_url).rstrip("/") + RESTREAM_CALLBACK_PATH
    from urllib.parse import urlencode
    query = urlencode({"response_type": "code", "client_id": settings["client_id"], "redirect_uri": callback, "state": state})
    return RedirectResponse(f"https://api.restream.io/login?{query}")


@app.get(RESTREAM_CALLBACK_PATH)
async def restream_callback(request: Request, code: str = "", state: str = "") -> RedirectResponse:
    expected_state = getattr(request.app.state, "restream_oauth_state", "")
    request.app.state.restream_oauth_state = ""
    if not code:
        return RedirectResponse("/admin?restream=denied")
    if not expected_state or not secrets.compare_digest(state, expected_state):
        raise HTTPException(400, "Invalid Restream OAuth state; please try connecting again")
    store = store_from(request)
    data = store.load()
    restream = data["settings"].get("restream", {})
    client = RestreamClient(restream)
    try:
        token = await client.exchange_code(code, str(request.base_url).rstrip("/") + RESTREAM_CALLBACK_PATH)
    except Exception as exc:
        raise HTTPException(502, f"Restream authorization failed: {exc}") from exc
    finally:
        await client.close()
    restream.update({"enabled": True, "access_token": token.get("access_token") or token.get("accessToken") or "", "refresh_token": token.get("refresh_token") or token.get("refreshToken") or "", "access_token_expires_at": token.get("expires") or token.get("accessTokenExpiresEpoch") or 0})
    data["settings"]["restream"] = restream
    store.save(data)
    await request.app.state.runtime.refresh(force=True)
    return RedirectResponse("/admin?restream=connected")


@app.get("/api/integrations/planning-center/catalog")
async def planning_center_catalog(request: Request) -> dict:
    require_user(request)
    app_settings = store_from(request).load()["settings"]
    if app_settings.get("demo_mode"):
        teams = [
            {"id": "band", "name": "Band", "service_type_id": "demo", "service_type_name": "Sunday Worship", "positions": [
                {"id": "demo-1", "name": "Vox 1", "key": "band::vox 1"},
                {"id": "demo-2", "name": "Vox 2", "key": "band::vox 2"},
                {"id": "demo-3", "name": "Worship Leader", "key": "band::worship leader"},
            ]},
            {"id": "production", "name": "Production", "service_type_id": "demo", "service_type_name": "Sunday Worship", "positions": [
                {"id": "demo-4", "name": "Audio", "key": "production::audio"},
                {"id": "demo-5", "name": "Lighting", "key": "production::lighting"},
                {"id": "demo-6", "name": "ProPresenter", "key": "production::propresenter"},
            ]},
            {"id": "speaking", "name": "Speaking", "service_type_id": "demo", "service_type_name": "Sunday Worship", "positions": [
                {"id": "demo-7", "name": "Pastor", "key": "speaking::pastor"},
            ]},
        ]
        return {"items": teams, "count": 7, "demo": True}
    settings = app_settings.get("planning_center", {})
    client = PlanningCenterClient(settings)
    if not client.configured:
        raise HTTPException(400, "Connect Planning Center in Setup to load teams and positions")
    try:
        teams = await client.position_catalog()
    except Exception as exc:
        raise HTTPException(502, f"Could not load Planning Center positions: {exc}") from exc
    return {"items": teams, "count": sum(len(team["positions"]) for team in teams)}


@app.get("/api/integrations/planning-center/people")
async def planning_center_people(request: Request) -> dict:
    require_role(request, "admin")
    app_settings = store_from(request).load()["settings"]
    if app_settings.get("demo_mode"):
        people = [
            {"id": "1", "name": "Jordan Lee", "email": "jordan@example.test", "photo": "/static/demo-people/jordan-lee.jpg"},
            {"id": "2", "name": "Morgan Reed", "email": "morgan@example.test", "photo": "/static/demo-people/morgan-reed.jpg"},
            {"id": "3", "name": "Taylor Brooks", "email": "taylor@example.test", "photo": "/static/demo-people/taylor-brooks.jpg"},
        ]
        return {"items": people, "count": len(people), "demo": True}
    client = PlanningCenterClient(app_settings.get("planning_center", {}))
    if not client.configured:
        raise HTTPException(400, "Connect Planning Center in Setup to match users")
    try:
        people = await client.people_catalog()
    except Exception as exc:
        raise HTTPException(502, f"Could not load Planning Center people: {exc}") from exc
    return {"items": people, "count": len(people)}


@app.get("/api/integrations/propresenter/thumbnail/{presentation_uuid}/{index}")
async def propresenter_thumbnail(presentation_uuid: str, index: int, request: Request) -> Response:
    settings = store_from(request).load()["settings"].get("propresenter", {})
    client = ProPresenterClient(settings)
    if not client.configured:
        raise HTTPException(400, "ProPresenter is not connected")
    try:
        content, media_type = await client.thumbnail(presentation_uuid, index)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Could not load the ProPresenter slide image: {exc}") from exc
    return Response(content=content, media_type=media_type, headers={"Cache-Control": "private, max-age=15, stale-while-revalidate=30"})


def require_propresenter_widget_control(request: Request, dashboard_slug: str | None, widget_id: str | None) -> dict:
    data = store_from(request).load()
    dashboard = next(
        (item for item in data.get("dashboards", []) if str(item.get("slug") or "") == str(dashboard_slug or "")),
        None,
    )
    widget = next(
        (item for item in (dashboard or {}).get("widgets", []) if str(item.get("id") or "") == str(widget_id or "")),
        None,
    )
    if not widget or widget.get("type") not in {"playlist", "pp_controls"} or widget.get("settings", {}).get("allow_remote_trigger") is False:
        raise HTTPException(403, "Enable ProPresenter control in this widget's settings")
    return data["settings"].get("propresenter", {})


@app.post("/api/integrations/propresenter/active-slide")
async def propresenter_trigger_active_slide(payload: ProPresenterSlideTrigger, request: Request) -> dict:
    settings = require_propresenter_widget_control(request, payload.dashboard_slug, payload.widget_id)
    client = ProPresenterClient(settings)
    if not client.configured:
        raise HTTPException(400, "ProPresenter is not connected")
    try:
        if payload.playlist_index is not None:
            await client.trigger_playlist_slide(payload.playlist_index, payload.presentation_uuid, payload.index, payload.is_pco)
        elif payload.presentation_uuid:
            await client.trigger_presentation_slide(payload.presentation_uuid, payload.index)
        else:
            await client.trigger_active_slide(payload.index)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Could not trigger the ProPresenter slide: {exc}") from exc
    finally:
        await client.close()
    return {"ok": True, "index": payload.index + 1}


@app.post("/api/integrations/propresenter/navigate/{direction}")
async def propresenter_navigate(direction: str, request: Request, payload: ProPresenterNavigationRequest | None = None) -> dict:
    settings = require_propresenter_widget_control(request, payload.dashboard_slug if payload else None, payload.widget_id if payload else None)
    client = ProPresenterClient(settings)
    if not client.configured:
        raise HTTPException(400, "ProPresenter is not connected")
    try:
        await client.trigger_navigation(direction)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Could not move ProPresenter {direction}: {exc}") from exc
    finally:
        await client.close()
    return {"ok": True, "direction": direction}


@app.post("/api/integrations/propresenter/navigate-item/{direction}")
async def propresenter_navigate_item(direction: str, request: Request, payload: ProPresenterNavigationRequest | None = None) -> dict:
    settings = require_propresenter_widget_control(request, payload.dashboard_slug if payload else None, payload.widget_id if payload else None)
    if direction not in {"next", "previous"}:
        raise HTTPException(400, "Invalid ProPresenter item direction")
    presentation = request.app.state.runtime.state.get("propresenter") or {}
    rows = presentation.get("playlist_presentations") or []
    active_uuid = str(presentation.get("presentation_uuid") or "")
    active = next((row for row in rows if active_uuid and str(row.get("presentation_uuid") or "") == active_uuid), None)
    if not active:
        try:
            current_index = int(presentation.get("service_item_index"))
        except (TypeError, ValueError):
            raise HTTPException(409, "ProPresenter did not report the current playlist item")
    else:
        current_index = int(active.get("index") or 0)
    triggerable = [row for row in rows if row.get("triggerable") is not False]
    if direction == "next":
        target = next((row for row in triggerable if int(row.get("index", -1)) > current_index), None)
    else:
        target = next((row for row in reversed(triggerable) if int(row.get("index", -1)) < current_index), None)
    if not target:
        raise HTTPException(409, f"There is no {direction} triggerable ProPresenter item")
    target_index = int(target.get("index") or 0)
    client = ProPresenterClient(settings)
    try:
        await client.trigger_playlist_presentation(target_index, None if target.get("is_pco") else target.get("presentation_uuid"))
    except Exception as exc:
        raise HTTPException(502, f"Could not move to the {direction} ProPresenter item: {exc}") from exc
    finally:
        await client.close()
    return {"ok": True, "direction": direction, "index": target_index}


@app.get("/api/integrations/propresenter/playlist-diagnostics")
async def propresenter_playlist_diagnostics(request: Request) -> dict:
    settings = store_from(request).load()["settings"].get("propresenter", {})
    client = ProPresenterClient(settings)
    if not client.configured:
        raise HTTPException(400, "ProPresenter is not connected")
    try:
        return await client.playlist_diagnostics()
    except Exception as exc:
        raise HTTPException(502, f"Could not read the ProPresenter playlist diagnostics: {exc}") from exc
    finally:
        await client.close()


@app.post("/api/integrations/propresenter/active-playlist-item")
async def propresenter_trigger_active_playlist_item(payload: ProPresenterSlideTrigger, request: Request) -> dict:
    settings = require_propresenter_widget_control(request, payload.dashboard_slug, payload.widget_id)
    client = ProPresenterClient(settings)
    if not client.configured:
        raise HTTPException(400, "ProPresenter is not connected")
    try:
        await client.trigger_playlist_presentation(payload.index, None if payload.is_pco else payload.presentation_uuid)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Could not trigger the ProPresenter playlist item: {exc}") from exc
    finally:
        await client.close()
    return {"ok": True, "index": payload.index + 1}


def run() -> None:
    config = load_config()
    portal_server = None
    if config.producer_port_enabled and config.producer_port != config.port:
        portal_server = uvicorn.Server(uvicorn.Config(
            producer_portal_app,
            host=config.host,
            port=config.producer_port,
            reload=False,
            lifespan="off",
            ssl_certfile=str(config.ssl_certfile) if config.ssl_certfile else None,
            ssl_keyfile=str(config.ssl_keyfile) if config.ssl_keyfile else None,
        ))
        def start_portal_when_ready() -> None:
            for _ in range(200):
                if hasattr(app.state, "runtime"):
                    portal_server.run()
                    return
                threading.Event().wait(0.05)
        threading.Thread(target=start_portal_when_ready, name="ChurchBoard producer portal", daemon=True).start()
    try:
        uvicorn.run(app, host=config.host, port=config.port, reload=False, ssl_certfile=str(config.ssl_certfile) if config.ssl_certfile else None, ssl_keyfile=str(config.ssl_keyfile) if config.ssl_keyfile else None)
    finally:
        if portal_server is not None:
            portal_server.should_exit = True
