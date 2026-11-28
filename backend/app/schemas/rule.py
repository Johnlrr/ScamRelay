"""Luồng 2 — RelayRule (SPEC §6.3b, §6.4, §7.2)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from app.schemas.common import Strict
from app.schemas.llm_rule import FieldName, LLMOutcome, OpName

Outcome = Literal["BENIGN", "TACTIC_MATCH", "UNCLEAR"]
Stage = Literal["DRAFT_INVALID", "SHADOW_LOG", "ASK_ONLY", "ENFORCE_HOLD", "ROLLED_BACK", "EXPIRED"]
ApproveStage = Literal["ASK_ONLY", "ENFORCE_HOLD"]
CompileSource = Literal["LLM", "CACHED_FALLBACK"]


# ---------------------------------------------------------------- bản nháp (domain, chuyên viên sửa được)


class Condition(Strict):
    field: FieldName
    op: OpName
    value_int: int | None = None
    value_bool: bool | None = None
    value_str_list: list[str] | None = None
    anchor_phrases: list[str] | None = None


class PurposeOption(Strict):
    label_vi: str
    outcome: LLMOutcome


class PurposeQuestion(Strict):
    question_vi: str
    options: list[PurposeOption]
    tactic_alert_vi: str


class StructuredVariant(Strict):
    transfer_note: str
    amount_vnd: int
    manipulation_intent: str


class RelayRuleDraft(Strict):
    tactic_family: str
    match_mode: Literal["ALL"] = "ALL"
    conditions: list[Condition]
    behavior_hints: list[Condition] = []
    purpose_question: PurposeQuestion
    variants: list[StructuredVariant]


# ---------------------------------------------------------------- luật hoàn chỉnh (server dựng)


class RuleOption(Strict):
    id: str                                      # "o1".."o4", server gán
    label_vi: str
    outcome: Outcome


class Approval(Strict):
    by: str
    stage: Stage
    at: datetime
    override_reason: str | None = None


class Lifecycle(Strict):
    stage: Stage
    ttl_hours: int
    expires_at: datetime
    corroboration_count: int
    approvals: list[Approval]
    benign_regression: dict | None               # {"checked": 240, "flagged": 0}
    variant_coverage: dict | None                # {"checked": 6, "triggered": 6}
    edited_by_human: bool


class ObservableSignals(Strict):
    match_mode: Literal["ALL"] = "ALL"
    conditions: list[Condition]                  # điều kiện nội dung (đã qua validator)
    guard_conditions: list[Condition]            # điều kiện sàn, server gắn (S4)
    normalize: list[str]
    threshold: float                             # config.SEMANTIC_THRESHOLD


class JitQuestion(Strict):
    question_vi: str
    options: list[RuleOption]                    # 4 phương án; UNCLEAR luôn ở cuối
    tactic_alert_vi: str
    anti_coaching_notice_vi: str


class RelayRule(Strict):
    rule_id: str                                 # "RL-20261128-0001"
    version: int
    source_incident_id: str
    target_scope: Literal["TACTIC_PATTERN"] = "TACTIC_PATTERN"
    tactic_family: str
    lifecycle: Lifecycle
    observable_signals: ObservableSignals
    behavior_hints: list[Condition]
    jit_purpose_question: JitQuestion
    variants: list[StructuredVariant]


# ---------------------------------------------------------------- kiểu dùng chung (SPEC §6.4)


class ValidationResult(BaseModel):
    ok: bool
    errors: list[str] = []
    warnings: list[str] = []                     # V3 chuyển điều kiện, V8 gỡ trường quyền, V6b
    sanitized_draft: RelayRuleDraft | None = None


class CompileResult(BaseModel):
    raw: dict                                    # JSON thô; router đưa vào validate_llm_output
    source: CompileSource
    degraded: bool = False
    llm_seconds: float


@dataclass
class AnchorSet:
    phrases: list[str]                           # đã qua norm_match
    vectors: np.ndarray | None                   # (N, dim) float32, L2; None khi chạy trigram
    degraded: bool = False


class FlaggedExample(BaseModel):
    transfer_note: str
    amount_vnd: int
    score: float
    top_anchor: str | None


class RegressionResult(BaseModel):
    rule_version: int
    benign_checked: int
    benign_flagged: int
    flagged_examples: list[FlaggedExample]
    flags_by_anchor: dict[str, int]              # anchor gây nhiều khớp nhầm nhất
    variants_checked: int
    variants_triggered: int
    variants_missed: list[str]
    seconds: float
    degraded: bool


# ---------------------------------------------------------------- API /v1/fraudops


class CompileRequest(Strict):
    incident_id: str


class RuleView(BaseModel):
    """Trạng thái đầy đủ của một luật cho màn /ops."""

    rule_id: str
    version: int
    stage: Stage
    source_incident_id: str
    tactic_family: str
    rule: RelayRule | None                       # None khi DRAFT_INVALID chưa dựng được
    draft: RelayRuleDraft | None                 # phần chuyên viên sửa được (PUT draft)
    validation: ValidationResult | None
    regression: RegressionResult | None          # chỉ khi khớp version hiện tại
    source: CompileSource | None
    degraded: bool
    edited_by_human: bool
    corroboration_count: int
    ttl_hours: int
    expires_at: datetime | None
    activated_at: datetime | None
    compile_requested_at: datetime | None
    ai_seconds: float


class RuleSummary(BaseModel):
    rule_id: str
    version: int
    stage: Stage
    tactic_family: str
    source_incident_id: str
    edited_by_human: bool
    expires_at: datetime | None
    activated_at: datetime | None
    benign_flagged: int | None = None            # của regression version hiện tại (nếu có)


class ApproveRequest(Strict):
    stage: ApproveStage
    ttl_hours: int = Field(24, ge=1, le=72)
    override_reason: str | None = None           # ≥ 15 ký tự khi benign_flagged > 0


class ActivationClock(BaseModel):
    """Đồng hồ 2 mốc (SPEC §7.2f)."""

    ai_seconds: float                            # compile + mọi lượt regression
    human_seconds: float                         # (approved_at − compile_requested_at) − ai_seconds
    report_to_live_seconds: float | None         # activated_at − incident.submitted_at


class ApproveResponse(BaseModel):
    rule: RuleView
    clock: ActivationClock
