"""StagePolicy và thứ tự mức nghiêm (SPEC §7.3, ABOUT §4.3). Tất định, không gọi AI.

Hành động CHỈ được chọn ở đây (INV-07): nhãn ý nghĩa × giai đoạn luật → hành động,
sau đó lấy mức nghiêm nhất với mức sàn (lớp đối tác + khoanh vùng) (INV-13).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.gateway import Decision, PartnerDecision
from app.schemas.rule import Outcome, Stage

SEVERITY: dict[str, int] = {
    "ALLOW": 0,
    "ALLOW_WITH_WARNING": 1,
    "HOLD_15M": 2,
    "STOP_AND_EXPLAIN": 3,
    "HOLD_UNTIL_VERIFIED": 4,
    "BLOCK": 5,
}

# Lớp đối tác (baseline) → quyết định cuối tương ứng (SPEC §9)
PARTNER_MAP: dict[str, Decision] = {"ALLOW": "ALLOW", "WARN": "HOLD_15M", "BLOCK": "BLOCK"}

# Chỉ hai giai đoạn này mới hỏi; SHADOW_LOG chỉ ghi log
STAGE_POLICY: dict[str, dict[str, Decision]] = {
    "ASK_ONLY": {"TACTIC_MATCH": "STOP_AND_EXPLAIN", "BENIGN": "ALLOW_WITH_WARNING", "UNCLEAR": "HOLD_15M"},
    "ENFORCE_HOLD": {"TACTIC_MATCH": "HOLD_UNTIL_VERIFIED", "BENIGN": "ALLOW_WITH_WARNING", "UNCLEAR": "HOLD_15M"},
}

LIVE_STAGES: tuple[str, ...] = ("ASK_ONLY", "ENFORCE_HOLD")
STAGE_RANK: dict[str, int] = {"SHADOW_LOG": 0, "ASK_ONLY": 1, "ENFORCE_HOLD": 2}

# Tập quyết định "được dừng", dùng chung cho baseline và ScamRelay khi đo (SPEC §13.4)
STOPPED_SET: frozenset[str] = frozenset({"HOLD_15M", "STOP_AND_EXPLAIN", "HOLD_UNTIL_VERIFIED", "BLOCK"})


def max_severity(*decisions: Decision) -> Decision:
    """Mức nghiêm nhất trong các quyết định (không có đầu vào → ALLOW)."""
    return max(decisions, key=SEVERITY.__getitem__, default="ALLOW")


def partner_floor(decision: PartnerDecision) -> Decision:
    return PARTNER_MAP[decision]


def stage_action(stage: Stage, outcome: Outcome) -> Decision | None:
    """Hành động của luật cho một câu trả lời; None nếu giai đoạn không còn hiệu lực (không áp)."""
    return STAGE_POLICY.get(stage, {}).get(outcome)


@dataclass
class Floor:
    """Mức sàn của một giao dịch: chỉ nâng, không bao giờ hạ (D9)."""

    decision: Decision = "ALLOW"
    reasons: list[str] = field(default_factory=list)

    def raise_to(self, decision: Decision, reason: str) -> Floor:
        if SEVERITY[decision] > SEVERITY[self.decision]:
            self.decision = decision
        if reason not in self.reasons:
            self.reasons.append(reason)
        return self

    def to_dict(self) -> dict:
        return {"decision": self.decision, "reasons": list(self.reasons)}

    @classmethod
    def from_dict(cls, d: dict) -> Floor:
        return cls(decision=d["decision"], reasons=list(d.get("reasons", [])))
