"""Bất biến phía API do bao viết test (PLAN P9): INV-01, INV-04, INV-10, INV-13 (SPEC §10).

Chạy qua HTTP với TestClient; LLM giả, embedding lấy từ embeddings_seed.npz (không gọi mạng).
"""

from __future__ import annotations

import ast
import copy
import json
import re
import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, db
from app.ai import llm_client
from app.ai.llm_client import LLMRateLimited
from app.core import gateway as core_gateway
from app.core.stage_policy import SEVERITY
from tests._fixtures import HKD_ANALYSIS, FakeLLM

APP_DIR = Path(__file__).resolve().parents[1] / "app"
HUNG_NOTE = "xac thuc ho so cap nhat thue HKD"
LAN_CHAT = "Cán bộ thuế gọi bảo đóng phí xác minh hộ kinh doanh, không đóng sẽ khóa mã số thuế."
OTP_ANALYSIS = {**copy.deepcopy(HKD_ANALYSIS), "otp_or_password_disclosed": "YES"}
UNCLEAR_ANALYSIS = {**copy.deepcopy(HKD_ANALYSIS), "tactic_family": "OTHER_NEW", "tactic_slug": "khac",
                    "money_requested_vnd": None, "manipulation_cues": [], "otp_or_password_disclosed": "UNKNOWN",
                    "remote_app_installed": "UNKNOWN"}


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


def live_rule(c, h) -> str:
    """Cô Lan báo → compile (LLM 429 → output thật đã lưu) → regression → approve ASK_ONLY (ghi đè nếu cần)."""
    inc = c.post("/v1/incidents/analyze", headers=h, json={"text": LAN_CHAT, "consent_handoff": True}).json()
    rid = c.post("/v1/fraudops/rules/compile", headers=h, json={"incident_id": inc["incident_id"]}).json()["rule_id"]
    reg = c.post(f"/v1/fraudops/rules/{rid}/regression-test", headers=h).json()
    body = {"stage": "ASK_ONLY", "ttl_hours": 24}
    if reg["benign_flagged"]:
        body["override_reason"] = "Test bất biến: chấp nhận khớp nhầm đã biết"
    r = c.post(f"/v1/fraudops/rules/{rid}/approve", headers=h, json=body)
    assert r.status_code == 200, r.text
    return rid


def option_id(c, h, rid, outcome) -> str:
    rule = c.get(f"/v1/fraudops/rules/{rid}", headers=h).json()["rule"]
    return next(o["id"] for o in rule["jit_purpose_question"]["options"] if o["outcome"] == outcome)


def all_strings(obj) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in all_strings(v)]
    if isinstance(obj, list):
        return [s for v in obj for s in all_strings(v)]
    return []


# ------------------------------------------------------------------ INV-01


NETWORK_MODULES = {"httpx", "requests", "urllib", "urllib3", "aiohttp", "http", "socket", "websockets", "smtplib"}


def test_outbound_allowlist_static():
    """Code của app không tự mở kết nối mạng; chỉ SDK Gemini (google.genai) được gọi ra ngoài."""
    offenders = []
    for f in APP_DIR.rglob("*.py"):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            mods = ([a.name for a in node.names] if isinstance(node, ast.Import)
                    else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            offenders += [f"{f.relative_to(APP_DIR)}: {m}" for m in mods if m.split(".")[0] in NETWORK_MODULES]
    assert not offenders, offenders
    genai_users = sorted(str(f.relative_to(APP_DIR)) for f in APP_DIR.rglob("*.py")
                         if re.search(r"^\s*(from google import genai|import google\.genai|from google\.genai)",
                                      f.read_text(encoding="utf-8"), re.M))
    assert genai_users == ["ai/llm_client.py", "core/semantic.py"], genai_users


def test_outbound_allowlist_runtime(tmp_path, monkeypatch):
    """Cả vòng demo (báo → luật → chặn) chạy xong mà không mở socket nào (LLM mock, embedding từ seed)."""
    attempts = []

    def deny(*a, **k):
        attempts.append(a[:2])
        raise OSError("INV-01: kết nối mạng bị cấm trong test")

    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)
    with make_client(tmp_path, monkeypatch, HKD_ANALYSIS, LLMRateLimited("429")) as c:
        h = login(c)
        rid = live_rule(c, h)
        ev = c.post("/v1/gateway/evaluate-transfer", headers=h, json={
            "wallet_id": "W-HUNG", "to_account_id": "ACC-OLD-7731", "amount_vnd": 1_200_000,
            "transfer_note": HUNG_NOTE}).json()
        assert ev["status"] == "CHALLENGE_JIT"
        sub = c.post("/v1/gateway/submit-challenge", headers=h, json={
            "challenge_id": ev["challenge"]["challenge_id"], "option_id": option_id(c, h, rid, "TACTIC_MATCH")})
        assert sub.json()["decision"] == "STOP_AND_EXPLAIN"
    assert attempts == []


# ------------------------------------------------------------------ INV-04

CLAIMS_EXTERNAL_DONE = re.compile(
    r"(đã|vừa)\s+(được\s+)?(khóa|phong tỏa|chặn|đóng băng|xác nhận)\b.*(ngân hàng|tổng đài|công an|nhà mạng|cơ quan)"
    r"|(ngân hàng|tổng đài|công an|nhà mạng|cơ quan)[^.]*\b(đã|vừa)\s+(được\s+)?(khóa|phong tỏa|chặn|đóng băng|xác nhận)",
    re.IGNORECASE)


def test_no_external_locked_status(tmp_path, monkeypatch):
    """Không trạng thái hay câu chữ nào nói tổ chức bên ngoài đã khóa/xác nhận; tối đa là chờ xác nhận."""
    from app.models import ExternalAction

    assert ExternalAction().status == "OPEN"
    reg_path = APP_DIR.parent / "data" / "action_registry.json"
    if reg_path.exists():
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        entries = reg.get("actions", reg) if isinstance(reg, dict) else reg
        entries = entries.values() if isinstance(entries, dict) else entries
        for e in entries:
            if isinstance(e, dict) and "external_status_on_click" in e:
                assert e["external_status_on_click"] == "PENDING_EXTERNAL_CONFIRMATION", e.get("id")

    with make_client(tmp_path, monkeypatch, HKD_ANALYSIS, OTP_ANALYSIS, UNCLEAR_ANALYSIS) as c:
        h = login(c)
        texts = []
        for body in ({"text": LAN_CHAT, "protect_wallet_id": "W-HUNG"},
                     {"text": "Tôi lỡ đọc mã OTP cho người lạ", "protect_wallet_id": "W-LAN"},
                     {"text": "Có người nhắn tin lạ"}):
            r = c.post("/v1/incidents/analyze", headers=h, json=body)
            assert r.status_code == 200, r.text
            texts += all_strings(r.json())
        texts += all_strings(c.get("/v1/wallets", headers=h).json())
    bad = [t for t in texts if CLAIMS_EXTERNAL_DONE.search(t)]
    assert not bad, bad
    assert not any("LOCKED" in t and "EXTERNAL" in t for t in texts)


# ------------------------------------------------------------------ INV-10


def test_containment_monotonic_core(tmp_path):
    """Tầng containment tự nó chỉ nâng (không dựa vào việc AI đã gộp tình tiết theo hướng nâng)."""
    from itertools import product

    from sqlmodel import Session

    from app.core import containment
    from app.models import Wallet

    rank = containment.MODE_RANK
    for old, new in product(rank, rank):
        assert rank[containment.raise_mode(old, new)] == max(rank[old], rank[new]), (old, new)

    eng = db.make_engine(f"sqlite:///{tmp_path / 'c.db'}")
    db.init_db(eng)
    with Session(eng) as s:
        w = Wallet(workspace_id="WS", id="W-X", label="X", owner_name="X", balance_vnd=1, known_contacts=[])
        s.add(w)
        for mode in ("COMPROMISE", "MANIPULATION", "UNCLEAR"):
            pol = containment.apply_containment(s, workspace_id="WS", wallet=w, incident_id="I", mode=mode,
                                                by_proxy=False)
            s.commit()
            assert pol.mode == "COMPROMISE" and w.compromise_locked


def test_containment_monotonic(tmp_path, monkeypatch):
    """Qua API: COMPROMISE không bị hạ bởi tình tiết bổ sung nhẹ hơn; MANIPULATION không về UNCLEAR."""
    from app.schemas.incident import AnalyzeRequest

    assert not {"mode", "release", "unlock", "downgrade"} & set(AnalyzeRequest.model_fields)

    with make_client(tmp_path, monkeypatch, OTP_ANALYSIS, HKD_ANALYSIS, UNCLEAR_ANALYSIS,
                     HKD_ANALYSIS, UNCLEAR_ANALYSIS) as c:
        h = login(c)
        a = c.post("/v1/incidents/analyze", headers=h, json={"text": "Tôi lỡ đọc OTP", "protect_wallet_id": "W-LAN"}).json()
        assert a["mode"] == "COMPROMISE"
        for _ in range(2):                                          # MANIPULATION rồi UNCLEAR: vẫn COMPROMISE
            f = c.post("/v1/incidents/analyze", headers=h, json={
                "incident_id": a["incident_id"], "followup_text": "À mà thật ra không sao đâu, nhầm thôi"}).json()
            assert f["mode"] == "COMPROMISE" and f["protective_hold"]["mode"] == "COMPROMISE"
        lan = next(w for w in c.get("/v1/wallets", headers=h).json()["wallets"] if w["id"] == "W-LAN")
        assert lan["protective_hold_notice"] and "toàn bộ" in lan["protective_hold_notice"]
        ev = c.post("/v1/gateway/evaluate-transfer", headers=h, json={
            "wallet_id": "W-LAN", "to_account_id": "ACC-EVN", "amount_vnd": 300_000, "transfer_note": "tien dien"}).json()
        assert ev["decision"] == "BLOCK"

        m = c.post("/v1/incidents/analyze", headers=h, json={"text": LAN_CHAT, "protect_wallet_id": "W-HUNG"}).json()
        assert m["mode"] == "MANIPULATION"
        f = c.post("/v1/incidents/analyze", headers=h, json={
            "incident_id": m["incident_id"], "followup_text": "Thôi bỏ qua"}).json()
        assert f["mode"] == "MANIPULATION" and f["protective_hold"]["mode"] == "MANIPULATION"


# ------------------------------------------------------------------ INV-13


def test_final_never_below_partner(tmp_path, monkeypatch):
    """Lớp đối tác WARN (→ HOLD_15M): chọn BENIGN vẫn ra HOLD_15M chứ không phải ALLOW_WITH_WARNING."""
    with make_client(tmp_path, monkeypatch, *[HKD_ANALYSIS, LLMRateLimited("429")] * 3) as c:
        h = login(c)
        risky = {"wallet_id": "W-HUNG", "to_account_id": "ACC-NEW-02", "amount_vnd": 5_000_000,
                 "transfer_note": HUNG_NOTE}                            # mới + ≥ 5 triệu + tài khoản 5 ngày tuổi
        for outcome in ("BENIGN", "UNCLEAR", "TACTIC_MATCH"):
            assert c.post("/v1/demo/reset", headers=h).status_code == 200   # số dư mới cho mỗi lựa chọn
            rid = live_rule(c, h)
            ev = c.post("/v1/gateway/evaluate-transfer", headers=h, json=risky).json()
            assert ev["baseline"]["decision"] == "WARN" and ev["baseline"]["as_final"] == "HOLD_15M", ev
            assert ev["status"] == "CHALLENGE_JIT"
            sub = c.post("/v1/gateway/submit-challenge", headers=h, json={
                "challenge_id": ev["challenge"]["challenge_id"], "option_id": option_id(c, h, rid, outcome)}).json()
            assert SEVERITY[sub["decision"]] >= SEVERITY["HOLD_15M"], (outcome, sub)
            if outcome == "BENIGN":
                assert sub["decision"] == "HOLD_15M"                    # không phải ALLOW_WITH_WARNING

        # không có luật nào khớp: kết quả đúng bằng mức sàn của lớp đối tác
        assert c.post("/v1/demo/reset", headers=h).status_code == 200
        ev = c.post("/v1/gateway/evaluate-transfer", headers=h, json=risky).json()
        assert ev["status"] == "FINAL" and ev["decision"] == ev["baseline"]["as_final"] == "HOLD_15M", ev
