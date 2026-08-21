from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, field_validator


class Widget(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    type: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_-]*$")
    x: int = Field(ge=0, le=23)
    y: int = Field(ge=0, le=100)
    w: int = Field(ge=1, le=24)
    h: int = Field(ge=1, le=20)
    title: str = Field(default="", max_length=100)
    settings: dict[str, Any] = Field(default_factory=dict)


class Dashboard(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=100)
    slug: str = Field(min_length=1, max_length=80)
    background_color: str = "#0a0d12"
    columns: int = Field(default=12, ge=4, le=24)
    row_height: int = Field(default=72, ge=40, le=160)
    widgets: list[Widget] = Field(default_factory=list, max_length=50)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
            raise ValueError("Use lowercase letters, numbers, and hyphens")
        return value

    @field_validator("background_color")
    @classmethod
    def validate_background_color(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"#[0-9a-f]{6}", value):
            raise ValueError("Choose a six-digit hexadecimal background color")
        return value


class SettingsUpdate(BaseModel):
    organization_name: str = Field(default="My Church", max_length=120)
    timezone: str = Field(default="America/New_York", max_length=100)
    demo_mode: bool = True
    planning_center: dict[str, Any] = Field(default_factory=dict)
    propresenter: dict[str, Any] = Field(default_factory=dict)
    mics: dict[str, Any] = Field(default_factory=dict)
    shure: dict[str, Any] = Field(default_factory=dict)
    sennheiser: dict[str, Any] = Field(default_factory=dict)
    open_sound_meter: dict[str, Any] = Field(default_factory=dict)
    prodmesh_rta: dict[str, Any] = Field(default_factory=dict)
    behringer: dict[str, Any] = Field(default_factory=dict)
    restream: dict[str, Any] = Field(default_factory=dict)
    obs: dict[str, Any] = Field(default_factory=dict)
    lighting: dict[str, Any] = Field(default_factory=dict)
    ndi: dict[str, Any] = Field(default_factory=dict)
    intercom: dict[str, Any] = Field(default_factory=dict)
    server: dict[str, Any] = Field(default_factory=dict)
    position_mic_map: dict[str, str] = Field(default_factory=dict)
    manual_plan: dict[str, str] | None = None
    manual_service_time: dict[str, str] | None = None
