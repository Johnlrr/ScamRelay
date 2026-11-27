"""Lưu output compile LLM THẬT của 3 thủ đoạn mẫu vào backend/data/fallback_tactics.json (SPEC D7).

    backend/.venv/bin/python bench/save_fallback.py

Lấy từ `bench/dev_compiled/<ca>.json` (do compile_dev.py ghi từ lượt gọi LLM thật). Chỉ chép NGUYÊN VĂN
`compile_raw` — không sửa tay (AGENTS §6). Ca nào không đạt (không phải source LLM, validator lỗi, sai
thủ đoạn) thì bỏ qua và báo; mục cũ trong file giữ nguyên.
"""

from __future__ import annotations

import json
import sys

import _common

from app.core.validator import validate_llm_output

FALLBACK_PATH = _common.BACKEND / "data" / "fallback_tactics.json"
COMPILED_DIR = _common.BENCH / "dev_compiled"
SOURCES = {                       # thủ đoạn → ca dev dùng làm nguồn
    "FAKE_HKD_TAX_VERIFICATION": "D-01",
    "RECOVERY_FEE_SCAM": "D-05",
    "IMPERSONATE_AUTHORITY": "D-11",
}


def main() -> int:
    data = json.loads(FALLBACK_PATH.read_text(encoding="utf-8"))
    problems = []
    for family, case_id in SOURCES.items():
        path = COMPILED_DIR / f"{case_id}.json"
        if not path.exists():
            problems.append(f"{family}: thiếu {path.name}")
            continue
        rec = json.loads(path.read_text(encoding="utf-8"))
        v = validate_llm_output(rec["compile_raw"])
        if rec.get("source") != "LLM":
            problems.append(f"{family}: {case_id} không phải output LLM trực tiếp")
        elif not v.ok:
            problems.append(f"{family}: {case_id} không qua validator: {v.errors[:2]}")
        elif rec["analysis"]["tactic_family"] != family or rec["compile_raw"].get("tactic_family") != family:
            problems.append(f"{family}: {case_id} được phân loại khác ({rec['analysis']['tactic_family']})")
        else:
            data["tactics"][family]["compile_output"] = rec["compile_raw"]
            data["tactics"][family]["compile_meta"] = {
                "case_id": case_id, "model": rec["model"], "prompts": rec["prompts"],
                "generated_at": rec["generated_at"], "validator_warnings": v.warnings,
            }
            print(f"{family}: lưu từ {case_id} ({rec['model']}, {rec['generated_at']})")
    FALLBACK_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for p in problems:
        print("BỎ QUA —", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
