"""Bảng theo dõi luật GET /v1/fraudops/rules/{id}/stats (SPEC §7.2h, có thể có)."""

from __future__ import annotations

from app.ai.llm_client import LLMRateLimited
from tests._fixtures import HKD_ANALYSIS
from tests.test_invariants_api import HUNG_NOTE, LAN_CHAT, _cleanup, login, make_client, option_id  # noqa: F401


def tx(wallet: str) -> dict:
    return {"wallet_id": wallet, "to_account_id": "ACC-OLD-7731", "amount_vnd": 1_200_000, "transfer_note": HUNG_NOTE}


def answer(c, h, wallet, rid, outcome) -> dict:
    ev = c.post("/v1/gateway/evaluate-transfer", headers=h, json=tx(wallet)).json()
    assert ev["status"] == "CHALLENGE_JIT", ev
    r = c.post("/v1/gateway/submit-challenge", headers=h, json={
        "challenge_id": ev["challenge"]["challenge_id"], "option_id": option_id(c, h, rid, outcome)})
    assert r.status_code == 200, r.text
    return r.json()


def test_rule_stats_counts_and_only_suggests(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch, HKD_ANALYSIS, LLMRateLimited("429")) as c:
        h = login(c)
        inc = c.post("/v1/incidents/analyze", headers=h, json={"text": LAN_CHAT, "consent_handoff": True}).json()
        rid = c.post("/v1/fraudops/rules/compile", headers=h, json={"incident_id": inc["incident_id"]}).json()["rule_id"]
        st = c.get(f"/v1/fraudops/rules/{rid}/stats", headers=h).json()
        assert st["asked"] == 0 and st["shadow_hits"] == 0 and st["last_hit_at"] is None and not st["suggest_upgrade"]

        # SHADOW_LOG: khớp chỉ ghi log, không hỏi
        ev = c.post("/v1/gateway/evaluate-transfer", headers=h, json=tx("W-HUNG")).json()
        assert ev["status"] == "FINAL"
        st = c.get(f"/v1/fraudops/rules/{rid}/stats", headers=h).json()
        assert st["shadow_hits"] == 1 and st["asked"] == 0 and st["last_hit_at"]

        reg = c.post(f"/v1/fraudops/rules/{rid}/regression-test", headers=h).json()
        body = {"stage": "ASK_ONLY", "ttl_hours": 24}
        if reg["benign_flagged"]:
            body["override_reason"] = "Test thống kê: chấp nhận khớp nhầm đã biết"
        assert c.post(f"/v1/fraudops/rules/{rid}/approve", headers=h, json=body).status_code == 200

        answer(c, h, "W-HUNG", rid, "BENIGN")
        answer(c, h, "W-HUNG", rid, "TACTIC_MATCH")
        st = c.get(f"/v1/fraudops/rules/{rid}/stats", headers=h).json()
        assert st["asked"] == 2 and st["answered"] == {"TACTIC_MATCH": 1, "BENIGN": 1, "UNCLEAR": 0}
        assert not st["suggest_upgrade"]

        answer(c, h, "W-LAN", rid, "TACTIC_MATCH")
        st = c.get(f"/v1/fraudops/rules/{rid}/stats", headers=h).json()
        assert st["answered"]["TACTIC_MATCH"] == 2 and st["suggest_upgrade"] and st["suggest_upgrade_reason_vi"]
        # chỉ gợi ý: luật vẫn ở ASK_ONLY
        assert c.get(f"/v1/fraudops/rules/{rid}", headers=h).json()["stage"] == "ASK_ONLY" == st["stage"]


def test_rule_stats_requires_judge_and_own_workspace(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as c:
        assert c.get("/v1/fraudops/rules/RL-X/stats").status_code == 401
        h = login(c)
        assert c.get("/v1/fraudops/rules/RL-KHONG-CO/stats", headers=h).status_code == 404
