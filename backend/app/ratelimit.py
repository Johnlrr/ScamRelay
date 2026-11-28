"""Rate limit cho các endpoint gọi LLM (SPEC §10): 10 lần/phút/phiên và 200 lần/ngày/IP.

ASGI middleware thuần, không cần decorator trên route. Bộ đếm `limits` (thư viện lõi của slowapi) lưu trong bộ
nhớ của process: Cloud Run chạy 1 worker; nhiều instance thì mỗi instance đếm riêng (chấp nhận cho demo —
lớp bảo vệ quota thật là giới hạn chi tiêu Gemini, SPEC §10).

- Phiên = tài khoản JWT nếu token hợp lệ; không thì cookie `sr_session`; không có cookie thì theo IP.
- Bị chặn → 429 `RATE_LIMITED` đúng định dạng lỗi SPEC §11, kèm header `Retry-After` (giây).
- Bộ đếm được xóa khi app khởi động (sự kiện lifespan), nên mỗi test có bộ đếm mới.
"""

from __future__ import annotations

import json
import math
import os
import time

from limits import parse
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

LIMITED_PATHS = frozenset({"/v1/incidents/analyze", "/v1/fraudops/rules/compile"})
SESSION_LIMIT = parse(os.environ.get("RATE_LIMIT_SESSION", "10/minute"))
IP_LIMIT = parse(os.environ.get("RATE_LIMIT_IP", "200/day"))
ENABLED = os.environ.get("RATE_LIMIT_ENABLED", "1") != "0"
SESSION_COOKIE = "sr_session"


def _session_key(request: Request, ip: str) -> str:
    from app.routers.deps import _username_from_request

    try:
        user = _username_from_request(request)
    except Exception:  # noqa: BLE001  token hỏng: route sẽ trả 401; ở đây đếm theo IP
        user = None
    if user:
        return f"user:{user}"
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie and len(cookie) <= 64:
        return f"cookie:{cookie}"
    return f"ip:{ip}"


class LlmRateLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.reset()

    def reset(self) -> None:
        self.limiter = MovingWindowRateLimiter(MemoryStorage())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            self.reset()
        elif (ENABLED and scope["type"] == "http" and scope["method"] == "POST"
              and scope["path"] in LIMITED_PATHS):
            request = Request(scope)
            ip = request.client.host if request.client else "unknown"
            checks = [(SESSION_LIMIT, "session", _session_key(request, ip)), (IP_LIMIT, "ip", f"ip:{ip}")]
            for limit, kind, key in checks:
                if not self.limiter.test(limit, kind, key):
                    await self._reject(send, limit, kind, key)
                    return
            for limit, kind, key in checks:
                self.limiter.hit(limit, kind, key)
        await self.app(scope, receive, send)

    async def _reject(self, send: Send, limit, kind: str, key: str) -> None:  # noqa: ANN001
        reset_at = self.limiter.get_window_stats(limit, kind, key).reset_time
        retry = max(1, math.ceil(reset_at - time.time()))
        msg = (f"Bạn thao tác quá nhanh. Vui lòng thử lại sau {retry} giây." if kind == "session"
               else "Địa chỉ mạng này đã dùng hết lượt phân tích hôm nay. Vui lòng thử lại vào ngày mai.")
        body = json.dumps({"error": {"code": "RATE_LIMITED", "message_vi": msg, "details": []}},
                          ensure_ascii=False).encode()
        await send({"type": "http.response.start", "status": 429,
                    "headers": [(b"content-type", b"application/json; charset=utf-8"),
                                (b"retry-after", str(retry).encode()),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
