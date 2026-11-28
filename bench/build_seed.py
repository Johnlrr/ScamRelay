"""Đóng gói embedding tính sẵn → backend/data/embeddings_seed.npz (nạp vào cache DB lúc khởi động).

    backend/.venv/bin/python bench/build_seed.py

Gồm: tập sạch, mọi transfer_note của ca dev (có câu demo của chú Hùng), anchor + biến thể của các luật
đã lưu trong fallback_tactics.json. Khóa = semantic.cache_key (model|dim|norm_match), nên server tra được
ngay mà không gọi API. Đổi EMBED_MODEL/EMBED_DIM hoặc bảng viết tắt → chạy lại script này.
"""

from __future__ import annotations

import asyncio
import json
import sys

import numpy as np

import _common

from app.config import EMBED_DIM, EMBED_MODEL
from app.core.preprocess import norm_match
from app.core.regression import load_benign_corpus
from app.core.semantic import GeminiEmbedder, NpzEmbeddingCache, SemanticMatcher, cache_key

OUT = _common.BACKEND / "data" / "embeddings_seed.npz"


def collect_texts() -> list[str]:
    texts = [s["transfer_note"] for s in load_benign_corpus()]
    for p in sorted((_common.BENCH / "cases" / "dev").glob("*.json")):
        texts += [t["transfer_note"] for t in json.loads(p.read_text(encoding="utf-8"))["transactions_B"]]
    tactics = json.loads((_common.BACKEND / "data" / "fallback_tactics.json").read_text(encoding="utf-8"))["tactics"]
    for spec in tactics.values():
        out = spec.get("compile_output") or {}
        for c in out.get("conditions", []):
            texts += c.get("anchor_phrases") or []
        texts += [v["transfer_note"] for v in out.get("variants", [])]
    normed = dict.fromkeys(n for n in (norm_match(t) for t in texts) if n)
    return list(normed)


async def main() -> int:
    _common.load_env()
    texts = collect_texts()
    matcher = SemanticMatcher(_common.PatientEmbedder(GeminiEmbedder()), NpzEmbeddingCache(_common.CACHE_PATH))
    vecs = await matcher.embed_texts(texts)
    if vecs is None:
        print("LỖI: không embed được")
        return 2
    keys = [cache_key(t, EMBED_MODEL, EMBED_DIM) for t in texts]
    np.savez_compressed(OUT, keys=np.array(keys), texts=np.array(texts), vectors=vecs.astype(np.float32),
                        meta=np.array([EMBED_MODEL, str(EMBED_DIM)]))
    print(f"ghi {OUT.relative_to(_common.ROOT)}: {len(texts)} vector, {OUT.stat().st_size // 1024} KB, "
          f"request mới: {matcher.embedder.requests}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
