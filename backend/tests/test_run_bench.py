"""Kiểm tra logic của bench/run_bench.py bằng API giả (không gọi mạng)."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("run_bench", ROOT / "bench" / "run_bench.py")
rb = importlib.util.module_from_spec(spec)
sys.modules["run_bench"] = rb          # dataclass cần module có trong sys.modules
spec.loader.exec_module(rb)

RULE = {"rule_id": "RL-1",
        "jit_purpose_question": {"options": [
            {"id": "o1", "label_vi": "Mua hàng", "outcome": "BENIGN"},
            {"id": "o2", "label_vi": "Người quen", "outcome": "BENIGN"},
            {"id": "o3", "label_vi": "Đóng phí hồ sơ", "outcome": "TACTIC_MATCH"},
            {"id": "o4", "label_vi": "Mục đích khác", "outcome": "UNCLEAR"}]}}
POLICY = {"BENIGN": "ALLOW_WITH_WARNING", "TACTIC_MATCH": "STOP_AND_EXPLAIN", "UNCLEAR": "HOLD_15M"}


class FakeApi:
    def __init__(self, flagged=0):
        self.calls, self.flagged, self.outcome_of = [], flagged, {o["id"]: o["outcome"] for o in RULE["jit_purpose_question"]["options"]}

    def __call__(self, method, path, body, token):
        self.calls.append((path, body))
        if path == "/v1/demo/reset":
            return 200, {}
        if path == "/v1/incidents/analyze":
            return 200, {"incident_id": "INC-1", "mode": "MANIPULATION", "analysis": {"tactic_family": "FAKE_HKD_TAX_VERIFICATION"}}
        if path == "/v1/fraudops/rules/compile":
            return 200, {"rule_id": "RL-1", "stage": "SHADOW_LOG", "rule": RULE, "source": "LLM", "validation": {"errors": []}}
        if path.endswith("/regression-test"):
            return 200, {"benign_flagged": self.flagged, "benign_checked": 265}
        if path.endswith("/approve"):
            if self.flagged and not body.get("override_reason"):
                return 409, {"error": {"code": "APPROVE_LOCKED"}}
            return 200, {"rule": {"rule_id": "RL-1", "stage": "ASK_ONLY", "rule": RULE},
                         "clock": {"ai_seconds": 7.5, "human_seconds": 30.0, "report_to_live_seconds": None}}
        if path == "/v1/gateway/evaluate-transfer":
            base = {"baseline": {"decision": "ALLOW", "risk_score": 30, "as_final": "ALLOW"}}
            if "thue" in body["transfer_note"]:
                return 200, {**base, "status": "CHALLENGE_JIT", "decision": None, "matched_rule_id": "RL-1",
                             "challenge": {"challenge_id": "CH-1", "question_vi": "Mục đích?",
                                           "options": [{"id": o["id"], "label_vi": o["label_vi"]} for o in RULE["jit_purpose_question"]["options"]]}}
            return 200, {**base, "status": "FINAL", "decision": "ALLOW", "matched_rule_id": None, "challenge": None}
        if path == "/v1/gateway/submit-challenge":
            return 200, {"decision": POLICY[self.outcome_of[body["option_id"]]]}
        return 404, {}


def case(txs, cat="VARIANT_NEW_TACTIC"):
    return {"case_id": "D-X", "category": cat, "incident_A": {"text": "abc", "followups": []},
            "expected_A": {}, "transactions_B": txs}


def tx(i, note, label, outcome, variant=True):
    return {"tx_id": f"D-X-{i}", "from_wallet": "W-HUNG", "to_account_id": "ACC-OLD-7731", "amount_vnd": 1_200_000,
            "transfer_note": note, "label": label, "is_variant": variant, "victim_belief_vi": "…", "dev_outcome": outcome}


def test_auto_flow_and_metrics():
    api = rb.Api(FakeApi())
    c = case([tx(1, "xac thuc ho so thue hkd", "SCAM", "TACTIC_MATCH"), tx(2, "tien hang", "LEGIT", "BENIGN", False)])
    r = rb.run_case(api, c, rb.auto_chooser)
    assert r.error is None and r.rule_stage == "ASK_ONLY" and not r.override_used
    assert [t.relay_final for t in r.txs] == ["STOP_AND_EXPLAIN", "ALLOW"]
    assert r.txs[0].chosen_option == "o3"
    m = rb.metrics([r])
    assert m["unsafe_allow_rate"] == {"scamrelay": "0/1 (0.0%)", "baseline": "1/1 (100.0%)"}
    assert m["variant_trigger_rate"] == "1/1 (100.0%)" and m["friction_rate"] == "0/1 (0.0%)"
    analyze_body = next(b for p, b in api.t.calls if p == "/v1/incidents/analyze")
    assert analyze_body["consent_handoff"] is True


def test_override_recorded_when_flagged():
    api = rb.Api(FakeApi(flagged=2))
    r = rb.run_case(api, case([tx(1, "thue hkd", "SCAM", "BENIGN")]), rb.auto_chooser)
    assert r.override_used and r.error is None
    assert r.txs[0].relay_final == "ALLOW_WITH_WARNING"          # bị dặn chọn BENIGN
    assert rb.metrics([r])["overrides_used"] == ["D-X"]


def test_interactive_never_shows_outcome():
    shown = []
    choose = rb.interactive_chooser(ask=lambda _: "3", out=shown.append)
    ch = {"question_vi": "Mục đích?", "options": [{"id": o["id"], "label_vi": o["label_vi"]} for o in RULE["jit_purpose_question"]["options"]]}
    assert choose({"tx_id": "H-1", "victim_belief_vi": "Tôi nộp phí"}, ch, RULE) == "o3"
    text = "\n".join(shown)
    assert "TACTIC_MATCH" not in text and "BENIGN" not in text and "UNCLEAR" not in text


def test_heldout_with_dev_outcome_rejected(tmp_path):
    (tmp_path / "H-01.json").write_text(json.dumps(case([tx(1, "a", "SCAM", "BENIGN")])), encoding="utf-8")
    with pytest.raises(SystemExit):
        rb.load_cases(tmp_path, interactive=True)


def test_markdown_reports_x_over_n():
    api = rb.Api(FakeApi())
    r = rb.run_case(api, case([tx(1, "thue", "SCAM", "TACTIC_MATCH")]), rb.auto_chooser)
    md = rb.to_markdown("dev", rb.metrics([r]), [r])
    assert "1/1" in md and "Unsafe Allow Rate" in md


def test_dev_cases_fit_seed_workspace():
    """Ca dev phải chạy được trên workspace seed: ví/tài khoản tồn tại, số tiền ≤ số dư và ≤ hạn mức API."""
    seed = json.loads((ROOT / "backend" / "data" / "seed_workspace.json").read_text(encoding="utf-8"))
    bal = {w["id"]: w["balance_vnd"] for w in seed["wallets"]}
    accounts = {a["id"] for a in seed["accounts"]}
    for p in sorted((ROOT / "bench" / "cases" / "dev").glob("*.json")):
        case = json.loads(p.read_text(encoding="utf-8"))
        assert case["incident_A"].get("protect_wallet_id") in (None, *bal), p.name
        for t in case["transactions_B"]:
            assert t["from_wallet"] in bal and t["to_account_id"] in accounts, t["tx_id"]
            assert 0 < t["amount_vnd"] <= min(bal[t["from_wallet"]], 50_000_000), t["tx_id"]
