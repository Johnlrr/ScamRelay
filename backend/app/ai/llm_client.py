"""LLMClient (SPEC §3, §7.1.3, §7.2a): Gemini Flash, structured output, temperature 0, timeout, retry.

- `response_schema` là LLM schema phẳng (SPEC §6.0); kết quả trả về là `dict` thô — việc kiểm tra
  nghiệp vụ thuộc validator / domain schema, KHÔNG ở đây.
- 429 / hết quota → ném `LLMRateLimited` ngay (retry không giúp gì) để lớp gọi chuyển fallback.
- Lỗi khác (timeout, 5xx, JSON hỏng) → retry đúng `retries` lần rồi ném `LLMError`.
- LLM không có tool nào; client chỉ gọi tới generativelanguage.googleapis.com (INV-01, INV-02).
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass

from pydantic import BaseModel

from app.core._contract_draft import LLM_MODEL


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


class LLMClient:
    def __init__(self, api_key: str | None = None, model: str = LLM_MODEL) -> None:
        from google import genai
        from google.genai import types

        self._types = types
        self._client = genai.Client(api_key=api_key or os.environ["GEMINI_API_KEY"])
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
        for _ in range(retries + 1):
            try:
                resp = await asyncio.wait_for(
                    self._client.aio.models.generate_content(model=self.model, contents=contents, config=cfg),
                    timeout=timeout_s,
                )
                data = json.loads(resp.text or "")
                if not isinstance(data, dict):
                    raise LLMError("LLM không trả object JSON")
                return LLMResponse(data=data, seconds=time.perf_counter() - start, model=self.model)
            except Exception as e:  # noqa: BLE001 — SDK ném nhiều loại; phân loại bên dưới
                if _is_rate_limit(e):
                    raise LLMRateLimited(f"429: {type(e).__name__}") from e
                last = e
        raise LLMError(f"{type(last).__name__}: {str(last)[:200]}") from last


_default: LLMClient | None = None


def get_llm() -> LLMClient | None:
    """Client mặc định của process; None nếu chưa có GEMINI_API_KEY (lớp gọi chuyển fallback)."""
    global _default
    if _default is None and os.environ.get("GEMINI_API_KEY"):
        _default = LLMClient()
    return _default


def set_llm(client: LLMClient | None) -> None:
    """Cho test/bench thay client (mock)."""
    global _default
    _default = client
