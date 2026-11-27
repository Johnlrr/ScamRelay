"""Tiện ích chung cho script trong bench/: đưa backend vào sys.path, nạp backend/.env, cache embedding file."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
BENCH = ROOT / "bench"
CACHE_PATH = BENCH / ".cache" / "embeddings.npz"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def load_env() -> None:
    """Nạp GEMINI_API_KEY… từ backend/.env (không in giá trị)."""
    from dotenv import load_dotenv

    load_dotenv(BACKEND / ".env")


class PatientEmbedder:
    """Bọc GeminiEmbedder cho script bench: gặp 429/lỗi tạm thời thì chờ rồi thử lại (không dùng ở server)."""

    def __init__(self, inner, retries: int = 6, wait_s: float = 65):
        self.inner, self.retries, self.wait_s = inner, retries, wait_s

    @property
    def requests(self) -> int:
        return self.inner.requests

    async def embed_batch(self, texts):
        import asyncio

        from app.core.semantic import EmbeddingError

        for attempt in range(self.retries + 1):
            try:
                return await self.inner.embed_batch(texts)
            except EmbeddingError as e:
                if attempt == self.retries:
                    raise
                print(f"  embedding lỗi ({str(e)[:80]}), chờ {self.wait_s:.0f}s rồi thử lại…", flush=True)
                await asyncio.sleep(self.wait_s)
