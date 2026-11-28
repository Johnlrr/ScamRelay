"""Kiểu dùng chung cho domain schema (SPEC §6.0) và định dạng lỗi thống nhất (SPEC §11)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class Strict(BaseModel):
    """Domain schema: không nhận trường lạ."""

    model_config = ConfigDict(extra="forbid")


class ErrorDetail(BaseModel):
    code: str                       # ví dụ APPROVE_LOCKED, REGRESSION_REQUIRED, CONSENT_REQUIRED
    message_vi: str
    details: list[Any] = []


class ErrorResponse(BaseModel):
    error: ErrorDetail
