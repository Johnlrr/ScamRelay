import asyncio

import numpy as np
import pytest

from app.core import semantic
from app.core.semantic import (InMemoryEmbeddingCache, NpzEmbeddingCache, SemanticMatcher, cache_key,
                               trigram_cosine, trigrams)
from tests._fixtures import FakeEmbedder


def run(coro):
    return asyncio.run(coro)


def test_cache_key_depends_on_model_dim_and_normalized_text():
    assert cache_key("a", "m1", 768) != cache_key("a", "m2", 768) != cache_key("a", "m1", 3072)


def test_embed_texts_normalizes_dedupes_and_caches():
    emb = FakeEmbedder()
    m = SemanticMatcher(emb, InMemoryEmbeddingCache(), dim=emb.dim)
    out = run(m.embed_texts(["Phí HKD", "phi ho kinh doanh", "tien hang"]))
    assert out.shape == (3, 64)
    assert emb.calls == [["phi ho kinh doanh", "tien hang"]]          # "Phí HKD" == "phi ho kinh doanh" sau norm_match
    np.testing.assert_allclose(out[0], out[1])
    run(m.embed_texts(["tien hang", "PHÍ HKD"]))
    assert len(emb.calls) == 1                                       # toàn bộ đã có trong cache
    run(m.embed_texts(["tien hang", "moi"]))
    assert emb.calls[-1] == ["moi"]                                  # chỉ gọi phần còn thiếu


def test_vectors_are_l2_normalized():
    m = SemanticMatcher(FakeEmbedder(), dim=64)
    out = run(m.embed_texts(["dong phi xac minh", "tien an"]))
    np.testing.assert_allclose(np.linalg.norm(out, axis=1), 1.0, rtol=1e-5)


def test_embedding_failure_returns_none_and_anchor_set_degraded():
    m = SemanticMatcher(FakeEmbedder(fail=True), dim=64)
    assert run(m.embed_texts(["abc def"])) is None
    a = run(m.prepare_anchors(["dong phi xac minh", "Đóng phí xác minh", "cap nhat thue"]))
    assert a.phrases == ["dong phi xac minh", "cap nhat thue"] and a.vectors is None and a.degraded


def test_no_embedder_means_degraded():
    m = SemanticMatcher(None, dim=64)
    assert run(m.prepare_anchors(["dong phi xac minh"])).degraded


def test_note_vector_short_note_skips_api():
    emb = FakeEmbedder()
    m = SemanticMatcher(emb, dim=64)
    assert run(m.note_vector("ab")) is None and emb.calls == []
    assert run(m.note_vector("tien hang")).shape == (64,)


def test_score_uses_trigram_when_embedding_fails():
    ok = SemanticMatcher(FakeEmbedder(), dim=64)
    anchors = run(ok.prepare_anchors(["dong phi xac minh ho kinh doanh"]))
    broken = SemanticMatcher(FakeEmbedder(fail=True), dim=64)
    s = run(broken.score("dong phi xac minh hkd", anchors))
    assert s == pytest.approx(1.0)
    assert run(ok.score("ab", anchors)) is None


def test_embed_texts_dedupes_within_call():
    emb = FakeEmbedder()
    m = SemanticMatcher(emb, dim=64)
    texts = [f"cau so {i} khac nhau" for i in range(7)]
    run(m.embed_texts(texts + texts))
    assert emb.calls == [texts]


class _FakeModels:
    def __init__(self, dim, fail_at=None):
        self.dim, self.fail_at, self.sizes = dim, fail_at, []

    async def embed_content(self, model, contents, config):
        from types import SimpleNamespace

        self.sizes.append(len(contents))
        if self.fail_at is not None and len(self.sizes) == self.fail_at:
            raise RuntimeError("429 RESOURCE_EXHAUSTED")
        assert config.task_type == "SEMANTIC_SIMILARITY" and config.output_dimensionality == self.dim
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[1.0] + [0.0] * (self.dim - 1)) for _ in contents])


def _gemini(dim=8, batch=3, fail_at=None):
    from types import SimpleNamespace

    from app.core.semantic import GeminiEmbedder

    e = GeminiEmbedder(api_key="test-key-not-used", dim=dim, batch_size=batch)
    fake = _FakeModels(dim, fail_at)
    e._client = SimpleNamespace(aio=SimpleNamespace(models=fake))
    return e, fake


def test_gemini_embedder_batches_requests():
    e, fake = _gemini()
    out = run(e.embed_batch([f"t{i}" for i in range(7)]))
    assert fake.sizes == [3, 3, 1] and e.requests == 3 and out.shape == (7, 8)


def test_gemini_embedder_wraps_errors():
    from app.core.semantic import EmbeddingError

    e, _ = _gemini(fail_at=2)
    with pytest.raises(EmbeddingError):
        run(e.embed_batch([f"t{i}" for i in range(7)]))


def test_gemini_embedder_rejects_wrong_dim():
    from app.core.semantic import EmbeddingError

    e, fake = _gemini(dim=8)
    fake.dim = 4
    e.dim = 8

    async def bad(model, contents, config):
        from types import SimpleNamespace
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[1.0, 0.0]) for _ in contents])

    fake.embed_content = bad
    with pytest.raises(EmbeddingError):
        run(e.embed_batch(["a"]))


def test_npz_cache_roundtrip(tmp_path):
    p = tmp_path / "c" / "emb.npz"
    c = NpzEmbeddingCache(p)
    v = np.arange(4, dtype=np.float32)
    c.put_many({"k1": v})
    c2 = NpzEmbeddingCache(p)
    np.testing.assert_array_equal(c2.get_many(["k1", "k2"])["k1"], v)
    assert not list(p.parent.glob("*.tmp*"))


def test_trigram_cosine_basic():
    assert trigram_cosine(trigrams("dong phi"), trigrams("Đóng phí")) == pytest.approx(1.0)
    assert trigram_cosine(trigrams(""), trigrams("abc")) == 0.0


def test_init_matcher_without_key_has_no_embedder(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    m = semantic.init_matcher(cache=InMemoryEmbeddingCache())
    assert m.embedder is None and semantic.get_matcher() is m


def test_empty_text_not_sent_to_api():
    emb = FakeEmbedder()
    m = SemanticMatcher(emb, dim=64)
    out = run(m.embed_texts(["", "  !! ", "tien hang"]))
    assert emb.calls == [["tien hang"]]
    assert not out[0].any() and not out[1].any()
