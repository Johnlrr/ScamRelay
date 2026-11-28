"""Đo chế độ dự phòng của analyze (classifier từ khóa, khi Gemini lỗi) trên các ca dev. Không gọi API.

    backend/.venv/bin/python bench/eval_fallback.py

Báo: đúng thủ đoạn x/n; mode tính theo quy tắc containment SPEC §6.1 đúng x/n; ca nào bị kết luận "NO"
(không được phép, INV-03). Kết quả: bench/results/fallback_eval_<thời điểm>.md
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

import _common

from app.ai.incident_ai import keyword_fallback
from app.core.preprocess import mask_pii


def mode_of(a) -> str:
    # Sao y quy tắc SPEC §6.1 (containment.py của linh tính thật; ở đây chỉ để đo)
    if "YES" in (a.otp_or_password_disclosed, a.remote_app_installed):
        return "COMPROMISE"
    if a.money_requested_vnd or a.manipulation_cues:
        return "MANIPULATION"
    return "UNCLEAR"


def main() -> int:
    rows, fam_ok, mode_ok, unsafe = [], 0, 0, 0
    cases = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((_common.BENCH / "cases" / "dev").glob("*.json"))]
    for c in cases:
        m = mask_pii(c["incident_A"]["text"])
        a = keyword_fallback(m.text, m.otp_mentioned)
        mode = mode_of(a)
        exp = c["expected_A"]
        fam_ok += a.tactic_family == exp["tactic_family"]
        mode_ok += mode == exp["mode"]
        unsafe += "NO" in (a.otp_or_password_disclosed, a.remote_app_installed)
        rows.append(f"| {c['case_id']} | {exp['tactic_family']} | {a.tactic_family} | {exp['mode']} | {mode} |")
    n = len(cases)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")
    md = [f"# Chế độ dự phòng của analyze (từ khóa) trên dev — {stamp}", "",
          f"- Đúng thủ đoạn: {fam_ok}/{n}", f"- Đúng mode (quy tắc SPEC §6.1): {mode_ok}/{n}",
          f"- Ca bị kết luận NO cho OTP/ứng dụng lạ (không được phép): {unsafe}/{n}",
          "- Mode UNCLEAR vẫn trả 3 việc an toàn mặc định (INV-03).",
          "- **Hạn chế:** từ khóa dự phòng và ca dev do cùng một người viết, nên con số này lạc quan; "
          "không dùng làm số liệu độc lập trên slide. Văn bản không chứa từ khóa nào → OTHER_NEW / UNCLEAR.", "",
          "| Ca | Thủ đoạn đúng | Dự phòng | Mode đúng | Dự phòng |", "|---|---|---|---|---|", *rows]
    out = _common.BENCH / "results" / f"fallback_eval_{stamp}.md"
    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
