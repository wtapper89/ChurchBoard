from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, Request, Response

from app.store import ConfigStore


SESSION_COOKIE = "churchboard_session"
SESSION_SECONDS = 60 * 60 * 24 * 14
PASSWORD_ITERATIONS = 310_000


def password_hash(password: str) -> str:
    if not password:
        return ""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def password_matches(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt_text, digest_text = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode())
        expected = base64.urlsafe_b64decode(digest_text.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in user.items() if key != "password_hash"}


class AuthManager:
    def __init__(self, store: ConfigStore):
        self.store = store
        self.sessions: dict[str, tuple[str, float]] = {}

    def enabled(self) -> bool:
        data = self.store.load()
        return bool(data.get("organization", {}).get("auth_enabled") and data.get("users"))

    def current_user(self, request: Request) -> dict[str, Any] | None:
        token = request.cookies.get(SESSION_COOKIE, "")
        session = self.sessions.get(token)
        if not session:
            return None
        user_id, expires_at = session
        if expires_at <= time.time():
            self.sessions.pop(token, None)
            return None
        user = next((item for item in self.store.load().get("users", []) if item.get("id") == user_id and item.get("active", True)), None)
        return public_user(user) if user else None

    def bootstrap(self, name: str, email: str, password: str, response: Response, secure: bool = False) -> dict[str, Any]:
        data = self.store.load()
        if data.get("users"):
            raise HTTPException(409, "ChurchBoard already has an administrator")
        if not password:
            raise HTTPException(400, "Enter an owner password; you can enable passwordless sign-in afterward")
        try:
            encoded = password_hash(password)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        user = {
            "id": uuid4().hex,
            "name": name.strip(),
            "email": email.strip().lower(),
            "role": "admin",
            "campus_ids": ["main"],
            "planning_center_person_id": "",
            "active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "password_hash": encoded,
        }
        if not user["name"] or "@" not in user["email"]:
            raise HTTPException(400, "Enter a name and valid email address")
        data["users"] = [user]
        data.setdefault("organization", {})["auth_enabled"] = True
        self.store.save(data)
        self._start_session(user["id"], response, secure)
        return public_user(user)

    def login(self, email: str, password: str, response: Response, secure: bool = False) -> dict[str, Any]:
        data = self.store.load()
        user = next(
            (item for item in data.get("users", []) if str(item.get("email") or "").lower() == email.strip().lower()),
            None,
        )
        passwords_required = bool(data.get("organization", {}).get("passwords_required", True))
        invalid_password = passwords_required and not password_matches(password, str(user.get("password_hash") or "")) if user else True
        if not user or not user.get("active", True) or invalid_password:
            raise HTTPException(401, "Incorrect email or password")
        self._start_session(str(user["id"]), response, secure)
        return public_user(user)

    def logout(self, request: Request, response: Response) -> None:
        self.sessions.pop(request.cookies.get(SESSION_COOKIE, ""), None)
        response.delete_cookie(SESSION_COOKIE, path="/")

    def _start_session(self, user_id: str, response: Response, secure: bool = False) -> None:
        token = secrets.token_urlsafe(36)
        self.sessions[token] = (user_id, time.time() + SESSION_SECONDS)
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=SESSION_SECONDS,
            httponly=True,
            samesite="lax",
            secure=secure,
            path="/",
        )


def require_user(request: Request) -> dict[str, Any]:
    auth: AuthManager = request.app.state.auth
    if not auth.enabled():
        return {"id": "local-owner", "name": "Local administrator", "email": "", "role": "admin", "campus_ids": ["main"]}
    user = auth.current_user(request)
    if not user:
        raise HTTPException(401, "Sign in to continue")
    return user


def require_role(request: Request, *roles: str) -> dict[str, Any]:
    user = require_user(request)
    if user.get("role") not in roles:
        raise HTTPException(403, "You do not have permission to do that")
    return user
