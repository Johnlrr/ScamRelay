"""Lỗi API thống nhất: {"error": {"code", "message_vi", "details"}} (SPEC §11)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    def __init__(self, status: int, code: str, message_vi: str, details: list[Any] | None = None) -> None:
        super().__init__(code)
        self.status, self.code, self.message_vi, self.details = status, code, message_vi, details or []


def _body(code: str, message_vi: str, details: list[Any] | None = None) -> dict:
    return {"error": {"code": code, "message_vi": message_vi, "details": details or []}}


_HTTP_CODES = {400: "INVALID_REQUEST", 401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED",
               409: "CONFLICT", 429: "RATE_LIMITED"}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(_body(exc.code, exc.message_vi, exc.details), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"loc": list(e.get("loc", [])), "msg": e.get("msg", "")} for e in exc.errors()]
        return JSONResponse(_body("INVALID_REQUEST", "Dữ liệu gửi lên không hợp lệ.", details), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
        msg = "Dữ liệu gửi lên không đọc được (JSON hỏng)." if exc.status_code == 400 else (
            exc.detail if isinstance(exc.detail, str) else "Có lỗi xảy ra.")
        return JSONResponse(_body(code, msg), status_code=exc.status_code)
