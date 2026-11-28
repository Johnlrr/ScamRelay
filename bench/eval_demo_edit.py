"""So sánh hai cách chuyên viên sửa luật trong demo, trên các luật HKD đã biên dịch của tập dev (offline).

- `exclude`: thêm cụm loại trừ vào NOT_CONTAINS_ANY (bench/_expert.py) — cách đã chốt cho demo (28/11).
- `remove`: xóa mọi câu mẫu được tô đậm (cách cũ).

Đo sau khi sửa: mẫu sạch còn khớp nhầm, biến thể của luật còn bật, câu demo của chú Hùng còn khớp Lớp 1.
Embedding thật (cache file bench/.cache + seed), chỉ tốn request cho câu chưa có.

    python bench/eval_demo_edit.py
"""

from __future__ import annotations

import asyncio
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import _common
from _expert import add_exclusions

from app.core.assembler import assemble_rule
from app.core.layer1 import layer1_explain, semantic_phrases
from app.core.preprocess import norm_match
from app.core.regression import run_regression
from app.core.semantic import GeminiEmbedder, NpzEmbeddingCache, SemanticMatcher, preload_seed
from app.core.validator import validate_llm_output
from app.schemas.gateway import DerivedTx

DEV_COMPILED = _common.BENCH / "dev_compiled"
RESULTS = _common.BENCH / "results"
HUNG_NOTE = "xac thuc ho so cap nhat thue HKD"
MAX_ROUNDS = 3


def hung_tx() -> DerivedTx:
    return DerivedTx(wallet_id="W-HUNG", to_account_id="ACC-OLD-7731", amount_vnd=1_200_000, transfer_note=HUNG_NOTE,
                     note_norm=norm_match(HUNG_NOTE), recipient_is_new=True, recipient_account_age_days=420,
                     tx_count_10m=0, is_verified_biller=False, is_known_contact=False, account_compromise_flag=False)


async def evaluate(m: SemanticMatcher, draft: dict) -> tuple:
    v = validate_llm_output(draft)
    if not v.ok:
        return None, None, None, v.errors
    rule = assemble_rule(v.sanitized_draft, rule_id="RL-EVAL", version=1, source_incident_id="INC", ttl_hours=24)
    anchors = await m.prepare_anchors(semantic_phrases(rule))
    reg = await run_regression(rule, anchors, matcher=m)
    tx = hung_tx()
    d = layer1_explain(rule, tx, anchors, note_vec=await m.note_vector(tx.note_norm))
    return reg, d, rule, []


async def run_strategy(m: SemanticMatcher, raw: dict, strategy: str) -> dict:
    draft = copy.deepcopy(raw)
    reg, d, _, errs = await evaluate(m, draft)
    first = {"flagged": reg.benign_flagged, "notes": [f.transfer_note for f in reg.flagged_examples],
             "hung": d.matched, "hung_score": round(d.semantic_score or 0, 3)}
    changes, rounds = [], 0
    while reg is not None and reg.benign_flagged and rounds < MAX_ROUNDS:
        rounds += 1
        if strategy == "exclude":
            added = add_exclusions(draft, [f.transfer_note for f in reg.flagged_examples])
            changes += [f"+{a}" for a in added]
            if added:
                pass
            else:
                # không còn cụm loại trừ phù hợp: xóa câu mẫu được tô đậm cho các mẫu còn lại (cách cũ)
                bad = set(reg.flags_by_anchor)
                for c in draft["conditions"]:
                    if c["op"] == "SEMANTIC_MATCH":
                        changes += [f"-{a}" for a in c["anchor_phrases"] if norm_match(a) in bad]
                        c["anchor_phrases"] = [a for a in c["anchor_phrases"] if norm_match(a) not in bad]
        else:
            bad = set(reg.flags_by_anchor)
            for c in draft["conditions"]:
                if c["op"] == "SEMANTIC_MATCH":
                    changes += [f"-{a}" for a in c["anchor_phrases"] if norm_match(a) in bad]
                    c["anchor_phrases"] = [a for a in c["anchor_phrases"] if norm_match(a) not in bad]
        reg, d, _, errs = await evaluate(m, draft)
    return {"first": first, "rounds": rounds, "changes": changes, "errors": errs,
            "flagged": None if reg is None else reg.benign_flagged,
            "variants": None if reg is None else f"{reg.variants_triggered}/{reg.variants_checked}",
            "hung": None if d is None else d.matched, "hung_score": None if d is None else round(d.semantic_score or 0, 3),
            "degraded": None if reg is None else reg.degraded}


async def main() -> None:
    _common.load_env()
    cache = NpzEmbeddingCache(_common.CACHE_PATH)
    preload_seed(cache)
    m = SemanticMatcher(_common.PatientEmbedder(GeminiEmbedder()), cache)
    rows = []
    for f in sorted(DEV_COMPILED.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        if data["analysis"]["tactic_family"] != "FAKE_HKD_TAX_VERIFICATION":
            continue
        res = {s: await run_strategy(m, data["compile_raw"], s) for s in ("exclude", "remove")}
        rows.append((data["case_id"], res))
        print(data["case_id"], {s: (r["flagged"], r["variants"], r["hung"], r["changes"]) for s, r in res.items()})

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")
    n = len(rows)
    flagged_any = [c for c, r in rows if r["exclude"]["first"]["flagged"]]

    def count(strategy: str, key: str, val) -> int:
        return sum(r[strategy][key] == val for _, r in rows)

    lines = [f"# Cách sửa luật trong demo: thêm cụm loại trừ hay xóa câu mẫu ({ts})", "",
             "Offline, luật HKD đã biên dịch của tập dev (`bench/dev_compiled`), embedding thật, ngưỡng theo `config.py`.",
             "Chuyên viên được mô phỏng bằng quy tắc tất định trong `bench/_expert.py` (không nhìn câu demo).", "",
             f"- Luật có khớp nhầm ở lần kiểm thử đầu: {len(flagged_any)}/{n}",
             f"- Câu demo khớp trước khi sửa: {sum(r['exclude']['first']['hung'] for _, r in rows)}/{n}", "",
             "| Cách sửa | Hết khớp nhầm | Câu demo của chú Hùng còn khớp |", "|---|---|---|",
             f"| Thêm cụm loại trừ | {count('exclude', 'flagged', 0)}/{n} | {count('exclude', 'hung', True)}/{n} |",
             f"| Xóa câu mẫu được tô đậm | {count('remove', 'flagged', 0)}/{n} | {count('remove', 'hung', True)}/{n} |", "",
             "| Ca | Khớp nhầm lần đầu | Loại trừ: thêm | còn nhầm / biến thể / Hùng | Xóa: bỏ | còn nhầm / biến thể / Hùng |",
             "|---|---|---|---|---|---|"]
    for case, r in rows:
        e, x = r["exclude"], r["remove"]
        lines.append(f"| {case} | {e['first']['flagged']} ({'; '.join(e['first']['notes'][:3])}) | "
                     f"{', '.join(e['changes']) or '-'} | {e['flagged']} / {e['variants']} / {e['hung']} ({e['hung_score']}) | "
                     f"{', '.join(x['changes']) or '-'} | {x['flagged']} / {x['variants']} / {x['hung']} ({x['hung_score']}) |")
    out = RESULTS / f"demo_edit_eval_{ts}.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (RESULTS / f"demo_edit_eval_{ts}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print("→", out)


if __name__ == "__main__":
    asyncio.run(main())
