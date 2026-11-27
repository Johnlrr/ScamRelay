"""Lớp đối tác mô phỏng (SPEC §9): điểm 0–100 + quyết định. Dùng làm đối chứng và làm mức sàn (D9).

Tất định, không gọi AI. `static_scam_keywords.json` chỉ có thủ đoạn đã biết (không có HKD 2026).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.core._contract_draft import PARTNER_WARN_SCORE, BaselineResult, DerivedTx
from app.core.preprocess import norm_match

KEYWORDS_PATH = Path(__file__).resolve().parents[2] / "data" / "static_scam_keywords.json"

# (điểm, mã lý do) — SPEC §9
W_RECIPIENT_NEW = 30
W_AMOUNT_GE_5M = 25
W_YOUNG_ACCOUNT = 15
W_VELOCITY = 50
W_KEYWORD = 60
AMOUNT_HIGH_VND = 5_000_000
YOUNG_ACCOUNT_DAYS = 30
VELOCITY_COUNT = 3


@lru_cache(maxsize=1)
def load_keywords() -> tuple[str, ...]:
    raw = json.loads(KEYWORDS_PATH.read_text(encoding="utf-8"))["keywords"]
    return tuple(dict.fromkeys(k for k in (norm_match(x) for x in raw) if k))


def known_keyword_hit(note: str) -> str | None:
    padded = f" {norm_match(note)} "
    return next((k for k in load_keywords() if f" {k} " in padded), None)


def baseline_score(tx: DerivedTx, *, warn_score: int = PARTNER_WARN_SCORE) -> BaselineResult:
    score, reasons = 0, []
    if tx.recipient_is_new:
        score += W_RECIPIENT_NEW
        reasons.append("RECIPIENT_NEW")
    if tx.amount_vnd >= AMOUNT_HIGH_VND:
        score += W_AMOUNT_GE_5M
        reasons.append("AMOUNT_GE_5M")
    if tx.recipient_account_age_days < YOUNG_ACCOUNT_DAYS:
        score += W_YOUNG_ACCOUNT
        reasons.append("RECIPIENT_ACCOUNT_YOUNG")
    if tx.tx_count_10m >= VELOCITY_COUNT:
        score += W_VELOCITY
        reasons.append("VELOCITY_10M")
    if known_keyword_hit(tx.note_norm or tx.transfer_note):
        score += W_KEYWORD
        reasons.append("KNOWN_SCAM_KEYWORD")
    score = max(0, min(100, score))

    if tx.account_compromise_flag:
        decision = "BLOCK"
        reasons.append("ACCOUNT_COMPROMISE_LOCKED")
    elif score >= warn_score:
        decision = "WARN"
    else:
        decision = "ALLOW"
    return BaselineResult(decision=decision, risk_score=score, reasons=reasons)
