"""Hiệu chỉnh SEMANTIC_THRESHOLD và TRIGRAM_THRESHOLD — CHỈ trên tập dev (SPEC §8.3).

    backend/.venv/bin/python bench/calibrate.py

Đầu vào: luật dev đã biên dịch bằng LLM thật (`bench/dev_compiled/*.json`, từ compile_dev.py),
các giao dịch B của ca dev, và tập sạch `backend/data/benign_corpus.json`.

Với mỗi ngưỡng t (0,60 → 0,95, bước 0,01) dùng ĐÚNG `layer1_explain` của gateway:
- trigger(t) = số giao dịch B `is_variant` khớp luật của chính ca đó / tổng biến thể dev
- flagged(t) = số cặp (luật dev, mẫu sạch) bị khớp + số giao dịch LEGIT của dev bị khớp
Chọn (SPEC §8.3, chốt 28/11): ngưỡng CAO NHẤT mà trigger vẫn đạt mức tối đa của bảng quét. Khớp nhầm còn lại
do regression + chuyên viên xử lý (khóa Approve).
Kết quả ghi `bench/results/calibration_<thời điểm>.{json,md}` (bảng phụ lục slide). Không tự sửa config.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

import _common

from app.core._contract_draft import DerivedTx
from app.core.assembler import assemble_rule
from app.core.layer1 import layer1_explain, semantic_phrases
from app.core.preprocess import norm_match
from app.core.regression import load_benign_corpus
from app.core.semantic import GeminiEmbedder, NpzEmbeddingCache, SemanticMatcher
from app.core.validator import validate_llm_output

DEV_DIR = _common.BENCH / "cases" / "dev"
COMPILED_DIR = _common.BENCH / "dev_compiled"
RESULTS_DIR = _common.BENCH / "results"
VERIFIED_BILLERS = {"ACC-EVN", "ACC-WATER", "ACC-TAX-GOV"}       # SPEC §5.2
SEM_RANGE = [round(0.60 + i * 0.01, 2) for i in range(36)]
TRI_RANGE = [round(0.30 + i * 0.01, 2) for i in range(61)]


@dataclass
class Scored:
    kind: str            # VARIANT | LEGIT_DEV | BENIGN
    case_id: str
    note: str
    sem: float | None    # None: không qua được điều kiện khác (sàn, NOT_CONTAINS, nội dung quá ngắn…)
    tri: float | None


def _tx(note: str, amount: int, to_account: str = "ACC-CAL") -> DerivedTx:
    return DerivedTx(wallet_id="CAL", to_account_id=to_account, amount_vnd=amount, transfer_note=note,
                     note_norm=norm_match(note), recipient_is_new=False, recipient_account_age_days=365,
                     tx_count_10m=0, is_verified_biller=to_account in VERIFIED_BILLERS, is_known_contact=False,
                     account_compromise_flag=False)


def _score(rule, tx, anchors, vec) -> tuple[float | None, float | None]:
    """Điểm semantic nếu MỌI điều kiện khác đều thỏa (ngưỡng đặt -1 để chỉ còn điều kiện semantic quyết)."""
    d = layer1_explain(rule, tx, anchors, note_vec=vec)
    sem = d.score if d.matched else None
    t = layer1_explain(rule, tx, anchors, note_vec=None, trigram_threshold=-1.0)
    tri = t.score if t.matched else None
    return sem, tri


def sweep(rows: list[Scored], grid: list[float], attr: str) -> list[dict]:
    variants = [r for r in rows if r.kind == "VARIANT"]
    table = []
    for t in grid:
        hit = sum(1 for r in variants if (s := getattr(r, attr)) is not None and s >= t)
        flagged = sum(1 for r in rows if r.kind != "VARIANT" and (s := getattr(r, attr)) is not None and s >= t)
        table.append({"threshold": t, "triggered": hit, "variants": len(variants), "flagged": flagged})
    return table


def choose(table: list[dict]) -> dict | None:
    if not table:
        return None
    best = max(r["triggered"] for r in table)
    return max((r for r in table if r["triggered"] == best), key=lambda r: r["threshold"])


async def main() -> int:
    _common.load_env()
    compiled = sorted(COMPILED_DIR.glob("*.json"))
    if not compiled:
        print("chưa có bench/dev_compiled/*.json — chạy compile_dev.py trước")
        return 2
    matcher = SemanticMatcher(_common.PatientEmbedder(GeminiEmbedder()), NpzEmbeddingCache(_common.CACHE_PATH))
    corpus = load_benign_corpus()
    corpus_vecs = await matcher.embed_texts([s["transfer_note"] for s in corpus])
    if corpus_vecs is None:
        print("LỖI: không embed được tập sạch (quota?) — chạy lại sau")
        return 2

    rows: list[Scored] = []
    used, skipped = [], []
    for path in compiled:
        rec = json.loads(path.read_text(encoding="utf-8"))
        v = validate_llm_output(rec["compile_raw"])
        if not v.ok:
            skipped.append(f"{rec['case_id']} (validator: {v.errors[0]})")
            continue
        rule = assemble_rule(v.sanitized_draft, rule_id=f"CAL-{rec['case_id']}", version=1,
                             source_incident_id=rec["case_id"], ttl_hours=24, threshold=-1.0)
        anchors = await matcher.prepare_anchors(semantic_phrases(rule))
        if anchors.vectors is None:
            print(f"LỖI: không embed được anchor của {rec['case_id']}")
            return 2
        case = json.loads((DEV_DIR / f"{rec['case_id']}.json").read_text(encoding="utf-8"))
        txs = case["transactions_B"]
        tx_vecs = await matcher.embed_texts([t["transfer_note"] for t in txs])
        if tx_vecs is None:
            print("LỖI: không embed được giao dịch dev")
            return 2
        used.append(rec["case_id"])
        for t, vec in zip(txs, tx_vecs):
            kind = "VARIANT" if t["label"] == "SCAM" and t["is_variant"] else ("LEGIT_DEV" if t["label"] == "LEGIT" else None)
            if kind is None:
                continue
            note_vec = vec if len(norm_match(t["transfer_note"])) >= 4 else None
            sem, tri = _score(rule, _tx(t["transfer_note"], t["amount_vnd"], t["to_account_id"]), anchors, note_vec)
            if note_vec is None:
                sem = None
            rows.append(Scored(kind, rec["case_id"], t["transfer_note"], sem, tri))
        for s, vec in zip(corpus, corpus_vecs):
            sem, tri = _score(rule, _tx(s["transfer_note"], int(s["amount_vnd"]),
                                        "ACC-TAX-GOV" if s.get("is_verified_biller") else "ACC-CAL"), anchors, vec)
            rows.append(Scored("BENIGN", rec["case_id"], s["transfer_note"], sem, tri))

    sem_table, tri_table = sweep(rows, SEM_RANGE, "sem"), sweep(rows, TRI_RANGE, "tri")
    sem_pick, tri_pick = choose(sem_table), choose(tri_table)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    top_benign = sorted((r for r in rows if r.kind != "VARIANT" and r.sem is not None), key=lambda r: -r.sem)[:15]
    variant_scores = sorted((r for r in rows if r.kind == "VARIANT"), key=lambda r: (r.sem is None, -(r.sem or 0)))
    report = {
        "generated_at": stamp, "dev_rules_used": used, "dev_rules_skipped": skipped,
        "benign_samples": len(corpus), "pairs_checked": sum(r.kind != "VARIANT" for r in rows),
        "semantic": {"pick": sem_pick, "table": sem_table},
        "trigram": {"pick": tri_pick, "table": tri_table},
        "variants": [{"case": r.case_id, "note": r.note, "sem": r.sem, "tri": r.tri} for r in variant_scores],
        "top_benign": [{"case": r.case_id, "kind": r.kind, "note": r.note, "sem": r.sem} for r in top_benign],
    }
    (RESULTS_DIR / f"calibration_{stamp}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n",
                                                          encoding="utf-8")
    md = [f"# Hiệu chỉnh ngưỡng (dev) — {stamp}", "",
          f"Luật dev dùng: {len(used)} ({', '.join(used)}). Bỏ qua: {', '.join(skipped) or 'không'}.",
          f"Tập sạch: {len(corpus)} mẫu × {len(used)} luật + giao dịch LEGIT dev = {report['pairs_checked']} cặp.", "",
          "| ngưỡng | biến thể bật câu hỏi | khớp nhầm (sạch) |", "|---|---|---|"]
    md += [f"| {r['threshold']:.2f} | {r['triggered']}/{r['variants']} | {r['flagged']} |" for r in sem_table]
    md += ["", f"**Chọn SEMANTIC_THRESHOLD:** {sem_pick['threshold'] if sem_pick else '—'}",
           f"**Chọn TRIGRAM_THRESHOLD:** {tri_pick['threshold'] if tri_pick else 'KHÔNG CÓ'}"]
    (RESULTS_DIR / f"calibration_{stamp}.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print("\n".join(md[:5]))
    for r in sem_table[::5]:
        print(f"  t={r['threshold']:.2f}  trigger {r['triggered']}/{r['variants']}  flagged {r['flagged']}")
    print(f"\nSEMANTIC pick: {sem_pick}\nTRIGRAM  pick: {tri_pick}")
    print("\nBiến thể (cosine):")
    for r in variant_scores:
        print(f"  {r.case_id} {('%.3f' % r.sem) if r.sem is not None else '  —  '}  {r.note}")
    print("\nMẫu sạch điểm cao nhất:")
    for r in top_benign[:8]:
        print(f"  {r.case_id} {r.sem:.3f} [{r.kind}] {r.note}")
    print(f"\nghi bench/results/calibration_{stamp}.{{json,md}}; request embedding: {matcher.embedder.requests}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
