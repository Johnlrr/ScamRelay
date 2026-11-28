"""Chạy analyze → compile bằng LLM THẬT cho các ca dev, lưu output thô để hiệu chỉnh ngưỡng và làm dự phòng.

    backend/.venv/bin/python bench/compile_dev.py [D-01 D-05 ...] [--force]

- Mỗi ca ghi `bench/dev_compiled/<case_id>.json`: analysis + compile raw + validation + metadata
  (model, phiên bản prompt, thời điểm, source). Chỉ ghi khi source == "LLM" (không ghi kết quả dự phòng).
- Ca đã có file thì bỏ qua (tiết kiệm quota), trừ khi `--force`.
- CHỈ chạy trên tập dev. Không bao giờ trỏ vào held-out.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone

import _common

from app.ai import incident_ai, llm_client, rule_ai
from app.core.preprocess import mask_pii
from app.core.validator import validate_llm_output

DEV_DIR = _common.BENCH / "cases" / "dev"
OUT_DIR = _common.BENCH / "dev_compiled"
PAUSE_S = 8          # giãn request cho gói miễn phí


async def compile_case(path, force: bool) -> str:
    case = json.loads(path.read_text(encoding="utf-8"))
    out = OUT_DIR / f"{case['case_id']}.json"
    if out.exists() and not force:
        return f"{case['case_id']}: đã có, bỏ qua"
    if "heldout" in str(path).lower():
        raise SystemExit("từ chối: script này chỉ chạy trên tập dev")
    masked = mask_pii(case["incident_A"]["text"])
    t0 = time.perf_counter()
    analyzed = await incident_ai.analyze_incident(masked.text, None, masked.otp_mentioned, [])
    if analyzed.degraded:
        return f"{case['case_id']}: analyze rơi vào fallback (LLM lỗi) — không lưu"
    compiled = await rule_ai.compile_rule(analyzed.analysis)
    if compiled.source != "LLM":
        return f"{case['case_id']}: compile rơi vào fallback — không lưu"
    v = validate_llm_output(compiled.raw)
    llm = llm_client.get_llm()
    record = {
        "case_id": case["case_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": llm.model if llm else None,
        "prompts": [incident_ai.PROMPT_VERSION, rule_ai.PROMPT_VERSION],
        "retry_prompt_if_unaccented": rule_ai.FIX_DIACRITICS_VERSION,
        "source": compiled.source,
        "analysis": analyzed.analysis.model_dump(mode="json"),
        "compile_raw": compiled.raw,
        "compile_seconds": round(compiled.llm_seconds, 2),
        "total_seconds": round(time.perf_counter() - t0, 2),
        "validation": {"ok": v.ok, "errors": v.errors, "warnings": v.warnings},
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    fam_ok = analyzed.analysis.tactic_family == case["expected_A"]["tactic_family"]
    return (f"{case['case_id']}: {analyzed.analysis.tactic_family} ({'đúng' if fam_ok else 'SAI'}), "
            f"validator {'OK' if v.ok else 'LỖI ' + '; '.join(v.errors[:2])}, {record['total_seconds']}s")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cases", nargs="*")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    _common.load_env()
    if llm_client.get_llm() is None:
        print("thiếu GEMINI_API_KEY")
        return 2
    paths = sorted(DEV_DIR.glob("*.json"))
    if args.cases:
        paths = [p for p in paths if p.stem in set(args.cases)]
    for i, p in enumerate(paths):
        if i:
            await asyncio.sleep(PAUSE_S)
        print(await compile_case(p, args.force), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
