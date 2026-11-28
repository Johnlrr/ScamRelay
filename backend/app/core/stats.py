"""Bảng theo dõi luật — khép vòng "Relay" (SPEC §7.2h, ABOUT §3.2; mục "có thể có").

Đếm từ audit log `rule_event` (gateway đã ghi CHALLENGE_ISSUED / ANSWERED / SHADOW_HIT). Chỉ đọc.
`suggest_upgrade` chỉ là GỢI Ý cho chuyên viên, không bao giờ tự nâng giai đoạn luật.
Schema đặt ở đây (không phải `schemas/**`) để không động vào file hợp đồng; vẫn hiện trong /openapi.json.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlmodel import Session, select

from app.models import RelayRuleRow, RuleEvent

SUGGEST_UPGRADE_MIN_TACTIC = 2           # SPEC §7.2h: answered.TACTIC_MATCH ≥ 2 và stage == ASK_ONLY
HIT_EVENTS = ("SHADOW_HIT", "CHALLENGE_ISSUED")


class AnsweredCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    TACTIC_MATCH: int = 0
    BENIGN: int = 0
    UNCLEAR: int = 0


class RuleStats(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule_id: str
    stage: str
    asked: int                           # số lần câu hỏi mục đích được hiển thị
    answered: AnsweredCounts             # người dùng tự chọn (nhãn ý nghĩa do server tra, không từ client)
    shadow_hits: int                     # khớp Lớp 1 khi luật còn SHADOW_LOG (chỉ ghi log, không hỏi)
    fp_reports: int                      # "Báo nhầm" (FP_REPORTED)
    last_hit_at: datetime | None
    suggest_upgrade: bool
    suggest_upgrade_reason_vi: str | None


def rule_stats(s: Session, row: RelayRuleRow) -> RuleStats:
    events = s.exec(select(RuleEvent).where(RuleEvent.workspace_id == row.workspace_id,
                                            RuleEvent.rule_id == row.id)).all()
    answered = AnsweredCounts()
    asked = shadow = fp = 0
    last: datetime | None = None
    for e in events:
        if e.event == "CHALLENGE_ISSUED":
            asked += 1
        elif e.event == "SHADOW_HIT":
            shadow += 1
        elif e.event == "FP_REPORTED":
            fp += 1
        elif e.event == "ANSWERED":
            outcome = (e.payload or {}).get("outcome")
            if outcome in AnsweredCounts.model_fields:
                setattr(answered, outcome, getattr(answered, outcome) + 1)
        if e.event in HIT_EVENTS and (last is None or e.created_at > last):
            last = e.created_at
    suggest = row.stage == "ASK_ONLY" and answered.TACTIC_MATCH >= SUGGEST_UPGRADE_MIN_TACTIC
    reason = (f"{answered.TACTIC_MATCH} người dùng đã tự chọn mục đích khớp thủ đoạn. Có thể cân nhắc nâng lên "
              "ENFORCE_HOLD (vẫn cần đủ 2 báo cáo độc lập và chuyên viên duyệt lần hai).") if suggest else None
    return RuleStats(rule_id=row.id, stage=row.stage, asked=asked, answered=answered, shadow_hits=shadow,
                     fp_reports=fp, last_hit_at=last, suggest_upgrade=suggest, suggest_upgrade_reason_vi=reason)
