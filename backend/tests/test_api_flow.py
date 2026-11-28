"""Golden end-to-end qua HTTP (SPEC §15): kịch bản demo ABOUT §7 + các bất biến phía API/gateway.

LLM mock (analyze trả HKD, compile gặp 429 → output thật đã lưu). Embedding: vector thật trong
embeddings_seed.npz, embedder không có (không gọi mạng). DB: SQLite tạm cho mỗi test.
"""

from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import config, db
from app.ai import llm_client
from app.ai.llm_client import LLMRateLimited
from app.core import gateway as core_gateway
from app.models import RuleEvent, Transaction
from tests._fixtures import HKD_ANALYSIS, FakeLLM

HUNG_TX = {"wallet_id": "W-HUNG", "to_account_id": "ACC-OLD-7731", "amount_vnd": 1_200_000,
           "transfer_note": "xac thuc ho so cap nhat thue HKD"}
LAN_CHAT = "Cán bộ thuế gọi bảo đóng 1,8 triệu phí xác minh hộ kinh doanh, không đóng sẽ khóa mã số thuế."
OTP_ANALYSIS = {**copy.deepcopy(HKD_ANALYSIS), "otp_or_password_disclosed": "YES"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(config, "JUDGE_ACCOUNTS", "judge_01:pw1,judge_02:pw2")
    db.set_engine(db.make_engine(f"sqlite:///{tmp_path / 't.db'}"))
    core_gateway.clear_anchor_cache()
    llm_client.set_llm(FakeLLM(HKD_ANALYSIS, LLMRateLimited("429"), OTP_ANALYSIS, OTP_ANALYSIS))
    from app.main import app

    with TestClient(app) as c:
        yield c
    llm_client.set_llm(None)
    core_gateway.clear_anchor_cache()


def login(c: TestClient, user: str = "judge_01", pw: str = "pw1") -> dict:
    r = c.post("/v1/auth/login", json={"username": user, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def balance(c, h, wallet_id):
    return next(w for w in c.get("/v1/wallets", headers=h).json()["wallets"] if w["id"] == wallet_id)


def tactic_option(c, h, rule_id, outcome="TACTIC_MATCH"):
    rule = c.get(f"/v1/fraudops/rules/{rule_id}", headers=h).json()["rule"]
    return next(o["id"] for o in rule["jit_purpose_question"]["options"] if o["outcome"] == outcome)


def build_live_rule(c, h) -> tuple[str, str]:
    """Cô Lan báo → compile → regression → sửa anchor rộng → regression sạch → approve ASK_ONLY."""
    inc = c.post("/v1/incidents/analyze", headers=h, json={
        "text": LAN_CHAT, "is_proxy": True, "protect_wallet_id": "W-LAN", "consent_handoff": True}).json()
    rule = c.post("/v1/fraudops/rules/compile", headers=h, json={"incident_id": inc["incident_id"]}).json()
    rid = rule["rule_id"]
    reg = c.post(f"/v1/fraudops/rules/{rid}/regression-test", headers=h).json()
    if reg["benign_flagged"] > 0:
        draft = rule["draft"]
        bad = set(reg["flags_by_anchor"])
        for cond in draft["conditions"]:
            if cond.get("anchor_phrases"):
                cond["anchor_phrases"] = [a for a in cond["anchor_phrases"]
                                          if not {a.lower(), _norm(a)} & bad]
        r = c.put(f"/v1/fraudops/rules/{rid}/draft", headers=h, json=draft)
        assert r.status_code == 200, r.text
        reg = c.post(f"/v1/fraudops/rules/{rid}/regression-test", headers=h).json()
    assert reg["benign_flagged"] == 0
    r = c.post(f"/v1/fraudops/rules/{rid}/approve", headers=h, json={"stage": "ASK_ONLY", "ttl_hours": 24})
    assert r.status_code == 200, r.text
    return inc["incident_id"], rid


def _norm(s):
    from app.core.preprocess import norm_match
    return norm_match(s)


# ---------------------------------------------------------------- kịch bản demo


def test_golden_demo_flow(client):
    c = client
    h = login(c)

    # 1) chú Hùng trước khi có luật → baseline và ScamRelay đều ALLOW
    r = c.post("/v1/gateway/evaluate-transfer", headers=h, json=HUNG_TX).json()
    assert r["status"] == "FINAL" and r["decision"] == "ALLOW" and r["baseline"]["as_final"] == "ALLOW"
    hung_balance = balance(c, h, "W-HUNG")["balance_vnd"]
    assert hung_balance == 8_000_000 - 1_200_000

    # 2) cô Lan (Tuấn kích hoạt hộ): MANIPULATION, tạm giữ bảo vệ ví, đồng ý chia sẻ
    inc = c.post("/v1/incidents/analyze", headers=h, json={
        "text": LAN_CHAT, "is_proxy": True, "protect_wallet_id": "W-LAN", "consent_handoff": True}).json()
    assert inc["mode"] == "MANIPULATION" and len(inc["actions"]) == 3
    assert inc["protective_hold"]["mode"] == "MANIPULATION"
    assert "balance" not in str(inc).lower()                                         # INV-11
    assert "Người thân đã yêu cầu" in balance(c, h, "W-LAN")["protective_hold_notice"]

    # 3) compile (LLM 429 → output thật đã lưu) → SHADOW_LOG
    rule = c.post("/v1/fraudops/rules/compile", headers=h, json={"incident_id": inc["incident_id"]}).json()
    assert rule["stage"] == "SHADOW_LOG" and rule["source"] == "CACHED_FALLBACK" and rule["degraded"]
    rid = rule["rule_id"]

    # 4) approve trước regression → REGRESSION_REQUIRED; regression bắt anchor rộng → APPROVE_LOCKED
    r = c.post(f"/v1/fraudops/rules/{rid}/approve", headers=h, json={"stage": "ASK_ONLY"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "REGRESSION_REQUIRED"
    reg = c.post(f"/v1/fraudops/rules/{rid}/regression-test", headers=h).json()
    assert reg["benign_checked"] >= 200 and reg["benign_flagged"] >= 1
    r = c.post(f"/v1/fraudops/rules/{rid}/approve", headers=h, json={"stage": "ASK_ONLY"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "APPROVE_LOCKED"            # INV-14

    # 5) chuyên viên xóa anchor gây khớp nhầm → version 2, regression cũ bị hủy
    draft = rule["draft"]
    bad = set(reg["flags_by_anchor"])
    draft["conditions"][0]["anchor_phrases"] = [a for a in draft["conditions"][0]["anchor_phrases"]
                                                if _norm(a) not in bad]
    edited = c.put(f"/v1/fraudops/rules/{rid}/draft", headers=h, json=draft).json()
    assert edited["version"] == 2 and edited["edited_by_human"] and edited["regression"] is None
    r = c.post(f"/v1/fraudops/rules/{rid}/approve", headers=h, json={"stage": "ASK_ONLY"})
    assert r.json()["error"]["code"] == "REGRESSION_REQUIRED"                                 # INV-14
    reg2 = c.post(f"/v1/fraudops/rules/{rid}/regression-test", headers=h).json()
    assert reg2["rule_version"] == 2 and reg2["benign_flagged"] == 0

    # 6) approve ASK_ONLY → đồng hồ 2 mốc
    ap = c.post(f"/v1/fraudops/rules/{rid}/approve", headers=h, json={"stage": "ASK_ONLY", "ttl_hours": 24}).json()
    assert ap["rule"]["stage"] == "ASK_ONLY"
    assert ap["clock"]["ai_seconds"] >= 0 and ap["clock"]["human_seconds"] >= 0
    # ENFORCE_HOLD bị khóa: chỉ 1 báo cáo (INV-16)
    r = c.post(f"/v1/fraudops/rules/{rid}/approve", headers=h, json={"stage": "ENFORCE_HOLD"})
    assert r.json()["error"]["code"] == "CORROBORATION_REQUIRED"

    # 7) chú Hùng sau khi có luật → bị hỏi; chọn TACTIC_MATCH → STOP_AND_EXPLAIN, 0đ rời ví
    r = c.post("/v1/gateway/evaluate-transfer", headers=h, json=HUNG_TX).json()
    assert r["status"] == "CHALLENGE_JIT" and r["decision"] is None and r["matched_rule_id"] == rid
    assert len(r["challenge"]["options"]) == 4
    assert all(set(o) == {"id", "label_vi"} for o in r["challenge"]["options"])               # INV-12
    assert r["challenge"]["anti_coaching_notice_vi"] == config.ANTI_COACHING_NOTICE_VI
    ch = r["challenge"]["challenge_id"]
    sub = c.post("/v1/gateway/submit-challenge", headers=h,
                 json={"challenge_id": ch, "option_id": tactic_option(c, h, rid)}).json()
    assert sub["decision"] == "STOP_AND_EXPLAIN" and sub["tactic_alert_vi"] and sub["retry_after"]
    assert balance(c, h, "W-HUNG")["balance_vnd"] == hung_balance
    # trả lời lại → bị từ chối (INV-08)
    r = c.post("/v1/gateway/submit-challenge", headers=h, json={"challenge_id": ch, "option_id": "o1"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "CHALLENGE_USED"

    # 8) giao dịch mua hàng sạch → ALLOW, không bị hỏi
    r = c.post("/v1/gateway/evaluate-transfer", headers=h, json={
        "wallet_id": "W-HUNG", "to_account_id": "ACC-SHOP", "amount_vnd": 450_000,
        "transfer_note": "tien hang phu tung"}).json()
    assert r["status"] == "FINAL" and r["decision"] == "ALLOW"

    # 9) ví cô Lan đang MANIPULATION: hóa đơn điện qua; người lạ bị giữ
    evn = {"wallet_id": "W-LAN", "to_account_id": "ACC-EVN", "amount_vnd": 400_000, "transfer_note": "tien dien thang 11"}
    assert c.post("/v1/gateway/evaluate-transfer", headers=h, json=evn).json()["decision"] == "ALLOW"
    r = c.post("/v1/gateway/evaluate-transfer", headers=h, json={
        "wallet_id": "W-LAN", "to_account_id": "ACC-NEW-01", "amount_vnd": 1_800_000, "transfer_note": "phi"}).json()
    assert r["decision"] == "HOLD_UNTIL_VERIFIED"

    # 10) "Mẹ lỡ đọc OTP" → COMPROMISE → hóa đơn điện cũng bị BLOCK
    f = c.post("/v1/incidents/analyze", headers=h, json={
        "incident_id": inc["incident_id"], "followup_text": "Mẹ lỡ đọc mã OTP cho họ rồi"}).json()
    assert f["mode"] == "COMPROMISE" and f["protective_hold"]["mode"] == "COMPROMISE"
    r = c.post("/v1/gateway/evaluate-transfer", headers=h, json=evn).json()
    assert r["decision"] == "BLOCK" and "CONTAINMENT_COMPROMISE" in r["reason_codes"]


def test_benign_answer_allows_with_warning(client):
    h = login(client)
    _, rid = build_live_rule(client, h)
    r = client.post("/v1/gateway/evaluate-transfer", headers=h, json=HUNG_TX).json()
    sub = client.post("/v1/gateway/submit-challenge", headers=h, json={
        "challenge_id": r["challenge"]["challenge_id"], "option_id": tactic_option(client, h, rid, "BENIGN")}).json()
    assert sub["decision"] == "ALLOW_WITH_WARNING" and sub["tactic_alert_vi"] is None
    assert config.ANTI_COACHING_NOTICE_VI in sub["message_vi"]


def test_unclear_answer_holds_and_fast_forward(client):
    h = login(client)
    _, rid = build_live_rule(client, h)
    r = client.post("/v1/gateway/evaluate-transfer", headers=h, json=HUNG_TX).json()
    sub = client.post("/v1/gateway/submit-challenge", headers=h, json={
        "challenge_id": r["challenge"]["challenge_id"], "option_id": tactic_option(client, h, rid, "UNCLEAR")}).json()
    assert sub["decision"] == "HOLD_15M"
    before = balance(client, h, "W-HUNG")["balance_vnd"]
    assert client.post("/v1/demo/fast-forward-holds", headers=h).json()["released"] == 1
    assert balance(client, h, "W-HUNG")["balance_vnd"] == before - HUNG_TX["amount_vnd"]


def test_rollback_then_pending_answer_uses_floor(client):
    h = login(client)
    _, rid = build_live_rule(client, h)
    r = client.post("/v1/gateway/evaluate-transfer", headers=h, json=HUNG_TX).json()
    opt = tactic_option(client, h, rid)
    assert client.post(f"/v1/fraudops/rules/{rid}/rollback", headers=h).json()["stage"] == "ROLLED_BACK"
    sub = client.post("/v1/gateway/submit-challenge", headers=h,
                      json={"challenge_id": r["challenge"]["challenge_id"], "option_id": opt}).json()
    assert sub["decision"] == "ALLOW" and "RULE_NO_LONGER_ACTIVE" in sub["reason_codes"]
    # sau rollback: không còn bị hỏi
    r = client.post("/v1/gateway/evaluate-transfer", headers=h, json=HUNG_TX).json()
    assert r["status"] == "FINAL"


def test_challenge_after_compromise_lock_blocked(client):
    """INV-08: mở hai tab — câu trả lời cũ không vượt được khóa mới."""
    h = login(client)
    inc_id, rid = build_live_rule(client, h)
    lan_tx = {**HUNG_TX, "wallet_id": "W-LAN"}
    r = client.post("/v1/gateway/evaluate-transfer", headers=h, json=lan_tx).json()
    # W-LAN đang MANIPULATION, người nhận lạ → mức sàn đã HOLD_UNTIL_VERIFIED, không cần hỏi
    assert r["status"] == "FINAL" and r["decision"] == "HOLD_UNTIL_VERIFIED"
    # ví chú Hùng: lấy challenge, rồi khoanh vùng COMPROMISE ví chú Hùng trước khi trả lời
    r = client.post("/v1/gateway/evaluate-transfer", headers=h, json=HUNG_TX).json()
    client.post("/v1/incidents/analyze", headers=h, json={
        "text": "Tôi lỡ đọc OTP cho người lạ", "protect_wallet_id": "W-HUNG"})
    sub = client.post("/v1/gateway/submit-challenge", headers=h, json={
        "challenge_id": r["challenge"]["challenge_id"], "option_id": tactic_option(client, h, rid, "BENIGN")}).json()
    assert sub["decision"] == "BLOCK"


def test_verified_biller_never_challenged(client):
    h = login(client)
    build_live_rule(client, h)
    r = client.post("/v1/gateway/evaluate-transfer", headers=h, json={
        **HUNG_TX, "to_account_id": "ACC-TAX-GOV"}).json()
    assert r["status"] == "FINAL" and r["decision"] == "ALLOW"                                   # INV-15


def test_workspace_isolation(client):
    h1 = login(client)
    _, rid = build_live_rule(client, h1)
    h2 = login(client, "judge_02", "pw2")
    assert client.get(f"/v1/fraudops/rules/{rid}", headers=h2).status_code == 404               # INV-09
    assert client.get("/v1/fraudops/incidents", headers=h2).json() == []
    r = client.post("/v1/gateway/evaluate-transfer", headers=h2, json=HUNG_TX).json()
    assert r["status"] == "FINAL"                                                               # luật của judge_01 không áp


def test_consent_required_and_auth(client):
    h = login(client)
    inc = client.post("/v1/incidents/analyze", headers=h, json={"text": LAN_CHAT}).json()
    assert inc["consent_handoff"] is False
    r = client.post("/v1/fraudops/rules/compile", headers=h, json={"incident_id": inc["incident_id"]})
    assert r.status_code == 403 and r.json()["error"]["code"] == "CONSENT_REQUIRED"
    assert client.get("/v1/fraudops/incidents", headers=h).json() == []
    # không đăng nhập
    assert client.get("/v1/fraudops/rules").status_code == 401
    assert client.post("/v1/auth/login", json={"username": "judge_01", "password": "sai"}).status_code == 401


def test_anonymous_session_has_no_wallets(client):
    r = client.get("/v1/wallets")
    assert r.status_code == 200 and r.json()["wallets"] == []
    r = client.post("/v1/gateway/evaluate-transfer", json=HUNG_TX)
    assert r.status_code == 404 and r.json()["error"]["code"] == "WALLET_NOT_FOUND"


def test_reset_restores_seed(client):
    h = login(client)
    client.post("/v1/gateway/evaluate-transfer", headers=h, json=HUNG_TX)
    assert balance(client, h, "W-HUNG")["balance_vnd"] < 8_000_000
    client.post("/v1/demo/reset", headers=h)
    assert balance(client, h, "W-HUNG")["balance_vnd"] == 8_000_000
    assert client.get("/v1/fraudops/rules", headers=h).json() == []


def test_healthz(client):
    r = client.get("/healthz").json()
    assert r["db"] is True and r["llm_model"] == config.LLM_MODEL


def test_healthz_reads_multi_key_env(client, monkeypatch):
    """PLAN H9: deploy có thể chỉ đặt GEMINI_API_KEYS (xoay vòng), không có GEMINI_API_KEY."""
    assert client.get("/healthz").json()["gemini_configured"] is False
    monkeypatch.setenv("GEMINI_API_KEYS", "fake-a,fake-b")
    assert client.get("/healthz").json()["gemini_configured"] is True


def test_feedback_false_positive(client):
    """Báo nhầm: ghi FP_REPORTED một lần/giao dịch, che PII, không đổi quyết định (SPEC §11, PLAN H7)."""
    c = client
    h = login(c)
    _, rid = build_live_rule(c, h)
    ev = c.post("/v1/gateway/evaluate-transfer", headers=h, json=HUNG_TX).json()
    assert ev["status"] == "CHALLENGE_JIT"
    sub = c.post("/v1/gateway/submit-challenge", headers=h, json={
        "challenge_id": ev["challenge"]["challenge_id"], "option_id": tactic_option(c, h, rid)}).json()

    body = {"tx_id": ev["tx_id"], "kind": "FALSE_POSITIVE", "note": "toi chuyen that, goi 0912345678"}
    r = c.post("/v1/gateway/feedback", headers=h, json=body)
    assert r.status_code == 200 and r.json()["recorded"] is True and r.json()["rule_id"] == rid
    assert c.post("/v1/gateway/feedback", headers=h, json=body).json()["recorded"] is False   # không đếm 2 lần
    assert c.get(f"/v1/fraudops/rules/{rid}/stats", headers=h).json()["fp_reports"] == 1

    with Session(db.get_engine()) as s:
        ev_row = s.exec(select(RuleEvent).where(RuleEvent.event == "FP_REPORTED")).one()
        tx = s.get(Transaction, ev["tx_id"])
    assert "0912345678" not in str(ev_row.payload)
    assert tx.decision == sub["decision"]                                                      # quyết định giữ nguyên

    # giao dịch không khớp luật / của workspace khác
    ok = c.post("/v1/gateway/evaluate-transfer", headers=h, json={
        "wallet_id": "W-LAN", "to_account_id": "ACC-TUAN", "amount_vnd": 100_000, "transfer_note": "an trua"}).json()
    assert c.post("/v1/gateway/feedback", headers=h, json={"tx_id": ok["tx_id"]}).json()["error"]["code"] == "NO_RULE_MATCHED"
    h2 = login(c, "judge_02", "pw2")
    assert c.post("/v1/gateway/feedback", headers=h2, json=body).status_code == 404
