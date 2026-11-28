"""Các nhánh degraded qua API (PLAN 30/11, bao): LLM lỗi, LLM 429, thủ đoạn mới khi LLM lỗi, embedding lỗi.

Yêu cầu chung (SPEC §7, INV-03): không trả 500, gắn `degraded`, không bao giờ kết luận "an toàn".
"""

from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from app import config, db
from app.ai import llm_client
from app.ai.incident_ai import load_fallback_tactics
from app.ai.llm_client import LLMError, LLMRateLimited
from app.core import gateway as core_gateway
from app.core.semantic import get_matcher
from tests._fixtures import HKD_ANALYSIS, FakeEmbedder, FakeLLM

NEW_TACTIC = {**copy.deepcopy(HKD_ANALYSIS), "tactic_family": "OTHER_NEW", "tactic_slug": "gia_trung_thuong_xe"}


def make_client(tmp_path, monkeypatch, *llm_responses) -> TestClient:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(config, "JUDGE_ACCOUNTS", "judge_01:pw1")
    db.set_engine(db.make_engine(f"sqlite:///{tmp_path / 't.db'}"))
    core_gateway.clear_anchor_cache()
    llm_client.set_llm(FakeLLM(*llm_responses))
    from app.main import app

    return TestClient(app)


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    llm_client.set_llm(None)
    core_gateway.clear_anchor_cache()


def login(c) -> dict:
    r = c.post("/v1/auth/login", json={"username": "judge_01", "password": "pw1"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.mark.parametrize("err", [LLMError("timeout"), LLMRateLimited("429")])
def test_analyze_llm_down_keyword_fallback(tmp_path, monkeypatch, err):
    cases = [
        ("Cán bộ thuế bảo đóng phí xác minh hộ kinh doanh không thì khóa mã số thuế", "MANIPULATION"),
        ("Tôi lỡ đọc mã OTP cho người tự xưng nhân viên hỗ trợ", "COMPROMISE"),
        ("Có tin nhắn lạ gửi tới", "UNCLEAR"),
    ]
    with make_client(tmp_path, monkeypatch, *[err] * len(cases)) as c:
        h = login(c)
        for text, mode in cases:
            r = c.post("/v1/incidents/analyze", headers=h, json={"text": text})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["degraded"] is True and body["mode"] == mode, (text, body["mode"])
            assert len(body["actions"]) == 3                              # INV-03: luôn có 3 việc an toàn
            a = body["analysis"]
            assert "NO" not in (a["otp_or_password_disclosed"], a["remote_app_installed"])


def test_compile_llm_down_uses_saved_real_output(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch, HKD_ANALYSIS, LLMError("503")) as c:
        h = login(c)
        inc = c.post("/v1/incidents/analyze", headers=h, json={"text": "phí xác minh hộ kinh doanh", "consent_handoff": True}).json()
        r = c.post("/v1/fraudops/rules/compile", headers=h, json={"incident_id": inc["incident_id"]})
        assert r.status_code == 200, r.text
        v = r.json()
        assert v["source"] == "CACHED_FALLBACK" and v["degraded"] is True and v["stage"] == "SHADOW_LOG"
        saved = load_fallback_tactics()["FAKE_HKD_TAX_VERIFICATION"]["compile_output"]
        assert v["rule"]["jit_purpose_question"]["question_vi"] == saved["purpose_question"]["question_vi"]


def test_compile_new_tactic_llm_down_returns_503_with_retry_hint(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch, NEW_TACTIC, LLMRateLimited("429")) as c:
        h = login(c)
        inc = c.post("/v1/incidents/analyze", headers=h, json={"text": "trúng thưởng xe máy, đóng phí nhận giải", "consent_handoff": True}).json()
        r = c.post("/v1/fraudops/rules/compile", headers=h, json={"incident_id": inc["incident_id"]})
        assert r.status_code == 503
        err = r.json()["error"]
        assert err["code"] == "COMPILE_UNAVAILABLE" and "Biên dịch lại" in err["message_vi"]


def test_embedding_down_falls_back_to_trigram(tmp_path, monkeypatch):
    """Anchor mới + API embedding lỗi: compile vẫn qua, regression gắn degraded, gateway không 500."""
    out = copy.deepcopy(load_fallback_tactics()["FAKE_HKD_TAX_VERIFICATION"]["compile_output"])
    sem = next(x for x in out["conditions"] if x["op"] == "SEMANTIC_MATCH")
    sem["anchor_phrases"] = sem["anchor_phrases"][:4] + ["phi tham dinh ho so ho kinh doanh dot moi"]
    with make_client(tmp_path, monkeypatch, HKD_ANALYSIS, out) as c:
        get_matcher().embedder = FakeEmbedder(fail=True)
        h = login(c)
        inc = c.post("/v1/incidents/analyze", headers=h, json={"text": "phí xác minh hộ kinh doanh", "consent_handoff": True}).json()
        r = c.post("/v1/fraudops/rules/compile", headers=h, json={"incident_id": inc["incident_id"]})
        assert r.status_code == 200, r.text
        rid = r.json()["rule_id"]
        reg = c.post(f"/v1/fraudops/rules/{rid}/regression-test", headers=h)
        assert reg.status_code == 200, reg.text
        assert reg.json()["degraded"] is True
        body = {"stage": "ASK_ONLY", "ttl_hours": 24}
        if reg.json()["benign_flagged"]:
            body["override_reason"] = "Test degraded: chấp nhận khớp nhầm trigram"
        assert c.post(f"/v1/fraudops/rules/{rid}/approve", headers=h, json=body).status_code == 200

        # nội dung gần như trùng anchor: trigram vẫn bắt được; nội dung khác hẳn thì không hỏi
        ev = c.post("/v1/gateway/evaluate-transfer", headers=h, json={
            "wallet_id": "W-HUNG", "to_account_id": "ACC-OLD-7731", "amount_vnd": 1_000_000,
            "transfer_note": "phi tham dinh ho so ho kinh doanh dot moi"})
        assert ev.status_code == 200, ev.text
        assert ev.json()["status"] == "CHALLENGE_JIT"
        ev = c.post("/v1/gateway/evaluate-transfer", headers=h, json={
            "wallet_id": "W-HUNG", "to_account_id": "ACC-SHOP", "amount_vnd": 300_000, "transfer_note": "tien hang thang 11"})
        assert ev.status_code == 200 and ev.json()["status"] == "FINAL"
