"""Route /v1/fraudops/* khi phải GHI cache embedding mới (anchor, biến thể chưa có trong seed).

Lỗi gốc (28/11, phát hiện khi chạy run_bench trên server thật): route giữ transaction đọc của request
qua lời gọi LLM/embedding; DbEmbeddingCache.put_many mở kết nối khác để ghi → SQLite "database is locked"
→ 500. Test cũ không bắt được vì mọi anchor đã có trong embeddings_seed.npz (không có gì để ghi).
"""

from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from app import config, db
from app.ai import llm_client
from app.ai.incident_ai import load_fallback_tactics
from app.core import gateway as core_gateway
from app.core.semantic import get_matcher
from tests._fixtures import HKD_ANALYSIS, FakeEmbedder, FakeLLM

NEW_ANCHOR = "phi tham dinh ho so ho kinh doanh dot moi"
NEW_VARIANT = "le phi tham dinh hkd dot moi"
CHAT = "Cán bộ thuế gọi bảo đóng phí xác minh hộ kinh doanh, không đóng sẽ khóa mã số thuế."


class Embedder768(FakeEmbedder):
    dim = 768          # cùng số chiều với seed, để vector mới và vector seed dùng chung được


def compile_output_with_new_texts() -> dict:
    out = copy.deepcopy(load_fallback_tactics()["FAKE_HKD_TAX_VERIFICATION"]["compile_output"])
    sem = next(c for c in out["conditions"] if c["op"] == "SEMANTIC_MATCH")
    sem["anchor_phrases"] = sem["anchor_phrases"][:5] + [NEW_ANCHOR]
    out["variants"][0]["transfer_note"] = NEW_VARIANT
    return out


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(config, "JUDGE_ACCOUNTS", "judge_01:pw1")
    db.set_engine(db.make_engine(f"sqlite:///{tmp_path / 't.db'}"))   # file thật: có khóa như khi chạy server
    core_gateway.clear_anchor_cache()
    llm_client.set_llm(FakeLLM(HKD_ANALYSIS, compile_output_with_new_texts()))
    from app.main import app

    with TestClient(app) as c:
        get_matcher().embedder = Embedder768()
        yield c
    llm_client.set_llm(None)
    core_gateway.clear_anchor_cache()


def test_compile_regression_edit_write_new_embeddings(client):
    h = {"Authorization": "Bearer " + client.post("/v1/auth/login", json={"username": "judge_01", "password": "pw1"})
         .json()["access_token"]}
    inc = client.post("/v1/incidents/analyze", headers=h, json={"text": CHAT, "consent_handoff": True}).json()

    r = client.post("/v1/fraudops/rules/compile", headers=h, json={"incident_id": inc["incident_id"]})
    assert r.status_code == 200, r.text
    view = r.json()
    assert view["stage"] == "SHADOW_LOG" and view["source"] == "LLM"
    emb = get_matcher().embedder
    assert any(NEW_ANCHOR in batch for batch in emb.calls)              # thật sự đã phải embed và ghi cache

    r = client.post(f"/v1/fraudops/rules/{view['rule_id']}/regression-test", headers=h)
    assert r.status_code == 200, r.text
    assert any(any("tham dinh hkd" in x or "tham dinh ho kinh doanh dot moi" in x for x in b) for b in emb.calls)

    draft = view["draft"]
    sem = next(c for c in draft["conditions"] if c["op"] == "SEMANTIC_MATCH")
    sem["anchor_phrases"] = sem["anchor_phrases"] + ["phi tham dinh ho so thue dot hai"]
    r = client.put(f"/v1/fraudops/rules/{view['rule_id']}/draft", headers=h, json=draft)
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 2

    # vector mới đã nằm trong cache DB: lượt sau không gọi embedder nữa
    n = len(emb.calls)
    r = client.post(f"/v1/fraudops/rules/{view['rule_id']}/regression-test", headers=h)
    assert r.status_code == 200, r.text
    assert len(emb.calls) == n
