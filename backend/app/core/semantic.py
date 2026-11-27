"""SEMANTIC_MATCH (SPEC §8): embedding Gemini + cache + cosine; fallback trigram ký tự.

- Mọi văn bản được đưa về `norm_match` trước khi embed và trước khi tính khóa cache.
- Embed theo lô (≤ EMBED_BATCH câu/request) vì quota tính theo request.
- Vector luôn được chuẩn hóa L2, nên cosine = tích vô hướng.
- Khi API embedding lỗi: trả None / `degraded=True` để lớp gọi chuyển sang trigram (không im lặng).

Cache là Protocol: linh cài bản lưu DB (`embedding_cache`); ở đây có bản bộ nhớ (test, mặc định)
và bản file `.npz` (bench/calibrate, để không tốn quota khi chạy lại).
"""

from __future__ import annotations

import hashlib
import math
import os
from collections import Counter
from pathlib import Path
from typing import Protocol

import numpy as np

from app.core._contract_draft import EMBED_DIM, EMBED_MODEL, AnchorSet
from app.core.preprocess import norm_match

EMBED_BATCH = 100          # SPEC §8.2: 50–100 câu/request
EMBED_TIMEOUT_S = 15
MIN_NOTE_LEN = 4           # SPEC §8.4: nội dung ngắn hơn thì không khớp semantic


class EmbeddingError(RuntimeError):
    """API embedding lỗi (timeout, 429, 5xx, sai số chiều…)."""


# ============================================================ cache


def cache_key(text_norm: str, model: str = EMBED_MODEL, dim: int = EMBED_DIM) -> str:
    return hashlib.sha256(f"{model}|{dim}|{text_norm}".encode("utf-8")).hexdigest()


class EmbeddingCache(Protocol):
    def get_many(self, keys: list[str]) -> dict[str, np.ndarray]: ...
    def put_many(self, items: dict[str, np.ndarray]) -> None: ...


class InMemoryEmbeddingCache:
    def __init__(self) -> None:
        self._data: dict[str, np.ndarray] = {}

    def get_many(self, keys: list[str]) -> dict[str, np.ndarray]:
        return {k: self._data[k] for k in keys if k in self._data}

    def put_many(self, items: dict[str, np.ndarray]) -> None:
        self._data.update(items)

    def __len__(self) -> int:
        return len(self._data)


class NpzEmbeddingCache(InMemoryEmbeddingCache):
    """Cache lưu file cho script bench/calibrate. Ghi lại file sau mỗi lần put."""

    def __init__(self, path: str | Path) -> None:
        super().__init__()
        self.path = Path(path)
        if self.path.exists():
            with np.load(self.path) as z:
                keys = [str(k) for k in z["keys"]]
                self._data = dict(zip(keys, z["vectors"].astype(np.float32)))

    def put_many(self, items: dict[str, np.ndarray]) -> None:
        super().put_many(items)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        keys = list(self._data)
        vectors = np.stack([self._data[k] for k in keys]) if keys else np.zeros((0, EMBED_DIM), np.float32)
        tmp = self.path.with_name(self.path.stem + ".tmp.npz")   # np.savez tự thêm .npz nếu thiếu
        np.savez(tmp, keys=np.array(keys), vectors=vectors)
        os.replace(tmp, self.path)


# ============================================================ embedder


class Embedder(Protocol):
    async def embed_batch(self, texts: list[str]) -> np.ndarray: ...


def l2_normalize(m: np.ndarray) -> np.ndarray:
    m = np.asarray(m, dtype=np.float32)
    norms = np.linalg.norm(m, axis=-1, keepdims=True)
    return m / np.where(norms == 0, 1.0, norms)


class GeminiEmbedder:
    """gemini-embedding-001, task_type SEMANTIC_SIMILARITY, 768 chiều, chuẩn hóa L2."""

    def __init__(self, api_key: str | None = None, model: str = EMBED_MODEL, dim: int = EMBED_DIM,
                 batch_size: int = EMBED_BATCH, timeout_s: float = EMBED_TIMEOUT_S) -> None:
        from google import genai
        from google.genai import types

        self._types = types
        self._client = genai.Client(
            api_key=api_key or os.environ["GEMINI_API_KEY"],
            http_options=types.HttpOptions(timeout=int(timeout_s * 1000)),
        )
        self.model, self.dim, self.batch_size = model, dim, batch_size
        self.requests = 0

    async def embed_batch(self, texts: list[str]) -> np.ndarray:
        out: list[np.ndarray] = []
        cfg = self._types.EmbedContentConfig(task_type="SEMANTIC_SIMILARITY", output_dimensionality=self.dim)
        for i in range(0, len(texts), self.batch_size):
            chunk = texts[i : i + self.batch_size]
            try:
                self.requests += 1
                resp = await self._client.aio.models.embed_content(model=self.model, contents=chunk, config=cfg)
            except Exception as e:  # SDK ném nhiều loại lỗi (httpx, APIError…): gom về một loại
                raise EmbeddingError(f"{type(e).__name__}: {e}") from e
            vecs = [e.values for e in (resp.embeddings or [])]
            if len(vecs) != len(chunk) or any(v is None or len(v) != self.dim for v in vecs):
                raise EmbeddingError(f"embedding trả {len(vecs)} vector cho {len(chunk)} câu hoặc sai số chiều")
            out.append(np.asarray(vecs, dtype=np.float32))
        if not out:
            return np.zeros((0, self.dim), np.float32)
        return l2_normalize(np.concatenate(out))


# ============================================================ trigram (fallback, Python thuần)


def trigrams(text: str) -> Counter:
    t = f"  {norm_match(text)} "
    return Counter(t[i : i + 3] for i in range(len(t) - 2))


def trigram_cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb)


# ============================================================ matcher


def best_cosine(note_vec: np.ndarray, anchor_vecs: np.ndarray) -> tuple[float, int]:
    sims = anchor_vecs @ note_vec
    idx = int(np.argmax(sims))
    return float(sims[idx]), idx


def best_trigram(note_norm: str, phrases: list[str]) -> tuple[float, int]:
    tn = trigrams(note_norm)
    sims = [trigram_cosine(tn, trigrams(p)) for p in phrases]
    idx = max(range(len(sims)), key=sims.__getitem__)
    return sims[idx], idx


class SemanticMatcher:
    """Cài `SemanticMatcher` Protocol trong interfaces (SPEC/PLAN §4)."""

    def __init__(self, embedder: Embedder | None, cache: EmbeddingCache | None = None,
                 model: str = EMBED_MODEL, dim: int = EMBED_DIM) -> None:
        self.embedder = embedder
        self.cache = cache if cache is not None else InMemoryEmbeddingCache()
        self.model, self.dim = model, dim

    async def embed_texts(self, texts: list[str]) -> np.ndarray | None:
        """Embed (theo `norm_match`) với cache; chỉ gọi API cho phần còn thiếu, theo lô.

        Trả ma trận (len(texts), dim) cùng thứ tự; None nếu API lỗi hoặc không có embedder.
        """
        normed = [norm_match(t) for t in texts]
        keys = [cache_key(t, self.model, self.dim) for t in normed]
        found = self.cache.get_many(list(dict.fromkeys(keys)))
        empty_key = cache_key("", self.model, self.dim)
        if empty_key in keys:                      # chuỗi rỗng: vector 0 (cosine 0), không gửi API
            found[empty_key] = np.zeros(self.dim, np.float32)
        missing = list(dict.fromkeys(t for t, k in zip(normed, keys) if k not in found))
        if missing:
            if self.embedder is None:
                return None
            try:
                vecs = await self.embedder.embed_batch(missing)
            except EmbeddingError:
                return None
            new = {cache_key(t, self.model, self.dim): v for t, v in zip(missing, vecs)}
            self.cache.put_many(new)
            found.update(new)
        if not keys:
            return np.zeros((0, self.dim), np.float32)
        return np.stack([found[k] for k in keys]).astype(np.float32)

    async def prepare_anchors(self, anchors: list[str]) -> AnchorSet:
        phrases = list(dict.fromkeys(p for p in (norm_match(a) for a in anchors) if p))
        vectors = await self.embed_texts(phrases) if phrases else None
        return AnchorSet(phrases=phrases, vectors=vectors, degraded=vectors is None)

    async def note_vector(self, note_norm: str) -> np.ndarray | None:
        """Tối đa 1 lần embed cho mỗi giao dịch (có cache). None: nội dung quá ngắn hoặc API lỗi."""
        if len(norm_match(note_norm)) < MIN_NOTE_LEN:
            return None
        m = await self.embed_texts([note_norm])
        return None if m is None else m[0]

    async def score(self, note_norm: str, anchors: AnchorSet) -> float | None:
        """Cosine cao nhất với bộ anchor; None khi nội dung quá ngắn. Embedding lỗi → trigram."""
        note = norm_match(note_norm)
        if len(note) < MIN_NOTE_LEN or not anchors.phrases:
            return None
        vec = await self.note_vector(note) if anchors.vectors is not None else None
        if vec is None:
            return best_trigram(note, anchors.phrases)[0]
        return best_cosine(vec, anchors.vectors)[0]


# ============================================================ matcher mặc định của process

_default_matcher: SemanticMatcher | None = None


def init_matcher(cache: EmbeddingCache | None = None, embedder: Embedder | None = None) -> SemanticMatcher:
    """Gọi 1 lần lúc khởi động (linh truyền cache DB). Không có embedder → GeminiEmbedder từ env."""
    global _default_matcher
    if embedder is None and os.environ.get("GEMINI_API_KEY"):
        embedder = GeminiEmbedder()
    _default_matcher = SemanticMatcher(embedder, cache)
    return _default_matcher


def get_matcher() -> SemanticMatcher:
    return _default_matcher if _default_matcher is not None else init_matcher()
