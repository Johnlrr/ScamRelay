"""LLMClient (SPEC §3, §7.1.3, §7.2a): Gemini Flash, structured output, temperature 0, timeout, retry.

- `response_schema` là LLM schema phẳng (SPEC §6.0); kết quả trả về là `dict` thô — việc kiểm tra
  nghiệp vụ thuộc validator / domain schema, KHÔNG ở đây.
- 429 / hết quota → ném `LLMRateLimited` ngay (retry không giúp gì) để lớp gọi chuyển fallback.
- Lỗi khác (timeout, 5xx, JSON hỏng) → retry đúng `retries` lần rồi ném `LLMError`.
- LLM không có tool nào; client chỉ gọi tới generativelanguage.googleapis.com (INV-01, INV-02).
- Nhiều key (SPEC §10, §14.6, bao chốt 28/11): `GEMINI_API_KEYS="k1,k2,…"` (key của các project khác nhau;
  key cùng project không thêm quota). Mỗi lời gọi bắt đầu ở key kế tiếp (xoay vòng); key nào trả 429 thì
  thử key sau; mọi key đều 429 mới ném `LLMRateLimited`. Không có biến này thì dùng `GEMINI_API_KEY`.
  Không bao giờ in key ra log hay thông báo lỗi.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass

from pydantic import BaseModel

from app.config import LLM_MODEL


class LLMError(RuntimeError):
    pass


class LLMRateLimited(LLMError):
    pass


@dataclass
class LLMResponse:
    data: dict
    seconds: float
    model: str


def _is_rate_limit(e: Exception) -> bool:
    code = getattr(e, "code", None) or getattr(e, "status_code", None)
    return code == 429 or "RESOURCE_EXHAUSTED" in str(e)


def gemini_api_keys() -> list[str]:
    """Danh sách key từ env: `GEMINI_API_KEYS` (phân tách bằng dấu phẩy) hoặc `GEMINI_API_KEY`. Bỏ trùng."""
    raw = os.environ.get("GEMINI_API_KEYS") or os.environ.get("GEMINI_API_KEY") or ""
    return list(dict.fromkeys(k.strip() for k in raw.split(",") if k.strip()))


class KeyRing:
    """Xoay vòng nhiều client (mỗi key một client). Dùng chung cho LLM và embedding."""

    def __init__(self, clients: list) -> None:
        if not clients:
            raise ValueError("cần ít nhất 1 key Gemini")
        self.clients = clients
        self._next = 0

    def order(self) -> list:
        """Thứ tự thử cho một lời gọi: bắt đầu ở client kế tiếp, rồi vòng hết các client còn lại."""
        i = self._next
        self._next = (i + 1) % len(self.clients)
        return self.clients[i:] + self.clients[:i]


class LLMClient:
    def __init__(self, api_key: str | None = None, model: str = LLM_MODEL) -> None:
        from google import genai
        from google.genai import types

        self._types = types
        keys = [api_key] if api_key else gemini_api_keys()
        self._ring = KeyRing([genai.Client(api_key=k) for k in keys])
        self.model = model

    async def generate_json(
        self,
        prompt: str,
        schema: type[BaseModel],
        *,
        system: str | None = None,
        timeout_s: float = 25,
        retries: int = 1,
        image: bytes | None = None,
        image_mime: str = "image/jpeg",
    ) -> LLMResponse:
        t = self._types
        contents: list = [prompt]
        if image is not None:
            contents.append(t.Part.from_bytes(data=image, mime_type=image_mime))
        cfg = t.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_schema=schema,
            system_instruction=system,
        )
        start = time.perf_counter()
        last: Exception | None = None
        clients = self._ring.order()
        k = 0                                    # client đang dùng; 429 thì chuyển client, không tốn lượt retry
        attempts = 0
        while attempts <= retries:
            try:
                resp = await asyncio.wait_for(
                    clients[k].aio.models.generate_content(model=self.model, contents=contents, config=cfg),
                    timeout=timeout_s,
                )
                data = json.loads(resp.text or "")
                if not isinstance(data, dict):
                    raise LLMError("LLM không trả object JSON")
                return LLMResponse(data=data, seconds=time.perf_counter() - start, model=self.model)
            except Exception as e:  # noqa: BLE001 — SDK ném nhiều loại; phân loại bên dưới
                if _is_rate_limit(e):
                    k += 1
                    if k >= len(clients):
                        raise LLMRateLimited(f"429 trên cả {len(clients)} key: {type(e).__name__}") from e
                    continue
                last = e
                attempts += 1
        raise LLMError(f"{type(last).__name__}: {str(last)[:200]}") from last


_default: LLMClient | None = None


def get_llm() -> LLMClient | None:
    """Client mặc định của process; None nếu chưa có key nào (lớp gọi chuyển fallback)."""
    global _default
    if _default is None and gemini_api_keys():
        _default = LLMClient()
    return _default


def set_llm(client: LLMClient | None) -> None:
    """Cho test/bench thay client (mock)."""
    global _default
    _default = client
