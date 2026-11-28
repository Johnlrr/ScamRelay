"""Runner benchmark (SPEC §13.3–13.4): gọi ĐÚNG các endpoint thật, không có nhánh dry-run.

    # Dev, tự chọn phương án theo dev_outcome
    backend/.venv/bin/python bench/run_bench.py --auto bench/cases/dev
    # Held-out (01/12 sau freeze, linh ngồi terminal): chọn phương án theo victim_belief_vi
    backend/.venv/bin/python bench/run_bench.py --interactive <thư mục held-out>

Biến môi trường: SCAMRELAY_URL (mặc định http://localhost:8000), BENCH_USER / BENCH_PASS (tài khoản
`bench_runner`). Kết quả: bench/results/<tên tập>_<thời điểm>.{json,md}; chế độ interactive ghi thêm
bench/results/heldout_mapping.json.

Mỗi ca: reset → analyze(A, consent_handoff=true) [+ follow-up] → compile → regression → approve ASK_ONLY
(flagged > 0 thì ghi đè với lý do cố định và GHI LẠI việc đó) → với mỗi giao dịch B: evaluate → nếu
CHALLENGE_JIT thì chọn phương án → submit-challenge.

Ở chế độ --auto, outcome của phương án lấy từ luật qua API FraudOps (JWT) — client ví vẫn không thấy
outcome (INV-12). Ở chế độ --interactive, terminal KHÔNG hiện outcome.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "bench" / "results"
STOPPED = {"HOLD_15M", "STOP_AND_EXPLAIN", "HOLD_UNTIL_VERIFIED", "BLOCK"}       # tập S (SPEC §13.4)
ALLOWED = {"ALLOW", "ALLOW_WITH_WARNING"}
OVERRIDE_REASON = "bench: ghi đè tự động, xem results"


class Transport(Protocol):
    def __call__(self, method: str, path: str, body: dict | None, token: str | None) -> tuple[int, dict]: ...


def http_transport(base_url: str, timeout: float = 90) -> Transport:
    def send(method: str, path: str, body: dict | None, token: str | None) -> tuple[int, dict]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(base_url.rstrip("/") + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                return resp.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return e.code, {"raw": raw.decode("utf-8", "replace")[:300]}
    return send


class ApiError(RuntimeError):
    pass


class Api:
    def __init__(self, transport: Transport):
        self.t = transport
        self.token: str | None = None

    def call(self, method: str, path: str, body: dict | None = None, ok: tuple[int, ...] = (200, 201)) -> dict:
        status, data = self.t(method, path, body, self.token)
        if status not in ok:
            raise ApiError(f"{method} {path} → {status}: {json.dumps(data, ensure_ascii=False)[:300]}")
        return data

    def login(self, user: str, password: str) -> None:
        self.token = self.call("POST", "/v1/auth/login", {"username": user, "password": password})["access_token"]


# ------------------------------------------------------------------ chọn phương án

Chooser = Callable[[dict, dict, dict], str]       # (tx_case, challenge, rule) → option_id


def auto_chooser(tx: dict, challenge: dict, rule: dict | None) -> str:
    want = tx.get("dev_outcome")
    if want is None:
        raise ApiError(f"{tx['tx_id']}: ca dev thiếu dev_outcome")
    by_id = {o["id"]: o["outcome"] for o in (rule or {}).get("jit_purpose_question", {}).get("options", [])}
    for o in challenge["options"]:
        if by_id.get(o["id"]) == want:
            return o["id"]
    raise ApiError(f"{tx['tx_id']}: không tìm thấy phương án có outcome {want}")


def interactive_chooser(ask: Callable[[str], str] = input, out: Callable[[str], None] = print) -> Chooser:
    def choose(tx: dict, challenge: dict, rule: dict | None) -> str:
        out("\n" + "=" * 72)
        out(f"[{tx['tx_id']}] Người chuyển tin rằng: {tx['victim_belief_vi']}")
        out(f"Câu hỏi: {challenge['question_vi']}")
        ids = [o["id"] for o in challenge["options"]]
        for i, o in enumerate(challenge["options"], 1):
            out(f"  {i}. {o['label_vi']}")
        while True:
            pick = ask(f"Chọn 1–{len(ids)}: ").strip()
            if pick.isdigit() and 1 <= int(pick) <= len(ids):
                return ids[int(pick) - 1]
    return choose


# ------------------------------------------------------------------ chạy

@dataclass
class TxResult:
    case_id: str
    tx_id: str
    category: str
    label: str
    is_variant: bool
    relay_final: str | None
    baseline_final: str | None
    matched_rule_id: str | None
    challenged: bool
    chosen_option: str | None = None
    chosen_label: str | None = None
    error: str | None = None


@dataclass
class CaseResult:
    case_id: str
    category: str
    analyze_mode: str | None = None
    tactic_family: str | None = None
    compile_source: str | None = None
    rule_id: str | None = None
    rule_stage: str | None = None
    benign_flagged: int | None = None
    benign_checked: int | None = None
    override_used: bool = False
    ai_seconds: float | None = None
    error: str | None = None
    txs: list[TxResult] = field(default_factory=list)


def run_case(api: Api, case: dict, choose: Chooser) -> CaseResult:
    res = CaseResult(case["case_id"], case["category"])
    rule: dict | None = None
    try:
        api.call("POST", "/v1/demo/reset")
        A = case["incident_A"]
        body = {"text": A["text"], "is_proxy": False, "consent_handoff": True}
        if A.get("protect_wallet_id"):
            body["protect_wallet_id"] = A["protect_wallet_id"]
        inc = api.call("POST", "/v1/incidents/analyze", body)
        for f in A.get("followups", []):
            inc = api.call("POST", "/v1/incidents/analyze",
                           {"followup_text": f, "incident_id": inc["incident_id"], "consent_handoff": True})
        res.analyze_mode = inc.get("mode")
        res.tactic_family = (inc.get("analysis") or {}).get("tactic_family")

        # compile trả RuleView: {rule_id, stage, rule: RelayRule | None, validation, source, ...}
        comp = api.call("POST", "/v1/fraudops/rules/compile", {"incident_id": inc["incident_id"]})
        res.rule_id, res.compile_source = comp["rule_id"], comp.get("source")
        if comp["stage"] == "DRAFT_INVALID" or comp.get("rule") is None:
            raise ApiError("luật DRAFT_INVALID: " + "; ".join((comp.get("validation") or {}).get("errors", [])[:3]))
        rule = comp["rule"]
        reg = api.call("POST", f"/v1/fraudops/rules/{comp['rule_id']}/regression-test")
        res.benign_flagged, res.benign_checked = reg["benign_flagged"], reg["benign_checked"]
        approve = {"stage": "ASK_ONLY", "ttl_hours": 24}
        if reg["benign_flagged"] > 0:
            approve["override_reason"] = OVERRIDE_REASON
            res.override_used = True
        # approve trả {rule: RuleView, clock: {ai_seconds, human_seconds, report_to_live_seconds}}
        appr = api.call("POST", f"/v1/fraudops/rules/{comp['rule_id']}/approve", approve)
        rule = appr["rule"]["rule"] or rule
        res.rule_stage = appr["rule"]["stage"]
        res.ai_seconds = (appr.get("clock") or {}).get("ai_seconds")
    except ApiError as e:
        res.error = str(e)
        rule = None if res.rule_stage is None else rule

    for tx in case["transactions_B"]:
        res.txs.append(run_tx(api, case, tx, rule, choose))
    return res


def run_tx(api: Api, case: dict, tx: dict, rule: dict | None, choose: Chooser) -> TxResult:
    r = TxResult(case["case_id"], tx["tx_id"], case["category"], tx["label"], bool(tx.get("is_variant")),
                 None, None, None, False)
    try:
        ev = api.call("POST", "/v1/gateway/evaluate-transfer", {
            "wallet_id": tx["from_wallet"], "to_account_id": tx["to_account_id"],
            "amount_vnd": tx["amount_vnd"], "transfer_note": tx["transfer_note"]})
        r.baseline_final = (ev.get("baseline") or {}).get("as_final")
        r.matched_rule_id = ev.get("matched_rule_id")
        if ev["status"] == "CHALLENGE_JIT":
            r.challenged = True
            ch = ev["challenge"]
            r.chosen_option = choose(tx, ch, rule)
            r.chosen_label = next((o["label_vi"] for o in ch["options"] if o["id"] == r.chosen_option), None)
            sub = api.call("POST", "/v1/gateway/submit-challenge",
                           {"challenge_id": ch["challenge_id"], "option_id": r.chosen_option})
            r.relay_final = sub["decision"]
        else:
            r.relay_final = ev["decision"]
    except ApiError as e:
        r.error = str(e)
    return r


# ------------------------------------------------------------------ chỉ số (SPEC §13.4, luôn x/n)

def ratio(x: int, n: int) -> str:
    return f"{x}/{n} ({(100 * x / n):.1f}%)" if n else "0/0 (—)"


def metrics(cases: list[CaseResult]) -> dict:
    txs = [t for c in cases for t in c.txs if t.error is None]
    scam = [t for t in txs if t.label == "SCAM"]
    legit = [t for t in txs if t.label == "LEGIT"]
    variants = [t for t in txs if t.is_variant]
    breakdown: dict[str, dict[str, int]] = {}
    for t in scam:
        for sysname, d in (("scamrelay", t.relay_final), ("baseline", t.baseline_final)):
            breakdown.setdefault(sysname, {}).setdefault(str(d), 0)
            breakdown[sysname][str(d)] += 1
    ai = sorted(c.ai_seconds for c in cases if c.ai_seconds is not None)
    by_cat = {}
    for cat in ("COACHED", "EMPTY_NOTE"):
        s = [t for t in scam if t.category == cat]
        by_cat[cat] = ratio(sum(t.relay_final in STOPPED for t in s), len(s))
    return {
        "unsafe_allow_rate": {
            "scamrelay": ratio(sum(t.relay_final not in STOPPED for t in scam), len(scam)),
            "baseline": ratio(sum(t.baseline_final not in STOPPED for t in scam), len(scam)),
        },
        "scam_decision_breakdown": breakdown,
        "legitimate_allow_rate": ratio(sum(t.relay_final in ALLOWED for t in legit), len(legit)),
        "friction_rate": ratio(sum(t.challenged for t in legit), len(legit)),
        "variant_trigger_rate": ratio(sum(t.matched_rule_id is not None for t in variants), len(variants)),
        "stopped_by_category": by_cat,
        "ai_seconds": {"n": len(ai), "p50": round(statistics.median(ai), 2) if ai else None,
                       "p95": round(ai[min(len(ai) - 1, round(0.95 * (len(ai) - 1)))], 2) if ai else None},
        "cases_with_error": [c.case_id for c in cases if c.error],
        "tx_errors": sum(t.error is not None for c in cases for t in c.txs),
        "overrides_used": [c.case_id for c in cases if c.override_used],
    }


def to_markdown(name: str, m: dict, cases: list[CaseResult]) -> str:
    lines = [f"# Benchmark {name}", "",
             "| Chỉ số | Giá trị |", "|---|---|",
             f"| Unsafe Allow Rate — ScamRelay | {m['unsafe_allow_rate']['scamrelay']} |",
             f"| Unsafe Allow Rate — baseline | {m['unsafe_allow_rate']['baseline']} |",
             f"| Legitimate Allow Rate | {m['legitimate_allow_rate']} |",
             f"| Friction Rate (giao dịch sạch bị hỏi) | {m['friction_rate']} |",
             f"| Variant Trigger Rate | {m['variant_trigger_rate']} |",
             f"| Ca COACHED được dừng | {m['stopped_by_category']['COACHED']} |",
             f"| Ca EMPTY_NOTE được dừng | {m['stopped_by_category']['EMPTY_NOTE']} |",
             f"| ai_seconds P50 / P95 (n={m['ai_seconds']['n']}) | {m['ai_seconds']['p50']} / {m['ai_seconds']['p95']} |",
             "", "Phân rã quyết định trên giao dịch SCAM (HOLD_15M chỉ là khoảng dừng):", ""]
    for sysname, d in m["scam_decision_breakdown"].items():
        lines.append(f"- {sysname}: " + ", ".join(f"{k} {v}" for k, v in sorted(d.items())))
    if m["overrides_used"]:
        lines += ["", f"Ghi đè khóa Approve (flagged > 0): {', '.join(m['overrides_used'])}"]
    if m["cases_with_error"] or m["tx_errors"]:
        lines += ["", f"Lỗi: ca {m['cases_with_error']}, {m['tx_errors']} giao dịch lỗi (không tính vào chỉ số)"]
    lines += ["", "| Giao dịch | Loại | Nhãn | Baseline | ScamRelay | Bị hỏi | Phương án |", "|---|---|---|---|---|---|---|"]
    for c in cases:
        for t in c.txs:
            lines.append(f"| {t.tx_id} | {t.category} | {t.label} | {t.baseline_final} | {t.relay_final or t.error} "
                         f"| {'có' if t.challenged else ''} | {t.chosen_label or ''} |")
    return "\n".join(lines) + "\n"


def load_cases(folder: Path, interactive: bool) -> list[dict]:
    cases = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.json"))]
    if interactive and any("dev_outcome" in t for c in cases for t in c["transactions_B"]):
        raise SystemExit("held-out không được có dev_outcome (SPEC §13.1)")
    return cases


def main(argv: list[str] | None = None, transport: Transport | None = None) -> int:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--auto", action="store_true")
    mode.add_argument("--interactive", action="store_true")
    ap.add_argument("folder", type=Path)
    args = ap.parse_args(argv)

    api = Api(transport or http_transport(os.environ.get("SCAMRELAY_URL", "http://localhost:8000")))
    user, pw = os.environ.get("BENCH_USER"), os.environ.get("BENCH_PASS")
    if user and pw:
        api.login(user, pw)
    choose = interactive_chooser() if args.interactive else auto_chooser
    cases = load_cases(args.folder, args.interactive)
    results = []
    for c in cases:
        results.append(run_case(api, c, choose))
        last = results[-1]
        print(f"{last.case_id}: {last.error or 'ok'} — " +
              ", ".join(f"{t.tx_id}={t.relay_final or t.error}" for t in last.txs), flush=True)

    name = args.folder.name
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")
    m = metrics(results)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"set": name, "mode": "interactive" if args.interactive else "auto", "generated_at": stamp,
               "metrics": m, "cases": [c.__dict__ | {"txs": [t.__dict__ for t in c.txs]} for c in results]}
    (RESULTS_DIR / f"{name}_{stamp}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                                                      encoding="utf-8")
    (RESULTS_DIR / f"{name}_{stamp}.md").write_text(to_markdown(name, m, results), encoding="utf-8")
    if args.interactive:
        mapping = [{"tx_id": t.tx_id, "chosen_option": t.chosen_option, "chosen_label": t.chosen_label}
                   for c in results for t in c.txs if t.challenged]
        (RESULTS_DIR / "heldout_mapping.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=1) + "\n",
                                                          encoding="utf-8")
    print(to_markdown(name, m, results).split("\n\n| Giao dịch")[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
