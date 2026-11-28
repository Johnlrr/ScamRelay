"""Nhiều key Gemini (SPEC §14.6): xoay vòng, 429 thì chuyển key, mọi key 429 mới báo rate limit."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import BaseModel

from app.ai import llm_client
from app.ai.llm_client import KeyRing, LLMClient, LLMError, LLMRateLimited, gemini_api_keys
from app.core.semantic import EmbeddingError, GeminiEmbedder


class Err429(Exception):
    code = 429


class FakeGenai:
    """Giả `genai.Client`: `aio.models.generate_content` / `embed_content` theo kịch bản."""

    def __init__(self, name: str, behavior: str, log: list[str]) -> None:
        self.name, self.behavior, self.log = name, behavior, log
        self.aio = SimpleNamespace(models=self)

    async def _call(self):
        self.log.append(self.name)
        if self.behavior == "429":
            raise Err429("RESOURCE_EXHAUSTED")
        if self.behavior == "500":
            raise RuntimeError("server error")

    async def generate_content(self, **_):
        await self._call()
        return SimpleNamespace(text='{"ok": true}')

    async def embed_content(self, contents, **_):
        await self._call()
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[1.0] + [0.0] * 767) for _ in contents])


class Out(BaseModel):
    ok: bool


def llm(*behaviors: str) -> tuple[LLMClient, list[str]]:
    from google.genai import types

    log: list[str] = []
    c = LLMClient.__new__(LLMClient)
    c._types, c.model = types, "m"
    c._ring = KeyRing([FakeGenai(f"k{i}", b, log) for i, b in enumerate(behaviors)])
    return c, log


def embedder(*behaviors: str) -> tuple[GeminiEmbedder, list[str]]:
    from google.genai import types

    log: list[str] = []
    e = GeminiEmbedder.__new__(GeminiEmbedder)
    e._types, e.model, e.dim, e.batch_size, e.requests = types, "m", 768, 100, 0
    e._ring = KeyRing([FakeGenai(f"k{i}", b, log) for i, b in enumerate(behaviors)])
    return e, log


def test_keys_from_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEYS", " a, b ,a,, c ")
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    assert gemini_api_keys() == ["a", "b", "c"]
    monkeypatch.delenv("GEMINI_API_KEYS")
    assert gemini_api_keys() == ["x"]
    monkeypatch.delenv("GEMINI_API_KEY")
    assert gemini_api_keys() == []
    llm_client.set_llm(None)
    assert llm_client.get_llm() is None


def test_round_robin_spreads_calls():
    c, log = llm("ok", "ok", "ok")
    for _ in range(4):
        asyncio.run(c.generate_json("p", Out))
    assert log == ["k0", "k1", "k2", "k0"]


def test_429_moves_to_next_key_without_using_retry():
    c, log = llm("429", "ok")
    r = asyncio.run(c.generate_json("p", Out, retries=0))
    assert r.data == {"ok": True} and log == ["k0", "k1"]


def test_all_keys_429_raises_rate_limited():
    c, log = llm("429", "429")
    with pytest.raises(LLMRateLimited):
        asyncio.run(c.generate_json("p", Out, retries=1))
    assert log == ["k0", "k1"]


def test_other_errors_use_retries_on_same_key():
    c, log = llm("500", "ok")
    with pytest.raises(LLMError) as ei:
        asyncio.run(c.generate_json("p", Out, retries=1))
    assert not isinstance(ei.value, LLMRateLimited) and log == ["k0", "k0"]


def test_error_message_never_contains_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEYS", "SECRET-KEY-1,SECRET-KEY-2")
    c, _ = llm("429", "429")
    with pytest.raises(LLMRateLimited) as ei:
        asyncio.run(c.generate_json("p", Out))
    assert "SECRET" not in str(ei.value)


def test_embedder_fails_over_on_429_and_errors_otherwise():
    e, log = embedder("429", "ok")
    v = asyncio.run(e.embed_batch(["a", "b"]))
    assert v.shape == (2, 768) and np.allclose(v[:, 0], 1.0) and log == ["k0", "k1"]
    e, _ = embedder("429", "429")
    with pytest.raises(EmbeddingError):
        asyncio.run(e.embed_batch(["a"]))
    e, log = embedder("500", "ok")
    with pytest.raises(EmbeddingError):
        asyncio.run(e.embed_batch(["a"]))
    assert log == ["k0"]                                   # lỗi khác 429 → trigram, không đốt key khác
