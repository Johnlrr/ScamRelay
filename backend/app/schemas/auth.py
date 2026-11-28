"""Auth và tiện ích demo (SPEC §10, §11)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import Strict


class LoginRequest(Strict):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    workspace_id: str
    expires_at: datetime


class ResetResponse(BaseModel):
    workspace_id: str
    reset_at: datetime


class FastForwardResponse(BaseModel):
    released: int                                # số giao dịch HOLD_15M đã giải phóng


class HealthResponse(BaseModel):
    status: str                                  # "ok" | "degraded"
    db: bool
    gemini_configured: bool
    registry_unverified: list[str]
    llm_model: str
