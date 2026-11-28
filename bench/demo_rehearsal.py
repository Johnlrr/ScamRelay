"""Tập dượt kịch bản demo 3 phút (ABOUT §7) qua HTTP, đúng thứ tự như video.

Dùng trước khi quay video và sau mỗi lần deploy (PLAN 30/11: "chạy thử mọi câu trong kịch bản demo").
Gọi LLM thật của server (khoảng 3 request: analyze, follow-up OTP, compile).

    SCAMRELAY_URL=https://… DEMO_USER=judge_01 DEMO_PASS=… python bench/demo_rehearsal.py

Mỗi bước in PASS/FAIL kèm số liệu; kết quả ghi vào bench/results/demo_rehearsal_<giờ UTC>.md.
Reset workspace của tài khoản dùng để chạy (không đụng workspace khác).
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import _common  # noqa: F401  (đưa backend vào sys.path)
from _expert import add_exclusions
from run_bench import Api, ApiError, http_transport

from app.core.preprocess import norm_match

RESULTS = Path(__file__).resolve().parent / "results"
STOP_SET = {"HOLD_15M", "STOP_AND_EXPLAIN", "HOLD_UNTIL_VERIFIED", "BLOCK"}

# Câu chữ đúng như kịch bản (ABOUT §7); đoạn chat ngắn, tổng hợp
LAN_CHAT = ("Có người xưng cán bộ thuế gọi mẹ, bảo phải chuẩn hóa tài khoản hộ kinh doanh theo quy định 2026, "
            "chuyển 1,8 triệu phí xác minh, không thì khóa mã số thuế.")
LAN_FOLLOWUP = "Mẹ lỡ đọc mã OTP cho người đó rồi."
HUNG_NOTE = "xac thuc ho so cap nhat thue HKD"
HUNG_TX = {"wallet_id": "W-HUNG", "to_account_id": "ACC-OLD-7731", "amount_vnd": 1_200_000, "transfer_note": HUNG_NOTE}


class Rehearsal:
    def __init__(self, api: Api) -> None:
        self.api = api
        self.rows: list[tuple[str, bool, str]] = []

    def check(self, step: str, ok: bool, detail: str) -> bool:
        self.rows.append((step, ok, detail))
        print(f"{'PASS' if ok else 'FAIL'}  {step}: {detail}", flush=True)
        return ok

    def wallet(self, wid: str) -> dict:
        return next(w for w in self.api.call("GET", "/v1/wallets")["wallets"] if w["id"] == wid)

    def transfer(self, **tx) -> dict:
        return self.api.call("POST", "/v1/gateway/evaluate-transfer", tx)

    def answer(self, ev: dict, rule: dict, outcome: str) -> dict:
        by_id = {o["id"]: o["outcome"] for o in rule["jit_purpose_question"]["options"]}
        oid = next(o["id"] for o in ev["challenge"]["options"] if by_id.get(o["id"]) == outcome)
        return self.api.call("POST", "/v1/gateway/submit-challenge",
                             {"challenge_id": ev["challenge"]["challenge_id"], "option_id": oid})

    # ------------------------------------------------------------------ kịch bản

    def run(self) -> None:
        api = self.api
        api.call("POST", "/v1/demo/reset")

        # 0:15–0:45 Khoanh vùng: Tuấn kích hoạt hộ cho mẹ
        t0 = time.perf_counter()
        inc = api.call("POST", "/v1/incidents/analyze", {
            "text": LAN_CHAT, "is_proxy": True, "protect_wallet_id": "W-LAN", "consent_handoff": True})
        a = inc["analysis"]
        self.check("Lan · analyze", inc["mode"] == "MANIPULATION" and len(inc["actions"]) == 3 and not inc["degraded"],
                   f"mode={inc['mode']}, {len(inc['actions'])} việc, {a['tactic_family']}, "
                   f"đòi {a['money_requested_vnd']}, degraded={inc['degraded']}, {time.perf_counter() - t0:.1f}s")
        self.check("Lan · thông báo trên ví", bool(self.wallet("W-LAN")["protective_hold_notice"]),
                   str(self.wallet("W-LAN")["protective_hold_notice"])[:90])
        ev = self.transfer(wallet_id="W-LAN", to_account_id="ACC-NEW-01", amount_vnd=1_800_000,
                           transfer_note="phi xac minh ho kinh doanh")
        self.check("Lan · khoản 1,8tr bị giữ", ev.get("decision") == "HOLD_UNTIL_VERIFIED",
                   f"{ev['status']} {ev.get('decision')} {ev.get('reason_codes')}")
        ev = self.transfer(wallet_id="W-LAN", to_account_id="ACC-EVN", amount_vnd=400_000,
                           transfer_note="tien dien thang 11")
        self.check("Lan · hóa đơn điện 400k vẫn qua", ev.get("decision") in ("ALLOW", "ALLOW_WITH_WARNING"),
                   f"{ev['status']} {ev.get('decision')}")
        t0 = time.perf_counter()
        f = api.call("POST", "/v1/incidents/analyze", {"incident_id": inc["incident_id"], "is_proxy": True,
                                                       "followup_text": LAN_FOLLOWUP})
        self.check("Lan · 'Mẹ lỡ đọc OTP' → khóa cứng", f["mode"] == "COMPROMISE",
                   f"mode={f['mode']}, OTP={f['analysis']['otp_or_password_disclosed']}, "
                   f"{time.perf_counter() - t0:.1f}s")
        ev = self.transfer(wallet_id="W-LAN", to_account_id="ACC-EVN", amount_vnd=400_000,
                           transfer_note="tien dien thang 11")
        self.check("Lan · hóa đơn điện giờ bị chặn", ev.get("decision") == "BLOCK", f"{ev.get('decision')}")

        # 0:45–1:00 Chú Hùng, trước khi có luật
        ev = self.transfer(**HUNG_TX)
        self.check("Hùng trước luật · baseline lọt", ev.get("decision") == "ALLOW"
                   and ev["baseline"]["as_final"] == "ALLOW",
                   f"ScamRelay={ev.get('decision')}, baseline={ev['baseline']['as_final']} "
                   f"(risk {ev['baseline'].get('risk_score')})")

        # 1:00–1:55 Tiếp sức
        t0 = time.perf_counter()
        comp = api.call("POST", "/v1/fraudops/rules/compile", {"incident_id": inc["incident_id"]})
        rid = comp["rule_id"]
        self.check("FraudOps · compile", comp["stage"] == "SHADOW_LOG",
                   f"stage={comp['stage']}, source={comp['source']}, degraded={comp['degraded']}, "
                   f"{time.perf_counter() - t0:.1f}s, validator errors={comp['validation']['errors']}")
        reg = api.call("POST", f"/v1/fraudops/rules/{rid}/regression-test")
        r = api.call("POST", f"/v1/fraudops/rules/{rid}/approve", {"stage": "ASK_ONLY"},
                     ok=(200, 409)) if reg["benign_flagged"] else None
        self.check("FraudOps · regression lần 1", True,
                   f"khớp nhầm {reg['benign_flagged']}/{reg['benign_checked']}, biến thể "
                   f"{reg['variants_triggered']}/{reg['variants_checked']}, anchor gây nhầm "
                   f"{dict(reg['flags_by_anchor'])}, mẫu sạch {[f['transfer_note'] for f in reg['flagged_examples']]}"
                   + (f"; Approve → {r['error']['code']}" if r and "error" in r else ""))
        if reg["benign_flagged"]:
            self.check("FraudOps · Approve bị khóa", bool(r and r.get("error", {}).get("code") == "APPROVE_LOCKED"),
                       str(r and r.get("error", {}).get("code")))
            # chuyên viên thêm cụm loại trừ cho mẫu sạch bị khớp (cách sửa đã chốt cho demo, bench/_expert.py);
            # không tìm được cụm phù hợp thì mới xóa câu mẫu được tô đậm
            draft, changes = comp["draft"], []
            for round_ in range(1, 4):
                added = add_exclusions(draft, [f["transfer_note"] for f in reg["flagged_examples"]])
                changes += [f"+loại trừ '{x}'" for x in added]
                if not added:
                    bad = set(reg["flags_by_anchor"])
                    for cond in draft["conditions"]:
                        if cond.get("op") == "SEMANTIC_MATCH":
                            keep = [x for x in cond["anchor_phrases"] if norm_match(x) not in bad]
                            changes += [f"-câu mẫu '{x}'" for x in cond["anchor_phrases"] if norm_match(x) in bad]
                            cond["anchor_phrases"] = keep or cond["anchor_phrases"]
                edited = api.call("PUT", f"/v1/fraudops/rules/{rid}/draft", draft)
                draft = edited["draft"]
                reg = api.call("POST", f"/v1/fraudops/rules/{rid}/regression-test")
                if reg["benign_flagged"] == 0:
                    break
            self.check("FraudOps · chuyên viên sửa luật, chạy lại", reg["benign_flagged"] == 0,
                       f"{round_} vòng: {', '.join(changes)}; v{edited['version']}: khớp nhầm "
                       f"{reg['benign_flagged']}/{reg['benign_checked']}, biến thể "
                       f"{reg['variants_triggered']}/{reg['variants_checked']}")
        body = {"stage": "ASK_ONLY", "ttl_hours": 24}
        if reg["benign_flagged"]:
            body["override_reason"] = "Tập dượt: chấp nhận khớp nhầm còn lại để xem tiếp luồng"
        ap = api.call("POST", f"/v1/fraudops/rules/{rid}/approve", body)
        clock = ap["clock"]
        self.check("FraudOps · Approve ASK_ONLY", ap["rule"]["stage"] == "ASK_ONLY",
                   f"AI {clock['ai_seconds']:.1f}s · con người {clock['human_seconds']:.1f}s · "
                   f"báo cáo→hiệu lực {clock['report_to_live_seconds']:.1f}s")
        rule = api.call("GET", f"/v1/fraudops/rules/{rid}")["rule"]

        # 1:55–2:30 Chặn đúng
        hung_before = self.wallet("W-HUNG")["balance_vnd"]
        ev = self.transfer(**HUNG_TX)
        asked = ev["status"] == "CHALLENGE_JIT"
        if not asked:
            print("        (chú Hùng không bị hỏi: câu mẫu còn lại không đủ gần câu demo)")
        self.check("Hùng sau luật · bị hỏi mục đích", asked and bool(ev["challenge"]["anti_coaching_notice_vi"]),
                   f"{ev['status']}, câu hỏi: {ev['challenge']['question_vi'] if asked else '-'}")
        if asked:
            for o in ev["challenge"]["options"]:
                print(f"        ○ {o['label_vi']}")
            sub = self.answer(ev, rule, "TACTIC_MATCH")
            after = self.wallet("W-HUNG")["balance_vnd"]
            self.check("Hùng · chọn mục đích khớp thủ đoạn → dừng, 0đ rời ví",
                       sub["decision"] == "STOP_AND_EXPLAIN" and after == hung_before,
                       f"{sub['decision']}, số dư {hung_before:,} → {after:,}; giải thích: "
                       f"{(sub.get('tactic_alert_vi') or '')[:80]}")
        ev = self.transfer(wallet_id="W-HUNG", to_account_id="ACC-SHOP", amount_vnd=450_000,
                           transfer_note="tien hang phu tung")
        self.check("Hùng · mua hàng thật vẫn qua", ev.get("decision") == "ALLOW", f"{ev['status']} {ev.get('decision')}")
        ev = self.transfer(wallet_id="W-HUNG", to_account_id="ACC-TAX-GOV", amount_vnd=1_000_000,
                           transfer_note="nop thue ho kinh doanh quy 4")
        self.check("Hùng · nộp thuế thật qua biller không bị hỏi", ev["status"] == "FINAL",
                   f"{ev['status']} {ev.get('decision')}")
        ev = self.transfer(wallet_id="W-HUNG", to_account_id="ACC-OLD-5520", amount_vnd=1_200_000,
                           transfer_note="phi cap nhat ho so thue ho kinh doanh")
        if ev["status"] == "CHALLENGE_JIT":
            sub = self.answer(ev, rule, "BENIGN")
            # lớp đối tác WARN (vd. chuyển dồn dập trong 10 phút) thì mức sàn HOLD_15M (INV-13)
            want = "HOLD_15M" if "PARTNER_WARN" in sub["reason_codes"] else "ALLOW_WITH_WARNING"
            self.check("Biến thể · chọn mục đích lành → qua kèm cảnh báo (hoặc mức sàn đối tác)",
                       sub["decision"] == want, f"{sub['decision']} {sub['reason_codes']}")
        else:
            self.check("Biến thể · bị hỏi", False, f"không bị hỏi ({ev.get('decision')})")

    def write(self, base_url: str) -> Path:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = RESULTS / f"demo_rehearsal_{ts}.md"
        passed = sum(ok for _, ok, _ in self.rows)
        host = "local" if "localhost" in base_url or "127.0.0.1" in base_url else base_url
        lines = [f"# Tập dượt kịch bản demo ({ts})", "",
                 f"Server: {host}. Kết quả: **{passed}/{len(self.rows)} bước PASS**. LLM thật của server.", "",
                 "| Bước | Kết quả | Chi tiết |", "|---|---|---|"]
        lines += [f"| {s} | {'PASS' if ok else '**FAIL**'} | {d.replace('|', '/')} |" for s, ok, d in self.rows]
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return out


def main() -> int:
    base = os.environ.get("SCAMRELAY_URL", "http://localhost:8000")
    user, pw = os.environ.get("DEMO_USER"), os.environ.get("DEMO_PASS")
    if not user or not pw:
        print("cần DEMO_USER và DEMO_PASS (tài khoản giám khảo hoặc bench_runner)")
        return 2
    api = Api(http_transport(base))
    api.login(user, pw)
    reh = Rehearsal(api)
    try:
        reh.run()
    except ApiError as e:
        reh.check("lỗi API", False, str(e)[:200])
    out = reh.write(base)
    print(f"\n→ {out}")
    return 0 if all(ok for _, ok, _ in reh.rows) else 1


if __name__ == "__main__":
    sys.exit(main())
