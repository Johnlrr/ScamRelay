"""TẠM THỜI — bản sao SPEC §6 (v2) và các hằng số SPEC §14.5 để bao viết và test trước Contract Drop.

Khi Contract Drop của linh lên main:
- kiểu dữ liệu → `app.schemas.rule` / `app.schemas.incident` / `app.schemas.llm_*` / `app.ai.interfaces`
- hằng số → `app.config`
rồi xóa file này. Chỉ module của bao import file này; không import từ router hay code của người khác.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict

# ============================================================ hằng số (SPEC §14.5) — TODO: app.config


def _env_float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


LLM_MODEL = os.environ.get("LLM_MODEL", "gemini-3.5-flash-lite")   # SPEC §0, chốt 28/11
EMBED_MODEL = os.environ.get("EMBED_MODEL", "gemini-embedding-001")
EMBED_DIM = _env_int("EMBED_DIM", 768)
SEMANTIC_THRESHOLD = _env_float("SEMANTIC_THRESHOLD", 0.90)   # SPEC §8.3, bench/results/calibration_20261128T0036Z.md
TRIGRAM_THRESHOLD = _env_float("TRIGRAM_THRESHOLD", 0.60)     # SPEC §8.3, cùng file kết quả
MIN_ASK_AMOUNT_VND = _env_int("MIN_ASK_AMOUNT_VND", 200_000)
PARTNER_WARN_SCORE = _env_int("PARTNER_WARN_SCORE", 50)
DEFAULT_RULE_TTL_HOURS = _env_int("DEFAULT_RULE_TTL_HOURS", 24)
ANTI_COACHING_NOTICE_VI = (
    "Nếu có người dặn bạn chọn một đáp án cụ thể ở màn hình này, đó là dấu hiệu lừa đảo. "
    "Hãy dừng lại và gọi kênh chính thức."
)

# ============================================================ RelayRule (SPEC §6.3)

FieldName = Literal[
    "transfer_note", "amount_vnd", "recipient_is_new", "recipient_account_age_days",
    "tx_count_10m", "is_verified_biller", "account_compromise_flag", "partner_risk_score",
]
OpName = Literal["EQ", "LTE", "GTE", "SEMANTIC_MATCH", "CONTAINS_ANY", "NOT_CONTAINS_ANY"]
LLMOutcome = Literal["BENIGN", "TACTIC_MATCH"]
Outcome = Literal["BENIGN", "TACTIC_MATCH", "UNCLEAR"]
Stage = Literal["DRAFT_INVALID", "SHADOW_LOG", "ASK_ONLY", "ENFORCE_HOLD", "ROLLED_BACK", "EXPIRED"]


# ---- lớp LLM (response_schema): phẳng, không extra=forbid, không ràng buộc độ dài
class ConditionLLM(BaseModel):
    field: FieldName
    op: OpName
    value_int: int | None = None
    value_bool: bool | None = None
    value_str_list: list[str] | None = None
    anchor_phrases: list[str] | None = None


class PurposeOptionLLM(BaseModel):
    label_vi: str
    outcome: LLMOutcome


class PurposeQuestionLLM(BaseModel):
    question_vi: str
    options: list[PurposeOptionLLM]
    tactic_alert_vi: str


class StructuredVariantLLM(BaseModel):
    transfer_note: str
    amount_vnd: int
    manipulation_intent: str


class RelayRuleDraftLLM(BaseModel):
    tactic_family: str
    conditions: list[ConditionLLM]
    purpose_question: PurposeQuestionLLM
    variants: list[StructuredVariantLLM]


# ---- lớp domain
class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Condition(_Strict):
    field: FieldName
    op: OpName
    value_int: int | None = None
    value_bool: bool | None = None
    value_str_list: list[str] | None = None
    anchor_phrases: list[str] | None = None


class PurposeOption(_Strict):
    label_vi: str
    outcome: LLMOutcome


class PurposeQuestion(_Strict):
    question_vi: str
    options: list[PurposeOption]
    tactic_alert_vi: str


class StructuredVariant(_Strict):
    transfer_note: str
    amount_vnd: int
    manipulation_intent: str


class RelayRuleDraft(_Strict):
    tactic_family: str
    match_mode: Literal["ALL"] = "ALL"
    conditions: list[Condition]
    behavior_hints: list[Condition] = []
    purpose_question: PurposeQuestion
    variants: list[StructuredVariant]


class RuleOption(_Strict):
    id: str
    label_vi: str
    outcome: Outcome


class Approval(_Strict):
    by: str
    stage: Stage
    at: datetime
    override_reason: str | None = None


class Lifecycle(_Strict):
    stage: Stage
    ttl_hours: int
    expires_at: datetime
    corroboration_count: int
    approvals: list[Approval]
    benign_regression: dict | None
    variant_coverage: dict | None
    edited_by_human: bool


class ObservableSignals(_Strict):
    match_mode: Literal["ALL"] = "ALL"
    conditions: list[Condition]
    guard_conditions: list[Condition]
    normalize: list[str]
    threshold: float


class JitQuestion(_Strict):
    question_vi: str
    options: list[RuleOption]
    tactic_alert_vi: str
    anti_coaching_notice_vi: str


class RelayRule(_Strict):
    rule_id: str
    version: int
    source_incident_id: str
    target_scope: Literal["TACTIC_PATTERN"] = "TACTIC_PATTERN"
    tactic_family: str
    lifecycle: Lifecycle
    observable_signals: ObservableSignals
    behavior_hints: list[Condition]
    jit_purpose_question: JitQuestion
    variants: list[StructuredVariant]


# ============================================================ kiểu dùng chung (SPEC §6.4)


class ValidationResult(BaseModel):
    ok: bool
    errors: list[str] = []
    warnings: list[str] = []
    sanitized_draft: RelayRuleDraft | None = None


class CompileResult(BaseModel):
    raw: dict
    source: Literal["LLM", "CACHED_FALLBACK"]
    degraded: bool = False
    llm_seconds: float


@dataclass
class AnchorSet:
    phrases: list[str]                 # đã qua norm_match
    vectors: np.ndarray | None         # (N, dim) float32, L2-normalized; None khi chạy trigram
    degraded: bool = False


class DerivedTx(BaseModel):
    wallet_id: str
    to_account_id: str
    amount_vnd: int
    transfer_note: str
    note_norm: str
    recipient_is_new: bool
    recipient_account_age_days: int
    tx_count_10m: int
    is_verified_biller: bool
    is_known_contact: bool
    account_compromise_flag: bool
    partner_risk_score: int | None = None


class BaselineResult(BaseModel):
    decision: Literal["ALLOW", "WARN", "BLOCK"]
    risk_score: int
    reasons: list[str]


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
    flags_by_anchor: dict[str, int]
    variants_checked: int
    variants_triggered: int
    variants_missed: list[str]
    seconds: float
    degraded: bool


# ============================================================ IncidentAnalysis (SPEC §6.1)

TacticFamily = Literal[
    "FAKE_HKD_TAX_VERIFICATION", "RECOVERY_FEE_SCAM", "FAKE_SUPPORT_REMOTE_APP",
    "IMPERSONATE_AUTHORITY", "JOB_TASK_SCAM", "OTHER_NEW",
]
Provenance = Literal["OBSERVED_IN_EVIDENCE", "USER_REPORTED", "INFERRED", "UNKNOWN"]
YesNoUnknown = Literal["YES", "NO", "UNKNOWN"]


class FactLLM(BaseModel):
    text: str
    provenance: Provenance


class IncidentAnalysisLLM(BaseModel):
    tactic_family: TacticFamily
    tactic_slug: str | None = None
    tactic_summary_vi: str
    money_lost_vnd: int | None = None
    money_requested_vnd: int | None = None
    otp_or_password_disclosed: YesNoUnknown
    remote_app_installed: YesNoUnknown
    facts: list[FactLLM]
    manipulation_cues: list[str]


class Fact(_Strict):
    text: str
    provenance: Provenance


class IncidentAnalysis(_Strict):
    tactic_family: TacticFamily
    tactic_slug: str | None = None
    tactic_summary_vi: str
    money_lost_vnd: int | None = None
    money_requested_vnd: int | None = None
    otp_or_password_disclosed: YesNoUnknown
    remote_app_installed: YesNoUnknown
    facts: list[Fact]
    manipulation_cues: list[str]


class AnalyzeResult(BaseModel):
    analysis: IncidentAnalysis
    degraded: bool = False
